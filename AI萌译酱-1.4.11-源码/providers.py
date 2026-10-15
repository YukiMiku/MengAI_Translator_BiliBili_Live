# -*- coding: utf-8 -*-
"""翻译服务：OpenAI 兼容 API / Ollama / DeepSeek 网页版 / ChatGPT 网页版。

- API 类（deepseek / openai / openai_compatible / ollama）走 HTTP，稳定可靠。
- 网页版（deepseek_web / chatgpt_web）**直接调用系统自带的 Edge / Chrome 浏览器**，
  通过浏览器调试协议（CDP）操作网页端，使用网页端免费服务。
  不需要安装 playwright / selenium，也不需要下载额外浏览器内核。
  首次使用在弹出的浏览器里登录一次即可，登录态保存在 data/<provider>_browser。
"""
import re
import json

import netutil
from storage import get_api_key
from browser import BrowserSession

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'

PROVIDERS = {
    'deepseek': {'label': 'DeepSeek (API)', 'label_ja': 'DeepSeek (API)',
                 'kind': 'api', 'base': 'https://api.deepseek.com/v1', 'model': 'deepseek-chat'},
    'deepseek_web': {'label': 'DeepSeek 网页版', 'label_ja': 'DeepSeek web',
                     'kind': 'web', 'url': 'https://chat.deepseek.com/'},
    'chatgpt_web': {'label': 'ChatGPT 网页版', 'label_ja': 'ChatGPT web',
                    'kind': 'web', 'url': 'https://chatgpt.com/'},
    'openai': {'label': 'OpenAI (API)', 'label_ja': 'OpenAI (API)',
               'kind': 'api', 'base': 'https://api.openai.com/v1', 'model': 'gpt-4o-mini'},
    'openai_compatible': {'label': 'OpenAI 兼容', 'label_ja': 'OpenAI 互換',
                          'kind': 'api', 'base': 'http://127.0.0.1:1234/v1', 'model': 'local-model'},
    'ollama': {'label': 'Ollama', 'label_ja': 'Ollama',
               'kind': 'ollama', 'base': 'http://127.0.0.1:11434', 'model': 'qwen3:4b'},
}

WEB_PROVIDERS = ('deepseek_web', 'chatgpt_web')


def provider_label(p, lang='zh'):
    """服务显示名：按界面语言返回（日语界面下 DeepSeek 网页版 -> DeepSeek web）。"""
    d = PROVIDERS.get(p) or {}
    if str(lang).lower().startswith('ja'):
        return d.get('label_ja') or d.get('label') or p
    return d.get('label') or p


def is_japanese(text):
    s = str(text or '')
    if not s.strip():
        return True
    hirakata = len(re.findall(r'[\u3040-\u30ff]', s))
    jp_punct = len(re.findall(r'[。、「」『』ー〜～・]', s))
    letters = len(re.findall(r'[A-Za-z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', s))
    if hirakata >= 1:
        return True
    if jp_punct >= 2 and not re.search(r'[\u3400-\u4dbf\u4e00-\u9fff]{4,}', s):
        return True
    if letters == 0:
        return True
    return False


def glossary_instruction(items):
    rows = [x for x in (items or []) if x.get('enabled') is not False and x.get('source') and x.get('target')]
    if not rows:
        return ''
    lines = []
    for x in rows[:100]:
        note = f"（{x['note']}）" if x.get('note') else ''
        lines.append(f"- {x['source']} => {x['target']}{note}")
    return (
        '\n\n【ローカル用語集 / Local Glossary】\n'
        '以下の用語は配信コメント内で見つかった場合、指定された日本語表現を優先してください。'
        '意味や文脈上必要な活用は許可しますが、勝手に別の訳へ変更しないでください。\n'
        + '\n'.join(lines)
    )


def effective_system_prompt(cfg, items):
    return f"{cfg.get('system_prompt') or ''}{glossary_instruction(items)}"


def normalize_base(s):
    return str(s or '').rstrip('/')


# --------------------------------------------------------------------------
# HTTP 翻译（API / Ollama）
# --------------------------------------------------------------------------
def _call_http(cfg, text, items):
    provider = (cfg.get('provider') or 'openai_compatible').lower()
    system = effective_system_prompt(cfg, items)

    if provider == 'ollama':
        base = normalize_base(cfg.get('base_url') or PROVIDERS['ollama']['base'])
        url = base + '/api/chat'
        status, tx = netutil.post_json(url, {
            'model': cfg.get('model') or PROVIDERS['ollama']['model'],
            'stream': False,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': text}],
        }, timeout=120)
        if status != 200:
            raise RuntimeError(f'Ollama HTTP {status}: {tx[:300]}')
        try:
            j = json.loads(tx)
        except Exception:
            raise RuntimeError('Ollama 返回的不是 JSON')
        return (j.get('message') or {}).get('content') or ''

    base = normalize_base(cfg.get('base_url') or PROVIDERS.get(provider, {}).get('base', 'http://127.0.0.1:1234/v1'))
    url = base + '/chat/completions'
    headers = {}
    key = get_api_key(cfg)
    # 没填 Key 就直接给出人话提示，不再发一个注定 401 的请求
    if provider in ('deepseek', 'openai') and not key:
        raise RuntimeError(
            f'尚未填写「{provider_label(provider)}」的 API Key，因此无法调用。\n'
            '解决办法（二选一）：\n'
            '  1) 在「翻译服务」里填入 API Key，再点「保存设置」；\n'
            '  2) 或把翻译服务改成「DeepSeek 网页版 / ChatGPT 网页版」——网页版不需要 API Key。')
    if key:
        headers['Authorization'] = f'Bearer {key}'
    payload = {
        'model': cfg.get('model') or PROVIDERS.get(provider, {}).get('model', ''),
        'temperature': 0.1,
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': text}],
    }
    status, tx = netutil.post_json(url, payload, headers=headers, timeout=120)
    if status in (401, 403):
        raise RuntimeError(
            f'API Key 无效或无权限（HTTP {status}）。\n'
            '请确认「翻译服务」选对了（网页版不需要 API Key），'
            '或重新填写正确的 API Key 后点「保存设置」。\n'
            f'服务返回：{tx[:200]}')
    if status != 200:
        raise RuntimeError(f'{provider_label(provider)} HTTP {status}: {tx[:300]}')
    try:
        j = json.loads(tx)
    except Exception:
        raise RuntimeError('翻译服务返回的不是 JSON')
    return (j.get('choices') or [{}])[0].get('message', {}).get('content') or (j.get('choices') or [{}])[0].get('text') or ''


# --------------------------------------------------------------------------
# 网页版（系统浏览器 + CDP，零依赖）
# --------------------------------------------------------------------------
def create_browser_session(provider, log=None):
    """创建一个网页版会话：内部使用系统自带的 Edge / Chrome，无需安装任何组件。"""
    return BrowserSession(provider, log=log)


# --------------------------------------------------------------------------
# 统一入口
# --------------------------------------------------------------------------
def call_provider(cfg, text, items, web_session=None):
    provider = (cfg.get('provider') or 'openai_compatible').lower()
    if provider in WEB_PROVIDERS:
        if web_session is None:
            raise RuntimeError('网页版会话未初始化')
        system = effective_system_prompt(cfg, items)
        prompt = f"{system}\n\n将下面这条弹幕翻译成日语，只输出译文：\n{text}" if system.strip() else text
        return web_session.translate(prompt)
    return _call_http(cfg, text, items)
