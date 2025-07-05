# Bark Email Contact Extractor

This project extracts contact information from Bark.com emails and optionally submits them to Google Sheets with duplicate checking.

## Features

- ✅ Extracts contact information from Gmail emails (from team@bark.com)
- ✅ Submits data to Google Sheets
- ✅ Checks for duplicates before submission (by email or phone number)
- ✅ Configurable settings
- ✅ Detailed processing summary

## Setup

### 1. Install Dependencies

```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client beautifulsoup4
```

### 2. Google API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable Gmail API and Google Sheets API
4. Create credentials (OAuth 2.0 Client ID)
5. Download the credentials file and rename it to `GmailBot_credentials.json`
6. Place it in the project directory

### 3. Google Sheets Setup

1. Create a new Google Sheet
2. Get the spreadsheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/YOUR_SPREADSHEET_ID/edit
   ```
3. Configure the spreadsheet ID in one of these ways:
   - Set `SPREADSHEET_ID` in `config.py`
   - Set environment variable: `GOOGLE_SHEET_ID=your_spreadsheet_id`
   - Provide it when prompted during runtime

### 4. First Run

Run the script for the first time:

```bash
python main.py
```

This will:
- Open a browser for Google OAuth authentication
- Create `token.json` and `sheets_token.json` files
- Process emails and extract contact information

## Configuration

Edit `config.py` to customize settings:

```python
# Google Sheets Configuration
SPREADSHEET_ID = 'your_spreadsheet_id_here'
SHEET_NAME = 'Contacts'  # Sheet tab name

# Email Processing
MAX_EMAILS = 20  # Max emails to process per run
EMAIL_QUERY = 'from:team@bark.com'  # Gmail search query
```

## Usage

### Basic Usage (without Google Sheets)
```bash
python main.py
# Choose 'n' when prompted for Google Sheets
```

### With Google Sheets
```bash
# Set spreadsheet ID in config.py or environment variable
python main.py
# Choose 'y' when prompted and enter spreadsheet ID
```

### Environment Variables
```bash
export GOOGLE_SHEET_ID="your_spreadsheet_id"
export SHEET_NAME="Contacts"
python main.py
```

### Frequent Execution (Every 3 Minutes)
```bash
# Install additional dependency
pip install schedule

# Run the scheduler
python scheduler.py
```

The scheduler will:
- Run every 3 minutes automatically
- Skip already processed emails
- Log all activities to `email_processor.log`
- Handle errors gracefully
- Show processing summary each run

## Data Structure

The script extracts these fields from emails:
- **Name**: Contact name
- **Field**: Service field/type
- **Address**: Location/address
- **Number**: Phone number
- **Email**: Email address

## Duplicate Checking

The system checks for duplicates based on:
1. **Email address** (case-insensitive)
2. **Phone number** (exact match)

If a duplicate is found, the entry is skipped and logged.

## Output

The script provides detailed output:
- Email processing status
- Extracted contact information
- Duplicate detection results
- Processing summary with counts

## Files

- `main.py` - Main entry point
- `bot.py` - Email processing and extraction logic
- `auth.py` - Gmail API authentication
- `sheets.py` - Google Sheets integration
- `config.py` - Configuration settings
- `GmailBot_credentials.json` - Google API credentials
- `token.json` - Gmail OAuth token (auto-generated)
- `sheets_token.json` - Sheets OAuth token (auto-generated)

## Troubleshooting

### Authentication Issues
- Delete `token.json` and `sheets_token.json` to re-authenticate
- Ensure `GmailBot_credentials.json` is in the project directory

### Google Sheets Issues
- Verify the spreadsheet ID is correct
- Ensure the Google account has edit access to the sheet
- Check that Google Sheets API is enabled in Google Cloud Console

### Email Processing Issues
- Verify Gmail API is enabled
- Check that emails from team@bark.com exist in your Gmail
- Ensure the email format matches the expected pattern 