# -*- coding: utf-8 -*-
"""B 站直播间实时弹幕客户端（只抓取连接之后的实时弹幕，不读取历史弹幕）。

- 仅依赖 Python 标准库（netutil / wsclient），无需 pip 安装任何东西。
- 鉴权使用 protover=2，服务端返回 zlib 压缩包，无需 brotli 依赖。
- 从 WebSocket 建立成功的那一刻起才开始接收弹幕，天然满足
  “启动时不再显示以往弹幕，从连接到直播间的时间点开始抓取”的要求。
"""
import json
import zlib
import time
import random
import struct
import socket
import hashlib
import threading
import urllib.parse

import netutil
from wsclient import WebSocketClient
from storage import bili_uid_from_cookie


# --------------------------------------------------------------------------
# B 站风控（-352）说明：
#   getDanmuInfo 现在需要 WBI 签名 + buvid 指纹，否则一律返回 code=-352。
#   下面实现了官方 web 端使用的 WBI 算法（mixin key 置换表 + md5(w_rid)）。
# --------------------------------------------------------------------------
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

_wbi_cache = {'img_key': '', 'sub_key': '', 'ts': 0.0}
_buvid_cache = {'buvid3': '', 'buvid4': '', 'ts': 0.0}
_cache_lock = threading.Lock()


def _mixin_key(orig):
    return ''.join(orig[i] for i in _MIXIN_KEY_ENC_TAB)[:32]


def _wbi_keys(force=False):
    """取 WBI 签名用的 img_key / sub_key（未登录也能取到，缓存 1 小时）。"""
    now = time.time()
    with _cache_lock:
        if not force and _wbi_cache['img_key'] and now - _wbi_cache['ts'] < 3600:
            return _wbi_cache['img_key'], _wbi_cache['sub_key']
    try:
        j = netutil.get_json('https://api.bilibili.com/x/web-interface/nav', timeout=12)
        wbi = (j.get('data') or {}).get('wbi_img') or {}
        img = (wbi.get('img_url') or '').rsplit('/', 1)[-1].split('.')[0]
        sub = (wbi.get('sub_url') or '').rsplit('/', 1)[-1].split('.')[0]
        if img and sub:
            with _cache_lock:
                _wbi_cache.update(img_key=img, sub_key=sub, ts=now)
    except Exception:
        pass
    with _cache_lock:
        return _wbi_cache['img_key'], _wbi_cache['sub_key']


def _buvid(force=False):
    """取 buvid3 / buvid4 指纹（缓存 1 小时）。"""
    now = time.time()
    with _cache_lock:
        if not force and _buvid_cache['buvid3'] and now - _buvid_cache['ts'] < 3600:
            return _buvid_cache['buvid3'], _buvid_cache['buvid4']
    try:
        j = netutil.get_json('https://api.bilibili.com/x/frontend/finger/spi', timeout=12)
        d = j.get('data') or {}
        b3, b4 = d.get('b_3') or '', d.get('b_4') or ''
        if b3:
            with _cache_lock:
                _buvid_cache.update(buvid3=b3, buvid4=b4, ts=now)
    except Exception:
        pass
    with _cache_lock:
        return _buvid_cache['buvid3'], _buvid_cache['buvid4']


def _browser_headers(cookie=''):
    """尽量贴近真实浏览器的请求头（带登录 cookie 时尤其不能缺 User-Agent）。"""
    h = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'),
        'Origin': 'https://live.bilibili.com',
        'Accept-Language': 'zh-CN,zh;q=0.9,ja;q=0.8',
        'Pragma': 'no-cache',
        'Cache-Control': 'no-cache',
    }
    if cookie:
        h['Cookie'] = cookie
    return h


def verify_bili_cookie(cookie):
    """用 nav 接口验证 cookie 是否有效，返回 (uid, 昵称)。失败抛异常。"""
    if not cookie:
        raise RuntimeError('尚未配置 cookie')
    j = netutil.get_json('https://api.bilibili.com/x/web-interface/nav',
                         referer='https://www.bilibili.com/',
                         headers=_browser_headers(cookie))
    d = j.get('data') or {}
    if not d.get('isLogin'):
        raise RuntimeError(j.get('message') or 'cookie 无效或已过期（isLogin=false）')
    return int(d.get('mid') or 0), str(d.get('uname') or '')


