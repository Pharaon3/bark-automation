# chromedriver_manager.py
"""
Fallback for when Selenium's built-in driver download ("Selenium Manager") fails with
"Unable to obtain driver for chrome".

  1. finds the version of the installed Chrome,
  2. looks up the matching chromedriver in Google's "Chrome for Testing" index,
  3. downloads it - directly first, then through your SOCKS5 proxies (proxies.txt) - which
     helps when Google's download servers are blocked from the server's own connection,
  4. caches it in %LOCALAPPDATA%\\bark_chromedriver\\<version>\\ so it is only downloaded once.

Standard library only.
"""
import http.client
import io
import json
import os
import re
import ssl
import subprocess
import sys
import zipfile
from urllib.parse import urljoin, urlparse

from config import PROXY_FILE, PROXY_MAX_ATTEMPTS
from proxy_pool import load_proxies, next_proxy
from socks_relay import connect_via_upstream

CACHE_DIR = os.path.join(os.getenv('LOCALAPPDATA') or os.path.expanduser('~'), 'bark_chromedriver')

INDEX_BY_BUILD = ('https://googlechromelabs.github.io/chrome-for-testing/'
                  'latest-patch-versions-per-build-with-downloads.json')
INDEX_BY_MILESTONE = ('https://googlechromelabs.github.io/chrome-for-testing/'
                      'latest-versions-per-milestone-with-downloads.json')

_VERSION_RE = re.compile(r'\d+\.\d+\.\d+\.\d+')


# ---------------------------------------------------------------- Chrome version
def chrome_version(binary):
    """Version string like '130.0.6723.92' of the Chrome at `binary`, or None."""
    if not binary:
        return None

    # 1. Windows Chrome keeps a folder named after its version next to chrome.exe
    try:
        versions = [d for d in os.listdir(os.path.dirname(binary)) if _VERSION_RE.fullmatch(d)]
        if versions:
            return max(versions, key=lambda v: tuple(int(p) for p in v.split('.')))
    except OSError:
        pass

    # 2. File properties through PowerShell (works for any chrome.exe, e.g. Playwright's)
    if sys.platform == 'win32':
        try:
            out = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 f"(Get-Item -LiteralPath '{binary}').VersionInfo.ProductVersion"],
                capture_output=True, text=True, timeout=30).stdout
            found = _VERSION_RE.search(out)
            if found:
                return found.group(0)
        except (OSError, subprocess.SubprocessError):
            pass

    # 3. Linux / macOS print their version
    try:
        out = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=20).stdout
        found = _VERSION_RE.search(out)
        if found:
            return found.group(0)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _platform():
    if sys.platform == 'win32':
        return 'win64' if sys.maxsize > 2 ** 32 else 'win32'
    if sys.platform.startswith('linux'):
        return 'linux64'
    return None


def _driver_filename():
    return 'chromedriver.exe' if (_platform() or '').startswith('win') else 'chromedriver'


def _build_of(version):
    return '.'.join(version.split('.')[:3])


def cached_chromedriver(binary):
    """Path of an already downloaded chromedriver for this Chrome build, or None."""
    version = chrome_version(binary)
    if not version:
        return None
    path = os.path.join(CACHE_DIR, _build_of(version), _driver_filename())
    return path if os.path.exists(path) else None


