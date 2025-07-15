#!/usr/bin/env python3
"""
Test script for Telegram bot configuration
"""

from telegram_bot import telegram_notifier
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED
import os

def test_telegram_config():
    """Test Telegram bot configuration and send a test message"""
    
    print("🤖 Telegram Bot Configuration Test")
    print("=" * 40)
    
    # Check if Telegram is enabled
    if not TELEGRAM_ENABLED:
        print("❌ Telegram notifications are disabled in config.py")
        print("Set TELEGRAM_ENABLED = True in config.py to enable")
        return False
    
    # Check bot token
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not configured")
        print("Set your bot token in config.py or TELEGRAM_BOT_TOKEN environment variable")
        return False
    
    # Check chat ID
    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID not configured")
        print("Set your chat ID in config.py or TELEGRAM_CHAT_ID environment variable")
        return False
    
    print(f"✅ Bot Token: {TELEGRAM_BOT_TOKEN[:10]}...")
    print(f"✅ Chat ID: {TELEGRAM_CHAT_ID}")
    
    # Test connection
    print("\n🔗 Testing bot connection...")
    if not telegram_notifier.test_connection():
        return False
    
    # Send test message
    print("\n📤 Sending test message...")
    test_message = """
🧪 <b>Test Message</b>

This is a test message from your Bark Email Processor bot.

✅ If you received this message, your Telegram configuration is working correctly!

You will now receive notifications when new emails are found and processed.
"""
    
    if telegram_notifier.send_notification(test_message.strip()):
        print("✅ Test message sent successfully!")
        print("📱 Check your Telegram chat for the test message")
        return True
    else:
        print("❌ Failed to send test message")
        return False

def get_chat_id_help():
    """Show help for getting chat ID"""
    print("\n📋 How to get your Chat ID:")
    print("1. Start a chat with your bot on Telegram")
    print("2. Send any message to the bot")
    print("3. Visit: https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates")
    print("4. Look for 'chat' -> 'id' in the response")
    print("5. For group chats, add the bot to the group first")

def get_bot_token_help():
    """Show help for getting bot token"""
    print("\n📋 How to create a Telegram bot:")
    print("1. Open Telegram and search for @BotFather")
    print("2. Send /newbot command")
    print("3. Follow the instructions to create your bot")
    print("4. Copy the bot token provided by BotFather")
    print("5. Set it as TELEGRAM_BOT_TOKEN in config.py")

if __name__ == "__main__":
    print("Bark Email Processor - Telegram Test")
    print("=" * 50)
    
    # Check environment variables
    env_token = os.getenv('TELEGRAM_BOT_TOKEN')
    env_chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    if env_token:
        print(f"📝 Found TELEGRAM_BOT_TOKEN in environment")
    if env_chat_id:
        print(f"📝 Found TELEGRAM_CHAT_ID in environment")
    
    # Run test
    success = test_telegram_config()
    
    if not success:
        print("\n" + "=" * 50)
        print("🔧 Configuration Help:")
        
        if not TELEGRAM_BOT_TOKEN:
            get_bot_token_help()
        
        if not TELEGRAM_CHAT_ID:
            get_chat_id_help()
        
        print("\n📝 Configuration options:")
        print("1. Set values in config.py")
        print("2. Set environment variables:")
        print("   - TELEGRAM_BOT_TOKEN")
        print("   - TELEGRAM_CHAT_ID")
        print("3. Run main.py and configure interactively")
    
    print("\n" + "=" * 50) 