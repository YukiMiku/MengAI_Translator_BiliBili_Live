# -*- coding: utf-8 -*-
"""仅用 Python 标准库实现的最小 WebSocket 客户端（RFC6455）。

用于连接 B 站弹幕服务器，替代 websocket-client，避免 pip 依赖问题。
支持：wss/tls、客户端掩码帧、64 位长度、分片、ping/pong/close。
"""
import os
import ssl
import socket
import base64
import hashlib
import struct
import threading
from urllib.parse import urlparse

WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


class WSError(Exception):
    pass


class WebSocketClient:
    def __init__(self, url, extra_headers=None, timeout=30):
        u = urlparse(url)
        self.secure = (u.scheme == 'wss')
        self.host = u.hostname
        self.port = u.port or (443 if self.secure else 80)
        self.path = u.path or '/'
        if u.query:
            self.path += '?' + u.query
        self.extra_headers = extra_headers or {}
        self.timeout = timeout
        self.sock = None
        self._buf = b''
        self._send_lock = threading.Lock()
        self._closed = False

    # -- 连接 ---------------------------------------------------------------
    def connect(self):
        raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.secure:
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=self.host)
        self.sock = raw

        key = base64.b64encode(os.urandom(16)).decode('ascii')
        lines = [
            f'GET {self.path} HTTP/1.1',
            f'Host: {self.host}:{self.port}',
            'Upgrade: websocket',
            'Connection: Upgrade',
            f'Sec-WebSocket-Key: {key}',
            'Sec-WebSocket-Version: 13',
        ]
        for k, v in self.extra_headers.items():
            lines.append(f'{k}: {v}')
        raw.sendall(('\r\n'.join(lines) + '\r\n\r\n').encode('latin-1'))

        buf = b''
        while b'\r\n\r\n' not in buf:
            chunk = raw.recv(4096)
            if not chunk:
                raise WSError('WebSocket 握手时连接被关闭')
            buf += chunk
            if len(buf) > 65536:
                raise WSError('WebSocket 握手响应异常')
        head, _, rest = buf.partition(b'\r\n\r\n')
        text = head.decode('latin-1')
        status_line = text.split('\r\n', 1)[0]
        if ' 101' not in status_line:
            raise WSError(f'WebSocket 握手失败：{status_line}')
        expect = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode('ascii')
        if expect.lower() not in text.lower():
            raise WSError('WebSocket Accept 校验失败')
        self._buf = rest
        self.sock.settimeout(60)
        return True

    # -- 发送 ---------------------------------------------------------------
    def send(self, data, opcode=OP_BINARY):
        if self._closed or self.sock is None:
            raise WSError('连接已关闭')
        if isinstance(data, str):
            data = data.encode('utf-8')
        n = len(data)
        header = bytearray([0x80 | opcode])
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack('>H', n)
        else:
            header.append(0x80 | 127)
            header += struct.pack('>Q', n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
        with self._send_lock:
            self.sock.sendall(bytes(header) + masked)

    # -- 接收 ---------------------------------------------------------------
    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WSError('连接已断开')
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _recv_frame(self):
        b1, b2 = self._recv_exact(2)
        fin = bool(b1 & 0x80)
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack('>H', self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack('>Q', self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else None
        payload = self._recv_exact(length) if length else b''
        if mask:
            payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        return fin, opcode, payload

    def recv_message(self):
        """返回 (opcode, payload)；自动处理 ping/pong，遇到 close 抛异常。"""
        fragments = []
        msg_op = None
        while True:
            fin, opcode, payload = self._recv_frame()
            if opcode == OP_PING:
                try:
                    self.send(payload, opcode=OP_PONG)
                except Exception:
                    pass
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                raise WSError('服务器关闭连接')
            if opcode in (OP_TEXT, OP_BINARY):
                msg_op = opcode
                fragments = [payload]
            elif opcode == OP_CONT:
                fragments.append(payload)
            else:
                continue
            if fin:
                return msg_op or opcode, b''.join(fragments)

    # -- 关闭 ---------------------------------------------------------------
    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.sock:
                self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
