import requests
import json
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED

class TelegramNotifier:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.enabled = TELEGRAM_ENABLED
        
        if self.enabled and (not self.bot_token or not self.chat_id):
            print("⚠️  Telegram notifications enabled but bot token or chat ID not configured")
            self.enabled = False
    
    def send_notification(self, message):
        """
        Send a notification message to Telegram
        """
        if not self.enabled:
            return False
            
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            return True
        except Exception as e:
            print(f"❌ Failed to send Telegram notification: {e}")
            return False
    
    def notify_email_found(self, fields):
        """
        Send a notification when a new email is found and processed
        """
        if not self.enabled:
            return False
            
        # Create a formatted message
        message = f"""
🔔 <b>New Lead Found!</b>

👤 <b>Name:</b> {fields.get('Name', 'N/A')}
📧 <b>Email:</b> {fields.get('Email', 'N/A')}
📞 <b>Phone:</b> {fields.get('Number', 'N/A')}
📍 <b>Address:</b> {fields.get('Address', 'N/A')}
💼 <b>Field:</b> {fields.get('Field', 'N/A')}

📝 <b>Additional Info:</b>
{fields.get('Additional Info', 'N/A')}

🔍 <b>Scanned Emails:</b>
{fields.get('Scanned Emails', 'None found')}
"""
        
        if fields.get('Project Details'):
            message += f"\n📋 <b>Project Details:</b>\n{fields.get('Project Details')}"
        
        return self.send_notification(message.strip())
    
    def notify_processing_summary(self, summary):
        """
        Send a summary of email processing results
        """
        if not self.enabled:
            return False
            
        message = f"""
📊 <b>Email Processing Summary</b>

✅ New emails processed: {summary.get('processed', 0)}
📤 Submitted to sheets: {summary.get('submitted', 0)}
🔄 Duplicates skipped: {summary.get('duplicates', 0)}
⏭️ Already processed: {summary.get('skipped', 0)}
"""
        
        return self.send_notification(message.strip())
    
    def test_connection(self):
        """
        Test the Telegram bot connection
        """
        if not self.enabled:
            print("❌ Telegram notifications are disabled")
            return False
            
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            bot_info = response.json()
            if bot_info.get('ok'):
                print(f"✅ Telegram bot connected: @{bot_info['result']['username']}")
                return True
            else:
                print("❌ Failed to connect to Telegram bot")
                return False
                
        except Exception as e:
            print(f"❌ Telegram connection test failed: {e}")
            return False

# Global instance
telegram_notifier = TelegramNotifier() 