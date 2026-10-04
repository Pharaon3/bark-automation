# thatsthem_fetch.py
"""
Standalone ThatsThem lookup. Reads the FullNameContacts tab, looks each person up on
ThatsThem (Selenium + rotating SOCKS5 proxy, see thatsthem.py), and writes the leads whose
ThatsThem email matches the masked lead email to the EmailPhoneContacts tab (the full row,
plus the matched email and all phone numbers; newest on top). Each match is also sent to
Telegram and Slack.

Usage:
    python thatsthem_fetch.py                 process every pending row once, then exit
    python thatsthem_fetch.py --dry-run       only list what would be looked up
    python thatsthem_fetch.py --limit 10      at most 10 lookups this run
    python thatsthem_fetch.py --loop 30       run, wait 30 minutes after it finishes, run again,
                                              and so on until you press Ctrl+C (a failed run does not stop it)
    python thatsthem_fetch.py --recheck       also retry rows that earlier had no match
    python thatsthem_fetch.py --delay 10      seconds to pause between lookups (default 3)

A row is "pending" when it has a Full Name, Address and masked Email and is not yet in
EmailPhoneContacts (matched by Project ID). Rows with no match are remembered in
thatsthem_checked.json so they are not looked up again; failed loads are retried next run.
"""
import argparse
import json
import os
import time
from datetime import datetime, timedelta

from config import (SPREADSHEET_ID, FULLNAME_SHEET_NAME, EMAIL_PHONE_SHEET_NAME,
                    THATSTHEM_WAIT_SECONDS)
from sheets import (get_sheets_service, ensure_tab, upsert_enriched_row,
                    HEADERS, ENRICH_HEADERS, ENRICH_LAST_COL, PID_IDX, FULLNAME_IDX)
import thatsthem
from notifier import notify_matched_email

CHECKED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'thatsthem_checked.json')
MAX_EMPTY_ATTEMPTS = 2     # a page with no profile cards is accepted as "nobody found" after this many tries


# ------------------------------------------------------------------ helpers
def cell(row, idx):
    return (row[idx] if len(row) > idx else '').strip()


def row_key(row):
    """Project ID, or name|address for the rare row without one."""
    pid = cell(row, PID_IDX)
    if pid:
        return pid
    return f"{cell(row, FULLNAME_IDX).lower()}|{cell(row, 2).lower()}"


def load_checked():
    try:
        with open(CHECKED_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_checked(checked):
    tmp = CHECKED_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(checked, f, indent=1)
    os.replace(tmp, CHECKED_FILE)


def is_final(entry):
    """Has this row been checked conclusively before?"""
    if not entry:
        return False
    if entry.get('status') in ('match', 'no_match'):
        return True
    return entry.get('status') == 'no_results' and entry.get('attempts', 0) >= MAX_EMPTY_ATTEMPTS


def read_tab(service, tab_name, last_col):
    return service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"'{tab_name}'!A:{last_col}"
    ).execute().get('values', [])