# ---------------------------------------------------------------- HTTPS (direct or via SOCKS5)
class _TunnelHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that goes through a SOCKS5 proxy (proxy_pool.Proxy), logging in if needed."""

    def __init__(self, host, port, proxy, timeout, context):
        super().__init__(host, port, timeout=timeout, context=context)
        self._tunnel_proxy = proxy
        self._tunnel_context = context

    def connect(self):
        name = self.host.encode('idna')
        sock = connect_via_upstream(self._tunnel_proxy, 3, bytes([len(name)]) + name,
                                    self.port.to_bytes(2, 'big'), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self.sock = self._tunnel_context.wrap_socket(sock, server_hostname=self.host)


def http_get(url, proxy=None, timeout=30, context=None):
    """GET `url` (https) and return the body bytes. Follows redirects. Raises OSError on failure."""
    context = context or ssl.create_default_context()
    for _ in range(6):
        parts = urlparse(url)
        port = parts.port or 443
        path = (parts.path or '/') + (f'?{parts.query}' if parts.query else '')
        if proxy is None:
            conn = http.client.HTTPSConnection(parts.hostname, port, timeout=timeout, context=context)
        else:
            conn = _TunnelHTTPSConnection(parts.hostname, port, proxy, timeout, context)
        try:
            conn.request('GET', path, headers={'User-Agent': 'Mozilla/5.0',
                                               'Accept-Encoding': 'identity'})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader('Location') or '')
                response.read()
                continue
            if response.status != 200:
                raise OSError(f'HTTP {response.status} from {parts.hostname}')
            return response.read()
        except (http.client.HTTPException, ssl.SSLError) as e:
            raise OSError(f'{type(e).__name__}: {e}') from e
        finally:
            conn.close()
    raise OSError('too many redirects')


def fetch(url, timeout=30):
    """Download `url`: directly first, then through the SOCKS5 proxies (rotation)."""
    errors = []

    try:
        return http_get(url, None, min(timeout, 20))
    except OSError as e:
        errors.append(f'direct: {type(e).__name__}: {str(e)[:100]}')

    proxies = load_proxies(PROXY_FILE)
    for _ in range(min(len(proxies), max(1, PROXY_MAX_ATTEMPTS))):
        proxy = next_proxy(proxies)
        try:
            return http_get(url, proxy, timeout)
        except OSError as e:
            errors.append(f'proxy {proxy.label}: {type(e).__name__}: {str(e)[:100]}')

    raise OSError('could not download ' + urlparse(url).hostname + ' (' + '; '.join(errors) + ')')


# ---------------------------------------------------------------- find + download the driver
def find_driver_url(version, platform=None):
    """Download URL of the chromedriver zip matching Chrome `version`."""
    platform = platform or _platform()
    if not platform:
        raise RuntimeError('automatic chromedriver download supports Windows and Linux only')

    def pick(downloads):
        for item in (downloads or {}).get('chromedriver', []):
            if item.get('platform') == platform:
                return item['url']
        return None

    build, major = _build_of(version), version.split('.')[0]

    data = json.loads(fetch(INDEX_BY_BUILD))
    url = pick(data.get('builds', {}).get(build, {}).get('downloads'))
    if url:
        return url

    data = json.loads(fetch(INDEX_BY_MILESTONE))
    url = pick(data.get('milestones', {}).get(major, {}).get('downloads'))
    if url:
        return url
    raise RuntimeError(f'no chromedriver listed for Chrome {version} ({platform})')


def ensure_chromedriver(binary):
    """
    Return the path of a chromedriver matching the Chrome at `binary`, downloading it
    if it is not cached yet. Raises RuntimeError / OSError with a readable reason.
    """
    version = chrome_version(binary)
    if not version:
        raise RuntimeError('could not read the Chrome version' if binary
                           else 'no Chrome found to match a driver to')

    target = os.path.join(CACHE_DIR, _build_of(version), _driver_filename())
    if os.path.exists(target):
        return target

    print(f"Downloading chromedriver for Chrome {version} ...")
    url = find_driver_url(version)
    archive = zipfile.ZipFile(io.BytesIO(fetch(url, timeout=120)))
    member = next((n for n in archive.namelist() if n.endswith('/' + _driver_filename())
                   or n == _driver_filename()), None)
    if not member:
        raise RuntimeError('the downloaded archive has no chromedriver in it')

    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + '.part'
    with open(tmp, 'wb') as f:
        f.write(archive.read(member))
    os.replace(tmp, target)
    if not _driver_filename().endswith('.exe'):
        os.chmod(target, 0o755)
    print(f"chromedriver saved to {target}")
    return target
