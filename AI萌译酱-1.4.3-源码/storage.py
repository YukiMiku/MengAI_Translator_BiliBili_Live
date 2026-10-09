# -*- coding: utf-8 -*-
"""配置持久化 / Windows DPAPI 加密 / 本地词库文件的读取、保存与导入。

- config.json 保存所有设置（API Key 只以 DPAPI 加密后的形式落盘）。
- 词库文件默认是纯文本，每行一条：  原词 => 译法 [| 拼音] [# 备注] [禁用]
- “导入词库文件”额外支持 CSV / JSON。
- 拼音栏（1.4.0 新增）只用于弹幕注音显示，**不参与翻译**；
  例：  小心心 => きらきら | xiǎo xīn xīn
"""
import os
import re
import csv
import io
import json
import base64
import ctypes
from ctypes import wintypes

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, 'data')
CONFIG_PATH = os.path.join(DATA_DIR, 'config.json')
BILI_COOKIE_FILE = os.path.join(DATA_DIR, 'bilibili_cookie.txt')

BILI_COOKIE_TEMPLATE = """# ============================================================
#  B 站登录信息（可选）
# ============================================================
#  作用：带上登录信息连接弹幕服务器后，B 站会返回**未打码的完整昵称**
#        和**真实 UID**（不登录时，昵称会变成 “首字***”，uid 为 0）。
#
#  只需配置一次；失效了再换一次即可（一般能管很久）。
#
#  ── 最省事：只填 SESSDATA 一个值 ───────────────────────────
#
#    1. 打开 https://www.bilibili.com ，确认右上角已登录
#    2. 按 F12 → 顶部选「Application / 应用程序」
#       → 左侧 Cookies → https://www.bilibili.com
#    3. 找到 SESSDATA，双击它的 Value、全选、复制
#    4. 在本文件**最下面新起一行**，写成这样，保存：
#
#           SESSDATA=你复制到的值
#
#    5. 回程序点「载入并验证」
#
#  ── 为什么只需要 SESSDATA？ ────────────────────────────────
#    · bili_jct 是"写操作"的防伪令牌；本程序只读弹幕，用不到。
#    · uid（DedeUserID）程序会自动调 nav 接口取到，不用你复制。
#    · buvid 程序也会自己获取。
#    这也是业界标准库 blivedm 的做法 —— 它只认 SESSDATA。
#
#  ── 也支持其它格式（任选其一）──────────────────────────────
#    · 一整行 cookie：SESSDATA=xxx; bili_jct=yyy; DedeUserID=123
#    · 浏览器扩展 Cookie-Editor 导出的 JSON，整段粘贴
#    · 扩展导出的 Netscape 格式 cookies.txt，原样粘贴
#    · 只贴 SESSDATA 的值本身（不带 "SESSDATA=" 也行）
#
#  ⚠ 安全提醒：SESSDATA 等同于你的 B 站登录凭证，拿到它就能以你的身份操作账号。
#     请不要把这个文件发给任何人，也不要传网盘。建议只用小号。
# ============================================================

"""

DEFAULT_SYSTEM_PROMPT_ZH = (
    '你是直播弹幕翻译助手。把输入的非日语弹幕自然、简洁地翻译成日语。'
    '只返回日语译文，不要解释，不要加引号。保留网络用语、颜文字、数字、专有名词的原意；不要擅自补充信息。'
)
DEFAULT_SYSTEM_PROMPT_JA = (
    'あなたはライブ配信コメントの翻訳アシスタントです。入力された日本語以外のコメントを、自然で簡潔な日本語に翻訳してください。'
    '日本語訳だけを返し、説明や引用符は付けないでください。ネットスラング、顔文字、数字、固有名詞の意味を保ち、情報を勝手に追加しないでください。'
)

