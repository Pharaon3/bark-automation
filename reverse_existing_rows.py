# reverse_existing_rows.py
"""
OPTIONAL, run ONCE: flips the rows that are already in your sheet tabs so the
newest is at the top (until now rows were added at the bottom, oldest first).

Run it BEFORE the updated bot adds any new rows. If you run it afterwards, the
rows added since the update would be moved to the bottom.

    python reverse_existing_rows.py

Tip: File > Make a copy in Google Sheets first, as a backup.
"""
from config import (SPREADSHEET_ID, SHEET_NAME, FULLNAME_SHEET_NAME,
                    EMAIL_PHONE_SHEET_NAME, CLICK_LOG_SHEET_NAME)
from sheets import get_sheets_service

TABS = [SHEET_NAME, FULLNAME_SHEET_NAME, EMAIL_PHONE_SHEET_NAME, CLICK_LOG_SHEET_NAME]


def _col_letter(n):
    letters = ''
    while n:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def reverse_tab(service, spreadsheet_id, tab_name):
    """Reverse the data rows of one tab (the header row stays first). Returns the row count."""
    meta = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields='sheets.properties.title'
    ).execute()
    if tab_name not in [s['properties']['title'] for s in meta.get('sheets', [])]:
        print(f"  '{tab_name}': tab not found, skipped")
        return 0

    values = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=f"'{tab_name}'"
    ).execute().get('values', [])

    data = values[1:]
    if len(data) < 2:
        print(f"  '{tab_name}': {len(data)} data row(s), nothing to reverse")
        return len(data)

    # Pad every row to the same width so shorter rows fully overwrite longer ones
    width = max(len(r) for r in values)
    data = [list(r) + [''] * (width - len(r)) for r in data]
    data.reverse()

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A2:{_col_letter(width)}{len(data) + 1}",
        valueInputOption='RAW',
        body={'values': data}
    ).execute()
    print(f"  '{tab_name}': reversed {len(data)} rows")
    return len(data)


def main():
    print("This reverses the existing rows in these tabs (newest will be on top):")
    for tab in TABS:
        print(f"  - {tab}")
    if input("Type YES to continue: ").strip() != 'YES':
        print("Cancelled, nothing changed.")
        return

    service = get_sheets_service()
    for tab in TABS:
        reverse_tab(service, SPREADSHEET_ID, tab)
    print("Done.")


if __name__ == '__main__':
    main()
