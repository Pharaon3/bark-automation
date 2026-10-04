import base64
import html
import os
from datetime import datetime, timedelta
import re
import json
import requests
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from auth import get_gmail_service
from config import (EMAIL_QUERY, MAX_EMAILS, CLICK_LINKS, CLICK_MODE,
                    CLICK_WAIT_SECONDS, CLICK_LOG_SHEET_NAME, CLICK_COOLDOWN_HOURS,
                    FULLNAME_SHEET_NAME, DELETE_PROCESSED_EMAILS, DELETE_MODE,
                    THATSTHEM_ENABLED, THATSTHEM_INLINE, THATSTHEM_WAIT_SECONDS,
                    EMAIL_PHONE_SHEET_NAME)
from sheets import (get_sheets_service, submit_to_sheet, create_sheet_if_not_exists,
                    check_duplicate_entry, upsert_full_name, copy_row_to_fullname_sheet,
                    get_source_row, enrichment_exists, upsert_enriched_row,
                    get_click_state, log_click, HEADERS,
                    PID_IDX, FULLNAME_IDX,
                    ADDED, UPDATED, DUPLICATE, ERROR)
from notifier import notify_matched_email, notify_scanned_emails
import thatsthem

# Enformion credentials come from environment variables (never hardcode them).
# Windows (cmd):  setx ENFORMION_AP_NAME "your-name"
#                 setx ENFORMION_AP_PASSWORD "your-password"
# Then open a NEW terminal so the variables are picked up.
ENFORMION_AP_NAME = os.getenv('ENFORMION_AP_NAME')
ENFORMION_AP_PASSWORD = os.getenv('ENFORMION_AP_PASSWORD')


# Subject like: "You're one step away from speaking to Tranell Ward"
# Matches both ' and the curly apostrophe, case-insensitive; skips an optional
# "speaking to" and captures the name.
STEP_AWAY_RE = re.compile(
    r"you[\u2019']re one step away from\s+(?:speaking\s+to\s+)?(.+)", re.IGNORECASE)


def match_email_pattern(email_to_check, pattern):
    if len(email_to_check) != len(pattern):
        return False
    for ec, pc in zip(email_to_check, pattern):
        if pc == '*':
            continue
        if ec != pc:
            return False
    return True