DEFAULT_CONFIG = {
    'room_id': '',
    'provider': 'deepseek',          # deepseek | deepseek_web | chatgpt_web | openai | openai_compatible | ollama
    'api_key_encrypted': '',
    'base_url': 'https://api.deepseek.com/v1',
    'model': 'deepseek-chat',
    'system_prompt': DEFAULT_SYSTEM_PROMPT_ZH,
    'max_concurrent': 3,
    'cache_enabled': True,
    'ui_language': 'ja',   # 默认日语；启动后可在界面切换成中文
    # 启动时显示 README：记住看过哪个版本；readme_disabled=True 表示永不再自动弹
    'readme_seen_version': '',
    'readme_disabled': False,
    'glossary_file': 'data/glossary.txt',
    'presets': [],
    'console_max_messages': 200,
    'dock_port': 17890,
    # 外观：弹幕区背景图
    'feed_bg_image': '',
    'feed_bg_scale': 100,      # 缩放（%），100 = 正好铺满
    'feed_bg_opacity': 100,    # 不透明度（%）
    'feed_bg_offset_x': 0,     # 水平位置（%），0 = 居中，范围 -100 ~ 100
    'feed_bg_offset_y': 0,     # 垂直位置（%），0 = 居中，范围 -100 ~ 100
    # ---- 1.4.0 新增：拼音注音 ----
    'show_pinyin': True,       # 弹幕区显示拼音注音（默认开启，可关闭）
    'feed_font_raw': 13,       # 原文（中文弹幕）字号
    'feed_font_pinyin': 11,    # 注音字号（原文 > 注音 >= 译文）
    'feed_font_trans': 10,     # 译文字号
    # ---- 1.4.0 新增：礼物栏 ----
    'gift_filter_free': False,  # 过滤免费礼物（银瓜子）；默认不过滤，对小主播友好
    'gift_pane_height': 170,    # 礼物栏高度（像素）
    'dock_gift_limit': 30,      # 停靠页显示多少条礼物（桌面窗口不限）
}


# --------------------------------------------------------------------------
# Windows DPAPI（与 v0.5 行为一致：API Key 不以明文落盘）
# --------------------------------------------------------------------------
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != 'nt':
        raise OSError('DPAPI 仅支持 Windows')
    kernel32 = ctypes.windll.kernel32
    crypt32 = ctypes.windll.crypt32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise OSError('DPAPI 调用失败')
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect_text(text: str) -> str:
    if not text:
        return ''
    try:
        return base64.b64encode(_dpapi(text.encode('utf-8'), True)).decode('ascii')
    except Exception:
        # 非 Windows 环境降级为 base64 混淆（会打印警告，但保证程序可用）
        return 'b64:' + base64.b64encode(text.encode('utf-8')).decode('ascii')


def unprotect_text(blob: str) -> str:
    if not blob:
        return ''
    if blob.startswith('b64:'):
        try:
            return base64.b64decode(blob[4:]).decode('utf-8')
        except Exception:
            return ''
    try:
        return _dpapi(base64.b64decode(blob), False).decode('utf-8')
    except Exception:
        return ''


# --------------------------------------------------------------------------
# 配置读写
# --------------------------------------------------------------------------
def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def resolve_glossary_path(cfg, glossary_file=None):
    p = glossary_file or cfg.get('glossary_file') or DEFAULT_CONFIG['glossary_file']
    if not os.path.isabs(p):
        p = os.path.join(APP_DIR, p)
    return os.path.normpath(p)


def load_config():
    _ensure_data_dir()
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            stored = json.load(f)
        cfg.update(stored)
    except Exception:
        pass
    cfg['presets'] = cfg.get('presets') if isinstance(cfg.get('presets'), list) else []
    cfg.setdefault('glossary_file', DEFAULT_CONFIG['glossary_file'])
    # 兼容 v0.5 的字段名
    if 'roomId' in cfg and not cfg.get('room_id'):
        cfg['room_id'] = str(cfg.get('roomId') or '')
    return cfg


# 最近一次配置写入失败的原因（None 表示正常）。
# 由 app.py 通过 config_save_hook 把提示写到日志面板上。
config_save_error = None
config_save_hook = None


def save_config(cfg):
    """保存配置。**永不抛异常**。

    这个函数在 _connect / 保存设置 / 读取预设 / 关闭窗口等很多地方被调用。
    一旦它抛出（最典型的是 config.json 被编辑器、杀毒软件或另一个程序占用，
    Windows 报 `PermissionError: [Errno 13]`），就会把**整个动作**打断 ——
    表现就是"点了连接完全没反应"。所以这里只记录失败并给出可操作的提示，
    让主流程照常继续：连不上/不保存设置是可以接受的，卡住不动不行。
    """
    global config_save_error
    import time as _time
    _ensure_data_dir()
    disk = dict(cfg)
    disk.pop('roomId', None)
    # 预先把 API Key 加密（调用方可能把明文 api_key 放进 cfg）
    if disk.get('api_key'):
        disk['api_key_encrypted'] = protect_text(disk['api_key'])
    disk.pop('api_key', None)
    disk['presets'] = []
    for p in (cfg.get('presets') or []):
        x = dict(p)
        if x.get('api_key'):
            x['api_key_encrypted'] = protect_text(x['api_key'])
        x.pop('api_key', None)
        x.setdefault('api_key_encrypted', '')
        disk['presets'].append(x)

    last = None
    for attempt in range(3):
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(disk, f, ensure_ascii=False, indent=2)
            config_save_error = None
            return True
        except OSError as e:
            # 被别人短暂占用时，稍等一下重试通常就成功了
            last = e
            _time.sleep(0.15)
        except Exception as e:
            last = e
            break
    config_save_error = (f'{type(last).__name__}: {last}' if last else '未知错误')
    if config_save_hook:
        try:
            config_save_hook(CONFIG_PATH, config_save_error)
        except Exception:
            pass
    return False


