# thatsthem.py
"""
Look a lead up on ThatsThem and return the email + phone numbers of the profile
whose email matches the masked email pattern from the Bark lead.

The page is loaded with Selenium (a visible Chrome window), optionally through a
rotating SOCKS5 proxy (see proxy_pool.py). On ThatsThem, emails and phone numbers
are shown partly redacted, but each one sits in an element like
    <span x-href="L2VtYWlsL2FsbGlkb2lzY3V0QHlhaG9vLmNvbQ==">a<span class="redacted"></span>@yahoo.com</span>
where x-href is base64 of "/email/allidoiscut@yahoo.com" (phones: "/phone/323-378-7861").
"""
import base64
import contextlib
import glob
import os
import re
import shutil
import sys
import time
from urllib.parse import quote

from bs4 import BeautifulSoup

from config import (THATSTHEM_USE_PROXY, THATSTHEM_DIRECT_FALLBACK, PROXY_FILE,
                    PROXY_MAX_ATTEMPTS, CHROME_BINARY, CHROMEDRIVER_PATH)
from proxy_pool import load_proxies, next_proxy
from socks_relay import LocalSocks5Relay
import chromedriver_manager

SEARCH_URL = 'https://thatsthem.com/search'

_URL_RE = re.compile(r"https?://\S+")

BLOCK_MARKERS = ('captcha', 'verify you are human', 'just a moment', 'access denied', 'unusual traffic')


# ---------------------------------------------------------------- URL
def normalize_address(address):
    """'Los Angeles, CA 90019' -> 'Los Angeles, CA, 90019' (format ThatsThem uses)."""
    address = (address or '').strip().rstrip(':').strip()
    return re.sub(r'\s*,?\s*(\d{5}(?:-\d{4})?)$', r', \1', address)


def build_search_url(full_name, address):
    return (f"{SEARCH_URL}?name={quote((full_name or '').strip(), safe='')}"
            f"&address={quote(normalize_address(address), safe='')}")


# ---------------------------------------------------------------- parsing
def decode_x_href(value):
    """Base64-decode an x-href value; returns '' if it isn't valid base64."""
    try:
        padded = value + '=' * (-len(value) % 4)
        return base64.b64decode(padded).decode('utf-8', errors='ignore')
    except Exception:
        return ''


def parse_records(html):
    """
    Return a list of profiles: [{'name': str, 'emails': [...], 'phones': [...]}].
    Each profile is a <div class="record">; if the page has none, the whole
    page is treated as a single profile.
    """
    soup = BeautifulSoup(html, 'html.parser')
    containers = soup.select('div.record') or [soup]

    records = []
    for container in containers:
        emails, phones = [], []
        for el in container.find_all(attrs={'x-href': True}):
            target = decode_x_href(el['x-href'])
            if target.startswith('/email/'):
                email = target[len('/email/'):].strip()
                if email and email not in emails:
                    emails.append(email)
            elif target.startswith('/phone/'):
                phone = target[len('/phone/'):].strip()
                if phone and phone not in phones:
                    phones.append(phone)

        heading = container.find(['h1', 'h2']) if container is not soup else None
        records.append({
            'name': heading.get_text(' ', strip=True) if heading else '',
            'emails': emails,
            'phones': phones,
        })
    return records


def match_email_pattern(email, pattern):
    """Same length and every non-'*' character equal (case-insensitive)."""
    email, pattern = email.lower(), pattern.lower()
    if len(email) != len(pattern):
        return False
    return all(pc == '*' or ec == pc for ec, pc in zip(email, pattern))


def find_match(records, email_pattern):
    """
    Return {'email': matched email, 'phones': [all phones of the matching
    profile(s)]} or None. If several profiles contain the matched email,
    their phone numbers are merged.
    """
    matched_email = None
    for record in records:
        for email in record['emails']:
            if match_email_pattern(email, email_pattern):
                matched_email = email
                break
        if matched_email:
            break
    if not matched_email:
        return None

    phones = []
    for record in records:
        if matched_email.lower() in (e.lower() for e in record['emails']):
            for phone in record['phones']:
                if phone not in phones:
                    phones.append(phone)
    return {'email': matched_email, 'phones': phones}


# ---------------------------------------------------------------- browser
DIRECT_ATTEMPTS = 2     # tries when connecting without a proxy

