"""Dublin Rental Hunter - Main entry point."""

import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import schedule
import yaml
from dotenv import load_dotenv

from core.aggregator import ListingAggregator
from core.database import Database
from notifications.ntfy_sender import NtfySender
from notifications.email_sender import EmailSender


def setup_logging(config: dict) -> None:
    """Configure logging based on config settings.

    Args:
        config: Application configuration.
    """
    log_config = config.get("logging", {})
    log_level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    log_file = log_config.get("file", "logs/rental_hunter.log")

    # Create logs directory if needed
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure logging
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_config() -> dict:
    """Load configuration from YAML file.

    Returns:
        Configuration dictionary.
    """
    config_path = Path(__file__).parent / "config" / "config.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def is_quiet_hours(config: dict) -> bool:
    """Check if current time is within quiet hours.

    Args:
        config: Application configuration.

    Returns:
        True if in quiet hours and notifications should be suppressed.
    """
    schedule_config = config.get("schedule", {})
    quiet_config = schedule_config.get("quiet_hours", {})

    if not quiet_config.get("enabled", False):
        return False

    try:
        start_str = quiet_config.get("start", "23:00")
        end_str = quiet_config.get("end", "07:00")

        now = datetime.now().time()
        start = datetime.strptime(start_str, "%H:%M").time()
        end = datetime.strptime(end_str, "%H:%M").time()

        # Handle overnight quiet hours (e.g., 23:00 to 07:00)
        if start > end:
            return now >= start or now <= end
        else:
            return start <= now <= end

    except Exception:
        return False


class RentalHunter:
    """Main application class for Dublin Rental Hunter."""

    def __init__(self):
        """Initialize the rental hunter."""
        # Load environment variables
        load_dotenv()

        # Load configuration
        self.config = load_config()

        # Set up logging
        setup_logging(self.config)
        self.logger = logging.getLogger(self.__class__.__name__)

        self.logger.info("=" * 50)
        self.logger.info("Dublin Rental Hunter starting up...")
        self.logger.info("=" * 50)

        # Initialize database
        db_path = self.config.get("database", {}).get("path", "data/rentals.db")
        self.database = Database(db_path)

        # Initialize aggregator (handles scrapers and filtering internally)
        self.aggregator = ListingAggregator(self.config, self.database)

        # Initialize notifiers
        self.ntfy = None
        self.email = None

        if self.config.get("ntfy", {}).get("enabled", False):
            self.ntfy = NtfySender(self.config)
            self.logger.info("ntfy notifications enabled")

        if self.config.get("email", {}).get("enabled", False):
            self.email = EmailSender(self.config)
            self.logger.info("Email notifications enabled")

        # Get server base URL for action buttons
        server_config = self.config.get("server", {})
        if server_config.get("enabled", False):
            host = os.getenv("SERVER_HOST", "localhost")
            port = server_config.get("port", 5151)
            self.server_base_url = f"http://{host}:{port}"
        else:
            self.server_base_url = None

        # Schedule configuration
        self.interval_minutes = self.config.get("schedule", {}).get("interval_minutes", 10)

        self.logger.info(f"Scrape interval: {self.interval_minutes} minutes")
        self.logger.info(f"Active filters: {self.aggregator.filter_manager.get_active_criteria_names()}")

    def run_scrape(self) -> None:
        """Run a single scrape cycle."""
        self.logger.info("-" * 40)
        self.logger.info("Starting scrape cycle...")

        try:
            # Get new listings that pass filters
            new_listings = self.aggregator.process_new_listings()

            if not new_listings:
                self.logger.info("No new matching listings found")
                return

            self.logger.info(f"Found {len(new_listings)} new matching listings")

            # Check quiet hours
            if is_quiet_hours(self.config):
                self.logger.info("In quiet hours - skipping notifications")
                return

            # Send notifications
            if self.ntfy:
                for listing in new_listings:
                    listing_dict = listing.to_dict()

                    if self.ntfy.send_listing(listing_dict, self.server_base_url):
                        self.database.mark_notified(listing.id)

        except Exception as e:
            self.logger.error(f"Error during scrape cycle: {e}")

    def send_daily_stats(self) -> None:
        """Send daily statistics summary."""
        if not self.ntfy:
            return

        try:
            stats = self.aggregator.get_stats()
            self.ntfy.send_stats(stats.get("database", {}))
            self.logger.info("Sent daily stats notification")
        except Exception as e:
            self.logger.error(f"Error sending stats: {e}")

    def reset_email_limit(self) -> None:
        """Reset email rate limit counter."""
        if self.email:
            self.email.reset_rate_limit()

    def run(self) -> None:
        """Run the rental hunter main loop."""
        self.logger.info("Dublin Rental Hunter started!")

        # Run initial scrape
        self.run_scrape()

        # Schedule periodic scrapes
        schedule.every(self.interval_minutes).minutes.do(self.run_scrape)

        # Schedule daily stats at 9 AM
        schedule.every().day.at("09:00").do(self.send_daily_stats)

        # Schedule hourly email rate limit reset
        schedule.every().hour.do(self.reset_email_limit)

        self.logger.info(f"Scheduled: scrape every {self.interval_minutes} minutes")
        self.logger.info("Scheduled: daily stats at 09:00")

        # Main loop
        try:
            while True:
                schedule.run_pending()
                time.sleep(30)  # Check schedule every 30 seconds

        except KeyboardInterrupt:
            self.logger.info("\nShutdown requested...")
        except Exception as e:
            self.logger.error(f"Fatal error: {e}")
        finally:
            self.logger.info("Dublin Rental Hunter stopped")

    def test_notifications(self) -> None:
        """Test notification services."""
        self.logger.info("Testing notifications...")

        if self.ntfy:
            if self.ntfy.test():
                self.logger.info("✓ ntfy test successful")
            else:
                self.logger.error("✗ ntfy test failed")

        if self.email:
            success, message = self.email.send_test()
            if success:
                self.logger.info(f"✓ Email test successful: {message}")
            else:
                self.logger.error(f"✗ Email test failed: {message}")


def main():
    """Main entry point."""
    hunter = RentalHunter()

    # Check for command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--test":
            hunter.test_notifications()
            return
        elif sys.argv[1] == "--once":
            hunter.run_scrape()
            return
        elif sys.argv[1] == "--stats":
            stats = hunter.aggregator.get_stats()
            print("\n📊 Database Statistics:")
            print(f"  Scrapers enabled: {stats['scrapers']['enabled']}")
            db = stats.get("database", {})
            print(f"  Total listings: {db.get('total', {}).get('all_time', 0)}")
            print(f"  Last 24h: {db.get('total', {}).get('last_24h', 0)}")
            print(f"  Notified: {db.get('notified', {}).get('all_time', 0)}")
            print(f"  Contacted: {db.get('contacted', {}).get('all_time', 0)}")
            return

    # Run main loop
    hunter.run()


if __name__ == "__main__":
    main()
