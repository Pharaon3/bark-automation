# browser_click.py
"""
Open a link in a VISIBLE (headed) Chromium window using a saved Bark login.

It only loads the page. It never clicks anything on the page, so it can't
press "Contact", "Send" or anything else that might spend credits.
"""
import os
from urllib.parse import urlparse

# Saved login session (cookies etc.). Created/updated by bark_login.py.
PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bark_browser_profile')

# Optional: use your installed Chrome/Edge instead of bundled Chromium, e.g.
#   setx BROWSER_CHANNEL chrome      (or "msedge")
BROWSER_CHANNEL = os.getenv('BROWSER_CHANNEL') or None


def launch_context(playwright, profile_dir=None):
    """Headed persistent context shared by the bot, the login helper and the ThatsThem lookup."""
    return playwright.chromium.launch_persistent_context(
        profile_dir or PROFILE_DIR,
        headless=False,                       # <- headed mode: a real window opens
        channel=BROWSER_CHANNEL,
        viewport={'width': 1280, 'height': 900},
    )


def open_link_headed(url, wait_seconds=5):
    """
    Load `url` in a visible browser window, wait for it to settle, then close.
    Returns True if the page loaded with a 2xx/3xx status.
    The URL holds login tokens, so only the final host/path is printed.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    with sync_playwright() as p:
        context = launch_context(p)
        try:
            page = context.pages[0] if context.pages else context.new_page()

            response = page.goto(url, wait_until='domcontentloaded', timeout=45000)
            try:
                page.wait_for_load_state('networkidle', timeout=15000)
            except PlaywrightTimeout:
                pass  # some pages never go idle; that's fine
            page.wait_for_timeout(int(wait_seconds * 1000))

            final = urlparse(page.url)
            status = response.status if response else 'no response'
            print(f"Opened link in browser: HTTP {status} -> {final.netloc}{final.path}")

            if 'login' in final.path.lower() or 'signin' in final.path.lower():
                print("WARNING: landed on a login page. Run `python bark_login.py` to sign in once.")
                return False  # not a real click, so it must not be logged as one

            return bool(response and response.ok)
        finally:
            context.close()
