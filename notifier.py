# notifier.py
"""
"Email address extracted" alerts, sent to Telegram AND Slack.

Two events:
  - notify_matched_email(...)  : ThatsThem found an email matching the masked lead email
                                 (alert includes the email and the phone numbers)
  - notify_scanned_emails(...) : the Enformion scan found matching emails

Each channel is independent: if one is off or fails, the other still gets the alert,
and a failure never stops the email processing.
"""
import html

import requests

from config import SLACK_WEBHOOK_URL, SLACK_ENABLED
from telegram_bot import telegram_notifier


# ---------------------------------------------------------------- Slack
def _slack_escape(value):
    """Slack requires & < > to be escaped in message text."""
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


class SlackNotifier:
    def __init__(self):
        self.webhook_url = SLACK_WEBHOOK_URL
        self.enabled = bool(SLACK_ENABLED and SLACK_WEBHOOK_URL)

    def send(self, text):
        """Post `text` (Slack mrkdwn) through the Incoming Webhook. Returns True on success."""
        if not self.enabled:
            return False
        try:
            response = requests.post(self.webhook_url, json={'text': text[:3500]}, timeout=10)
            if response.status_code != 200:
                # Body is a short code like "invalid_token" / "no_service" (webhook removed)
                print(f"❌ Slack rejected the message: HTTP {response.status_code} {response.text[:80]}")
                return False
            return True
        except Exception as e:
            # The error text contains the webhook URL (a secret), so print only the type
            print(f"❌ Failed to send Slack notification ({type(e).__name__})")
            return False


slack_notifier = SlackNotifier()


# ---------------------------------------------------------------- helpers
def _safe(label, send):
    """Run one channel's send; never raise."""
    try:
        return bool(send())
    except Exception as e:
        print(f"{label} notification failed: {type(e).__name__}")
        return False


def _telegram_matched_text(info, matched_email, phones):
    def v(key):
        return html.escape(str(info.get(key))) if info.get(key) else 'N/A'

    return (
        "📧 <b>Email extracted (ThatsThem)</b>\n\n"
        f"👤 <b>Full Name:</b> {v('Full Name')}\n"
        f"📧 <b>Email:</b> {html.escape(matched_email)}\n"
        f"📞 <b>Phones:</b> {html.escape(', '.join(phones)) if phones else 'none found'}\n"
        f"📍 <b>Address:</b> {v('Address')}\n"
        f"💼 <b>Field:</b> {v('Field')}\n"
        f"🆔 <b>Project ID:</b> {v('Project ID')}\n"
        f"🔎 <b>Masked email:</b> {v('Email')}"
    )


def _slack_matched_text(info, matched_email, phones):
    def v(key):
        return _slack_escape(info.get(key)) if info.get(key) else 'N/A'

    return (
        ":email: *Email extracted (ThatsThem)*\n"
        f"*Full Name:* {v('Full Name')}\n"
        f"*Email:* {_slack_escape(matched_email)}\n"
        f"*Phones:* {_slack_escape(', '.join(phones)) if phones else 'none found'}\n"
        f"*Address:* {v('Address')}\n"
        f"*Field:* {v('Field')}\n"
        f"*Project ID:* {v('Project ID')}\n"
        f"*Masked email:* {v('Email')}"
    )


def _slack_scanned_text(fields):
    def v(key):
        return _slack_escape(fields.get(key)) if fields.get(key) else 'N/A'

    text = (
        ":mag: *Email extracted (scan)*\n"
        f"*Name:* {v('Name')}\n"
        f"*Scanned Emails:* {v('Scanned Emails')}\n"
        f"*Masked email:* {v('Email')}\n"
        f"*Phone:* {v('Number')}\n"
        f"*Address:* {v('Address')}\n"
        f"*Field:* {v('Field')}\n"
        f"*Project ID:* {v('Project ID')}"
    )
    return text


# ---------------------------------------------------------------- public API
def notify_matched_email(row_by_header, matched_email, phones):
    """
    ThatsThem match found. `row_by_header` is the sheet row as {header: value}
    (needs Full Name, Address, Field, Project ID, Email). Returns {'telegram': bool, 'slack': bool}.
    """
    return {
        'telegram': _safe('Telegram', lambda: telegram_notifier.send_notification(
            _telegram_matched_text(row_by_header, matched_email, phones))),
        'slack': _safe('Slack', lambda: slack_notifier.send(
            _slack_matched_text(row_by_header, matched_email, phones))),
    }


def notify_scanned_emails(fields):
    """Enformion scan found emails for this lead. Returns {'telegram': bool, 'slack': bool}."""
    return {
        'telegram': _safe('Telegram', lambda: telegram_notifier.notify_email_found(fields)),
        'slack': _safe('Slack', lambda: slack_notifier.send(_slack_scanned_text(fields))),
    }
