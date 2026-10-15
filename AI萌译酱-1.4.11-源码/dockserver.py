# -*- coding: utf-8 -*-
"""精简的本地 HTTP + WebSocket 服务，供 OBS / 直播姬停靠窗口显示实时翻译。

- GET  /dock         -> dock.html（停靠页，只显示，不操作）
- GET  /ws           -> WebSocket 广播
                        console_message / translation / status / popularity /
                        clear_messages / settings / gift
- GET  /api/language -> 仅界面语言（保留给旧页面）
- GET  /api/settings -> 显示设置：语言、是否显示拼音、三个字号、礼物条数
- GET  /api/gifts?before=<id>&limit=<n>
                     -> 礼物回溯（1.4.0）：返回 before 之前最近的 n 件礼物，
                        停靠页滚到顶部时用来往前翻历史

纯标准库实现，无需额外依赖。
"""
import os
import json
import base64
import struct
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


def _ws_frame(text):
    b = text.encode('utf-8')
    n = len(b)
    if n < 126:
        h = bytes([0x81, n])
    elif n < 65536:
        h = bytes([0x81, 126]) + struct.pack('>H', n)
    else:
        h = bytes([0x81, 127]) + struct.pack('>Q', n)
    return h + b


class _Handler(BaseHTTPRequestHandler):
    server_version = 'AI-MengYiJiang'

    def log_message(self, *a):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path == '/ws':
            self._upgrade()
            return
        ds = self.server.dockserver
        if path == '/api/language':
            self._json({'uiLanguage': getattr(ds, 'language', 'zh')})
            return
        if path == '/api/settings':
            self._json(ds.settings or {'uiLanguage': getattr(ds, 'language', 'zh')})
            return
        if path == '/api/gifts':
            q = parse_qs(url.query)
            try:
                before = int((q.get('before') or [''])[0])
            except Exception:
                before = -1
            try:
                limit = int((q.get('limit') or ['0'])[0])
            except Exception:
                limit = 0
            limit = max(1, min(200, limit or 30))
            self._json({'gifts': ds.gifts_before(before, limit)})
            return
        if path in ('/', '/dock', '/index.html'):
            path = '/dock.html'
        self._serve_static(path)

    def _json(self, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path):
        root = os.path.normpath(self.server.public_dir)
        safe = os.path.normpath(os.path.join(root, path.lstrip('/')))
        if not safe.startswith(root) or not os.path.isfile(safe):
            self.send_error(404)
            return
        ext = os.path.splitext(safe)[1].lower()
        ctype = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
                 '.css': 'text/css; charset=utf-8', '.ico': 'image/x-icon'}.get(ext, 'application/octet-stream')
        with open(safe, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _upgrade(self):
        key = self.headers.get('Sec-WebSocket-Key')
        if not key:
            self.send_error(400)
            return
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode('ascii')
        resp = ('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                'Sec-WebSocket-Accept: ' + accept + '\r\n\r\n').encode('latin-1')
        sock = self.connection
        try:
            sock.sendall(resp)
        except Exception:
            return
        ds = self.server.dockserver
        ds.add_client(sock)
        try:
            while True:
                data = sock.recv(4096)
                if not data:
                    break
        except Exception:
            pass
        finally:
            ds.remove_client(sock)


class DockServer:
    def __init__(self, port, public_dir):
        self.port = port
        self.public_dir = public_dir
        self.clients = set()
        self._lock = threading.Lock()
        self.httpd = None
        self.language = 'zh'
        # 1.4.0：下发给停靠页的显示设置 + 礼物回溯的数据来源
        self.settings = {}
        self.gift_provider = None      # callable(before_id, limit) -> [gift dict, ...]

    def gifts_before(self, before, limit):
        try:
            if self.gift_provider:
                return self.gift_provider(before, limit)
        except Exception:
            pass
        return []

    def add_client(self, sock):
        with self._lock:
            self.clients.add(sock)

    def remove_client(self, sock):
        with self._lock:
            self.clients.discard(sock)

    def broadcast(self, obj):
        text = json.dumps(obj, ensure_ascii=False)
        with self._lock:
            socks = list(self.clients)
        frame = _ws_frame(text)
        for s in socks:
            try:
                s.sendall(frame)
            except Exception:
                self.remove_client(s)

    def start(self):
        self.httpd = ThreadingHTTPServer(('127.0.0.1', self.port), _Handler)
        self.httpd.public_dir = self.public_dir
        self.httpd.dockserver = self
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name='dock-http').start()

    def stop(self):
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        try:
            self.httpd.server_close()
        except Exception:
            pass
