import html
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED, TELEGRAM_PROXY

MAX_MESSAGE_LEN = 4000  # Telegram limit is 4096
PROXIES = {'http': TELEGRAM_PROXY, 'https': TELEGRAM_PROXY} if TELEGRAM_PROXY else None


def _v(fields, key, default='N/A'):
    """Return an HTML-escaped value; handles missing keys AND None values."""
    value = fields.get(key)
    return html.escape(str(value)) if value else default


class TelegramNotifier:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.enabled = TELEGRAM_ENABLED

        if self.enabled and (not self.bot_token or not self.chat_id):
            print("⚠️  Telegram enabled but bot token or chat ID not configured")
            self.enabled = False

    def send_notification(self, message):
        """Send a notification message to Telegram."""
        if not self.enabled:
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message[:MAX_MESSAGE_LEN],
                "parse_mode": "HTML"
            }
            response = requests.post(url, json=payload, timeout=10, proxies=PROXIES)
            response.raise_for_status()
            return True
        except Exception as e:
            # The error text contains the URL (with the bot token), so print only the type
            print(f"❌ Failed to send Telegram notification ({type(e).__name__})")
            return False

    def notify_email_found(self, fields):
        """Send a notification when a new lead is found and saved."""
        if not self.enabled:
            return False

        message = f"""
🔔 <b>New Lead Found!</b>

👤 <b>Name:</b> {_v(fields, 'Name')}
📧 <b>Email:</b> {_v(fields, 'Email')}
📞 <b>Phone:</b> {_v(fields, 'Number')}
📍 <b>Address:</b> {_v(fields, 'Address')}
💼 <b>Field:</b> {_v(fields, 'Field')}
🆔 <b>Project ID:</b> {_v(fields, 'Project ID')}

📝 <b>Additional Info:</b>
{_v(fields, 'Additional Info')}

🔍 <b>Scanned Emails:</b>
{_v(fields, 'Scanned Emails', 'None found')}
"""
        if fields.get('Project Details'):
            message += f"\n📋 <b>Project Details:</b>\n{_v(fields, 'Project Details')}"

        return self.send_notification(message.strip())

    def notify_processing_summary(self, summary):
        """Send a summary of email processing results."""
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
        """Test the Telegram bot connection."""
        if not self.enabled:
            print("❌ Telegram notifications are disabled")
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            response = requests.get(url, timeout=10, proxies=PROXIES)
            response.raise_for_status()

            bot_info = response.json()
            if bot_info.get('ok'):
                print(f"✅ Telegram bot connected: @{bot_info['result']['username']}")
                return True
            print("❌ Failed to connect to Telegram bot")
            return False

        except Exception as e:
            # Don't print the exception: it contains the URL with the bot token
            print(f"❌ Telegram connection test failed ({type(e).__name__})")
            return False


# Global instance
telegram_notifier = TelegramNotifier()
