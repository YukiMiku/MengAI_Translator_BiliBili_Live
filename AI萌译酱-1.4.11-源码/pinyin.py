# -*- coding: utf-8 -*-
"""拼音注音引擎（1.4.0 新增）

职责：
  · 把一句中文弹幕切成「注音单元」，供逐字对齐渲染使用
  · 引擎是内嵌的 pypinyin（MIT，见 lib/pypinyin/LICENSE.txt），纯 Python、离线可用
  · 词表里的拼音栏是「覆盖层」，优先于引擎结果（用于人名 / 专有名词 / 新词）

为什么要自己切分（重要）：
  pypinyin 会把**连续的非汉字**合并成一个返回项：
      '123abc'        -> ['123abc']                     长度 1 ≠ 6
      '123 听歌 abc'  -> ['123 ', 'tīng', 'gē', ' abc']  长度 4 ≠ 10
  所以不能拿它的返回列表直接做逐字对齐。这里改为按 CJK 区间自己分段：
  **中文段整段交给引擎**（保住词组上下文，多音字才准），非中文段整段作为一个单元。
  最终单元序列与输入逐字符一一覆盖，渲染端可直接按单元排布。

声调：引擎用符号形式（xiǎo）。词表输入允许 xiao3 / xiao3xin1 / xiǎo xīn 混写，
      统一由 normalize() 转成符号形式。
"""
import os
import re
import sys
import threading

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(APP_DIR, 'lib')

# --------------------------------------------------------------------------
# CJK 判定
# --------------------------------------------------------------------------
_CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2FA1F),
)


def is_cjk(ch):
    o = ord(ch)
    for lo, hi in _CJK_RANGES:
        if lo <= o <= hi:
            return True
    return False


# --------------------------------------------------------------------------
# 声调符号：数字形式 -> 符号形式
# --------------------------------------------------------------------------
_TONE_TABLE = {
    'a': 'āáǎà', 'o': 'ōóǒò', 'e': 'ēéěè',
    'i': 'īíǐì', 'u': 'ūúǔù', 'ü': 'ǖǘǚǜ',
}
_SYL_RE = re.compile(
    r'[a-zA-ZüÜāáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜv:]+[0-5]?')
_MARKED = 'āáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜ'


def _mark(syl, tone):
    """给一个无声调音节加上声调符号。"""
    if not tone or not (1 <= tone <= 4):
        return syl
    s = syl.replace('v', 'ü').replace('V', 'Ü').replace(':', 'ü')
    low = s.lower()
    idx = -1
    for v in ('a', 'o', 'e'):
        p = low.find(v)
        if p >= 0:
            idx = p
            break
    if idx < 0:
        if 'iu' in low:
            idx = low.find('iu') + 1
        elif 'ui' in low:
            idx = low.find('ui') + 1
        else:
            for v in ('i', 'u', 'ü'):
                p = low.find(v)
                if p >= 0:
                    idx = p
                    break
    if idx < 0 or idx >= len(s):
        return s
    ch = s[idx]
    base = ch.lower()
    if base not in _TONE_TABLE:
        return s
    marked = _TONE_TABLE[base][tone - 1]
    if ch.isupper():
        marked = marked.upper()
    return s[:idx] + marked + s[idx + 1:]


def normalize(text):
    """统一成「符号声调 + 空格分隔」。支持 xiao3 / xiao3xin1 / xiǎo xīn / xiao（轻声）。"""
    if not text:
        return ''
    text = str(text).strip()
    if not text:
        return ''
    text = re.sub(r'[，,、;；\u3000]+', ' ', text)
    text = text.replace('-', ' ')
    out = []
    for raw in text.split():
        for m in _SYL_RE.finditer(raw):
            tok = m.group(0)
            if not tok:
                continue
            dm = re.match(r'^(.*?)([0-5])$', tok)
            if dm and dm.group(1):
                out.append(_mark(dm.group(1), int(dm.group(2))))
            else:
                out.append(tok.replace('v', 'ü').replace(':', 'ü'))
    return ' '.join(x for x in out if x)


def syllables(text):
    """拆成音节列表。"""
    n = normalize(text)
    return n.split() if n else []


def has_tone(text):
    """是否含声调信息（符号或数字）。"""
    s = str(text or '')
    if any(c in _MARKED for c in s):
        return True
    return bool(re.search(r'[a-zA-ZüÜ][0-5](?![a-zA-Z])', s))


# --------------------------------------------------------------------------
# 引擎
# --------------------------------------------------------------------------
_py = None
_style = None
_engine_error = ''
_lock = threading.Lock()
_warmed = threading.Event()

_overrides = {}
_override_maxlen = 0
_cache = {}
_CACHE_MAX = 4000