LAUNCH_HELP = (
    "Chrome could not be started (this is not a proxy problem). What to do:\n"
    "  1. Run  python thatsthem.py --check  : it shows the Chrome version, whether Google's download\n"
    "     servers can be reached (directly and through your proxies), and the exact error.\n"
    "  2. Or download chromedriver yourself (same version as Chrome) from\n"
    "     https://googlechromelabs.github.io/chrome-for-testing/  and set CHROMEDRIVER_PATH to the .exe.\n"
    "  3. Make sure Google Chrome is installed (or run: python -m playwright install chromium),\n"
    "     and update Selenium:  pip install -U selenium"
)


class BrowserLaunchError(RuntimeError):
    """Chrome / chromedriver could not be started (not a proxy or network problem)."""


def find_chrome_binary():
    """
    Path of the Chrome/Chromium to drive, or None to let Selenium look for Chrome itself.
    Order: CHROME_BINARY, installed Google Chrome, Playwright's Chromium, chrome on PATH.
    """
    if CHROME_BINARY:
        if os.path.exists(CHROME_BINARY):
            return CHROME_BINARY
        print(f"Warning: CHROME_BINARY does not exist ({CHROME_BINARY}); looking for Chrome elsewhere.")

    for root in (os.getenv('PROGRAMFILES'), os.getenv('PROGRAMFILES(X86)'), os.getenv('LOCALAPPDATA')):
        if root:
            path = os.path.join(root, 'Google', 'Chrome', 'Application', 'chrome.exe')
            if os.path.exists(path):
                return path

    playwright_root = os.getenv('PLAYWRIGHT_BROWSERS_PATH')
    if not playwright_root or playwright_root == '0':
        playwright_root = os.path.join(os.getenv('LOCALAPPDATA') or '', 'ms-playwright')
    matches = glob.glob(os.path.join(playwright_root, 'chromium-*', 'chrome-win*', 'chrome.exe'))
    if matches:
        def revision(path):
            found = re.search(r'chromium-(\d+)', path)
            return int(found.group(1)) if found else 0
        return max(matches, key=revision)

    for name in ('google-chrome', 'chromium', 'chromium-browser', 'chrome'):
        path = shutil.which(name)
        if path:
            return path
    return None


@contextlib.contextmanager
def _chrome_proxy_server(proxy):
    """
    Yield the value for Chrome's --proxy-server flag (or None for a direct connection).
    Chrome can't log in to a SOCKS5 proxy, so for proxies with a username/password a
    local relay is started on 127.0.0.1 that does the login and Chrome connects to that.
    """
    if proxy is None:
        yield None
    elif not proxy.has_auth:
        yield f"socks5://{proxy.host}:{proxy.port}"
    else:
        relay = LocalSocks5Relay(proxy)
        port = relay.start()
        try:
            yield f"socks5://127.0.0.1:{port}"
        finally:
            relay.stop()


def _build_options(proxy_server=None):
    from selenium import webdriver

    options = webdriver.ChromeOptions()
    options.add_argument('--window-size=1280,900')
    options.add_argument('--no-first-run')
    options.add_argument('--no-default-browser-check')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    binary = find_chrome_binary()
    if binary:
        options.binary_location = binary
    if proxy_server:
        options.add_argument(f'--proxy-server={proxy_server}')
    return options


def _error_text(error, limit=700):
    """Readable reason for a launch error. Selenium hides the real reason in the
    exception's cause chain, so all of it is included."""
    parts, seen, current = [], set(), error
    while current is not None and id(current) not in seen and len(parts) < 4:
        seen.add(id(current))
        text = ' | '.join(line.strip() for line in str(current).strip().splitlines() if line.strip())
        parts.append(f"{type(current).__name__}: {text}")
        current = current.__cause__ or current.__context__
    return ' <- '.join(parts)[:limit]


