# main.py
from bot import get_emails
import os
from config import SPREADSHEET_ID, SHEET_NAME

def main():
    print("Starting email processing...")
    
    # Get spreadsheet ID from config, environment variable, or user input
    spreadsheet_id = SPREADSHEET_ID or os.getenv('GOOGLE_SHEET_ID')
    
    if not spreadsheet_id:
        print("\nGoogle Sheets Integration:")
        print("To submit data to Google Sheets, you need to:")
        print("1. Create a Google Sheet")
        print("2. Get the spreadsheet ID from the URL")
        print("3. Set SPREADSHEET_ID in config.py or GOOGLE_SHEET_ID environment variable")
        print("   or provide it when prompted")
        print()
        
        use_sheets = input("Do you want to submit data to Google Sheets? (y/n): ").lower().strip()
        
        if use_sheets == 'y':
            spreadsheet_id = input("Enter your Google Sheet ID: ").strip()
            if not spreadsheet_id:
                print("No spreadsheet ID provided. Running without sheet submission.")
                spreadsheet_id = None
        else:
            spreadsheet_id = None
    
    # Get sheet name from config or environment
    sheet_name = SHEET_NAME or os.getenv('SHEET_NAME', 'Contacts')
    
    # Process emails
    get_emails(spreadsheet_id=spreadsheet_id, sheet_name=sheet_name)

if __name__ == '__main__':
    main()
