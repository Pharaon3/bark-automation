# main.py
from bot import get_emails
from config import SPREADSHEET_ID, SHEET_NAME
from telegram_bot import telegram_notifier
from notifier import slack_notifier

_telegram_checked = False


def setup_telegram():
    """Test the Telegram connection once per process (never prompts for input)."""
    global _telegram_checked
    if _telegram_checked:
        return
    _telegram_checked = True

    if telegram_notifier.enabled:
        telegram_notifier.test_connection()
    else:
        print("Telegram notifications disabled")

    print("Slack notifications enabled" if slack_notifier.enabled else "Slack notifications disabled")


def main():
    print("Starting email processing...")

    setup_telegram()

    if not SPREADSHEET_ID:
        print("ERROR: SPREADSHEET_ID is not set (config.py or GOOGLE_SHEET_ID env var).")
        return

    get_emails(spreadsheet_id=SPREADSHEET_ID, sheet_name=SHEET_NAME)


if __name__ == '__main__':
    main()
