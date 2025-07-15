import base64
import re
import json
import requests
from bs4 import BeautifulSoup
from auth import get_gmail_service
from sheets import get_sheets_service, submit_to_sheet, create_sheet_if_not_exists
from telegram_bot import telegram_notifier

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
    """
    Recursively scan JSON data for email addresses and check if they match the pattern.
    """
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
    """
    Scan for emails using the Enformion API and return matching emails for each last name in lastname.txt.
    """
    url = "https://devapi.enformion.com/Contact/Enrich"

    # Read last names from lastname.txt
    lastnames = []
    try:
        with open('lastname.txt', 'r') as f:
            lastnames = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"Error reading lastname.txt: {e}")
        return []

    headers = {
        "accept": "application/json",
        "galaxy-ap-name": "cc490f58acad474b9f0b4294d46ba207",
        "galaxy-ap-password": "fa062caea4cc4e3a8daba44f3240565c",
        "galaxy-search-type": "DevAPIContactEnrich",
        "content-type": "application/json"
    }

    all_matching_emails = []

    for lastname in lastnames:
        payload = {
            "firstName": name,
            "lastName": lastname,
            "Address": { "addressLine2": address }
        }
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            json_data = response.json()
            matching_emails = scan_emails_in_json(json_data, email_pattern)
            all_matching_emails.extend(matching_emails)
        except Exception as e:
            print(f"Error scanning emails from API for last name '{lastname}': {e}")
            continue

    return all_matching_emails

def get_email_text(payload):
    # Extracts text from email payload, falling back to HTML if text/plain is empty
    if 'parts' in payload:
        for part in payload['parts']:
            mime = part.get('mimeType', '')
            body = part.get('body', {})
            data = body.get('data')
            if data:
                decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                if mime == 'text/plain':
                    return decoded.strip()
                elif mime == 'text/html':
                    soup = BeautifulSoup(decoded, 'html.parser')
                    return soup.get_text(separator='\n').strip()
    else:
        # Fallback for non-multipart emails
        data = payload.get('body', {}).get('data')
        if data:
            return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore').strip()
    return ""

def extract_fields(text):
    def find(pattern, group=1):
        match = re.search(pattern, text, re.DOTALL)
        value = match.group(group) if match else None
        return value.strip() if value is not None else None

    name = find(r"🔔 (.*?) is looking")
    # Project Details: from 'Project Details' to 'Contact $clientname'
    project_details = None
    if name:
        # Escape name for regex
        name_escaped = re.escape(name)
        pd_match = re.search(r"Project Details(.*?)Contact " + name_escaped, text, re.DOTALL)
        if pd_match:
            project_details = pd_match.group(1)
            # Clean up: strip, remove multiple blank lines, trim each line
            project_details = '\n'.join(
                [line.strip() for line in project_details.strip().splitlines()]
            )
            # Replace multiple blank lines with a single blank line
            import re as _re
            project_details = _re.sub(r'\n{2,}', '\n', project_details)

    # Extract basic fields
    extracted_email = find(r"[\w\*\.\-]+@[\w\*\.\-]+", group=0)
    address = find(r"📍(.*?)(:|\n)")
    
    # Scan for additional emails using the API
    scanned_emails = []
    if name and address and extracted_email:
        print(f"Scanning for emails matching pattern: {extracted_email}")
        scanned_emails = scan_emails_from_api(name, address, extracted_email)
        if scanned_emails:
            print(f"Found {len(scanned_emails)} matching emails: {', '.join(scanned_emails)}")
        else:
            print("No matching emails found in API response")

    return {
        'Name': name,
        'Field': find(r"is looking for a (.*?)\n"),
        'Address': address,
        'Number': find(r"(\(?\d{3}\)?[\s-]?[*\d]{3}-?[*\d]{4})", group=0),
        'Email': extracted_email,
        'Additional Info': find(r"“(.*?)”"),
        'Project Details': project_details,
        'Scanned Emails': ', '.join(scanned_emails) if scanned_emails else ''
    }


