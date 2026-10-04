# Configuration for the Bark Email Processor
import os

# Google Sheets
# Spreadsheet ID is in the URL: https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
SPREADSHEET_ID = os.getenv('GOOGLE_SHEET_ID', '1wggK4_RkCzbHoUM1wenwYZYozWzpqdyGZNNm9cLHMj4')
SHEET_NAME = os.getenv('SHEET_NAME', 'Contacts')  # Must match the tab name exactly

# Rows that get a Full Name are also copied to this tab (created automatically)
FULLNAME_SHEET_NAME = os.getenv('FULLNAME_SHEET_NAME', 'FullNameContacts')

# ThatsThem lookup: when a lead gets a Full Name, search ThatsThem in a visible
# browser, match its emails against the masked lead email, and write the matched
# email + phone numbers (with all other fields) to this tab.
THATSTHEM_ENABLED = os.getenv('THATSTHEM_ENABLED', 'true').strip().lower() in ('1', 'true', 'yes')
THATSTHEM_WAIT_SECONDS = float(os.getenv('THATSTHEM_WAIT_SECONDS', '30'))   # seconds each ThatsThem page stays open before it is read
# False (default): the email bot does NOT look anyone up on ThatsThem while it processes
# emails; run `python thatsthem_fetch.py` instead (it reads FullNameContacts and fills
# EmailPhoneContacts). True: also do the lookup inside the bot, as before.
THATSTHEM_INLINE = os.getenv('THATSTHEM_INLINE', 'false').strip().lower() in ('1', 'true', 'yes')
EMAIL_PHONE_SHEET_NAME = os.getenv('EMAIL_PHONE_SHEET_NAME', 'EmailPhoneContacts')

# SOCKS5 proxy for the ThatsThem lookup. Put proxies in proxies.txt (one per line) or in
# the SOCKS5_PROXIES environment variable; each lookup uses the next one in the list.
# With USE_PROXY on and no proxy configured, the lookup is skipped (no direct connection).
THATSTHEM_USE_PROXY = os.getenv('THATSTHEM_USE_PROXY', 'true').strip().lower() in ('1', 'true', 'yes')
PROXY_FILE = os.getenv('PROXY_FILE', 'proxies.txt')
PROXY_MAX_ATTEMPTS = int(os.getenv('PROXY_MAX_ATTEMPTS', '3'))   # tries per lookup if a proxy is dead
# If every proxy fails (or none is configured), open the ThatsThem link directly, without a proxy.
# Set to false to skip the lookup instead.
THATSTHEM_DIRECT_FALLBACK = os.getenv('THATSTHEM_DIRECT_FALLBACK', 'true').strip().lower() in ('1', 'true', 'yes')

# Browser for Selenium. Normally nothing to set: installed Google Chrome, or the Chromium from
# `python -m playwright install chromium`, is found automatically.
CHROME_BINARY = os.getenv('CHROME_BINARY', '').strip()          # full path to chrome.exe (optional)
CHROMEDRIVER_PATH = os.getenv('CHROMEDRIVER_PATH', '').strip()  # full path to chromedriver.exe (optional)

# Email processing
MAX_EMAILS = 20                      # Max emails fetched per run
EMAIL_QUERY = '{from:team@bark.com from:team@bark-mail.com} -in:trash'   # Gmail search query

# Click the first dashboard link (https://www.bark.com/sellers/dashboard/?clktrk=...)
# in every email that is added to / updated in the sheet. Set CLICK_LINKS=false to turn off.
CLICK_LINKS = os.getenv('CLICK_LINKS', 'true').strip().lower() in ('1', 'true', 'yes')
# 'browser' = open the link in a visible (headed) Chromium window with your saved
#             Bark login (run `python bark_login.py` once first)
# 'http'    = plain HTTP GET, no browser
CLICK_MODE = os.getenv('CLICK_MODE', 'browser').strip().lower()
CLICK_WAIT_SECONDS = float(os.getenv('CLICK_WAIT_SECONDS', '5'))  # time to keep the page open
# Every click is logged to this tab (time + receiving email + Project ID).
CLICK_LOG_SHEET_NAME = os.getenv('CLICK_LOG_SHEET_NAME', 'ClickLog')
# A receiving email that clicked any link within this many hours is not clicked again.
CLICK_COOLDOWN_HOURS = float(os.getenv('CLICK_COOLDOWN_HOURS', '24'))