def get_api_key(cfg):
    return unprotect_text(cfg.get('api_key_encrypted') or '') or cfg.get('api_key') or ''


# --------------------------------------------------------------------------
# B 站登录（文件层面：data/bilibili_cookie.txt 为唯一来源）
# --------------------------------------------------------------------------
def ensure_bili_cookie_template():
    """cookie 文件不存在时，生成一个带说明的模板。"""
    _ensure_data_dir()
    if not os.path.exists(BILI_COOKIE_FILE):
        try:
            with open(BILI_COOKIE_FILE, 'w', encoding='utf-8') as f:
                f.write(BILI_COOKIE_TEMPLATE)
        except Exception:
            pass
    return BILI_COOKIE_FILE


def parse_bili_cookie_text(text):
    """从文本里解析出 cookie 字典。

    支持：每行一对 key=value / 整行 cookie 串 / Cookie-Editor 的 JSON /
          Netscape cookies.txt / 只给 SESSDATA 的值。
    """
    if not text:
        return {}
    jar = {}

    def put(k, v):
        k = (k or '').strip()
        v = (v or '').strip()
        if not k or not v:
            return
        if k not in jar:
            jar[k] = v

    raw = text.strip()
    # Cookie-Editor 导出的 JSON
    if raw.startswith('[') or raw.startswith('{'):
        try:
            data = json.loads(raw)
        except Exception:
            data = None
        if isinstance(data, dict):
            data = data.get('cookies') if isinstance(data.get('cookies'), list) else [data]
        if isinstance(data, list):
            for it in data:
                if isinstance(it, dict):
                    put(it.get('name'), it.get('value'))
            if jar:
                return jar
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # Netscape cookies.txt：domain \t flag \t path \t secure \t expiry \t name \t value
        if '\t' in line:
            parts = line.split('\t')
            if len(parts) >= 7 and 'bilibili' in parts[0]:
                put(parts[5], parts[6])
                continue
        if '=' not in line:
            # 只有一行的裸值，按 SESSDATA 处理
            if len(line) > 12 and 'SESSDATA' not in jar and '\t' not in line:
                put('SESSDATA', line)
            continue
        for piece in line.split(';'):
            k, _, v = piece.partition('=')
            put(k, v)
    return jar


def build_bili_cookie(jar):
    """把 cookie 字典拼成 Cookie 头需要的顺序串。"""
    order = ['SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5',
             'buvid3', 'buvid4', 'b_nut', 'bili_ticket']
    parts = [f'{k}={jar[k]}' for k in order if jar.get(k)]
    for k, v in jar.items():
        if k not in order and v:
            parts.append(f'{k}={v}')
    return '; '.join(parts)


