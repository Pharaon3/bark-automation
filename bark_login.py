# bark_login.py
"""
Run this ONCE (and again if Bark logs you out):

    python bark_login.py

A browser window opens. Log in to Bark yourself, wait until you can see your
dashboard, then come back to this terminal and press Enter. The session is
saved in the 'bark_browser_profile' folder and reused by the bot.
Your password is typed by you in the browser; this script never sees it.
"""
from playwright.sync_api import sync_playwright
from browser_click import launch_context, PROFILE_DIR


def main():
    with sync_playwright() as p:
        context = launch_context(p)
        page = context.pages[0] if context.pages else context.new_page()
        # Redirects to the login page if you're not signed in yet
        page.goto('https://www.bark.com/sellers/dashboard/')

        print("\nLog in to Bark in the browser window.")
        input("When your dashboard is visible, press Enter here to save the session... ")

        context.close()
    print(f"Session saved to: {PROFILE_DIR}")


if __name__ == '__main__':
    main()
