from playwright.sync_api import sync_playwright

PROXY = {
    "server": "http://151.242.6.157:46609",   # e.g. http://123.45.67.89:8080
    "username": "AZ9J0OZE",         # remove both lines if the proxy has no auth
    "password": "JRPGAERY",
}

TESTS = [
    ("proxy check", "https://api.ipify.org?format=json"),
    ("target", "https://thatsthem.com/"),
]

def run(use_proxy: bool, headless: bool):
    print(f"\n=== proxy={use_proxy} headless={headless} ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            proxy=PROXY if use_proxy else None,
            # channel="chrome",  # uncomment to use installed Google Chrome
        )
        page = browser.new_context().new_page()
        for label, url in TESTS:
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                print(f"[OK ] {label}: status {resp.status}")
                if label == "proxy check":
                    print("      IP seen:", page.inner_text("body"))
            except Exception as e:
                print(f"[ERR] {label}: {str(e).splitlines()[0]}")
        browser.close()

run(use_proxy=True,  headless=True)
run(use_proxy=True,  headless=False)
run(use_proxy=False, headless=False)