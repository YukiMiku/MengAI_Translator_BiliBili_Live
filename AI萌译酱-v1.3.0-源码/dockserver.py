# -*- coding: utf-8 -*-
"""精简的本地 HTTP + WebSocket 服务，供 OBS / 直播姬停靠窗口显示实时翻译。

- GET  /dock   -> dock.html（停靠页，只显示，不操作）
- GET  /ws     -> WebSocket 广播（console_message / translation / status / popularity / clear_messages）

纯标准库实现，无需额外依赖。
"""
import os
import json
import base64
import struct
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

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
        path = urlparse(self.path).path
        if path == '/ws':
            self._upgrade()
            return
        if path == '/api/language':
            body = json.dumps({'uiLanguage': getattr(self.server.dockserver, 'language', 'zh')}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ('/', '/dock', '/index.html'):
            path = '/dock.html'
        self._serve_static(path)

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