def load_bili_cookie():
    """读取 cookie 文件，返回 (cookie串, 字典, 错误信息)。"""
    ensure_bili_cookie_template()
    try:
        with open(BILI_COOKIE_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    except Exception as e:
        return '', {}, f'读取 cookie 文件失败：{e}'
    jar = parse_bili_cookie_text(text)
    if not jar:
        return '', {}, ''
    if not jar.get('SESSDATA'):
        return '', jar, 'cookie 文件里没有找到 SESSDATA'
    return build_bili_cookie(jar), jar, ''


def bili_uid_from_cookie(cookie):
    """从 cookie 串里取 DedeUserID（= 真实 uid）。"""
    for part in (cookie or '').split(';'):
        k, _, v = part.strip().partition('=')
        if k.strip() == 'DedeUserID' and v.strip():
            try:
                return int(v.strip())
            except Exception:
                return 0
    return 0


def get_preset_api_key(preset):
    return unprotect_text(preset.get('api_key_encrypted') or '') or preset.get('api_key') or ''


# --------------------------------------------------------------------------
# 词库文件：解析 / 保存 / 合并
# --------------------------------------------------------------------------
def parse_glossary_line(line):
    raw = line.strip()
    if not raw:
        return None
    if raw.startswith('#') and not raw.startswith('#['):
        return None
    enabled = True
    if raw.startswith('#[') or raw.endswith('[禁用]') or raw.endswith('[disabled]'):
        enabled = False
    raw = raw.lstrip('#').strip()
    if raw.endswith('[禁用]'):
        raw = raw[:-len('[禁用]')].strip()
    elif raw.endswith('[disabled]'):
        raw = raw[:-len('[disabled]')].strip()

    note = ''
    m = re.search(r'\s+[#＃]\s*(.*)$', raw)
    if m:
        note = m.group(1).strip()
        raw = raw[:m.start()].strip()

    # 拼音栏：写在译法之后、备注之前，形如「原词 => 译法 | xiǎo xīn xīn」
    pinyin = ''
    if '|' in raw:
        head, _, tail = raw.rpartition('|')
        head, tail = head.strip(), tail.strip()
        if head and tail:
            raw, pinyin = head, tail

    source = target = None
    for sep in ('=>', '\t', ',', '=', '＝'):
        if sep in raw:
            left, _, right = raw.partition(sep)
            source = left.strip()
            target = right.strip()
            break
    if source is None:
        return None
    # 注意：不再把译文末尾的「（…）」当作备注。
    # 译文本体经常以全角括号结尾（例：くさ（笑）），那样会被误切掉。
    # 备注一律用「 # 备注」书写，语义明确、不会歧义。
    source = source.strip()
    target = target.strip()
    if not source or not target:
        return None
    return {'source': source, 'target': target, 'note': note, 'enabled': enabled,
            'pinyin': pinyin}


def parse_glossary_csv(content):
    items = []
    try:
        rows = list(csv.reader(io.StringIO(content)))
    except Exception:
        return items
    start = 0
    # 有表头时按列名取（1.4.0 起多一列 pinyin）；没有表头则沿用旧的固定列序。
    # 判定要谨慎：数据行的首格也可能是「原词」，所以**必须同时找到 target 列名**
    # 才认定是表头，否则会把一整行数据当成表头丢掉。
    cols = {'source': 0, 'target': 1, 'note': 2, 'enabled': 3}
    if rows and rows[0]:
        head = [str(c).strip().lower() for c in rows[0]]
        alias = {
            'source': ('source', '原词', '原文'),
            'target': ('target', '译法', '日语', '译文', '翻译'),
            'pinyin': ('pinyin', '拼音', '注音'),
            'note': ('note', '备注'),
            'enabled': ('enabled', '启用', '禁用', '有效'),
        }

        def find_col(key):
            for i, h in enumerate(head):
                for n in alias[key]:
                    if n in h:
                        return i
            return None

        if head and any(n in head[0] for n in ('source', '原词', '原文')):
            cand = {k: find_col(k) for k in alias}
            if cand.get('target') is not None:
                start = 1
                cols = {k: v for k, v in cand.items() if v is not None}
    for row in rows[start:]:
        if not row or len(row) < 2:
            continue

        def cell(key, default=''):
            i = cols.get(key)
            return str(row[i]).strip() if (i is not None and i < len(row)) else default

        source = cell('source')
        target = cell('target')
        if not source or not target:
            continue
        note = cell('note')
        pinyin = cell('pinyin')
        enabled = True
        i = cols.get('enabled')
        if i is not None and i < len(row):
            v = str(row[i]).strip().lower()
            enabled = v not in ('0', 'false', 'no', 'off', '禁用', '停用')
        items.append({'source': source, 'target': target, 'note': note,
                      'enabled': enabled, 'pinyin': pinyin})
    return items


def parse_glossary_json(content):
    try:
        data = json.loads(content)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get('glossary') or data.get('items') or data.get('词表') or []
    if not isinstance(data, list):
        return []
    items = []
    for it in data:
        if not isinstance(it, dict):
            continue
        source = str(it.get('source') or it.get('原词') or '').strip()
        target = str(it.get('target') or it.get('译法') or it.get('日语') or it.get('译文') or '').strip()
        if not source or not target:
            continue
        note = str(it.get('note') or it.get('备注') or '').strip()
        pinyin = str(it.get('pinyin') or it.get('拼音') or it.get('注音') or '').strip()
        enabled = it.get('enabled', True) not in (False, 0, '0', 'false', 'False', 'no', '禁用')
        items.append({'source': source, 'target': target, 'note': note,
                      'enabled': enabled, 'pinyin': pinyin})
    return items


def load_glossary_file(path):
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
    except FileNotFoundError:
        return []
    ext = os.path.splitext(path)[1].lower()
    if ext == '.csv':
        return parse_glossary_csv(content)
    if ext == '.json':
        return parse_glossary_json(content)
    items = []
    for line in content.splitlines():
        it = parse_glossary_line(line)
        if it:
            items.append(it)
    return items


def save_glossary_file(path, items):
    lines = []
    for it in items:
        if not it.get('source') or not it.get('target'):
            continue
        note = (' # ' + str(it['note']).strip()) if it.get('note') else ''
        py = str(it.get('pinyin') or '').strip()
        py_part = (' | ' + py) if py else ''
        flag = ' [禁用]' if (it.get('enabled') is False) else ''
        lines.append(f"{it['source']} => {it['target']}{py_part}{note}{flag}")
    body = '\n'.join(lines) + ('\n' if lines else '')
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body)


