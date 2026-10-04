# socks_relay.py
"""
Chrome can use a SOCKS5 proxy but cannot send a username/password to it.
This module runs a tiny SOCKS5 server on 127.0.0.1 (no auth, random port)
that forwards every connection through an authenticated upstream SOCKS5
proxy. Chrome is pointed at the local port, the relay does the login.

Standard library only; it handles CONNECT (all that Chrome needs for HTTP/HTTPS).
"""
import select
import socket
import threading

SOCKS_VERSION = 5


def _recv_exact(sock, count):
    data = b''
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ConnectionError('connection closed')
        data += chunk
    return data


def _read_address(sock, atyp):
    """Read the destination address bytes for the given ATYP (raw, to pass through)."""
    if atyp == 1:       # IPv4
        return _recv_exact(sock, 4)
    if atyp == 4:       # IPv6
        return _recv_exact(sock, 16)
    if atyp == 3:       # domain name
        length = _recv_exact(sock, 1)
        return length + _recv_exact(sock, length[0])
    raise ValueError('unsupported address type')


def connect_via_upstream(proxy, atyp, address, port_bytes, timeout=30):
    """
    Open a connection to the destination THROUGH `proxy` (a proxy_pool.Proxy).
    The destination is passed to the proxy exactly as the client sent it, so
    domain names are resolved by the proxy, not locally.
    Returns the connected socket. Raises OSError on any failure.
    """
    upstream = socket.create_connection((proxy.host, proxy.port), timeout=timeout)
    try:
        methods = b'\x00\x02' if proxy.has_auth else b'\x00'
        upstream.sendall(bytes([SOCKS_VERSION, len(methods)]) + methods)
        version, method = _recv_exact(upstream, 2)
        if version != SOCKS_VERSION or method == 0xFF:
            raise OSError('upstream proxy refused the login method')

        if method == 2:                                   # username / password (RFC 1929)
            user, pwd = proxy.username.encode(), proxy.password.encode()
            upstream.sendall(b'\x01' + bytes([len(user)]) + user + bytes([len(pwd)]) + pwd)
            _, status = _recv_exact(upstream, 2)
            if status != 0:
                raise OSError('upstream proxy login failed')
        elif method != 0:
            raise OSError('upstream proxy chose an unsupported method')

        upstream.sendall(bytes([SOCKS_VERSION, 1, 0, atyp]) + address + port_bytes)
        header = _recv_exact(upstream, 4)                 # VER REP RSV ATYP
        if header[1] != 0:
            raise OSError(f'upstream proxy could not connect (code {header[1]})')
        _read_address(upstream, header[3])                # bound address (ignored)
        _recv_exact(upstream, 2)                          # bound port (ignored)

        upstream.settimeout(None)
        return upstream
    except Exception:
        upstream.close()
        raise


def pipe(a, b):
    """Copy bytes both ways between two sockets until either side closes."""
    sockets = [a, b]
    try:
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 120)
            if errored or not readable:
                return
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                (b if source is a else a).sendall(data)
    except OSError:
        return
    finally:
        for s in sockets:
            try:
                s.close()
            except OSError:
                pass


class LocalSocks5Relay:
    def __init__(self, proxy):
        self.proxy = proxy
        self._server = None
        self._thread = None
        self.port = None

    def start(self):
        """Start listening on 127.0.0.1 (random free port). Returns the port."""
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(('127.0.0.1', 0))
        self._server.listen(50)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self.port

    def stop(self):
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None

    # ------------------------------------------------------------------
    def _accept_loop(self):
        while self._server:
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client):
        try:
            client.settimeout(30)

            # Greeting: accept "no authentication" from the local client
            _, method_count = _recv_exact(client, 2)
            _recv_exact(client, method_count)
            client.sendall(b'\x05\x00')

            # Request
            version, command, _, atyp = _recv_exact(client, 4)
            address = _read_address(client, atyp)
            port_bytes = _recv_exact(client, 2)
            if version != SOCKS_VERSION or command != 1:      # only CONNECT
                client.sendall(b'\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00')
                client.close()
                return

            try:
                upstream = connect_via_upstream(self.proxy, atyp, address, port_bytes)
            except OSError:
                client.sendall(b'\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00')   # connection refused
                client.close()
                return

            client.sendall(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')       # success
            client.settimeout(None)
            pipe(client, upstream)
        except Exception:
            try:
                client.close()
            except OSError:
                pass
