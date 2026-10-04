# send_emails.py
"""
Sends an email to every lead in the EmailPhoneContacts tab (to its "Matched Email") and notes
the time in the "Email Sent At" column (column M) of the same row.

Usage:
    python send_emails.py --dry-run            show who would get an email, and a preview of the first one
    python send_emails.py --test me@gmail.com  send ONE sample email to yourself (nothing is marked as sent)
    python send_emails.py                      send to everyone pending, then exit
    python send_emails.py --limit 5            at most 5 emails this run
    python send_emails.py --delay 60           seconds between emails (default 30)
    python send_emails.py --loop 30            repeat every 30 minutes (Ctrl+C to stop)

A row is pending when it has a valid Matched Email, "Email Sent At" is empty, and that address
- has not been emailed before (each address gets ONE email, even if it appears in several rows),
- is not in do_not_contact.txt (one address per line, or @domain.com), and
- was not rejected by the mail server earlier (email_rejected.json).

The text comes from email_template.txt. The postal address (MAIL_POSTAL_ADDRESS) and an opt-out
line are appended automatically, plus a List-Unsubscribe header. Setup: see config.py (SMTP_*, MAIL_*).
"""
import argparse
import json
import os
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from config import (SPREADSHEET_ID, EMAIL_PHONE_SHEET_NAME, SMTP_HOST, SMTP_PORT, SMTP_USER,
                    SMTP_PASSWORD, MAIL_FROM_NAME, MAIL_FROM_EMAIL, MAIL_REPLY_TO,
                    MAIL_POSTAL_ADDRESS, MAIL_REQUIRE_ADDRESS, MAIL_DAILY_LIMIT, MAIL_TEMPLATE_FILE)
from sheets import (get_sheets_service, ensure_tab, ENRICH_HEADERS, ENRICH_LAST_COL, PID_IDX,
                    FULLNAME_IDX, MATCHED_EMAIL_IDX, SENT_IDX)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SENT_LOG = os.path.join(BASE_DIR, 'email_sent_log.json')          # {address: {"at": ..., "project_id": ...}}
REJECTED_FILE = os.path.join(BASE_DIR, 'email_rejected.json')     # {address: {"reason": ..., "at": ...}}
DNC_FILE = os.path.join(BASE_DIR, 'do_not_contact.txt')
SENT_COLUMN = ENRICH_LAST_COL                                     # 'M'
EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")
MAX_CONSECUTIVE_ERRORS = 3


# ------------------------------------------------------------------ small helpers
def cell(row, idx):
    return (row[idx] if len(row) > idx else '').strip()


