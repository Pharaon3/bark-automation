import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_sheets_service():
    """Get Google Sheets service with authentication."""
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists('sheets_token.json'):
        creds = Credentials.from_authorized_user_file('sheets_token.json', SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('GmailBot_credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('sheets_token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('sheets', 'v4', credentials=creds)
    return service

def check_duplicate_entry(service, spreadsheet_id, sheet_name, new_data):
    """
    Check if an entry with the same email or phone number already exists.
    Returns True if duplicate found, False otherwise.
    """
    try:
        # Get all existing data from the sheet
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f'{sheet_name}!A:G'  # Now columns A-G: Name, Field, Address, Number, Email, Additional Info, Project Details
        ).execute()
        
        values = result.get('values', [])
        
        if not values:
            return False  # No existing data, so no duplicates
        
        # Check for duplicates based on email or phone number
        new_email = new_data.get('Email', '').strip()
        new_number = new_data.get('Number', '').strip()
        
        for row in values[1:]:  # Skip header row
            if len(row) >= 5:  # Ensure we have enough columns
                existing_email = row[4].strip() if len(row) > 4 else ''  # Email is in column E (index 4)
                existing_number = row[3].strip() if len(row) > 3 else ''  # Number is in column D (index 3)
                
                # Check if email matches (if both have emails)
                if new_email and existing_email and new_email.lower() == existing_email.lower():
                    print(f"⚠️  Duplicate found: Email {new_email} already exists")
                    return True
                
                # Check if phone number matches (if both have numbers)
                if new_number and existing_number and new_number == existing_number:
                    print(f"⚠️  Duplicate found: Phone number {new_number} already exists")
                    return True
        
        return False
        
    except HttpError as error:
        print(f"Error checking for duplicates: {error}")
        return False

def submit_to_sheet(service, spreadsheet_id, sheet_name, contact_data):
    """
    Submit contact data to Google Sheet if it's not a duplicate.
    Returns True if successfully submitted, False if duplicate or error.
    """
    try:
        # Check for duplicates first
        if check_duplicate_entry(service, spreadsheet_id, sheet_name, contact_data):
            return False
        
        # Prepare the row data
        row_data = [
            contact_data.get('Name', ''),
            contact_data.get('Field', ''),
            contact_data.get('Address', ''),
            contact_data.get('Number', ''),
            contact_data.get('Email', ''),
            contact_data.get('Additional Info', ''),
            contact_data.get('Project Details', '')
        ]
        
        # Append the new row
        body = {
            'values': [row_data]
        }
        
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f'{sheet_name}!A:G',
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        print(f"✅ Successfully added to sheet: {contact_data.get('Name', 'Unknown')}")
        return True
        
    except HttpError as error:
        print(f"Error submitting to sheet: {error}")
        return False

def create_sheet_if_not_exists(service, spreadsheet_id, sheet_name):
    """
    Create a new sheet if it doesn't exist and add headers.
    """
    try:
        # Try to get the sheet to see if it exists
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f'{sheet_name}!A1:G1'
        ).execute()
        
        values = result.get('values', [])
        
        # If no data exists, add headers
        if not values:
            headers = ['Name', 'Field', 'Address', 'Number', 'Email', 'Additional Info', 'Project Details']
            body = {
                'values': [headers]
            }
            
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f'{sheet_name}!A1:G1',
                valueInputOption='RAW',
                body=body
            ).execute()
            
            print(f"📋 Created headers in sheet '{sheet_name}'")
        
    except HttpError as error:
        print(f"Error creating/checking sheet: {error}")
        raise 