def _live_headers(room_id=None, cookie=''):
    h = _browser_headers(cookie)
    h['Accept'] = 'application/json, text/plain, */*'
    if room_id:
        h['Referer'] = f'https://live.bilibili.com/{room_id}'
    b3, b4 = _buvid()
    if b3 and not cookie:
        h['Cookie'] = f'buvid3={b3}; buvid4={b4}'
    return h


def _enc_wbi(params):
    """给参数加上 wts 与 w_rid（WBI 签名）。"""
    img, sub = _wbi_keys()
    p = {k: str(v) for k, v in params.items()}
    if not img or not sub:
        return p
    mixin = _mixin_key(img + sub)
    p['wts'] = str(int(time.time()))
    p = {k: ''.join(ch for ch in str(v) if ch not in "!'()*") for k, v in sorted(p.items())}
    query = urllib.parse.urlencode(p)
    p['w_rid'] = hashlib.md5((query + mixin).encode('utf-8')).hexdigest()
    return p


def get_room_info(room_id):
    """房间基本信息。注意：老接口 roomInitStatic 已经 404 失效，改用 Room/get_info。"""
    j = netutil.get_json(f'https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}',
                         referer=f'https://live.bilibili.com/{room_id}')
    if j.get('code') != 0:
        raise RuntimeError(j.get('message') or j.get('msg') or f'房间查询失败 {j.get("code")}')
    d = j.get('data') or {}
    return {
        'real_id': int(d.get('room_id') or room_id),
        'live_status': int(d.get('live_status') or 0),
        'short_id': int(d.get('short_id') or room_id),
        'uname': d.get('uname') or '',
    }


def get_room_state(room_id):
    """返回 live_status：0 未开播 / 1 直播中 / 2 轮播中。"""
    j = netutil.get_json(f'https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}',
                         referer=f'https://live.bilibili.com/{room_id}')
    if j.get('code') != 0:
        raise RuntimeError(j.get('message') or j.get('msg') or f'直播状态查询失败 {j.get("code")}')
    return int((j.get('data') or {}).get('live_status') or 0)


def get_danmu_info(room_id, cookie=''):
    """弹幕服务器地址与 token。需要 WBI 签名，被 -352 拦截时自动刷新密钥重试一次。"""
    last = None
    for attempt in (0, 1):
        params = _enc_wbi({'id': room_id, 'type': 0})
        url = ('https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo?'
               + urllib.parse.urlencode(params))
        j = netutil.get_json(url, headers=_live_headers(room_id, cookie))
        code = j.get('code')
        if code == 0:
            return j.get('data') or {}
        last = code
        if code == -352 and attempt == 0:
            # 风控拦截：刷新 WBI 密钥与 buvid 后重试
            _wbi_keys(force=True)
            _buvid(force=True)
            time.sleep(0.6)
            continue
        break
    raise RuntimeError(f'弹幕信息查询被 B 站风控拦截（code={last}）。'
                       '可稍后重试，或先用「测试弹幕」验证翻译流程。')


def _pack(op, body, ver=1):
    if isinstance(body, str):
        body = body.encode('utf-8')
    header = struct.pack('>IHHII', 16 + len(body), 16, ver, op, 1)
    return header + body


def _parse_frames(buf):
    out = []
    pos = 0
    n = len(buf)
    while pos + 16 <= n:
        plen, hlen = struct.unpack_from('>IH', buf, pos)
        if plen < 16 or plen < hlen or pos + plen > n:
            break
        ver, op = struct.unpack_from('>HI', buf, pos + 6)
        body = buf[pos + hlen:pos + plen]
        out.append((ver, op, body))
        pos += plen
    return out


def _extract_danmu(event):
    if not event or event.get('cmd') != 'DANMU_MSG':
        return None
    info = event.get('info')
    if not isinstance(info, list) or len(info) < 3:
        return None
    text = str(info[1] or '')
    if not text:
        return None
    user_info = info[2] if isinstance(info[2], list) else []
    uid = user_info[0] if len(user_info) > 0 else None
    user = user_info[1] if len(user_info) > 1 else '匿名用户'
    return {'user': str(user or '匿名用户'), 'text': text, 'uid': uid}