# ------------------------------------------------------------------ one pass
def run_once(args):
    service = get_sheets_service()

    tabs = [s['properties']['title'] for s in service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID, fields='sheets.properties.title').execute().get('sheets', [])]
    if FULLNAME_SHEET_NAME not in tabs:
        print(f"Tab '{FULLNAME_SHEET_NAME}' does not exist yet; nothing to do.")
        return

    ensure_tab(service, SPREADSHEET_ID, EMAIL_PHONE_SHEET_NAME, ENRICH_HEADERS)

    source_rows = read_tab(service, FULLNAME_SHEET_NAME, 'J')[1:]
    done_keys = {row_key(r) for r in read_tab(service, EMAIL_PHONE_SHEET_NAME, ENRICH_LAST_COL)[1:]}
    checked = {} if args.recheck else load_checked()
    if args.recheck:                      # forget only the "no match" verdicts
        saved = load_checked()
        checked = {k: v for k, v in saved.items() if v.get('status') == 'match'}

    pending, skipped_done, skipped_checked, incomplete = [], 0, 0, 0
    for source_row in source_rows:
        row = list(source_row) + [''] * (len(HEADERS) - len(source_row))
        if not (cell(row, FULLNAME_IDX) and cell(row, 2) and cell(row, 4)):
            incomplete += 1
            continue
        key = row_key(row)
        if key in done_keys:
            skipped_done += 1
        elif is_final(checked.get(key)):
            skipped_checked += 1
        else:
            pending.append((key, row))

    print(f"\n{datetime.now():%Y-%m-%d %H:%M:%S}  {FULLNAME_SHEET_NAME}: {len(source_rows)} rows | "
          f"pending {len(pending)} | already in {EMAIL_PHONE_SHEET_NAME} {skipped_done} | "
          f"checked before (no match) {skipped_checked} | incomplete {incomplete}")

    if args.limit:
        pending = pending[:args.limit]

    if args.dry_run:
        for key, row in pending:
            print(f"  would look up: {cell(row, FULLNAME_IDX)} | {cell(row, 2)} | {cell(row, 4)} | Project ID {cell(row, PID_IDX) or '-'}")
        return

    counts = {'match': 0, 'no_match': 0, 'no_results': 0, 'failed': 0, 'error': 0}
    consecutive_failures = 0

    for number, (key, row) in enumerate(pending, start=1):
        full_name, address, masked = cell(row, FULLNAME_IDX), cell(row, 2), cell(row, 4)
        print(f"\n[{number}/{len(pending)}] {full_name} | {address} | {masked}")

        try:
            status, result = thatsthem.lookup_detailed(full_name, address, masked,
                                                       THATSTHEM_WAIT_SECONDS)
        except ImportError:
            print("Selenium is not installed. Run: pip install selenium  (Google Chrome must be installed too)")
            return
        except thatsthem.BrowserLaunchError as e:
            print(f"\nStopping this run: {e}")
            return
        except Exception as e:
            print(f"Lookup crashed: {type(e).__name__}")
            counts['error'] += 1
            continue

        if status == 'failed':
            counts['failed'] += 1
            consecutive_failures += 1
            if consecutive_failures >= args.max_failures:
                print(f"\n{consecutive_failures} lookups in a row could not load (proxy problem, CAPTCHA "
                      f"or block). Stopping this run; the rest is retried next time.")
                break
        else:
            consecutive_failures = 0

        if status == 'match':
            try:
                upsert_enriched_row(service, SPREADSHEET_ID, EMAIL_PHONE_SHEET_NAME,
                                    row, result['email'], result['phones'])
            except Exception as e:
                print(f"Could not write to '{EMAIL_PHONE_SHEET_NAME}' ({type(e).__name__}); retried next run.")
                counts['error'] += 1
                continue
            counts['match'] += 1
            checked[key] = {'status': 'match', 'at': datetime.now().isoformat(timespec='seconds')}
            done_keys.add(key)
            print(f"MATCH: {result['email']} | {len(result['phones'])} phone number(s)")
            notify_matched_email(dict(zip(HEADERS, row)), result['email'], result['phones'])

        elif status == 'no_match':
            counts['no_match'] += 1
            checked[key] = {'status': 'no_match', 'at': datetime.now().isoformat(timespec='seconds')}
            print("No profile email matched the pattern.")

        elif status == 'no_results':
            counts['no_results'] += 1
            attempts = checked.get(key, {}).get('attempts', 0) + 1
            checked[key] = {'status': 'no_results', 'attempts': attempts,
                            'at': datetime.now().isoformat(timespec='seconds')}
            print(f"ThatsThem returned no profiles (attempt {attempts} of {MAX_EMPTY_ATTEMPTS}).")

        save_checked(checked)
        if number < len(pending) and args.delay > 0:
            time.sleep(args.delay)

    print(f"\nDone: {counts['match']} matched, {counts['no_match']} no match, "
          f"{counts['no_results']} no results, {counts['failed']} failed to load, "
          f"{counts['error']} errors")


# ------------------------------------------------------------------ CLI
def main():
    parser = argparse.ArgumentParser(description="Fill EmailPhoneContacts from FullNameContacts using ThatsThem.")
    parser.add_argument('--dry-run', action='store_true', help="list pending rows, look nothing up")
    parser.add_argument('--limit', type=int, default=0, help="max lookups per run (0 = all)")
    parser.add_argument('--loop', type=float, default=0, metavar='MINUTES', help="repeat every N minutes")
    parser.add_argument('--recheck', action='store_true', help="retry rows that had no match before")
    parser.add_argument('--delay', type=float, default=3, help="seconds between lookups (default 3)")
    parser.add_argument('--max-failures', type=int, default=3,
                        help="stop the run after this many consecutive load failures (default 3)")
    args = parser.parse_args()

    try:
        while True:
            try:
                run_once(args)
            except Exception as e:
                if not args.loop:
                    raise                      # single run: show the full error
                # Loop mode must survive a bad run (network, Google token, sheet error...)
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
