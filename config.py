# Configuration for the Bark Email Processor

# Google Sheets Configuration
# Get your spreadsheet ID from the URL: https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
SPREADSHEET_ID = '1Nkea97k32Zea5SjY-xNT950EVcBiQcuauObzoQAUuHA'  # Set this to your Google Sheet ID
SHEET_NAME = 'Contacts'  # Name of the sheet tab to use

# Email Processing Configuration
MAX_EMAILS = 20  # Maximum number of emails to process per run
EMAIL_QUERY = 'from:team@bark.com'  # Gmail search query

# Duplicate Checking
# Fields to check for duplicates (in order of priority)
DUPLICATE_FIELDS = ['Email', 'Number']  # Check email first, then phone number

# Sheet Column Mapping
# Map extracted fields to sheet columns (A=0, B=1, C=2, D=3, E=4)
COLUMN_MAPPING = {
    'Name': 0,      # Column A
    'Field': 1,     # Column B  
    'Address': 2,   # Column C
    'Number': 3,    # Column D
    'Email': 4      # Column E
}

# Headers for the Google Sheet
SHEET_HEADERS = ['Name', 'Field', 'Address', 'Number', 'Email'] 