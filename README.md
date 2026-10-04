# Bark Lead Automation

Turns Bark.com lead emails into a Google Sheet, finds each lead's real email address and phone numbers,
and (optionally) emails them. Everything runs on one Windows PC or VPS.

```
Bark lead emails ──► Gmail (your main account; other accounts forward into it)
        │
        ▼
  scheduler.py / main.py  (every 3 min)
        │   extract fields · duplicate check by Project ID · newest row on top
        ├──► Contacts tab ─────────────────────────────────────────────┐
        │      "You're one step away from…" email adds the Full Name   │
        ├──► FullNameContacts tab (rows that have a Full Name)         │
        ├──► opens the Bark link in Chrome (filters + ClickLog tab)    │
        ├──► Telegram / Slack alerts                                   │
        └──► moves the treated email to Gmail Trash                    │
                                                                       ▼
  thatsthem_fetch.py  (or the Chrome extension)  reads FullNameContacts, looks the person up on ThatsThem,
        │   matches the masked email, collects phone numbers
        └──► EmailPhoneContacts tab ──► alert to Telegram / Slack
                                              │
  send_emails.py  emails the Matched Email ◄──┘   and notes the time in "Email Sent At"
```

## Contents

1. [Features](#features)
2. [Requirements and install](#requirements-and-install)
3. [Setup, step by step](#setup-step-by-step)
4. [Running it](#running-it)
5. [Google Sheet layout](#google-sheet-layout)
6. [How the main rules work](#how-the-main-rules-work)
7. [Configuration (environment variables)](#configuration-environment-variables)
8. [Windows VPS notes](#windows-vps-notes)
9. [Troubleshooting](#troubleshooting)
10. [Files](#files)
11. [Security and responsible use](#security-and-responsible-use)

## Features

- Reads Bark emails from `team@bark.com` and `team@bark-mail.com` in Gmail, including **Spam**, and handles emails that were
  auto-forwarded once or several times (A → B → C).
- Extracts Name, Field, Address, masked Number and Email, Additional Info, Project Details and the **Project ID**.
- **Duplicates are detected by Project ID only.** New rows are inserted at the **top** of every tab (latest first).
- "You're one step away from speaking to *Full Name*" emails add the **Full Name** to the lead's row and copy the row to **FullNameContacts**.
- Opens the first Bark dashboard link of every treated email in a visible Chrome window, with two filters
  (see [click rules](#click-rules)) and a **ClickLog** tab with the time and the receiving email.
- Looks people up on **ThatsThem** (Selenium, rotating SOCKS5 proxies, direct fallback) and writes the matching email and all
  phone numbers to **EmailPhoneContacts**. Also available as a **Chrome extension**.
- **Telegram and Slack alerts** when an email address is extracted.
- Sends outreach email from **Gmail or Outlook** to the matched addresses and notes it in an **Email Sent At** column.
- Moves every treated email to Gmail Trash after it has been handled.
- Logs everything to `email_processor.log`; secrets come from environment variables.

## Requirements and install

- Windows (the instructions use `setx`), Python 3.10 or newer, Google Chrome.
- A Google account for Gmail and Sheets, and a Google Cloud project with an OAuth client.

```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
pip install beautifulsoup4 requests schedule playwright selenium
python -m playwright install chromium          # use "python -m": the plain "playwright" command is often not on PATH
```

Optional: `pip install msal` (sending through Outlook with OAuth2) and `pip install "requests[socks]"` (Telegram through a proxy).

## Setup, step by step

### 1. Google API access (Gmail + Sheets)

1. In the [Google Cloud Console](https://console.cloud.google.com/) create or pick a project and enable the **Gmail API** and **Google Sheets API**.
2. **OAuth consent screen:** add your Google account under *Test users*, then click **Publish app**. Without publishing, the sign-in
   expires every 7 days.
3. **Credentials > Create credentials > OAuth client ID > Application type: Desktop app** (not "Web application", or you get
   `redirect_uri_mismatch`). Download the JSON and save it as `GmailBot_credentials.json` in the project folder.
4. The first run opens a browser to sign in and creates `token.json` (Gmail) and `sheets_token.json` (Sheets). The Gmail permission is
   `gmail.modify` (read + Trash). If you used an older read-only token, the script notices and asks you to sign in again.
5. Google shows "unverified app" for your own project: **Advanced > Go to ... (unsafe)** and allow.

### 2. The spreadsheet

Create a Google Sheet, copy the ID from its URL (`https://docs.google.com/spreadsheets/d/<ID>/edit`) and set it:

```
setx GOOGLE_SHEET_ID "<ID>"        (or edit SPREADSHEET_ID in config.py)
```

The tabs and their headers are created automatically. The signed-in Google account needs edit access.

### 3. Forwarding (if your Bark accounts are on other mailboxes)

Set up auto-forwarding from each account into the Gmail the bot reads. Forwarding twice (A → B → C) works: the original receiving
address is read from the `X-Forwarded-For` / `Delivered-To` headers. If Outlook forwards, use **Redirect** rather than Forward so the
sender stays `team@bark.com`.

### 4. Bark login for link clicking (once)

```
python bark_login.py
```

A browser opens: sign in to Bark yourself, wait for the dashboard, press Enter in the terminal. The session is saved in
`bark_browser_profile/`. Repeat if Bark logs you out. Set `CLICK_LINKS=false` to turn clicking off.

### 5. Alerts (optional)

Telegram: create a bot with `@BotFather` (`/newbot`), message it once, open `https://api.telegram.org/bot<TOKEN>/getUpdates` to find
`"chat":{"id": ...}`.

```
setx TELEGRAM_BOT_TOKEN "<token>"
setx TELEGRAM_CHAT_ID "<chat id>"
setx TELEGRAM_ENABLED "true"
setx TELEGRAM_PROXY "socks5h://user:pass@host:1080"      (only if Telegram is blocked on your network)
```

Slack: <https://api.slack.com/apps> > Create New App > *Incoming Webhooks* > On > *Add New Webhook to Workspace* > copy the URL.

```
setx SLACK_WEBHOOK_URL "https://hooks.slack.com/services/..."
```

Open a **new** terminal (so `setx` takes effect) and test with `python test_notifications.py`.

### 6. Email scan with Enformion (optional)

```
setx ENFORMION_AP_NAME "<name>"
setx ENFORMION_AP_PASSWORD "<password>"
```

Put last names to try, one per line, in `lastname.txt`. Without credentials the scan is skipped.

### 7. ThatsThem lookup (optional)

Needs Google Chrome plus Selenium. Check the setup first:

```
python thatsthem.py --check
```

It prints the Chrome version, tests whether Google's driver download servers are reachable (directly and through your proxies),
and starts a test browser. Selenium downloads the matching chromedriver itself; if that fails, the script downloads it (also through
your proxies) and caches it. As a last resort download chromedriver by hand and set `CHROMEDRIVER_PATH`.

Proxies (optional): copy `proxies.example.txt` to `proxies.txt`, one SOCKS5 proxy per line (`host:port`, `user:pass@host:port`,
`host:port:user:pass`, `socks5://user:pass@host:port`). Each lookup uses the next proxies in the list; if all fail, the page is opened
directly (`THATSTHEM_DIRECT_FALLBACK`). A CAPTCHA or block page is never worked around: the lookup is skipped.

### 8. Sending email (optional)

Edit the message in `email_template.txt` (first line `Subject: ...`; placeholders `{first_name}` `{full_name}` `{field}` `{city}` `{address}`
`{project_id}` `{sender_name}`). Then choose one account:

**Gmail** (needs 2-Step Verification, then an App Password at <https://myaccount.google.com/apppasswords>):

```
setx SMTP_USER "you@gmail.com"
setx SMTP_PASSWORD "<16-character app password, no spaces>"
```

**Outlook / Hotmail / Microsoft 365:** Microsoft is retiring password logins for SMTP, so OAuth2 is the dependable way:

```
pip install msal
setx SMTP_USER "you@outlook.com"
setx SMTP_AUTH "oauth2-microsoft"
setx MS_CLIENT_ID "<Application (client) ID of your Azure app registration>"
setx MS_TENANT "consumers"                      (use "organizations" for a work/school account)
python send_emails.py --login                   (once: prints a code and a web address to sign in)
```

For both:

```
setx MAIL_FROM_NAME "Your Name"
setx MAIL_POSTAL_ADDRESS "Your Company, 123 Main St, City, ST 12345"
```

Open a new terminal, then `python send_emails.py --test you@example.com` to send one sample to yourself.

## Running it

| What | Command |
|---|---|
| Process emails once | `python main.py` |
| Process emails every 3 minutes | `python scheduler.py` |
| ThatsThem lookups (one pass) | `python thatsthem_fetch.py` |
| ThatsThem lookups every 30 min | `python thatsthem_fetch.py --loop 30` |
| Send emails (one pass) | `python send_emails.py` |
| Send emails every 30 min | `python send_emails.py --loop 30` |

Useful options:

- `thatsthem_fetch.py`: `--dry-run` (list only), `--limit N`, `--delay S`, `--recheck` (retry rows that had no match), `--max-failures N`.
- `send_emails.py`: `--dry-run` (list + preview of the first email), `--test ADDRESS`, `--limit N`, `--delay S` (default 30), `--login`.
- `python thatsthem.py --check` diagnoses Chrome/chromedriver/proxy problems. `python test_notifications.py` tests Telegram and Slack.

Typical set-up on a server: three Task Scheduler tasks "At log on" running `scheduler.py`, `thatsthem_fetch.py --loop 30` and
`send_emails.py --loop 30`. Start with the `--dry-run` options before sending anything.

**Chrome extension:** `thatsthem-extension.zip` is the ThatsThem lookup as a Chrome extension (no chromedriver). Unzip it, load it at
`chrome://extensions` (Developer mode > Load unpacked), and follow `thatsthem-extension/README.md` (an Apps Script gives it access to the
sheet). Limitation: Chrome cannot log in to SOCKS5 proxies, so use proxies without username/password there.

## Google Sheet layout

| Tab | Columns | Filled by |
|---|---|---|
| **Contacts** | A-J: Name, Field, Address, Number, Email, Additional Info, Project Details, Scanned Emails, Project ID, Full Name | the email bot |
| **FullNameContacts** | A-J, same as Contacts | a copy of every row that has a Full Name |
| **EmailPhoneContacts** | A-J plus K: Matched Email, L: Phone Numbers, M: **Email Sent At** | `thatsthem_fetch.py` / the extension; M by `send_emails.py` |
| **ClickLog** | Clicked At, Received By, Project ID, Name, Message ID | the email bot, after each click |

New rows go to row 2 (just under the header), so the newest is first. `python reverse_existing_rows.py` flips rows that already existed;
run it once, **before** the updated bot adds new rows.

## How the main rules work

**Email processing**
- An email is marked processed (`processed_emails.json`) only when it is finished: added, duplicate, or not a lead. Sheet or network
  errors leave it in the mailbox and it is retried on the next run.
- Every finished email, including duplicates and non-lead mail, is then moved to Gmail Trash (`DELETE_MODE=trash`, recoverable 30 days;
  `delete` removes permanently, `DELETE_PROCESSED_EMAILS=false` turns it off). Emails that failed are never removed.
- If a "one step away" email arrives before the lead email, a placeholder row (Project ID + Full Name) is created and the lead email fills it in.

### Click rules
- Only the **first** link starting with `https://www.bark.com/sellers/dashboard/?clktrk=` in an email is opened, in a visible Chromium window.
- **Skipped** if the same Project ID was already clicked from any receiving email, or if that receiving email already clicked any link in the last
  24 hours (`CLICK_COOLDOWN_HOURS`). Each click is logged in ClickLog.
- Landing on a Bark login page does not count as a click (run `bark_login.py`).

**ThatsThem matching**
- Search URL: `https://thatsthem.com/search?name=<Full Name>&address=<Address>`. The page stays open `THATSTHEM_WAIT_SECONDS` (default 30).
- Emails on the page are base64 in `x-href` attributes; they are decoded and compared with the masked lead email: same length and every
  non-`*` character equal. The phone numbers of every profile that contains the matched email are collected.
- Rows already in EmailPhoneContacts (by Project ID) are skipped. "No match" is remembered in `thatsthem_checked.json`; a page with no
  profiles is tried twice; failed loads are retried; a run stops after 3 failed loads in a row.

**Sending**
- One email per address, even if it appears in several rows. Skips `do_not_contact.txt` (addresses or `@domain.com`), invalid addresses, and
  addresses the server rejected (`email_rejected.json`).
- Every email gets your postal address, an opt-out line and a `List-Unsubscribe` header. Sending is refused until `MAIL_POSTAL_ADDRESS` is set.
- Limits: 30 seconds between emails and `MAIL_DAILY_LIMIT` (100) per day. Each send is first saved in `email_sent_log.json`, then noted in
  column M, so a failed sheet update can never cause a second email.

## Configuration (environment variables)

Set with `setx NAME "value"`, then open a new terminal. Defaults are in `config.py`.

| Variable | Default | Meaning |
|---|---|---|
| `GOOGLE_SHEET_ID` | set in `config.py` | the spreadsheet |
| `SHEET_NAME` | `Contacts` | main tab |
| `FULLNAME_SHEET_NAME` / `EMAIL_PHONE_SHEET_NAME` / `CLICK_LOG_SHEET_NAME` | `FullNameContacts` / `EmailPhoneContacts` / `ClickLog` | tab names |
| `CLICK_LINKS` | `true` | open Bark links |
| `CLICK_MODE` | `browser` | `browser` (visible Chromium, saved login) or `http` |
| `CLICK_WAIT_SECONDS` / `CLICK_COOLDOWN_HOURS` | `5` / `24` | page time / per-mailbox cooldown |
| `DELETE_PROCESSED_EMAILS` / `DELETE_MODE` | `true` / `trash` | clean up Gmail (`trash` or `delete`) |
| `ENFORMION_AP_NAME` / `ENFORMION_AP_PASSWORD` | - | email scan credentials |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `TELEGRAM_ENABLED` / `TELEGRAM_PROXY` | - / - / `false` / - | Telegram |
| `SLACK_WEBHOOK_URL` / `SLACK_ENABLED` | - / `true` | Slack |
| `THATSTHEM_WAIT_SECONDS` | `30` | seconds each ThatsThem page stays open |
| `THATSTHEM_INLINE` | `false` | also do the lookup inside the email bot |
| `THATSTHEM_USE_PROXY` / `PROXY_FILE` / `SOCKS5_PROXIES` | `true` / `proxies.txt` / - | proxies |
| `PROXY_MAX_ATTEMPTS` / `THATSTHEM_DIRECT_FALLBACK` | `3` / `true` | proxy tries / open directly if all fail |
| `CHROME_BINARY` / `CHROMEDRIVER_PATH` | auto | only if Chrome or chromedriver are in an unusual place |
| `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_HOST` / `SMTP_PORT` | - / - / from address / `587` | sending account |
| `SMTP_AUTH` / `MS_CLIENT_ID` / `MS_TENANT` | `password` / - / `consumers` | Outlook OAuth2 |
| `MAIL_FROM_NAME` / `MAIL_FROM_EMAIL` / `MAIL_REPLY_TO` | - | sender details |
| `MAIL_POSTAL_ADDRESS` / `MAIL_REQUIRE_ADDRESS` | - / `true` | footer address, and whether it is mandatory |
| `MAIL_DAILY_LIMIT` / `MAIL_TEMPLATE_FILE` | `100` / `email_template.txt` | daily cap / message file |

The Gmail query and `MAX_EMAILS` are set in `config.py` (`EMAIL_QUERY` keeps `-in:trash` so treated mail is not read again).

## Windows VPS notes

- **Resources:** 2 vCPU / 2 GB RAM is enough on Windows Server with Desktop Experience (Chrome peaks around 400-700 MB, one at a time); 4 GB is comfortable.
- **Run in a logged-in desktop session, not as a Windows service.** The browsers are visible and need a desktop. Use auto-logon plus Task Scheduler
  "At log on". Closing the RDP window normally keeps the session alive; signing out does not.
- Do the Google, Bark and Microsoft sign-ins once over RDP. Publish the OAuth app so tokens do not expire weekly.
- `email_processor.log` has no size limit; check it occasionally. Lock RDP down (strong password, NLA, allow only your IP).

## Troubleshooting

| Problem | Fix |
|---|---|
| `Error 400: redirect_uri_mismatch` | the OAuth client must be of type **Desktop app** |
| `Error 403: access_denied` (not verified) | add your account under Test users, or publish the app |
| Sign-in needed every week | consent screen is in *Testing*: click **Publish app** |
| `'playwright' is not recognized` | use `python -m playwright install chromium` |
| `NoSuchDriverException: Unable to obtain driver for chrome` | run `python thatsthem.py --check` and follow its output; set `CHROMEDRIVER_PATH` as a last resort |
| Telegram times out | Telegram is blocked on the network: use a VPN or `TELEGRAM_PROXY` |
| Emails are not moved to Trash | delete `token.json` and run again to grant the `gmail.modify` permission |
| Bark links open a login page | run `python bark_login.py` again |
| ThatsThem: "CAPTCHA/block page" | the lookup is skipped on purpose; wait, or ask ThatsThem to allow your IP |
| `SMTPAuthenticationError` (Gmail) | use an App Password without spaces, with 2-Step Verification on |
| `SMTPAuthenticationError` (Outlook) | use `SMTP_AUTH=oauth2-microsoft` and run `python send_emails.py --login` |
| "Cannot send yet: MAIL_POSTAL_ADDRESS is not set" | set your postal address |
| A row was not added | check `Project ID`: duplicates are matched only by it; look at `email_processor.log` |
| Re-process an old email | remove its ID from `processed_emails.json` (careful: clicks and removals will run again) |

## Files

| File | Purpose |
|---|---|
| `main.py`, `scheduler.py` | run the email bot once / every 3 minutes |
| `bot.py` | read Gmail, extract fields, write sheets, click, alert, clean up |
| `auth.py`, `sheets.py` | Gmail and Google Sheets access (and the sheet helpers) |
| `browser_click.py`, `bark_login.py` | open Bark links in Chromium; one-time Bark login |
| `notifier.py`, `telegram_bot.py`, `test_notifications.py` | Telegram and Slack alerts and their test |
| `thatsthem.py`, `thatsthem_fetch.py` | ThatsThem lookup (Selenium) and the standalone batch script |
| `proxy_pool.py`, `socks_relay.py`, `chromedriver_manager.py` | proxy rotation, SOCKS5 login relay, chromedriver download |
| `send_emails.py`, `email_template.txt`, `ms_oauth.py` | outreach email, its text, Outlook OAuth2 |
| `reverse_existing_rows.py` | one-time: flip existing rows to newest-first |
| `thatsthem-extension/`, `thatsthem-extension.zip` | the Chrome extension version of the ThatsThem lookup |
| `config.py` | all settings |
| `GmailBot_credentials.json`, `token.json`, `sheets_token.json` | Google credentials and tokens (keep private) |
| `processed_emails.json`, `email_processor.log` | processed Gmail IDs; log |
| `proxies.txt`, `lastname.txt`, `do_not_contact.txt` | your proxies; last names for the scan; addresses never to email |
| `thatsthem_checked.json`, `email_sent_log.json`, `email_rejected.json`, `ms_token_cache.json` | local memory of lookups, sends, rejections, Microsoft sign-in |
| `bark_browser_profile/` | saved Bark login |

## Security and responsible use

- **Keep secrets private.** Never commit `*_credentials.json`, `*token*.json`, `ms_token_cache.json`, `proxies.txt`, `bark_browser_profile/`
  or anything with passwords. API keys, bot tokens and passwords belong in environment variables. If a secret ever appeared in a log or chat,
  rotate it.
- **Bark's terms.** Bark hides lead contact details until you pay for them. Finding and using them another way may break Bark's terms and could
  cost you the seller account.
- **Email law.** Commercial email must include a real postal address and a working opt-out and honor it (CAN-SPAM in the US; consent rules are
  stricter in the EU, UK and Canada). Add everyone who asks to stop to `do_not_contact.txt`.
- **Data sources.** Use ThatsThem and Enformion only as your agreement with them allows; the scripts never bypass CAPTCHAs or blocks.