def export_glossary(path, items):
    """按扩展名导出词库：.csv -> CSV；.json -> JSON；其余 -> 纯文本。"""
    ext = os.path.splitext(path)[1].lower()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if ext == '.csv':
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['source', 'target', 'pinyin', 'note', 'enabled'])
            for it in items:
                w.writerow([it.get('source', ''), it.get('target', ''), it.get('pinyin', ''),
                            it.get('note', ''),
                            'true' if it.get('enabled', True) is not False else 'false'])
    elif ext == '.json':
        out = [{'source': it.get('source', ''), 'target': it.get('target', ''),
                'pinyin': it.get('pinyin', ''), 'note': it.get('note', ''),
                'enabled': it.get('enabled', True) is not False} for it in items]
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    else:
        save_glossary_file(path, items)


def merge_glossary(existing, incoming):
    """按 source 合并：同 source 用新值覆盖，其余追加。返回新列表。"""
    merged = []
    index = {}
    for it in existing:
        key = str(it.get('source', '')).strip().lower()
        if not key:
            continue
        merged.append(dict(it))
        index[key] = len(merged) - 1
    for it in incoming:
        source = str(it.get('source', '')).strip()
        if not source or not it.get('target'):
            continue
        key = source.lower()
        if key in index:
            merged[index[key]] = dict(it)
        else:
            merged.append(dict(it))
            index[key] = len(merged) - 1
    return merged

# --------------------------------------------------------------------------
# 预设文件（1.4.1 起：一个预设一个文件，放在 data/presets/ 下）
# --------------------------------------------------------------------------
# 原先预设是塞在 config.json 的 presets 数组里的。这样不便于"保留一份旧预设，
# 迭代后直接导回来测试"，所以改成独立文件：
#     data/presets/<预设名>.json
# 想迁移/备份时，直接拷这个目录即可；界面上也提供「导出 / 导入 / 打开文件夹」。
PRESET_DIR = os.path.join(DATA_DIR, 'presets')
PRESET_EXT = '.json'


def preset_dir():
    os.makedirs(PRESET_DIR, exist_ok=True)
    return PRESET_DIR


def safe_preset_name(name):
    """把预设名变成安全的文件名（去掉路径分隔符与 Windows 保留字符）。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', str(name or '').strip())
    s = s.strip(' .')
    return s or 'preset'


def preset_file_path(name):
    return os.path.join(preset_dir(), safe_preset_name(name) + PRESET_EXT)


def list_presets():
    """返回 [(名字, 路径), ...]，按文件名排序。"""
    d = preset_dir()
    out = []
    try:
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(PRESET_EXT):
                out.append((f[:-len(PRESET_EXT)], os.path.join(d, f)))
    except Exception:
        pass
    return out


def load_preset_file(path):
    """读一个预设文件；'name' 缺失时用文件名补上。"""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if not str(data.get('name') or '').strip():
        data['name'] = os.path.splitext(os.path.basename(path))[0]
    return data


def save_preset_file(path, preset):
    """写一个预设文件（UTF-8、可读的缩进格式）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(preset, f, ensure_ascii=False, indent=2)
        f.write('\n')


def delete_preset_file(path):
    try:
        os.remove(path)
        return True
    except Exception:
        return False


def migrate_presets_from_config(cfg):
    """把旧版塞在 config.json 里的预设落成单独文件（只做一次，不覆盖已有同名文件）。

    返回迁移成功的条数。迁移后把 config 里的数组清空，之后只认文件。
    """
    items = cfg.get('presets') or []
    if not isinstance(items, list) or not items:
        return 0
    moved = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get('name') or '').strip()
        if not name:
            continue
        path = preset_file_path(name)
        if os.path.exists(path):
            continue
        try:
            save_preset_file(path, it)
            moved += 1
        except Exception:
            pass
    cfg['presets'] = []
    try:
        save_config(cfg)
    except Exception:
        pass
    return moved
