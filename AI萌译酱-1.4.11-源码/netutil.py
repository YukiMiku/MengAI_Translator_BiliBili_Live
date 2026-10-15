# -*- coding: utf-8 -*-
"""仅用 Python 标准库实现的 HTTP 工具（替代 requests，避免 pip 依赖问题）。"""
import json
import gzip
import zlib
import urllib.request
import urllib.error

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')


def _decode_body(resp):
    data = resp.read()
    enc = (resp.headers.get('Content-Encoding') or '').lower()
    try:
        if 'gzip' in enc:
            data = gzip.decompress(data)
        elif 'deflate' in enc:
            try:
                data = zlib.decompress(data)
            except zlib.error:
                data = zlib.decompress(data, -zlib.MAX_WBITS)
    except Exception:
        pass
    return data


def request(url, method='GET', payload=None, headers=None, timeout=60):
    """返回 (status_code, bytes)。HTTP 错误也会返回状态码而不是抛异常。"""
    hdrs = {'User-Agent': UA}
    if headers:
        hdrs.update(headers)
    body = None
    if payload is not None:
        body = json.dumps(payload).encode('utf-8')
        hdrs.setdefault('Content-Type', 'application/json')
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _decode_body(resp)
    except urllib.error.HTTPError as e:
        try:
            return e.code, _decode_body(e)
        except Exception:
            return e.code, b''


def get_json(url, referer=None, timeout=15, headers=None):
    hdrs = {'Accept': 'application/json, text/plain, */*'}
    if referer:
        hdrs['Referer'] = referer
    if headers:
        hdrs.update(headers)
    status, data = request(url, headers=hdrs, timeout=timeout)
    if status != 200:
        raise RuntimeError(f'HTTP {status}')
    return json.loads(data.decode('utf-8', 'ignore'))


def post_json(url, payload, headers=None, timeout=120):
    """返回 (status_code, text)。"""
    status, data = request(url, method='POST', payload=payload, headers=headers, timeout=timeout)
    return status, data.decode('utf-8', 'ignore')
