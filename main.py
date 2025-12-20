"""Dublin Rental Hunter - Main entry point."""

import time
import yaml
from pathlib import Path
from dotenv import load_dotenv

from scrapers.daft_scraper import DaftScraper
from scrapers.rent_ie_scraper import RentIeScraper
from scrapers.myhome_scraper import MyHomeScraper
from core.database import Database
from core.filter import ListingFilter
from core.aggregator import ListingAggregator
from notifications.ntfy_sender import NtfyNotifier
from notifications.email_sender import EmailNotifier


def load_config() -> dict:
    """Load configuration from YAML file."""
    config_path = Path(__file__).parent / "config" / "config.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def main():
    """Main function to run the rental hunter."""
    # Load environment variables
    load_dotenv()

    # Load configuration
    config = load_config()

    # Initialize database
    db = Database(config.get("database", {}).get("path", "rentals.db"))

    # Initialize scrapers
    scrapers = []
    scraper_config = config.get("scrapers", {})

    if scraper_config.get("daft", {}).get("enabled"):
        scrapers.append(DaftScraper(scraper_config["daft"]))
    if scraper_config.get("rent_ie", {}).get("enabled"):
        scrapers.append(RentIeScraper(scraper_config["rent_ie"]))
    if scraper_config.get("myhome", {}).get("enabled"):
        scrapers.append(MyHomeScraper(scraper_config["myhome"]))

    # Initialize aggregator and filter
    aggregator = ListingAggregator(scrapers)
    listing_filter = ListingFilter(config)

    # Initialize notifiers
    notifiers = []
    notification_config = config.get("notifications", {})

    if notification_config.get("ntfy", {}).get("enabled"):
        notifiers.append(NtfyNotifier(notification_config["ntfy"]))
    if notification_config.get("email", {}).get("enabled"):
        notifiers.append(EmailNotifier(notification_config["email"]))

    # Main loop
    scrape_interval = config.get("scrape_interval", 30) * 60  # Convert to seconds

    print("Dublin Rental Hunter started!")
    print(f"Scraping every {config.get('scrape_interval', 30)} minutes...")

    while True:
        try:
            # Scrape all sources
            print("Scraping rental listings...")
            listings = aggregator.aggregate()
            listings = aggregator.deduplicate(listings)

            # Filter listings
            filtered_listings = listing_filter.filter_listings(listings)
            print(f"Found {len(filtered_listings)} matching listings")

            # Process new listings
            for listing in filtered_listings:
                if db.add_listing(listing):
                    # Send notifications for new listings
                    for notifier in notifiers:
                        notifier.send_notification(listing)
                    db.mark_as_notified(listing.get("id"))

            # Wait for next scrape
            time.sleep(scrape_interval)

        except KeyboardInterrupt:
            print("\nShutting down...")
            break
        except Exception as e:
            print(f"Error during scraping: {e}")
            time.sleep(60)  # Wait a minute before retrying

    db.close()


if __name__ == "__main__":
    main()