import os
from datetime import datetime

def get_processed_emails():
    """Get list of already processed email IDs"""
    try:
        if os.path.exists('processed_emails.json'):
            with open('processed_emails.json', 'r') as f:
                return set(json.load(f))
        return set()
    except Exception:
        return set()

def save_processed_email(email_id):
    """Save email ID to processed list"""
    try:
        processed = get_processed_emails()
        processed.add(email_id)
        with open('processed_emails.json', 'w') as f:
            json.dump(list(processed), f)
    except Exception as e:
        print(f"Warning: Could not save processed email ID: {e}")

def get_emails(spreadsheet_id=None, sheet_name='Contacts', check_processed=True):
    """
    Process emails and submit contact data to Google Sheets.
    
    Args:
        spreadsheet_id (str): Google Sheets spreadsheet ID
        sheet_name (str): Name of the sheet to use (default: 'Contacts')
        check_processed (bool): Whether to skip already processed emails
    """
    # Get Gmail service
    gmail_service = get_gmail_service()
    
    # Get Sheets service if spreadsheet_id is provided
    sheets_service = None
    if spreadsheet_id:
        try:
            sheets_service = get_sheets_service()
            create_sheet_if_not_exists(sheets_service, spreadsheet_id, sheet_name)
            print(f"Connected to Google Sheets: {spreadsheet_id}")
        except Exception as e:
            print(f"Failed to connect to Google Sheets: {e}")
            print("Continuing without sheet submission...")
            sheets_service = None
    
    # Get processed emails if checking is enabled
    processed_emails = get_processed_emails() if check_processed else set()
    
    # Get emails from Gmail
    results = gmail_service.users().messages().list(userId='me', q='from:team@bark.com', maxResults=20).execute()
    messages = results.get('messages', [])
    
    if not messages:
        print("No new messages found.")
        return

    processed_count = 0
    submitted_count = 0
    duplicate_count = 0
    skipped_count = 0

    for msg in messages:
        # Skip if already processed
        if check_processed and msg['id'] in processed_emails:
            skipped_count += 1
            continue
            
        msg_data = gmail_service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        text = get_email_text(msg_data['payload'])

        if not text:
            print(f"[{msg['id']}] No readable text found.")
            save_processed_email(msg['id'])  # Mark as processed even if no text
            continue

        print(f"\n--- Message {msg['id']} ---")
        # print("Preview:", text)  # Print first 200 characters

        try:
            fields = extract_fields(text)
            print("Extracted:", fields)
            processed_count += 1
            
            # Only send Telegram notification if scanned emails are found
            if fields.get('Scanned Emails'):
                telegram_notifier.notify_email_found(fields)
            
            # Submit to Google Sheets if service is available
            if sheets_service and spreadsheet_id:
                if submit_to_sheet(sheets_service, spreadsheet_id, sheet_name, fields):
                    submitted_count += 1
                else:
                    duplicate_count += 1
            else:
                print("📝 Data extracted but not submitted to sheets (no sheet connection)")
            
            # Mark as processed
            save_processed_email(msg['id'])
                
        except Exception as e:
            print(f"Failed to extract data: {e}")
            save_processed_email(msg['id'])  # Mark as processed even if failed
    
    # Print summary
    print(f"\nProcessing Summary:")
    print(f"   New emails processed: {processed_count}")
    print(f"   Already processed (skipped): {skipped_count}")
    if sheets_service and spreadsheet_id:
        print(f"   Submitted to sheets: {submitted_count}")
        print(f"   Duplicates skipped: {duplicate_count}")
    else:
        print(f"   Sheet submission: Disabled")
    
    # Send Telegram summary notification
    # summary = {
    #     'processed': processed_count,
    #     'submitted': submitted_count,
    #     'duplicates': duplicate_count,
    #     'skipped': skipped_count
    # }
    # telegram_notifier.notify_processing_summary(summary)