# After an email's lead data has been written to the sheet (and the click / lookups are done),
# remove that email from the Gmail account the script reads.
#   DELETE_MODE='trash'  -> move to Trash (recoverable for 30 days)  [default]
#   DELETE_MODE='delete' -> delete permanently (cannot be undone)
# Every email the script has finished with is removed: added to the sheet, duplicate,
# not a lead, or already treated in an earlier run. Emails that FAILED (they will be
# retried) are kept, because the email is the only copy of the lead data.
DELETE_PROCESSED_EMAILS = os.getenv('DELETE_PROCESSED_EMAILS', 'true').strip().lower() in ('1', 'true', 'yes')
DELETE_MODE = os.getenv('DELETE_MODE', 'trash').strip().lower()

# Telegram (secrets come from environment variables, never hardcode them)
#   setx TELEGRAM_BOT_TOKEN "<new token from @BotFather>"
#   setx TELEGRAM_CHAT_ID   "<your chat id>"
#   setx TELEGRAM_ENABLED   "true"
# Open a NEW terminal after setx so the values are picked up.
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
TELEGRAM_ENABLED = os.getenv('TELEGRAM_ENABLED', 'false').strip().lower() in ('1', 'true', 'yes')

# Optional: send Telegram through a proxy (Telegram is blocked on some networks), e.g.
#   setx TELEGRAM_PROXY "socks5h://user:pass@host:1080"      (needs: pip install "requests[socks]")
TELEGRAM_PROXY = os.getenv('TELEGRAM_PROXY', '').strip()

# Slack (Incoming Webhook). Alerts are sent when SLACK_WEBHOOK_URL is set.
#   setx SLACK_WEBHOOK_URL "https://hooks.slack.com/services/XXX/YYY/ZZZ"
# The URL is a secret: anyone with it can post to your channel. Don't commit or share it.
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL', '').strip()
SLACK_ENABLED = os.getenv('SLACK_ENABLED', 'true').strip().lower() in ('1', 'true', 'yes')

# ---------------------------------------------------------------- send_emails.py (outreach mail)
# Sending account (SMTP). Gmail example: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, SMTP_USER=you@gmail.com,
# SMTP_PASSWORD=<16-character App Password> (Google Account > Security > 2-Step Verification > App passwords).
#   setx SMTP_USER "you@gmail.com"
#   setx SMTP_PASSWORD "xxxxxxxxxxxxxxxx"
#   setx MAIL_FROM_NAME "Your Name"
#   setx MAIL_POSTAL_ADDRESS "Your Company, 123 Main St, City, ST 12345"
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))            # 587 = STARTTLS, 465 = SSL
SMTP_USER = os.getenv('SMTP_USER', '').strip()
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
MAIL_FROM_NAME = os.getenv('MAIL_FROM_NAME', '').strip()
MAIL_FROM_EMAIL = os.getenv('MAIL_FROM_EMAIL', '').strip() or SMTP_USER
MAIL_REPLY_TO = os.getenv('MAIL_REPLY_TO', '').strip()
# A valid postal address is required in commercial email by US law (CAN-SPAM); it is added to the footer.
MAIL_POSTAL_ADDRESS = os.getenv('MAIL_POSTAL_ADDRESS', '').strip()
MAIL_REQUIRE_ADDRESS = os.getenv('MAIL_REQUIRE_ADDRESS', 'true').strip().lower() in ('1', 'true', 'yes')
MAIL_DAILY_LIMIT = int(os.getenv('MAIL_DAILY_LIMIT', '100'))   # max emails per calendar day
MAIL_TEMPLATE_FILE = os.getenv('MAIL_TEMPLATE_FILE', 'email_template.txt')