def _extract_gift(event):
    """取出礼物事件（1.4.0 新增）。

    只认 SEND_GIFT：它在一轮连击里会被反复推送，num / total_num 递增，
    按 batch_combo_id 归组就能得到「最终数目」，所以界面上一行原地更新即可。

    COMBO_SEND 返回 merge_only=True —— 它只是连击的汇总（常在本轮结束时才到），
    用来补最终数字；**没有对应行时不要新建**，否则会和 SEND_GIFT 重复成两行。

    「同一人、不同时间送同一个礼物」属于**不同的 batch_combo_id**（或没有），
    因此天然不会合并，各占一行。
    """
    cmd = str((event or {}).get('cmd') or '')
    if cmd not in ('SEND_GIFT', 'COMBO_SEND'):
        return None
    data = event.get('data')
    if not isinstance(data, dict):
        return None
    gift = str(data.get('giftName') or data.get('gift_name') or '').strip()
    if not gift:
        return None

    def _int(*keys, default=0):
        for k in keys:
            v = data.get(k)
            if v not in (None, ''):
                try:
                    return int(v)
                except Exception:
                    pass
        return default

    num = _int('num', 'gift_num', 'combo_num', default=1) or 1
    total = _int('total_num', 'combo_num', 'num', default=num) or num
    user_info = data.get('user_info') if isinstance(data.get('user_info'), dict) else {}
    return {
        'user': str(data.get('uname') or user_info.get('uname') or '匿名用户'),
        'uid': data.get('uid') or user_info.get('uid') or 0,
        'gift': gift,
        'num': max(1, num),
        'total': max(1, total),
        'price': _int('price', 'discount_price'),
        'coin_type': str(data.get('coin_type') or ''),
        'combo_id': str(data.get('batch_combo_id') or data.get('combo_id') or ''),
        'action': str(data.get('action') or ''),
        'blind': bool(data.get('blind_gift')),
        'merge_only': cmd == 'COMBO_SEND',
    }