def _start_chrome(options):
    """
    Start a visible Chrome. Tries, in order:
      1. the chromedriver in CHROMEDRIVER_PATH,
      2. a chromedriver this script downloaded earlier,
      3. Selenium's own driver download (Selenium Manager),
      4. our own download (directly, then through the SOCKS5 proxies), cached for next time.
    Any failure ends as a BrowserLaunchError, never as a 'bad proxy'.
    """
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.chrome.service import Service

    def launch(driver_path=None):
        kwargs = {'options': options}                 # headed: no --headless
        if driver_path:
            kwargs['service'] = Service(executable_path=driver_path)
        return webdriver.Chrome(**kwargs)

    binary = options.binary_location or find_chrome_binary()

    if CHROMEDRIVER_PATH:
        try:
            return launch(CHROMEDRIVER_PATH)
        except WebDriverException as e:
            raise BrowserLaunchError(
                f"CHROMEDRIVER_PATH does not work: {_error_text(e)}\n{LAUNCH_HELP}") from e

    cached = chromedriver_manager.cached_chromedriver(binary)
    if cached:
        try:
            return launch(cached)
        except WebDriverException as e:
            print(f"Downloaded chromedriver failed to start ({type(e).__name__}); trying the other options.")

    reasons = []
    try:
        return launch()
    except WebDriverException as e:
        reasons.append(f"Selenium's own driver download failed: {_error_text(e)}")

    try:
        driver_path = chromedriver_manager.ensure_chromedriver(binary)
    except Exception as e:
        reasons.append(f"Automatic chromedriver download failed: {type(e).__name__}: {e}")
    else:
        try:
            return launch(driver_path)
        except WebDriverException as e:
            reasons.append(f"The downloaded chromedriver would not start: {_error_text(e)}")

    raise BrowserLaunchError('\n'.join(reasons) + '\n' + LAUNCH_HELP)


def _load_page(url, wait_seconds, proxy):
    """Open `url` in a NEW visible Chrome window, wait, return the page source, close it."""
    with _chrome_proxy_server(proxy) as proxy_server:
        driver = _start_chrome(_build_options(proxy_server))
        try:
            driver.set_page_load_timeout(45)
            driver.get(url)
            time.sleep(wait_seconds)
            return driver.page_source
        finally:
            driver.quit()


def _try_load(url, wait_seconds, proxy, attempt):
    """One load attempt. Returns the HTML, or None on a connection problem.
    BrowserLaunchError (Chrome itself won't start) is NOT swallowed."""
    from selenium.common.exceptions import WebDriverException

    where = f"via proxy {proxy.label}" if proxy else "directly (no proxy)"
    try:
        html = _load_page(url, wait_seconds, proxy)
    except (WebDriverException, OSError) as e:
        # Error text can contain the search URL (name/address): print only a scrubbed first line
        first_line = (str(e).strip().splitlines() or [''])[0][:120]
        print(f"ThatsThem: load failed {where} (attempt {attempt}): {type(e).__name__}: "
              f"{_URL_RE.sub('<url>', first_line)}")
        return None

    print(f"ThatsThem page loaded {where}: {len(html)} chars")
    return html


def fetch_page_html(url, wait_seconds=30):
    """
    Load the page in a new visible Chrome window and return the HTML.

    1. With proxies configured: tries the next proxies in the rotation, up to PROXY_MAX_ATTEMPTS.
    2. If every proxy fails (or none is configured) and THATSTHEM_DIRECT_FALLBACK is on,
       it opens the link directly, without a proxy.
    3. A CAPTCHA / block page is NOT retried from another IP or directly: the lookup is skipped.
    4. If Chrome itself cannot start, BrowserLaunchError is raised (no proxy is blamed).
    """
    proxies = load_proxies(PROXY_FILE) if THATSTHEM_USE_PROXY else []
    html = None

    if proxies:
        for attempt in range(1, max(1, PROXY_MAX_ATTEMPTS) + 1):
            html = _try_load(url, wait_seconds, next_proxy(proxies), attempt)
            if html is not None:
                break
        if html is None:
            if not THATSTHEM_DIRECT_FALLBACK:
                print("ThatsThem: all proxy attempts failed, skipping this lookup.")
                return None
            print("ThatsThem: all proxy attempts failed; opening the link directly (no proxy).")
    elif THATSTHEM_USE_PROXY:
        if not THATSTHEM_DIRECT_FALLBACK:
            print(f"ThatsThem: no SOCKS5 proxies found (add them to {PROXY_FILE} or set SOCKS5_PROXIES). "
                  "Skipping lookup.")
            return None
        print("ThatsThem: no SOCKS5 proxies found; opening the link directly (no proxy).")

    if html is None:
        for attempt in range(1, DIRECT_ATTEMPTS + 1):
            html = _try_load(url, wait_seconds, None, attempt)
            if html is not None:
                break

    if html is None:
        print("ThatsThem: could not load the page, skipping this lookup.")
        return None

    if 'class="record' not in html and any(m in html.lower() for m in BLOCK_MARKERS):
        print("ThatsThem showed a CAPTCHA/block page; skipping this lookup.")
        return None
    return html


