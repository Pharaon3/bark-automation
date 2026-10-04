# proxy_pool.py
"""
SOCKS5 proxy list + rotation.

Proxies are read from a text file (default: proxies.txt next to the scripts),
one per line, or from the SOCKS5_PROXIES environment variable (separated by
commas, semicolons or newlines). Accepted formats:

    host:port
    host:port:username:password
    username:password@host:port
    socks5://username:password@host:port       (socks5h:// works too)

Lines starting with # are ignored. A single rotating-gateway endpoint (one
line that gives you a new IP per connection) works too: rotation then happens
on the provider's side.
"""
import os
import random
import re
import threading
from dataclasses import dataclass
from urllib.parse import unquote

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass(frozen=True)
class Proxy:
    host: str
    port: int
    username: str = ''
    password: str = ''

    @property
    def has_auth(self):
        return bool(self.username)

    @property
    def label(self):
        """Safe to print: never contains the credentials."""
        return f"{self.host}:{self.port}"


def parse_proxy(line):
    """Parse one proxy line. Returns a Proxy, or None for blank/comment lines.
    Raises ValueError for an unrecognised format."""
    line = (line or '').strip()
    if not line or line.startswith('#'):
        return None

    line = re.sub(r'^socks5h?://', '', line, flags=re.IGNORECASE).rstrip('/')
    username = password = ''

    if '@' in line:
        credentials, hostport = line.rsplit('@', 1)
        username, _, password = credentials.partition(':')
        username, password = unquote(username), unquote(password)
        host, _, port = hostport.rpartition(':')
    else:
        parts = line.split(':')
        if len(parts) == 2:
            host, port = parts
        elif len(parts) == 4:
            host, port, username, password = parts
        else:
            raise ValueError('unrecognised proxy format')

    if not host or not port.isdigit():
        raise ValueError('bad host or port')
    return Proxy(host.strip(), int(port), username, password)


def load_proxies(path='proxies.txt'):
    """Load the proxy list from SOCKS5_PROXIES, else from `path`. Bad lines are
    skipped with a warning that never shows the line itself (it holds credentials)."""
    env_value = os.getenv('SOCKS5_PROXIES', '').strip()
    if env_value:
        lines = re.split(r'[,;\n]+', env_value)
        source = 'SOCKS5_PROXIES'
    else:
        full_path = path if os.path.isabs(path) else os.path.join(BASE_DIR, path)
        if not os.path.exists(full_path):
            return []
        with open(full_path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        source = os.path.basename(full_path)

    proxies = []
    for number, line in enumerate(lines, start=1):
        try:
            proxy = parse_proxy(line)
        except ValueError as e:
            print(f"Warning: ignoring entry {number} in {source}: {e}")
            continue
        if proxy and proxy not in proxies:
            proxies.append(proxy)
    return proxies


# Round-robin with a random starting point, so a restart doesn't always begin
# with the first proxy. The counter lives for the life of the process.
_lock = threading.Lock()
_counter = random.randrange(1_000_000)


def next_proxy(proxies):
    """Return the next proxy in rotation."""
    global _counter
    with _lock:
        proxy = proxies[_counter % len(proxies)]
        _counter += 1
    return proxy
