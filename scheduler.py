import time
import schedule
import logging
from datetime import datetime
from main import main as process_emails

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('email_processor.log'),
        logging.StreamHandler()
    ]
)

def job():
    """Run the email processing job with error handling"""
    try:
        logging.info("🔄 Starting scheduled email processing...")
        process_emails()
        logging.info("✅ Email processing completed successfully")
    except Exception as e:
        logging.error(f"❌ Error during email processing: {e}")

def run_scheduler():
    """Run the scheduler with the specified interval"""
    print("🚀 Starting Email Processor Scheduler")
    print("📅 Will run every 3 minutes")
    print("📝 Logs will be saved to 'email_processor.log'")
    print("⏹️  Press Ctrl+C to stop")
    print("-" * 50)
    
    # Schedule the job to run every 3 minutes
    schedule.every(3).minutes.do(job)
    
    # Run the job immediately on startup
    logging.info("🚀 Initial run starting...")
    job()
    
    # Keep the scheduler running
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logging.info("⏹️  Scheduler stopped by user")
            break
        except Exception as e:
            logging.error(f"❌ Scheduler error: {e}")
            time.sleep(60)  # Wait 1 minute before retrying

if __name__ == "__main__":
    run_scheduler() 