def _ensure_path():
    if LIB_DIR not in sys.path:
        sys.path.insert(0, LIB_DIR)


def _load_engine():
    global _py, _style, _engine_error
    if _py is not None or _engine_error:
        return _py
    with _lock:
        if _py is not None or _engine_error:
            return _py
        try:
            _ensure_path()
            import pypinyin as _p
            _py = _p
            _style = _p.Style.TONE
        except Exception as e:
            _engine_error = '%s: %s' % (type(e).__name__, e)
    return _py


def available():
    return _load_engine() is not None


def engine_error():
    return _engine_error


def warmup(on_done=None):
    """后台预热：首次加载 2.4MB 词组词典约 0.2~0.5 秒，避免首条弹幕卡顿。"""
    def run():
        try:
            if _load_engine() is not None:
                _py.lazy_pinyin('预热', style=_style)
        except Exception:
            pass
        _warmed.set()
        if on_done:
            try:
                on_done()
            except Exception:
                pass
    t = threading.Thread(target=run, name='pinyin-warmup', daemon=True)
    t.start()
    return t


def is_warm():
    return _warmed.is_set()


# --------------------------------------------------------------------------
# 词表覆盖层
# --------------------------------------------------------------------------
def set_overrides(items):
    """items：词表条目列表（{'source':…, 'pinyin':…}）。只有带拼音的生效。"""
    global _overrides, _override_maxlen
    ov = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        src = str(it.get('source') or '').strip()
        py = str(it.get('pinyin') or '').strip()
        if not src or not py:
            continue
        syl = syllables(py)
        if syl:
            ov[src] = syl
    _overrides = ov
    _override_maxlen = max((len(k) for k in ov), default=0)
    _cache.clear()
    return len(ov)


def override_count():
    return len(_overrides)


# --------------------------------------------------------------------------
# 切分与注音
# --------------------------------------------------------------------------
def _split_segments(text):
    """按 CJK / 非 CJK 分段：[(是否中文, 子串), ...]"""
    segs = []
    buf = []
    cur = None
    for ch in text:
        flag = is_cjk(ch)
        if cur is None or flag == cur:
            buf.append(ch)
        else:
            segs.append((cur, ''.join(buf)))
            buf = [ch]
        cur = flag
    if buf:
        segs.append((cur, ''.join(buf)))
    return segs


def _engine_units(seg):
    """对一段**全中文**文本取拼音，返回 [[字, 拼音或 None], ...]，长度 == len(seg)。"""
    py = _load_engine()
    if py is None:
        return [[ch, None] for ch in seg]
    try:
        res = list(py.lazy_pinyin(seg, style=_style))
    except Exception:
        return [[ch, None] for ch in seg]
    out = []
    i = 0
    for tok in res:
        tok = str(tok)
        if i >= len(seg):
            break
        if tok and not is_cjk(tok[0]) and seg.startswith(tok, i):
            for ch in tok:
                out.append([ch, None])
            i += len(tok)
        else:
            out.append([seg[i], tok or None])
            i += 1
    while i < len(seg):
        out.append([seg[i], None])
        i += 1
    return out[:len(seg)]


def annotate(text):
    """把文本变成注音单元序列。

    返回 [[单元文本, 拼音或 None], ...]；所有单元文本拼接 == 输入文本。
    中文单字各成一个单元（带拼音）；非中文连续段合成一个单元（拼音 None）。
    """
    text = '' if text is None else str(text)
    if not text:
        return []
    hit = _cache.get(text)
    if hit is not None:
        return hit

    fallback = []
    for flag, seg in _split_segments(text):
        if flag:
            fallback.extend([ch, None] for ch in seg)
        else:
            fallback.append([seg, None])

    ov = _overrides
    maxlen = _override_maxlen
    units = []
    for flag, seg in _split_segments(text):
        if not flag:
            units.append([seg, None])
            continue
        base = _engine_units(seg)          # 整段跑，词组上下文完整
        i = 0
        n = len(seg)
        while i < n:
            matched = None
            if maxlen:
                for ln in range(min(maxlen, n - i), 0, -1):
                    cand = seg[i:i + ln]
                    if cand in ov:
                        matched = (cand, ov[cand])
                        break
            if matched:
                word, syl = matched
                if len(syl) == len(word):
                    for k, ch in enumerate(word):
                        units.append([ch, syl[k]])
                else:
                    units.append([word, ' '.join(syl)])
                i += len(word)
            else:
                units.append(base[i] if i < len(base) else [seg[i], None])
                i += 1

    if ''.join(u[0] for u in units) != text:
        units = fallback
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[text] = units
    return units


def annotate_text(text):
    """只要拼音字符串（自检 / 调试用）。"""
    return ' '.join(u[1] for u in annotate(text) if u[1])
