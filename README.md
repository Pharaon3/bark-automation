# Bark Email Contact Extractor

This project extracts contact information from Bark.com emails and optionally submits them to Google Sheets with duplicate checking.

## Features

- ✅ Extracts contact information from Gmail emails (from team@bark.com)
- ✅ Submits data to Google Sheets
- ✅ Checks for duplicates before submission (by email or phone number)
- ✅ Telegram notifications when new emails are found
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

### 4. Telegram Bot Setup (Optional)

To receive notifications on Telegram when new emails are found:

1. Create a Telegram bot:
   - Open Telegram and search for @BotFather
   - Send `/newbot` command
   - Follow instructions to create your bot
   - Copy the bot token provided

2. Get your chat ID:
   - Start a chat with your bot
   - Send any message to the bot
   - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Look for `"chat" -> "id"` in the response

3. Configure the bot:
   - Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `config.py`
   - Or set environment variables: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
   - Or configure interactively when running the script

4. Test the configuration:
   ```bash
   python test_telegram.py
   ```

### 5. First Run

Run the script for the first time:

```bash
python main.py
```

This will:
- Open a browser for Google OAuth authentication
- Create `token.json` and `sheets_token.json` files
- Configure Telegram notifications (if enabled)
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

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = 'your_bot_token_here'  # From @BotFather
TELEGRAM_CHAT_ID = 'your_chat_id_here'      # Your chat ID
TELEGRAM_ENABLED = True                      # Set to False to disable
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
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
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
- `telegram_bot.py` - Telegram notification system
- `test_telegram.py` - Telegram configuration test script
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

### Telegram Issues
- Verify bot token is correct
- Ensure chat ID is correct (user or group)
- Check that the bot has permission to send messages
- Test configuration with `python test_telegram.py` 