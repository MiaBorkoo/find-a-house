"""Dublin Rental Hunter - Main application entry point."""

import argparse
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import schedule
import yaml
from dotenv import load_dotenv

from core.aggregator import ListingAggregator
from core.database import Database
from notifications.email_sender import EmailSender
from notifications.ntfy_sender import NtfySender
from server.app import run_server


def setup_logging(level=logging.INFO):
    """Set up logging with console and file handlers.

    Args:
        level: Logging level (default: INFO).

    Returns:
        Configured logger instance.
    """
    # Create logs directory if needed
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(level)

    # Clear existing handlers
    logger.handlers = []

    # Console handler with simple format
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_format = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler with full timestamp
    file_handler = logging.FileHandler(logs_dir / "rental_hunter.log")
    file_handler.setLevel(level)
    file_format = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    return logger


class RentalHunter:
    """Main application class for Dublin Rental Hunter."""

    def __init__(self):
        """Initialize the rental hunter."""
        # Load environment variables
        load_dotenv()

        # Load configuration
        config_path = Path(__file__).parent / "config" / "config.yaml"
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        # Set up logging
        log_level = getattr(
            logging,
            self.config.get("logging", {}).get("level", "INFO").upper(),
            logging.INFO,
        )
        setup_logging(log_level)
        self.logger = logging.getLogger(self.__class__.__name__)

        self.logger.info("=" * 50)
        self.logger.info("Dublin Rental Hunter starting up...")
        self.logger.info("=" * 50)

        # Initialize database
        db_path = self.config.get("database", {}).get("path", "data/rentals.db")
        self.database = Database(db_path)

        # Initialize notification senders
        self.ntfy_sender = NtfySender(self.config)
        self.email_sender = EmailSender(self.config)

        # Initialize aggregator
        self.aggregator = ListingAggregator(self.config, self.database)

        # State
        self.running = True
        self.server_thread = None

        # Determine server base URL for action buttons
        server_config = self.config.get("server", {})
        if server_config.get("enabled", True):
            port = server_config.get("port", 5151)
            self.server_base_url = os.getenv("SERVER_URL", f"http://localhost:{port}")
        else:
            self.server_base_url = None

        self.logger.info(f"Active filters: {self.aggregator.filter_manager.get_active_criteria_names()}")

    def start_server(self):
        """Start Flask server in background thread."""
        if self.config.get("server", {}).get("enabled", True):
            self.server_thread = threading.Thread(
                target=run_server,
                args=(self.database, self.email_sender, self.ntfy_sender, self.config),
                daemon=True,
            )
            self.server_thread.start()
            port = self.config.get("server", {}).get("port", 5151)
            self.logger.info(f"Server started on port {port}")

    def run_once(self) -> dict:
        """Run a single scrape cycle.

        Returns:
            Dictionary with found and notified counts.
        """
        self.logger.info("Starting scan...")

        # Get new listings
        new_listings = self.aggregator.process_new_listings()

        if not new_listings:
            self.logger.info("No new matching listings found")
            return {"found": 0, "notified": 0}

        self.logger.info(f"Found {len(new_listings)} new matching listings")

        # Check quiet hours
        if self._is_quiet_hours():
            self.logger.info("Quiet hours - skipping notifications")
            return {"found": len(new_listings), "notified": 0}

        # Send notifications
        notified = 0
        for listing in new_listings:
            listing_dict = listing.to_dict()
            if self.ntfy_sender.send_listing(listing_dict, self.server_base_url):
                self.database.mark_notified(listing_dict["id"])
                notified += 1
            time.sleep(1)  # Rate limit notifications

        self.logger.info(f"Sent {notified} notifications")
        return {"found": len(new_listings), "notified": notified}

    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours.

        Returns:
            True if in quiet hours and notifications should be suppressed.
        """
        quiet_config = self.config.get("schedule", {}).get("quiet_hours", {})

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

    def run_daemon(self):
        """Run continuously on schedule."""
        # Start server
        self.start_server()

        # Schedule scraping
        interval = self.config.get("schedule", {}).get("interval_minutes", 10)
        schedule.every(interval).minutes.do(self.run_once)

        # Schedule hourly email rate limit reset
        schedule.every().hour.do(self.email_sender.reset_rate_limit)

        self.logger.info(f"Daemon started. Scanning every {interval} minutes.")

        # Run immediately on start
        self.run_once()

        # Main loop
        while self.running:
            schedule.run_pending()
            time.sleep(1)

    def stop(self):
        """Graceful shutdown."""
        self.logger.info("Shutting down...")
        self.running = False


def main():
    """Main entry point with CLI."""
    parser = argparse.ArgumentParser(description="Dublin Rental Hunter")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # run command - single scan
    subparsers.add_parser("run", help="Run a single scan")

    # daemon command - continuous
    subparsers.add_parser("daemon", help="Run continuously")

    # test-ntfy command
    subparsers.add_parser("test-ntfy", help="Send test notification")

    # test-email command
    subparsers.add_parser("test-email", help="Send test email")

    # stats command
    subparsers.add_parser("stats", help="Show statistics")

    # list command
    list_parser = subparsers.add_parser("list", help="List recent listings")
    list_parser.add_argument("--hours", type=int, default=24, help="Hours to look back")

    args = parser.parse_args()

    # Handle commands
    if args.command == "run":
        hunter = RentalHunter()
        hunter.run_once()

    elif args.command == "daemon":
        hunter = RentalHunter()

        # Set up signal handlers
        def signal_handler(sig, frame):
            hunter.stop()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        hunter.run_daemon()

    elif args.command == "test-ntfy":
        load_dotenv()
        with open("config/config.yaml") as f:
            config = yaml.safe_load(f)
        ntfy = NtfySender(config)
        if ntfy.test():
            print("ntfy test successful!")
        else:
            print("ntfy test failed")

    elif args.command == "test-email":
        load_dotenv()
        with open("config/config.yaml") as f:
            config = yaml.safe_load(f)
        email = EmailSender(config)
        success, msg = email.send_test()
        if success:
            print(f"Email test successful! {msg}")
        else:
            print(f"Email test failed: {msg}")

    elif args.command == "stats":
        hunter = RentalHunter()
        stats = hunter.database.get_stats()
        total = stats.get("total", {})
        notified = stats.get("notified", {})
        contacted = stats.get("contacted", {})
        print("\nStatistics:")
        print(f"  Total listings: {total.get('all_time', 0)}")
        print(f"  Notified: {notified.get('all_time', 0)}")
        print(f"  Contacted: {contacted.get('all_time', 0)}")
        print(f"  Last 24h: {total.get('last_24h', 0)}")

    elif args.command == "list":
        hunter = RentalHunter()
        listings = hunter.database.get_recent_listings(args.hours)
        print(f"\nListings from last {args.hours} hours:\n")
        for listing in listings:
            if listing.get("contacted_at"):
                status = "[contacted]"
            elif listing.get("notified_at"):
                status = "[notified]"
            else:
                status = "[new]"
            price = listing.get("price", "?")
            title = listing.get("title", "Unknown")[:50]
            print(f"{status} E{price}/mo - {title}")
            print(f"   {listing.get('url', 'No URL')}\n")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
