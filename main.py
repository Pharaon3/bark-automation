# main.py
from bot import get_emails
import os
from config import SPREADSHEET_ID, SHEET_NAME, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED
from telegram_bot import telegram_notifier

def main():
    print("Starting email processing...")
    
    # Configure Telegram notifications
    setup_telegram()
    
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

def setup_telegram():
    """Setup Telegram notifications"""
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED
    
    # Check if Telegram is already configured
    if TELEGRAM_ENABLED and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        print("✅ Telegram notifications are configured")
        telegram_notifier.test_connection()
        return
    
    print("\n📱 Telegram Notifications:")
    print("To receive notifications on Telegram, you need to:")
    print("1. Create a bot with @BotFather on Telegram")
    print("2. Get your bot token")
    print("3. Get your chat ID (user or group)")
    print("4. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in config.py")
    print("   or provide them when prompted")
    print()
    
    use_telegram = input("Do you want to enable Telegram notifications? (y/n): ").lower().strip()
    
    if use_telegram == 'y':
        # Get bot token
        bot_token = TELEGRAM_BOT_TOKEN or os.getenv('TELEGRAM_BOT_TOKEN')
        if not bot_token:
            bot_token = input("Enter your Telegram bot token: ").strip()
        
        # Get chat ID
        chat_id = TELEGRAM_CHAT_ID or os.getenv('TELEGRAM_CHAT_ID')
        if not chat_id:
            chat_id = input("Enter your Telegram chat ID: ").strip()
        
        if bot_token and chat_id:
            TELEGRAM_BOT_TOKEN = bot_token
            TELEGRAM_CHAT_ID = chat_id
            TELEGRAM_ENABLED = True
            
            # Update the telegram notifier with new settings
            telegram_notifier.bot_token = bot_token
            telegram_notifier.chat_id = chat_id
            telegram_notifier.enabled = True
            
            print("✅ Telegram notifications configured")
            telegram_notifier.test_connection()
        else:
            print("❌ Telegram configuration incomplete. Notifications disabled.")
            TELEGRAM_ENABLED = False
    else:
        print("📱 Telegram notifications disabled")
        TELEGRAM_ENABLED = False

if __name__ == '__main__':
    main()
