import os
import re
from datetime import datetime
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
TOKEN_FILE = 'sheets_token.json'
CREDENTIALS_FILE = 'GmailBot_credentials.json'

# Columns A..J
HEADERS = ['Name', 'Field', 'Address', 'Number', 'Email',
           'Additional Info', 'Project Details', 'Scanned Emails',
           'Project ID', 'Full Name']
LAST_COL = 'J'
LEAD_COLS = len(HEADERS) - 1          # lead emails fill A..I (Full Name is separate)
PID_IDX = HEADERS.index('Project ID')       # 8  -> column I
FULLNAME_IDX = HEADERS.index('Full Name')   # 9  -> column J

# Return values
ADDED = 'added'
UPDATED = 'updated'
DUPLICATE = 'duplicate'
ERROR = 'error'


def get_sheets_service():
    """Get Google Sheets service with authentication."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            print("Sheets token expired or revoked, re-authorizing...")
            creds = None
            os.remove(TOKEN_FILE)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    return build('sheets', 'v4', credentials=creds)


def _clean(value):
    """Return a stripped string, treating None as empty."""
    return (value or '').strip()


def _cell(row, idx):
    return _clean(row[idx]) if len(row) > idx else ''


def _read_values(service, spreadsheet_id, sheet_name):
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f'{sheet_name}!A:{LAST_COL}'
    ).execute()
    return result.get('values', [])


# ------------------------------------------------------------------
# New rows go to the TOP (row 2, right under the header): latest first,
# oldest last.
# ------------------------------------------------------------------
_SHEET_IDS = {}


def _sheet_id(service, spreadsheet_id, tab_name):
    """Numeric id of a tab (needed for row inserts); cached."""
    key = (spreadsheet_id, tab_name)
    if key not in _SHEET_IDS:
        meta = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id, fields='sheets.properties(sheetId,title)'
        ).execute()
        for sheet in meta.get('sheets', []):
            props = sheet['properties']
            _SHEET_IDS[(spreadsheet_id, props['title'])] = props['sheetId']
    return _SHEET_IDS[key]


def insert_row_at_top(service, spreadsheet_id, tab_name, row):
    """
    Insert `row` as the first data row (sheet row 2, under the header) and
    shift the existing rows down. One atomic API call. Values are stored as
    plain text, like valueInputOption=RAW. Returns the new row's number (2).
    """
    def attempt():
        sheet_id = _sheet_id(service, spreadsheet_id, tab_name)
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'requests': [
                {'insertDimension': {
                    'range': {'sheetId': sheet_id, 'dimension': 'ROWS',
                              'startIndex': 1, 'endIndex': 2},
                    'inheritFromBefore': False}},
                {'updateCells': {
                    'start': {'sheetId': sheet_id, 'rowIndex': 1, 'columnIndex': 0},
                    'rows': [{'values': [
                        {'userEnteredValue': {'stringValue': '' if v is None else str(v)}}
                        for v in row]}],
                    'fields': 'userEnteredValue'}},
            ]}
        ).execute()

    try:
        attempt()
    except HttpError:
        _SHEET_IDS.clear()      # tab may have been deleted/recreated: refresh ids, retry once
        attempt()
    return 2


def check_duplicate_entry(service, spreadsheet_id, sheet_name, new_data):
    """
    Return True if a lead with the same Project ID is already listed.
    Project ID is the ONLY duplicate key (masked emails / phone numbers /
    names are not compared: different people can share the same masked values).
    A match only counts if that row already has a Name; rows created from a
    "one step away" email (Project ID + Full Name only) are placeholders that
    the real lead email should fill in, not be rejected by.
    A lead without a Project ID is never treated as a duplicate.
    Raises HttpError if the sheet cannot be read.
    """
    new_pid = _clean(new_data.get('Project ID'))
    if not new_pid:
        return False

    for row in _read_values(service, spreadsheet_id, sheet_name)[1:]:  # skip header
        if _cell(row, PID_IDX) == new_pid and _cell(row, 0):
            print(f"Duplicate found: Project ID {new_pid} already exists")
            return True

    return False


def submit_to_sheet(service, spreadsheet_id, sheet_name, contact_data):
    """
    Save a lead email. Returns ADDED, DUPLICATE or ERROR.
    If a placeholder row with the same Project ID exists (created from a
    "one step away" email), it is filled in and its Full Name is kept.
    """
    try:
        if check_duplicate_entry(service, spreadsheet_id, sheet_name, contact_data):
            return DUPLICATE

        row_data = [(contact_data.get(h) or '') for h in HEADERS]
        pid = _clean(contact_data.get('Project ID'))

        if pid:
            values = _read_values(service, spreadsheet_id, sheet_name)
            for row_number, row in enumerate(values[1:], start=2):
                if _cell(row, PID_IDX) == pid and not _cell(row, 0):
                    service.spreadsheets().values().update(
                        spreadsheetId=spreadsheet_id,
                        range=f'{sheet_name}!A{row_number}:I{row_number}',
                        valueInputOption='RAW',
                        body={'values': [row_data[:LEAD_COLS]]}
                    ).execute()
                    print(f"Filled in existing row {row_number} for Project ID {pid}")
                    return ADDED

        insert_row_at_top(service, spreadsheet_id, sheet_name, row_data)

        print(f"Successfully added to sheet: {contact_data.get('Name') or 'Unknown'}")
        return ADDED

    except HttpError as error:
        print(f"Error submitting to sheet: {error}")
        return ERROR


def upsert_full_name(service, spreadsheet_id, sheet_name, project_id, full_name):
    """
    "One step away" email: find the row with this Project ID and set its
    Full Name (column J). If no row matches, append a new row with the
    Project ID and Full Name. Returns (status, row_number) where status is
    UPDATED, ADDED or ERROR and row_number is the 1-based sheet row (or None).
    """
    try:
        project_id = _clean(project_id)

        if project_id:
            values = _read_values(service, spreadsheet_id, sheet_name)
            for row_number, row in enumerate(values[1:], start=2):
                if _cell(row, PID_IDX) == project_id:
                    service.spreadsheets().values().update(
                        spreadsheetId=spreadsheet_id,
                        range=f'{sheet_name}!{LAST_COL}{row_number}',
                        valueInputOption='RAW',
                        body={'values': [[full_name]]}
                    ).execute()
                    print(f"Updated Full Name in row {row_number} (Project ID {project_id}): {full_name}")
                    return UPDATED, row_number

        new_row = [''] * len(HEADERS)
        new_row[PID_IDX] = project_id
        new_row[FULLNAME_IDX] = full_name
        new_row_number = insert_row_at_top(service, spreadsheet_id, sheet_name, new_row)
        print(f"No row with Project ID {project_id or '(none)'}; added new row for {full_name}")
        return ADDED, new_row_number

    except HttpError as error:
        print(f"Error updating Full Name: {error}")
        return ERROR, None


def _col_letter(n):
    """1 -> A, 2 -> B ... (up to Z)."""
    return chr(64 + n)


def ensure_tab(service, spreadsheet_id, tab_name, headers=None):
    """Create the tab if missing and make sure its header row is complete."""
    headers = headers or HEADERS
    last = _col_letter(len(headers))

    meta = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields='sheets.properties.title'
    ).execute()
    titles = [s['properties']['title'] for s in meta.get('sheets', [])]
    if tab_name not in titles:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'requests': [{'addSheet': {'properties': {'title': tab_name}}}]}
        ).execute()
        print(f"Created tab '{tab_name}'")

    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A1:{last}1"
    ).execute()
    values = result.get('values', [])
    if not values or len(values[0]) < len(headers):
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A1:{last}1",
            valueInputOption='RAW',
            body={'values': [headers]}
        ).execute()


def copy_row_to_fullname_sheet(service, spreadsheet_id, source_sheet, dest_sheet,
                               row_number=None, project_id=None):
    """
    Copy a full row (all columns A..J) from `source_sheet` to `dest_sheet`,
    but only if that row has a Full Name. The row is found by `row_number`,
    or by `project_id` when no row number is given.
    In `dest_sheet` a row with the same Project ID is overwritten (no
    duplicates); otherwise a new row is appended.
    Returns True if a row was copied, False if there was nothing to copy.
    Raises HttpError on API failure so the caller can retry.
    """
    source_row = None
    if row_number is None:
        pid = _clean(project_id)
        if not pid:
            return False
        values = _read_values(service, spreadsheet_id, source_sheet)
        for number, row in enumerate(values[1:], start=2):
            if _cell(row, PID_IDX) == pid:
                row_number, source_row = number, row
                break
        if source_row is None:
            return False
    else:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f'{source_sheet}!A{row_number}:{LAST_COL}{row_number}'
        ).execute()
        source_row = (result.get('values') or [[]])[0]

    row = list(source_row) + [''] * (len(HEADERS) - len(source_row))
    if not _clean(row[FULLNAME_IDX]):
        return False  # no Full Name on this row -> nothing to copy

    ensure_tab(service, spreadsheet_id, dest_sheet)

    pid = _clean(row[PID_IDX])
    target = None
    if pid:
        dest_values = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{dest_sheet}'!A:{LAST_COL}"
        ).execute().get('values', [])
        for number, drow in enumerate(dest_values[1:], start=2):
            if _cell(drow, PID_IDX) == pid:
                target = number
                break

    if target:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{dest_sheet}'!A{target}:{LAST_COL}{target}",
            valueInputOption='RAW',
            body={'values': [row]}
        ).execute()
        print(f"Updated row {target} in '{dest_sheet}' (Project ID {pid})")
    else:
        insert_row_at_top(service, spreadsheet_id, dest_sheet, row)
        print(f"Copied row to '{dest_sheet}'")
    return True


# ------------------------------------------------------------------
# EmailPhoneContacts support (ThatsThem results)
# ------------------------------------------------------------------
ENRICH_HEADERS = HEADERS + ['Matched Email', 'Phone Numbers', 'Email Sent At']   # columns A..M
ENRICH_LAST_COL = _col_letter(len(ENRICH_HEADERS))                                # 'M'
MATCHED_EMAIL_IDX = ENRICH_HEADERS.index('Matched Email')                         # 10 -> column K
PHONES_IDX = ENRICH_HEADERS.index('Phone Numbers')                                # 11 -> column L
SENT_IDX = ENRICH_HEADERS.index('Email Sent At')                                  # 12 -> column M


def get_source_row(service, spreadsheet_id, sheet_name, row_number=None, project_id=None):
    """
    Return (row_number, row) with the row padded to all columns,
    found by row number or, failing that, by Project ID.
    Returns (None, None) if not found.
    """
    if row_number is not None:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f'{sheet_name}!A{row_number}:{LAST_COL}{row_number}'
        ).execute()
        row = (result.get('values') or [[]])[0]
    else:
        pid = _clean(project_id)
        if not pid:
            return None, None
        row = None
        for number, candidate in enumerate(
                _read_values(service, spreadsheet_id, sheet_name)[1:], start=2):
            if _cell(candidate, PID_IDX) == pid:
                row_number, row = number, candidate
                break
        if row is None:
            return None, None

    return row_number, list(row) + [''] * (len(HEADERS) - len(row))


def enrichment_exists(service, spreadsheet_id, tab_name, project_id):
    """True if `tab_name` already has a row with this Project ID."""
    pid = _clean(project_id)
    if not pid:
        return False
    ensure_tab(service, spreadsheet_id, tab_name, ENRICH_HEADERS)
    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A:{ENRICH_LAST_COL}"
    ).execute().get('values', [])
    return any(_cell(r, PID_IDX) == pid for r in values[1:])


def upsert_enriched_row(service, spreadsheet_id, tab_name, row, matched_email, phones):
    """
    Write `row` (all fields A..J) plus Matched Email and Phone Numbers to
    `tab_name`. A row with the same Project ID is overwritten; otherwise a new
    row is appended.
    """
    ensure_tab(service, spreadsheet_id, tab_name, ENRICH_HEADERS)

    new_row = list(row)[:len(HEADERS)]
    new_row += [''] * (len(HEADERS) - len(new_row))
    new_row += [matched_email, ', '.join(phones)]

    pid = _clean(new_row[PID_IDX])
    target = None
    if pid:
        values = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A:{ENRICH_LAST_COL}"
        ).execute().get('values', [])
        for number, existing in enumerate(values[1:], start=2):
            if _cell(existing, PID_IDX) == pid:
                target = number
                break

    if target:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A{target}:{ENRICH_LAST_COL}{target}",
            valueInputOption='RAW',
            body={'values': [new_row]}
        ).execute()
        print(f"Updated row {target} in '{tab_name}'")
    else:
        insert_row_at_top(service, spreadsheet_id, tab_name, new_row)
        print(f"Added row to '{tab_name}'")


# ------------------------------------------------------------------
# ClickLog: one row per link click (used for the "already clicked" and
# "24 hours per receiving email" filters)
# ------------------------------------------------------------------
CLICK_HEADERS = ['Clicked At', 'Received By', 'Project ID', 'Name', 'Message ID']
_CLICK_LOG_READY = set()


def _parse_time(value):
    """Parse an ISO timestamp from the log; returns an aware datetime or None."""
    try:
        moment = datetime.fromisoformat(_clean(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.astimezone()  # naive -> local time


def _ensure_click_log(service, spreadsheet_id, tab_name):
    if tab_name not in _CLICK_LOG_READY:
        ensure_tab(service, spreadsheet_id, tab_name, CLICK_HEADERS)
        _CLICK_LOG_READY.add(tab_name)


def get_click_state(service, spreadsheet_id, tab_name, project_id, received_by):
    """
    Read the click log once and return:
      project_clicked  - True if ANY receiving email already clicked this Project ID
      last_click       - datetime of the most recent click by `received_by`, or None
    Raises HttpError if the log can't be read.
    """
    _ensure_click_log(service, spreadsheet_id, tab_name)
    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A:E"
    ).execute().get('values', [])

    pid = _clean(project_id)
    receiver = _clean(received_by).lower()
    project_clicked = False
    last_click = None

    for row in values[1:]:
        if pid and _cell(row, 2) == pid:
            project_clicked = True
        if receiver and _cell(row, 1).lower() == receiver:
            moment = _parse_time(_cell(row, 0))
            if moment and (last_click is None or moment > last_click):
                last_click = moment

    return project_clicked, last_click


def log_click(service, spreadsheet_id, tab_name, received_by, project_id, name, message_id):
    """Append one click (current local time with UTC offset) to the log."""
    _ensure_click_log(service, spreadsheet_id, tab_name)
    clicked_at = datetime.now().astimezone()
    insert_row_at_top(service, spreadsheet_id, tab_name,
                      [clicked_at.isoformat(timespec='seconds'),
                       received_by or '', project_id or '', name or '', message_id or ''])
    return clicked_at


def create_sheet_if_not_exists(service, spreadsheet_id, sheet_name):
    """
    Create the tab if it is missing, and write the headers if row 1 is empty or lacks
    the newest columns.
    """
    try:
        ensure_tab(service, spreadsheet_id, sheet_name, HEADERS)
    except HttpError as error:
        print(f"Error creating/checking sheet: {error}")
        raise
