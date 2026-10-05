# -*- coding: utf-8 -*-
"""配置持久化 / Windows DPAPI 加密 / 本地词库文件的读取、保存与导入。

- config.json 保存所有设置（API Key 只以 DPAPI 加密后的形式落盘）。
- 词库文件默认是纯文本，每行一条：  原词 => 译法 [# 备注] [禁用]
- “导入词库文件”额外支持 CSV / JSON。
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


def save_config(cfg):
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
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(disk, f, ensure_ascii=False, indent=2)


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
    return {'source': source, 'target': target, 'note': note, 'enabled': enabled}


def parse_glossary_csv(content):
    items = []
    try:
        rows = list(csv.reader(io.StringIO(content)))
    except Exception:
        return items
    start = 0
    if rows and rows[0] and str(rows[0][0]).strip().lower() in ('source', '原词'):
        start = 1
    for row in rows[start:]:
        if not row or len(row) < 2:
            continue
        source = str(row[0]).strip()
        target = str(row[1]).strip()
        if not source or not target:
            continue
        note = str(row[2]).strip() if len(row) > 2 else ''
        enabled = True
        if len(row) > 3:
            v = str(row[3]).strip().lower()
            enabled = v not in ('0', 'false', 'no', 'off', '禁用', '停用')
        items.append({'source': source, 'target': target, 'note': note, 'enabled': enabled})
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
        enabled = it.get('enabled', True) not in (False, 0, '0', 'false', 'False', 'no', '禁用')
        items.append({'source': source, 'target': target, 'note': note, 'enabled': enabled})
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
        flag = ' [禁用]' if (it.get('enabled') is False) else ''
        lines.append(f"{it['source']} => {it['target']}{note}{flag}")
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
            w.writerow(['source', 'target', 'note', 'enabled'])
            for it in items:
                w.writerow([it.get('source', ''), it.get('target', ''), it.get('note', ''),
                            'true' if it.get('enabled', True) is not False else 'false'])
    elif ext == '.json':
        out = [{'source': it.get('source', ''), 'target': it.get('target', ''),
                'note': it.get('note', ''), 'enabled': it.get('enabled', True) is not False} for it in items]
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
