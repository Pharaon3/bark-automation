# test_notifications.py
"""
Sends a sample "email extracted" alert to Telegram and Slack (whichever are
configured) so you can check the setup without waiting for a real lead:

    python test_notifications.py

The sample data is made up.
"""
from notifier import notify_matched_email, slack_notifier
from telegram_bot import telegram_notifier


def main():
    print(f"Telegram enabled: {telegram_notifier.enabled}")
    print(f"Slack enabled:    {slack_notifier.enabled}")
    if not (telegram_notifier.enabled or slack_notifier.enabled):
        print("\nNothing is configured. See the setup guide "
              "(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / TELEGRAM_ENABLED, SLACK_WEBHOOK_URL).")
        return

    sample = {
        'Full Name': 'Test Person',
        'Address': 'Los Angeles, CA 90019',
        'Field': 'Test Field',
        'Project ID': '00000000',
        'Email': 't*******n@g***l.com',
    }
    result = notify_matched_email(sample, 'test.person@gmail.com', ['555-010-0100', '555-010-0101'])

    for channel, ok in result.items():
        enabled = telegram_notifier.enabled if channel == 'telegram' else slack_notifier.enabled
        status = 'sent' if ok else ('FAILED' if enabled else 'skipped (not configured)')
        print(f"{channel.capitalize():9} {status}")


if __name__ == '__main__':
    main()