class DanmakuClient:
    """连接直播间，只推送实时弹幕。

    回调：
      on_danmaku(dict)         实时弹幕 {user, text, uid, ts}
      on_gift(dict)            礼物 {user, uid, gift, num, total, price, coin_type, combo_id}
      on_status(dict)          状态变化 {connected, live, message, room_id}
      on_popularity(int)       人气值
      on_log(level, message)   日志
    """

    def __init__(self, room_id, on_danmaku, on_status=None, on_popularity=None, on_log=None,
                 cookie='', uid=0, on_gift=None):
        self.room_id = str(room_id)
        self.cookie = (cookie or '').strip()
        # uid：优先用调用方传入的（已通过 nav 验证过）；否则尝试从 cookie 里的 DedeUserID 取
        self.uid = int(uid or 0) or (bili_uid_from_cookie(self.cookie) if self.cookie else 0)
        self.on_danmaku = on_danmaku
        self.on_gift = on_gift or (lambda g: None)
        self.on_status = on_status or (lambda s: None)
        self.on_popularity = on_popularity or (lambda v: None)
        self.on_log = on_log or (lambda lv, m: None)
        self._stop = threading.Event()
        self._ws = None
        self._heartbeat = None
        self._heartbeat_ws = None
        self._thread = None
        self._watch = None
        self._watch_stop = None
        self.live_status = 0        # 0=未开播 1=直播中 2=轮播中
        self.real_room_id = ''
        self.auth_ok = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='bili-danmaku')
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._heartbeat_ws = None
        self._cancel_status_watch()
        ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    # -- 主循环 -------------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            try:
                info = get_room_info(self.room_id)
                real_id = info['real_id']
                self.real_room_id = str(real_id)
                self.live_status = int(info.get('live_status') or 0)
                self.on_log('info', f"房间 {real_id}"
                                    + (f"（{info['uname']}）" if info.get('uname') else '')
                                    + ' 开播状态：'
                                    + {0: '未开播', 1: '直播中', 2: '轮播中'}.get(
                                        self.live_status, str(self.live_status)))
                # 未开播也照样连接弹幕服务器（和 LAPLACE Chat 一样）：
                # 这样不开播也能验证连接/翻译流程，开播后同一条连接会立刻收到实时弹幕。
                self._connect_ws(real_id, self.live_status)
                if not self._stop.is_set():
                    self._wait_stop(10)
            except Exception as e:
                if self._stop.is_set():
                    break
                msg = str(e)
                if ('WinError 10038' in msg or 'WinError 10054' in msg
                        or '连接已断开' in msg or '连接已关闭' in msg or '服务器关闭连接' in msg):
                    msg = '实时连接断开，10 秒后自动重连…'
                else:
                    msg = '连接失败：' + msg
                # 失败也要落到日志面板上：只改状态栏容易被忽略，
                # 用户会以为"点了没反应"。
                try:
                    self.on_log('error', msg)
                except Exception:
                    pass
                self._emit_status(connected=False, live=False, message=msg, room_id=self.room_id)
                self._wait_stop(10)

    def _connect_ws(self, real_id, live_status=0):
        self.live_status = int(live_status or 0)
        try:
            info = get_danmu_info(real_id, self.cookie)
        except Exception as e:
            # 未开播时少数房间拿不到弹幕服务器信息，退回默认服务器
            self.on_log('error', f'获取弹幕服务器信息失败，改用默认服务器：{e}')
            info = {}
        host_list = info.get('host_list') or []
        host = next((h for h in host_list if h.get('wss_port')), host_list[0] if host_list else None)
        if not host:
            host = {'host': 'broadcastlv.chat.bilibili.com', 'wss_port': 443}
        host_name = host.get('host') or 'broadcastlv.chat.bilibili.com'
        ws_url = f"wss://{host_name}:{host.get('wss_port') or 443}/sub"
        token = info.get('token') or ''
        self._emit_status(connected=False, live=self.live_status == 1,
                          message='正在连接弹幕服务器…', room_id=self.room_id, real_room_id=str(real_id))

        # 有登录 cookie 时，握手要带上 Cookie，并且不能缺 User-Agent
        ws = WebSocketClient(ws_url, extra_headers=_browser_headers(self.cookie), timeout=20)
        ws.connect()
        self._ws = ws

        # uid 优先用调用方传入的值；没有就从 nav 接口取（与 blivedm 的做法一致）。
        # 这样用户只需提供 SESSDATA 一个值，不必再去复制 DedeUserID。
        if not self.uid and self.cookie:
            try:
                nav_uid, uname = verify_bili_cookie(self.cookie)
                self.uid = nav_uid
                self.on_log('info', f'已通过 nav 接口取得登录 uid={nav_uid}（{uname}）')
            except Exception as e:
                self.on_log('error', f'cookie 校验未通过，本次按未登录方式连接：{e}')

        b3, _b4 = _buvid()
        auth = {
            'uid': self.uid or 0, 'roomid': real_id, 'protover': 2,
            'buvid': b3 or ''.join(random.choice('0123456789abcdef') for _ in range(32)),
            'platform': 'web', 'type': 2, 'key': token,
        }
        ws.send(_pack(7, json.dumps(auth)))
        self._start_heartbeat(ws)
        self._start_status_watch(real_id)
        self.auth_ok = True
        self._emit_connected_status()

        try:
            while not self._stop.is_set():
                try:
                    opcode, payload = ws.recv_message()
                except (socket.timeout, TimeoutError):
                    continue  # 静默期，继续等待
                if not payload:
                    continue
                for ver, op, body in _parse_frames(payload):
                    self._handle_packet(ver, op, body, 0)
        finally:
            self._cancel_heartbeat()
            self._cancel_status_watch()
            try:
                ws.close()
            except Exception:
                pass
            self._ws = None
            if not self._stop.is_set():
                self._emit_status(connected=False, live=False,
                                  message='实时连接断开，稍后自动重连…', room_id=self.room_id,
                                  real_room_id=str(real_id))

    def _emit_connected_status(self):
        ls = self.live_status
        if ls == 1:
            msg = '已连接：直播中，正在接收实时弹幕…'
        elif ls == 2:
            msg = '已连接：轮播中，正在接收弹幕…'
        else:
            msg = '已连接（当前未开播）：开播后弹幕会实时到达；可先用「测试弹幕」验证翻译流程'
        self._emit_status(connected=True, live=(ls == 1), live_status=ls,
                          message=msg, room_id=self.room_id, real_room_id=self.real_room_id)

    def _start_status_watch(self, real_id):
        """连接期间定时刷新开播状态，开播/下播时更新界面提示。"""
        self._cancel_status_watch()
        self._watch_stop = threading.Event()
        stop_event = self._watch_stop

        def watch():
            while not self._stop.is_set() and not stop_event.is_set():
                stop_event.wait(20)
                if self._stop.is_set() or stop_event.is_set():
                    break
                try:
                    live = int(get_room_state(real_id))
                except Exception:
                    continue
                if live != self.live_status:
                    self.live_status = live
                    self.on_log('info', '开播状态变化：' + {0: '未开播', 1: '直播中', 2: '轮播中'}.get(live, str(live)))
                    self._emit_connected_status()

        self._watch = threading.Thread(target=watch, daemon=True, name='bili-status')
        self._watch.start()

    def _cancel_status_watch(self):
        if self._watch_stop is not None:
            self._watch_stop.set()
            self._watch_stop = None

    def _start_heartbeat(self, ws):
        self._cancel_heartbeat()
        self._heartbeat_ws = ws

        def beat():
            while not self._stop.is_set() and self._heartbeat_ws is ws:
                self._stop.wait(30)
                if self._stop.is_set() or self._heartbeat_ws is not ws:
                    break
                try:
                    ws.send(_pack(2, b'[object Object]'))
                except Exception:
                    break

        self._heartbeat = threading.Thread(target=beat, daemon=True, name='bili-heartbeat')
        self._heartbeat.start()

    def _cancel_heartbeat(self):
        self._heartbeat_ws = None

    # -- 协议解析 -----------------------------------------------------------
    def _handle_packet(self, ver, op, body, depth=0):
        if depth > 5:
            return
        if op == 3:
            if len(body) >= 4:
                self.on_popularity(struct.unpack('>I', body[:4])[0])
            return
        if op == 8:
            try:
                x = json.loads(body.decode('utf-8', 'ignore'))
                if x.get('code') == 0:
                    self.auth_ok = True
                    self._emit_connected_status()
                else:
                    self.auth_ok = False
                    self._emit_status(connected=False, live=False,
                                      message=f"弹幕鉴权失败（code={x.get('code')}），"
                                              '可能是房间号无效或需要登录态，可先用「测试弹幕」验证翻译',
                                      room_id=self.room_id, real_room_id=self.real_room_id)
            except Exception:
                pass
            return
        if op != 5:
            return
        for cver, cop, cbody in self._parse_message_body(body, ver):
            if cop in (3, 8, 5):
                self._handle_packet(cver, cop, cbody, depth + 1)
                continue
            try:
                obj = json.loads(cbody.decode('utf-8', 'ignore'))
            except Exception:
                continue
            if isinstance(obj, list):
                for o in obj:
                    self._process_event(o)
            else:
                self._process_event(obj)

    def _parse_message_body(self, body, ver):
        if ver == 0:
            return [(ver, 0, body)]
        if ver == 2:
            try:
                return _parse_frames(zlib.decompress(body))
            except Exception:
                return []
        if ver == 3:
            try:
                import brotli
                return _parse_frames(brotli.decompress(body))
            except Exception:
                pass
            try:
                return _parse_frames(zlib.decompress(body))
            except Exception:
                return []
        return [(ver, 0, body)]

    def _process_event(self, event):
        d = _extract_danmu(event)
        if d:
            d['ts'] = int(time.time() * 1000)
            self.on_danmaku(d)
            return
        g = _extract_gift(event)
        if g:
            g['ts'] = int(time.time() * 1000)
            self.on_gift(g)

    def _emit_status(self, **kw):
        base = {'connected': False, 'live': False, 'message': '未连接',
                'room_id': self.room_id, 'real_room_id': self.real_room_id,
                'live_status': self.live_status}
        base.update(kw)
        self.on_status(base)

    def _wait_stop(self, seconds):
        self._stop.wait(seconds)