def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def load_do_not_contact():
    """Addresses and @domains the script must never email."""
    entries = set()
    try:
        with open(DNC_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.split('#')[0].strip().lower()
                if line:
                    entries.add(line)
    except OSError:
        pass
    return entries


def blocked_by_dnc(address, dnc):
    address = address.lower()
    return address in dnc or ('@' + address.split('@')[-1]) in dnc


def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def sent_today(timestamp):
    try:
        return datetime.fromisoformat(timestamp).astimezone().date() == datetime.now().astimezone().date()
    except (TypeError, ValueError):
        return False


# ------------------------------------------------------------------ template
def read_template():
    path = MAIL_TEMPLATE_FILE if os.path.isabs(MAIL_TEMPLATE_FILE) else os.path.join(BASE_DIR, MAIL_TEMPLATE_FILE)
    with open(path, 'r', encoding='utf-8') as f:
        lines = [l.rstrip('\r\n') for l in f if not l.lstrip().startswith('#')]
    text = '\n'.join(lines).strip('\n')
    match = re.match(r'(?is)^subject:\s*(.+?)\r?\n(.*)$', text)
    if not match:
        raise ValueError("email_template.txt must start with a line like:  Subject: Your {field} request")
    return match.group(1).strip(), match.group(2).strip('\n')


def placeholders(row):
    full_name = cell(row, FULLNAME_IDX) or cell(row, 0)
    parts = full_name.split()
    address = cell(row, 2)
    return {
        'full_name': full_name.title() if full_name.isupper() else full_name,
        'first_name': (parts[0].capitalize() if parts else 'there'),
        'last_name': (parts[-1].capitalize() if len(parts) > 1 else ''),
        'name': cell(row, 0),
        'field': cell(row, 1) or 'service',
        'address': address,
        'city': address.split(',')[0].strip() if address else 'your area',
        'project_id': cell(row, PID_IDX),
        'sender_name': MAIL_FROM_NAME,
    }


def fill(text, values):
    """Replace {name} placeholders; unknown ones are left untouched."""
    return re.sub(r'\{(\w+)\}', lambda m: str(values.get(m.group(1), m.group(0))), text)


def footer():
    lines = ['', '--']
    if MAIL_POSTAL_ADDRESS:
        lines.append(MAIL_POSTAL_ADDRESS)
    lines.append('If you do not want to hear from me, reply with "unsubscribe" and I will not email you again.')
    return '\n'.join(lines)


def build_message(row, to_address, subject_prefix=''):
    subject_t, body_t = read_template()
    values = placeholders(row)
    message = EmailMessage()
    message['From'] = formataddr((MAIL_FROM_NAME, MAIL_FROM_EMAIL)) if MAIL_FROM_NAME else MAIL_FROM_EMAIL
    message['To'] = to_address
    message['Subject'] = subject_prefix + fill(subject_t, values)
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid(domain=(MAIL_FROM_EMAIL.split('@')[-1] or None))
    if MAIL_REPLY_TO:
        message['Reply-To'] = MAIL_REPLY_TO
    message['List-Unsubscribe'] = f'<mailto:{MAIL_REPLY_TO or MAIL_FROM_EMAIL}?subject=unsubscribe>'
    message.set_content(fill(body_t, values) + '\n' + footer())
    return message


# ------------------------------------------------------------------ SMTP
def smtp_connect():
    context = ssl.create_default_context()
    if SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60, context=context)
        server.ehlo()
    else:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60)
        server.ehlo()
        if server.has_extn('starttls'):
            server.starttls(context=context)
            server.ehlo()
        elif SMTP_HOST not in ('localhost', '127.0.0.1'):
            server.close()
            raise smtplib.SMTPException('the mail server does not offer STARTTLS; refusing to send the password unencrypted')
    if SMTP_USER and SMTP_PASSWORD:
        server.login(SMTP_USER, SMTP_PASSWORD)
    return server


# ------------------------------------------------------------------ sheet access
def read_rows(service):
    values = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"'{EMAIL_PHONE_SHEET_NAME}'!A:{SENT_COLUMN}"
    ).execute().get('values', [])
    return values[1:]


def write_sent_mark(service, project_id, address, stamp):
    """
    Put `stamp` in the "Email Sent At" cell of the row with this Project ID + Matched Email.
    The row is looked up again right now, because new rows are inserted at the TOP of the tab
    and row numbers shift. Returns True if a row was marked.
    """
    for number, row in enumerate(read_rows(service), start=2):
        same_pid = (not project_id) or cell(row, PID_IDX) == project_id
        if same_pid and cell(row, MATCHED_EMAIL_IDX).lower() == address.lower():
            if cell(row, SENT_IDX):
                return True                       # already marked
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{EMAIL_PHONE_SHEET_NAME}'!{SENT_COLUMN}{number}",
                valueInputOption='RAW', body={'values': [[stamp]]}
            ).execute()
            return True
    return False