def scan_emails_in_json(json_data, target_pattern):
    """Recursively scan JSON for email addresses matching the masked pattern."""
    matching_emails = []

    def scan_recursive(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in ['email', 'emailaddress', 'email_address']:
                    if isinstance(value, str) and '@' in value:
                        if match_email_pattern(value, target_pattern):
                            matching_emails.append(value)
                else:
                    scan_recursive(value)
        elif isinstance(obj, list):
            for item in obj:
                scan_recursive(item)

    scan_recursive(json_data)
    return matching_emails


def scan_emails_from_api(name, address, email_pattern):
    """Query Enformion for each last name in lastname.txt; return matching emails."""
    if not ENFORMION_AP_NAME or not ENFORMION_AP_PASSWORD:
        print("Enformion credentials not set (ENFORMION_AP_NAME / ENFORMION_AP_PASSWORD); skipping scan.")
        return []

    url = "https://devapi.enformion.com/Contact/Enrich"

    try:
        with open('lastname.txt', 'r') as f:
            lastnames = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"Error reading lastname.txt: {e}")
        return []

    headers = {
        "accept": "application/json",
        "galaxy-ap-name": ENFORMION_AP_NAME,
        "galaxy-ap-password": ENFORMION_AP_PASSWORD,
        "galaxy-search-type": "DevAPIContactEnrich",
        "content-type": "application/json"
    }

    all_matching_emails = []

    for lastname in lastnames:
        payload = {
            "firstName": name,
            "lastName": lastname,
            "Address": {"addressLine2": address}
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            all_matching_emails.extend(scan_emails_in_json(response.json(), email_pattern))
        except Exception as e:
            print(f"Error scanning emails from API for last name '{lastname}': {e}")
            continue

    return all_matching_emails


def _decode(data):
    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')


def get_email_text(payload):
    """
    Extract readable text from a Gmail payload. Recurses through nested
    multipart structures; prefers text/plain, falls back to text/html.
    """
    mime = payload.get('mimeType', '')
    data = payload.get('body', {}).get('data')

    if data and mime == 'text/plain':
        return _decode(data).strip()
    if data and mime == 'text/html':
        soup = BeautifulSoup(_decode(data), 'html.parser')
        return soup.get_text(separator='\n').strip()

    parts = payload.get('parts', [])
    for preferred in ('text/plain', 'text/html', None):
        for part in parts:
            if preferred is None or part.get('mimeType') == preferred:
                result = get_email_text(part)
                if result:
                    return result

    if data:
        return _decode(data).strip()
    return ""


def get_raw_bodies(payload):
    """
    Return the decoded text of ALL text parts (plain + HTML, raw markup kept).
    Needed because get_email_text() strips HTML, which removes link URLs
    (the project ID lives in the 'View details' link).
    """
    chunks = []
    mime = payload.get('mimeType', '')
    data = payload.get('body', {}).get('data')
    if data and mime.startswith('text/'):
        chunks.append(_decode(data))
    for part in payload.get('parts', []):
        chunks.append(get_raw_bodies(part))
    return '\n'.join(c for c in chunks if c)


def extract_project_id(raw):
    """
    Project ID is the 'prx' query parameter of the 'View details' link:
    https://barkpro.app.link/project?prx=57083278&...
    The first match is the project link; later 'prx%3D...' copies are encoded duplicates.
    """
    if not raw:
        return None
    match = re.search(r"[?&;]prx=(\d+)", raw)
    return match.group(1) if match else None


def extract_fields(text, raw=None):
    """Parse the lead fields out of the email text (no network calls)."""
    def find(pattern, group=1):
        match = re.search(pattern, text, re.DOTALL)
        value = match.group(group) if match else None
        return value.strip() if value is not None else None

    name = find(r"🔔 (.*?) is looking")

    # Project Details: from 'Project Details' to 'Contact <client name>'
    project_details = None
    if name:
        pd_match = re.search(r"Project Details(.*?)Contact " + re.escape(name), text, re.DOTALL)
        if pd_match:
            lines = [line.strip() for line in pd_match.group(1).strip().splitlines()]
            project_details = re.sub(r'\n{2,}', '\n', '\n'.join(lines))

    return {
        'Name': name,
        'Field': find(r"is looking for a (.*?)\n"),
        'Address': find(r"📍(.*?)(:|\n)"),
        'Number': find(r"(\(?\d{3}\)?[\s-]?[*\d]{3}-?[*\d]{4})", group=0),
        'Email': find(r"[\w\*\.\-]+@[\w\*\.\-]+", group=0),
        'Additional Info': find(r"“(.*?)”"),
        'Project Details': project_details,
        'Scanned Emails': '',
        'Project ID': extract_project_id(raw or text)
    }


def find_scanned_emails(fields):
    """Run the (paid) Enformion scan for a lead. Returns a comma-separated string."""
    name, address, email = fields.get('Name'), fields.get('Address'), fields.get('Email')
    if not (name and address and email):
        return ''

    print(f"Scanning for emails matching pattern: {email}")
    found = scan_emails_from_api(name, address, email)
    if found:
        print(f"Found {len(found)} matching emails: {', '.join(found)}")
    else:
        print("No matching emails found in API response")
    return ', '.join(found)


# Dashboard button link, e.g. "Contact Kalyan" / "Contact <name> Now"
BARK_LINK_PREFIX = 'https://www.bark.com/sellers/dashboard/?clktrk='
BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')


def find_first_bark_link(raw):
    """
    Return the FIRST link whose href starts with BARK_LINK_PREFIX
    (HTML entities such as &amp; are decoded), or None.
    """
    if not raw:
        return None

    soup = BeautifulSoup(raw, 'html.parser')
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if href.startswith(BARK_LINK_PREFIX):
            return href

    # Fallback: bare URL in a text/plain part
    match = re.search(r"https://www\.bark\.com/sellers/dashboard/\?clktrk=[^\s\"'<>)]+", raw)
    return html.unescape(match.group(0)) if match else None


def click_link_http(url):
    """
    "Click" with a plain HTTP GET (no browser, no JavaScript).
    The URL contains login tokens, so it is never printed.
    """
    for attempt in (1, 2):
        try:
            response = requests.get(url, headers={'User-Agent': BROWSER_UA},
                                    timeout=30, allow_redirects=True)
            final = urlparse(response.url)
            hops = [str(h.status_code) for h in response.history]
            kept = sorted(parse_qs(final.query).keys())
            print(f"Clicked link (http): {response.status_code} -> {final.netloc}{final.path}"
                  f" | redirects: {hops or 'none'} | params kept: {kept or 'none'}")
            return response.ok
        except Exception as e:
            print(f"Link click failed (attempt {attempt}): {type(e).__name__}")
    return False


def click_link(url):
    """
    Click the link. CLICK_MODE='browser' (default) opens it in a visible
    (headed) Chromium window with your saved Bark login; 'http' uses a plain GET.
    """
    if not url or not url.startswith(BARK_LINK_PREFIX):
        return False

    if CLICK_MODE == 'http':
        return click_link_http(url)

    try:
        from browser_click import open_link_headed
        return open_link_headed(url, CLICK_WAIT_SECONDS)
    except ImportError:
        print("Playwright is not installed. Run: pip install playwright  then  playwright install chromium")
        return False
    except Exception as e:
        # Strip URLs from the message: they contain login tokens
        msg = re.sub(r"https?://\S+", "<url>", str(e)).strip().splitlines()
        print(f"Browser click failed: {type(e).__name__}: {msg[0][:200] if msg else ''}")
        return False


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _headers_by_name(headers):
    by_name = {}
    for h in headers:
        by_name.setdefault(h['name'].lower(), []).append(h['value'])
    return by_name


def _emails_in(values):
    found = []
    for value in values:
        found += [a.lower() for a in _EMAIL_RE.findall(value or '')]
    return found


def get_forward_chain(headers):
    """
    Mailboxes the message passed through, OLDEST FIRST (original receiver first).
    With A -> B -> C forwarding the raw headers look like this (newest on top):

        Delivered-To: C            X-Forwarded-For: B C
        Delivered-To: B            X-Forwarded-For: A B
        Delivered-To: A

    so reading them bottom-up gives A, B, C. Both sources are tried and the
    longer chain wins (X-Forwarded-For on a tie).
    """
    by_name = _headers_by_name(headers)

    def build(values_newest_first):
        chain = []
        for value in reversed(values_newest_first):          # oldest header first
            for address in _emails_in([value]):
                if address not in chain:
                    chain.append(address)
        return chain

    forwarded_for = build(by_name.get('x-forwarded-for', []))
    delivered_to = build(by_name.get('delivered-to', []))
    return forwarded_for if len(forwarded_for) >= len(delivered_to) else delivered_to


def get_received_email(headers, own_address=''):
    """
    Which mailbox ORIGINALLY received the email, before it was auto-forwarded
    (once or several times) to the main account. Returns (address, source).
    Uses the forward chain's oldest mailbox; if the headers carry no chain it
    falls back to X-Original-To / X-Gm-Original-To / To. The main account's own
    address is ignored unless nothing else is found (mail sent straight to it).
    """
    chain = [a for a in get_forward_chain(headers) if a != own_address]
    if chain:
        return chain[0], 'forward chain'

    by_name = _headers_by_name(headers)
    for name in ('x-original-to', 'x-gm-original-to', 'to'):
        others = [a for a in _emails_in(by_name.get(name, [])) if a != own_address]
        if others:
            return others[0], name

    return (own_address or 'unknown'), 'own address'


def click_with_filters(sheets_service, spreadsheet_id, raw, project_id, name,
                       received_by, message_id):
    """
    Click the first dashboard link in the email, unless:
      1. this Project ID was already clicked (from any receiving email), or
      2. this receiving email clicked any link in the last CLICK_COOLDOWN_HOURS.
    After a successful click, log the time + receiving email to the ClickLog tab.
    If the log can't be read the click is skipped (better safe than sorry).
    """
    if not CLICK_LINKS:
        return

    try:
        link = find_first_bark_link(raw)
        if not link:
            print("No dashboard link found in this email, nothing to click.")
            return

        if not (sheets_service and spreadsheet_id):
            print("Click skipped: no sheet connection to check the click log.")
            return

        project_clicked, last_click = get_click_state(
            sheets_service, spreadsheet_id, CLICK_LOG_SHEET_NAME, project_id, received_by)

        if project_clicked:
            print(f"Click skipped: Project ID {project_id} was already clicked.")
            return

        if last_click is not None:
            age = datetime.now().astimezone() - last_click
            if age < timedelta(hours=CLICK_COOLDOWN_HOURS):
                hours = age.total_seconds() / 3600
                print(f"Click skipped: {received_by} already clicked {hours:.1f}h ago "
                      f"(cooldown {CLICK_COOLDOWN_HOURS:g}h).")
                return

        if click_link(link):
            clicked_at = log_click(sheets_service, spreadsheet_id, CLICK_LOG_SHEET_NAME,
                                   received_by, project_id, name, message_id)
            print(f"Click logged: {clicked_at.isoformat(timespec='seconds')} | {received_by} "
                  f"| Project ID {project_id}")
        else:
            print("Click did not succeed, not logged.")

    except Exception as e:
        print(f"Click step failed: {type(e).__name__}: {str(e)[:200]}")


def remove_email(gmail_service, message_id):
    """
    Remove the email from Gmail once its lead data is safely in the sheet:
    moved to Trash (default) or deleted permanently (DELETE_MODE='delete').
    Never raises. Returns True if the email was removed.
    """
    if not DELETE_PROCESSED_EMAILS:
        return False

    try:
        messages = gmail_service.users().messages()
        if DELETE_MODE == 'delete':
            messages.delete(userId='me', id=message_id).execute()
            print("Email permanently deleted from Gmail.")
        else:
            messages.trash(userId='me', id=message_id).execute()
            print("Email moved to Gmail Trash.")
        return True
    except Exception as e:
        text = str(e)
        if '403' in text or 'insufficient' in text.lower():
            print("Could not remove email: Gmail permission missing. "
                  "Delete token.json and run again to grant the new permission.")
        else:
            print(f"Could not remove email: {type(e).__name__}: {text[:150]}")
        return False


def enrich_with_thatsthem(sheets_service, spreadsheet_id, sheet_name,
                          row_number=None, project_id=None):
    """
    For a row that has a Full Name: search ThatsThem (visible browser), compare
    its decoded emails with the row's masked email, and if one matches write
    the row + matched email + all phone numbers to EMAIL_PHONE_SHEET_NAME.
    Best effort: callers catch exceptions, nothing here is retried.
    """
    if not (THATSTHEM_ENABLED and THATSTHEM_INLINE):
        return   # lookups are done by the separate thatsthem_fetch.py script

    row_number, row = get_source_row(sheets_service, spreadsheet_id, sheet_name,
                                     row_number=row_number, project_id=project_id)
    if not row:
        print("ThatsThem: source row not found, skipping.")
        return

    full_name = (row[FULLNAME_IDX] or '').strip()
    address = (row[2] or '').strip()
    email_pattern = (row[4] or '').strip()
    pid = (row[PID_IDX] or '').strip()

    if not (full_name and address and email_pattern):
        print("ThatsThem: row needs Full Name, Address and Email; skipping for now.")
        return

    if pid and enrichment_exists(sheets_service, spreadsheet_id, EMAIL_PHONE_SHEET_NAME, pid):
        print(f"ThatsThem: Project ID {pid} already in '{EMAIL_PHONE_SHEET_NAME}', skipping.")
        return

    try:
        result = thatsthem.lookup(full_name, address, email_pattern, THATSTHEM_WAIT_SECONDS)
    except ImportError:
        print("Selenium is not installed. Run: pip install selenium  (Google Chrome must be installed too)")
        return

    if not result:
        print("ThatsThem: no email matched the pattern, nothing written.")
        return

    print(f"ThatsThem: matched email, {len(result['phones'])} phone number(s) found.")
    upsert_enriched_row(sheets_service, spreadsheet_id, EMAIL_PHONE_SHEET_NAME,
                        row, result['email'], result['phones'])

    # Alert Telegram + Slack: an email address was extracted
    notify_matched_email(dict(zip(HEADERS, row)), result['email'], result['phones'])


def get_processed_emails():
    """Get set of already processed email IDs."""
    try:
        if os.path.exists('processed_emails.json'):
            with open('processed_emails.json', 'r') as f:
                return set(json.load(f))
        return set()
    except Exception:
        return set()


def save_processed_email(email_id):
    """Save email ID to processed list."""
    try:
        processed = get_processed_emails()
        processed.add(email_id)
        with open('processed_emails.json', 'w') as f:
            json.dump(list(processed), f)
    except Exception as e:
        print(f"Warning: Could not save processed email ID: {e}")


def get_emails(spreadsheet_id=None, sheet_name='Contacts', check_processed=True):
    """
    Process lead emails and submit them to Google Sheets.

    An email is marked processed only when handled for good: added to the
    sheet, found to be a duplicate, or recognised as not a lead email. Every
    such email is then removed from Gmail (Trash by default), whether or not
    it was listed in the sheet. Errors leave it unmarked and in the mailbox,
    so it is retried on the next run (deleting it then would lose the lead).
    """
    gmail_service = get_gmail_service()

    try:
        own_address = gmail_service.users().getProfile(userId='me').execute() \
            .get('emailAddress', '').lower()
    except Exception:
        own_address = ''

    sheets_service = None
    if spreadsheet_id:
        try:
            sheets_service = get_sheets_service()
            create_sheet_if_not_exists(sheets_service, spreadsheet_id, sheet_name)
            print(f"Connected to Google Sheets: {spreadsheet_id}")
        except Exception as e:
            print(f"Failed to connect to Google Sheets: {e}")
            sheets_service = None

    processed_emails = get_processed_emails() if check_processed else set()

    results = gmail_service.users().messages().list(
        userId='me', q=EMAIL_QUERY, maxResults=MAX_EMAILS, includeSpamTrash=True
    ).execute()
    messages = results.get('messages', [])

    if not messages:
        print("No new messages found.")
        return

    added_count = 0
    removed_count = 0
    updated_count = 0
    duplicate_count = 0
    skipped_count = 0
    not_lead_count = 0
    error_count = 0

    for msg in messages:
        if check_processed and msg['id'] in processed_emails:
            skipped_count += 1
            # Treated in an earlier run but still in the mailbox: remove it now
            if remove_email(gmail_service, msg['id']):
                removed_count += 1
            continue

        try:
            msg_data = gmail_service.users().messages().get(
                userId='me', id=msg['id'], format='full'
            ).execute()
            hdrs = {h['name']: h['value'] for h in msg_data['payload'].get('headers', [])}
            subject = hdrs.get('Subject') or ''
            raw = get_raw_bodies(msg_data['payload'])
            msg_headers = msg_data['payload'].get('headers', [])
            received_by, received_via = get_received_email(msg_headers, own_address)
            chain_text = ' -> '.join(get_forward_chain(msg_headers)) or 'none'

            # --- "You're one step away from <Full Name>" emails ---
            step_match = STEP_AWAY_RE.search(subject)
            if step_match:
                full_name = step_match.group(1).strip()
                project_id = extract_project_id(raw)
                print(f"\n--- Message {msg['id']} ---")
                print(f"From: {hdrs.get('From')} | Subject: {subject}")
                print(f"Received by: {received_by} (via {received_via}) | forward chain: {chain_text}")
                print(f"'One step away' email -> Full Name: {full_name} | Project ID: {project_id}")

                if not (sheets_service and spreadsheet_id):
                    print("No sheet connection, will retry next run.")
                    error_count += 1
                    continue

                status, row_number = upsert_full_name(sheets_service, spreadsheet_id,
                                                      sheet_name, project_id, full_name)
                if status in (UPDATED, ADDED):
                    # Copy the full row to the FullNameContacts tab
                    try:
                        copy_row_to_fullname_sheet(sheets_service, spreadsheet_id, sheet_name,
                                                   FULLNAME_SHEET_NAME,
                                                   row_number=row_number, project_id=project_id)
                    except Exception as e:
                        error_count += 1
                        print(f"Copy to '{FULLNAME_SHEET_NAME}' failed, will retry next run: {e}")
                        continue

                    # ThatsThem lookup (best effort, never blocks or retries)
                    try:
                        enrich_with_thatsthem(sheets_service, spreadsheet_id, sheet_name,
                                              row_number=row_number, project_id=project_id)
                    except Exception as e:
                        print(f"Warning: ThatsThem lookup failed: {type(e).__name__}: {str(e)[:200]}")

                    if status == UPDATED:
                        updated_count += 1
                    else:
                        added_count += 1
                    save_processed_email(msg['id'])
                    click_with_filters(sheets_service, spreadsheet_id, raw, project_id,
                                       full_name, received_by, msg['id'])
                    if remove_email(gmail_service, msg['id']):
                        removed_count += 1
                else:  # ERROR
                    error_count += 1
                    print("Sheet write failed, will retry next run.")
                continue

            text = get_email_text(msg_data['payload'])

            if not text:
                print(f"[{msg['id']}] No readable text found.")
                save_processed_email(msg['id'])
                if remove_email(gmail_service, msg['id']):
                    removed_count += 1
                continue

            print(f"\n--- Message {msg['id']} ---")
            print(f"From: {hdrs.get('From')} | Subject: {subject}")
            print(f"Received by: {received_by} (via {received_via}) | forward chain: {chain_text}")
            # print("Preview:", text[:1500])  # uncomment to debug parsing

            fields = extract_fields(text, raw)

            # Not a lead notification (welcome mail, receipt, promo, ...)
            if not fields.get('Name') and not fields.get('Email'):
                print(f"[{msg['id']}] Doesn't look like a lead email, skipping.")
                not_lead_count += 1
                save_processed_email(msg['id'])
                if remove_email(gmail_service, msg['id']):
                    removed_count += 1
                continue

            print("Extracted:", fields)

            if not (sheets_service and spreadsheet_id):
                print("No sheet connection, will retry next run.")
                error_count += 1
                continue

            # Check for duplicates BEFORE spending paid API calls on the scan
            if check_duplicate_entry(sheets_service, spreadsheet_id, sheet_name, fields):
                duplicate_count += 1
                save_processed_email(msg['id'])
                click_with_filters(sheets_service, spreadsheet_id, raw, fields.get('Project ID'),
                                   fields.get('Name'), received_by, msg['id'])
                if remove_email(gmail_service, msg['id']):
                    removed_count += 1
                continue

            fields['Scanned Emails'] = find_scanned_emails(fields)

            status = submit_to_sheet(sheets_service, spreadsheet_id, sheet_name, fields)
            if status == ADDED:
                added_count += 1
                save_processed_email(msg['id'])

                # If this lead filled in a row that already has a Full Name
                # (its "one step away" email came first), refresh the copy.
                if fields.get('Project ID'):
                    try:
                        copied = copy_row_to_fullname_sheet(sheets_service, spreadsheet_id,
                                                            sheet_name, FULLNAME_SHEET_NAME,
                                                            project_id=fields['Project ID'])
                        if copied:  # row has a Full Name -> its lookup was waiting for this lead
                            enrich_with_thatsthem(sheets_service, spreadsheet_id, sheet_name,
                                                  project_id=fields['Project ID'])
                    except Exception as e:
                        print(f"Warning: Full Name follow-up failed: {type(e).__name__}: {str(e)[:200]}")

                click_with_filters(sheets_service, spreadsheet_id, raw, fields.get('Project ID'),
                                   fields.get('Name'), received_by, msg['id'])
                # Notify only after a successful save, so retries don't spam
                if fields.get('Scanned Emails'):
                    notify_scanned_emails(fields)      # Telegram + Slack

                # Lead data is in the sheet and all follow-up steps are done
                if remove_email(gmail_service, msg['id']):
                    removed_count += 1
            elif status == DUPLICATE:
                duplicate_count += 1
                save_processed_email(msg['id'])
                click_with_filters(sheets_service, spreadsheet_id, raw, fields.get('Project ID'),
                                   fields.get('Name'), received_by, msg['id'])
                if remove_email(gmail_service, msg['id']):
                    removed_count += 1
            else:  # ERROR
                error_count += 1
                print("Sheet write failed, will retry next run.")

        except Exception as e:
            # Deliberately NOT marked as processed, so it is retried
            error_count += 1
            print(f"Failed to process {msg['id']}: {e}")

    print("\nProcessing Summary:")
    print(f"   Added to sheet: {added_count}")
    print(f"   Removed from Gmail: {removed_count}")
    print(f"   Full Name updated on existing row: {updated_count}")
    print(f"   Duplicates skipped: {duplicate_count}")
    print(f"   Already processed (skipped): {skipped_count}")
    print(f"   Not lead emails (ignored): {not_lead_count}")
    print(f"   Errors (will retry): {error_count}")