def has_profile_cards(html):
    """True if the page shows at least one ThatsThem profile card."""
    return bool(BeautifulSoup(html, 'html.parser').select('div.record'))


def lookup_detailed(full_name, address, email_pattern, wait_seconds=30):
    """
    Full lookup that says WHY there is no result. Returns (status, result):
      ('match', {'email': ..., 'phones': [...]})  a profile's email matches the pattern
      ('no_match', None)    profiles were found, but none has a matching email
      ('no_results', None)  the page showed no profile cards at all (nobody found, or the
                            page did not finish loading)
      ('failed', None)      the page could not be loaded (proxy problems, CAPTCHA/block)
    """
    html = fetch_page_html(build_search_url(full_name, address), wait_seconds)
    if not html:
        return 'failed', None

    records = parse_records(html)
    cards = has_profile_cards(html)
    print(f"ThatsThem: {len(records) if cards else 0} profile(s) parsed")

    result = find_match(records, email_pattern)
    if result:
        return 'match', result
    return ('no_match' if cards else 'no_results'), None


def lookup(full_name, address, email_pattern, wait_seconds=30):
    """
    Full lookup. Returns {'email': ..., 'phones': [...]} when a profile's
    email matches `email_pattern`, otherwise None.
    """
    return lookup_detailed(full_name, address, email_pattern, wait_seconds)[1]


# ---------------------------------------------------------------- self check
def _reachable(url, proxy=None):
    """(ok, detail). Any HTTP answer, even an error page, means the host can be reached."""
    try:
        chromedriver_manager.http_get(url, proxy, timeout=15)
        return True, 'ok'
    except OSError as e:
        text = str(e)
        return text.startswith('HTTP '), text[:100]


def check_setup():
    """python thatsthem.py --check : shows what is installed and tries to start Chrome."""
    print(f"Python   {sys.version.split()[0]}")
    try:
        import selenium
        print(f"Selenium {selenium.__version__}")
    except ImportError:
        print("Selenium is NOT installed. Run: pip install selenium")
        return

    binary = find_chrome_binary()
    print(f"Browser  {binary or 'not found in the usual places (Selenium will try to find Chrome itself)'}")
    print(f"Chrome   version {chromedriver_manager.chrome_version(binary) or 'unknown'}")
    cached = chromedriver_manager.cached_chromedriver(binary)
    print(f"Driver   {CHROMEDRIVER_PATH or cached or 'none cached yet (downloaded automatically on first start)'}")

    if not CHROMEDRIVER_PATH and not cached:
        print("\nCan this server reach Google's driver download servers?")
        proxies = load_proxies(PROXY_FILE)
        for host_url in ('https://googlechromelabs.github.io/', 'https://storage.googleapis.com/'):
            host = host_url.split('//')[1].rstrip('/')
            ok, detail = _reachable(host_url)
            print(f"  {host:32} directly: {'OK' if ok else 'FAILED (' + detail + ')'}")
            if not ok and proxies:
                ok, detail = _reachable(host_url, proxies[0])
                print(f"  {'':32} via proxy {proxies[0].label}: {'OK' if ok else 'FAILED (' + detail + ')'}")

    print("\nStarting a test browser window (about:blank)...")
    try:
        driver = _start_chrome(_build_options())
    except BrowserLaunchError as e:
        print(f"\nFAILED:\n{e}")
        return
    try:
        driver.get('about:blank')
        caps = driver.capabilities
        print(f"OK: Chrome {caps.get('browserVersion')} / chromedriver "
              f"{caps.get('chrome', {}).get('chromedriverVersion', '?').split(' ')[0]}")
    finally:
        driver.quit()


if __name__ == '__main__':
    if '--check' in sys.argv:
        check_setup()
    else:
        print("Usage: python thatsthem.py --check")