# ------------------------------------------------------------------ one pass
def run_once(args):
    if not args.dry_run:
        problems = []
        if not (SMTP_HOST and MAIL_FROM_EMAIL):
            problems.append('SMTP_USER / MAIL_FROM_EMAIL is not set')
        if SMTP_USER and not SMTP_PASSWORD:
            problems.append('SMTP_PASSWORD is not set')
        if MAIL_REQUIRE_ADDRESS and not MAIL_POSTAL_ADDRESS:
            problems.append('MAIL_POSTAL_ADDRESS is not set (a postal address is required in commercial email; '
                            'set MAIL_REQUIRE_ADDRESS=false to skip this check)')
        if problems:
            print('Cannot send yet:\n  - ' + '\n  - '.join(problems) + '\nSee the comments in config.py.')
            return

    service = get_sheets_service()
    ensure_tab(service, SPREADSHEET_ID, EMAIL_PHONE_SHEET_NAME, ENRICH_HEADERS)
    rows = read_rows(service)

    sent_log = load_json(SENT_LOG)
    rejected = load_json(REJECTED_FILE)
    dnc = load_do_not_contact()

    # Sends whose sheet mark failed earlier (journal says sent, cell is empty): write them now.
    # Only the row the email was sent for is marked, not other rows that share the same address.
    for row in rows:
        address = cell(row, MATCHED_EMAIL_IDX).lower()
        entry = sent_log.get(address)
        if entry and not cell(row, SENT_IDX) and entry.get('project_id', '') == cell(row, PID_IDX):
            try:
                if write_sent_mark(service, cell(row, PID_IDX), address, entry['at']):
                    print(f"Recorded an earlier send in the sheet: {address}")
            except Exception as e:
                print(f"Could not record the earlier send for {address} ({type(e).__name__})")
    rows = read_rows(service)

    already = {a for a in sent_log}
    already |= {cell(r, MATCHED_EMAIL_IDX).lower() for r in rows if cell(r, SENT_IDX)}
    sent_today_count = len({a for a, v in sent_log.items() if sent_today(v.get('at'))} |
                           {cell(r, MATCHED_EMAIL_IDX).lower() for r in rows if sent_today(cell(r, SENT_IDX))})

    pending, seen = [], set()
    skipped = {'no email': 0, 'invalid': 0, 'already sent': 0, 'do not contact': 0, 'rejected before': 0, 'duplicate': 0}
    for row in rows:
        address = cell(row, MATCHED_EMAIL_IDX)
        key = address.lower()
        if not address:
            skipped['no email'] += 1
        elif not EMAIL_RE.match(address):
            skipped['invalid'] += 1
        elif key in already or cell(row, SENT_IDX):
            skipped['already sent'] += 1
        elif blocked_by_dnc(address, dnc):
            skipped['do not contact'] += 1
        elif key in rejected:
            skipped['rejected before'] += 1
        elif key in seen:
            skipped['duplicate'] += 1
        else:
            seen.add(key)
            pending.append((address, row))

    budget = max(0, MAIL_DAILY_LIMIT - sent_today_count)
    print(f"\n{datetime.now():%Y-%m-%d %H:%M:%S}  {EMAIL_PHONE_SHEET_NAME}: {len(rows)} rows | pending {len(pending)} | "
          f"sent today {sent_today_count} of {MAIL_DAILY_LIMIT} | skipped: " +
          ', '.join(f'{k} {v}' for k, v in skipped.items() if v) )

    # ---- test mode: one sample email to yourself, nothing is marked
    if args.test:
        sample = pending[0][1] if pending else [''] * len(ENRICH_HEADERS)
        if not pending:
            print('No pending row; using empty sample data.')
        message = build_message(sample, args.test, subject_prefix='[TEST] ')
        server = smtp_connect()
        try:
            server.send_message(message)
        finally:
            server.quit()
        print(f"Test email sent to {args.test}. Nothing was marked in the sheet.")
        return

    limit = min(budget, args.limit) if args.limit else budget
    batch = pending[:limit]
    if pending and not batch:
        print(f"Daily limit reached ({MAIL_DAILY_LIMIT}); nothing more is sent today.")

    # ---- dry run: list + preview
    if args.dry_run:
        for address, row in batch:
            print(f"  would email: {address} | {cell(row, FULLNAME_IDX)} | {cell(row, 1)} | {cell(row, 2)}")
        if batch:
            message = build_message(batch[0][1], batch[0][0])
            print('\n----- preview of the first email -----')
            print(f"From:    {message['From']}\nTo:      {message['To']}\nSubject: {message['Subject']}\n")
            print(message.get_content())
            print('--------------------------------------')
        return

    if not batch:
        return

    counts = {'sent': 0, 'rejected': 0, 'error': 0}
    consecutive_errors = 0
    server = None
    try:
        for number, (address, row) in enumerate(batch, start=1):
            print(f"[{number}/{len(batch)}] {address} | {cell(row, FULLNAME_IDX)}")
            try:
                if server is None:
                    server = smtp_connect()
                server.send_message(build_message(row, address))
            except smtplib.SMTPRecipientsRefused as e:
                reason = str(list(e.recipients.values())[0])[:200] if e.recipients else 'refused'
                rejected[address.lower()] = {'reason': reason, 'at': now_iso()}
                save_json(REJECTED_FILE, rejected)
                counts['rejected'] += 1
                print(f"   rejected by the mail server: {reason}")
                consecutive_errors = 0
                continue
            except (smtplib.SMTPException, OSError) as e:
                counts['error'] += 1
                consecutive_errors += 1
                print(f"   send failed: {type(e).__name__}: {str(e)[:150]}")
                try:
                    if server:
                        server.close()
                except Exception:
                    pass
                server = None
                if isinstance(e, smtplib.SMTPAuthenticationError):
                    print('Login was refused: check SMTP_USER / SMTP_PASSWORD (Gmail needs an App Password). Stopping.')
                    break
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(f"{consecutive_errors} errors in a row; stopping this run (it is retried next time).")
                    break
                continue

            consecutive_errors = 0
            stamp = now_iso()
            sent_log[address.lower()] = {'at': stamp, 'project_id': cell(row, PID_IDX)}
            save_json(SENT_LOG, sent_log)                # first: never send to this address twice
            counts['sent'] += 1
            try:
                if write_sent_mark(service, cell(row, PID_IDX), address, stamp):
                    print(f"   sent, noted in the sheet: {stamp}")
                else:
                    print('   sent, but its row was not found in the sheet (the next run tries again)')
            except Exception as e:
                print(f"   sent, but the sheet could not be updated ({type(e).__name__}); the next run records it")

            if number < len(batch) and args.delay > 0:
                time.sleep(args.delay)
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass

    print(f"\nDone: {counts['sent']} sent, {counts['rejected']} rejected, {counts['error']} errors")


# ------------------------------------------------------------------ CLI
def main():
    parser = argparse.ArgumentParser(description="Email the leads in EmailPhoneContacts and note it in the sheet.")
    parser.add_argument('--dry-run', action='store_true', help="list who would be emailed and preview the first email")
    parser.add_argument('--test', metavar='ADDRESS', help="send one sample email to this address; nothing is marked")
    parser.add_argument('--limit', type=int, default=0, help="max emails this run (0 = up to the daily limit)")
    parser.add_argument('--delay', type=float, default=30, help="seconds between emails (default 30)")
    parser.add_argument('--loop', type=float, default=0, metavar='MINUTES', help="repeat every N minutes")
    args = parser.parse_args()

    try:
        while True:
            try:
                run_once(args)
            except Exception as e:
                if not args.loop:
                    raise
                print(f"\nRun failed ({type(e).__name__}: {str(e)[:200]}). Will try again next cycle.")
            if not args.loop:
                break
            next_run = datetime.now() + timedelta(minutes=args.loop)
            print(f"\nNext run at {next_run:%H:%M:%S} (in {args.loop:g} minutes). Ctrl+C to stop.")
            time.sleep(args.loop * 60)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == '__main__':
    main()
