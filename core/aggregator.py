"""Aggregator module for combining listings from multiple scrapers."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from scrapers.base_scraper import Listing
from scrapers.daft_scraper import DaftScraper
from scrapers.rent_ie_scraper import RentIeScraper
from scrapers.myhome_scraper import MyHomeScraper
from core.database import Database
from core.filter import FilterManager


class ListingAggregator:
    """Aggregates rental listings from multiple scrapers and processes them."""

    def __init__(self, config: dict, database: Database):
        """Initialize the aggregator.

        Args:
            config: Full application configuration.
            database: Database instance for storing listings.
        """
        self.config = config
        self.database = database
        self.logger = logging.getLogger(self.__class__.__name__)

        # Initialize scrapers based on config
        self.scrapers = []
        scraper_config = config.get("scrapers", {})

        if scraper_config.get("daft", {}).get("enabled", False):
            try:
                # Pass search config to scraper for filtering
                daft_config = self._build_scraper_config("daft", scraper_config)
                self.scrapers.append(DaftScraper(daft_config))
                self.logger.info("Daft.ie scraper enabled")
            except Exception as e:
                self.logger.error(f"Failed to initialize Daft scraper: {e}")

        if scraper_config.get("rent_ie", {}).get("enabled", False):
            try:
                rent_config = self._build_scraper_config("rent_ie", scraper_config)
                self.scrapers.append(RentIeScraper(rent_config))
                self.logger.info("Rent.ie scraper enabled")
            except Exception as e:
                self.logger.error(f"Failed to initialize Rent.ie scraper: {e}")

        if scraper_config.get("myhome", {}).get("enabled", False):
            try:
                myhome_config = self._build_scraper_config("myhome", scraper_config)
                self.scrapers.append(MyHomeScraper(myhome_config))
                self.logger.info("MyHome.ie scraper enabled")
            except Exception as e:
                self.logger.error(f"Failed to initialize MyHome scraper: {e}")

        if not self.scrapers:
            self.logger.warning("No scrapers enabled!")

        # Initialize filter manager
        self.filter_manager = FilterManager(config)

    def _build_scraper_config(self, scraper_name: str, scraper_config: dict) -> dict:
        """Build configuration for a scraper including search criteria.

        Args:
            scraper_name: Name of the scraper (daft, rent_ie, myhome).
            scraper_config: Scrapers section of config.

        Returns:
            Combined config with scraper settings and search criteria.
        """
        # Start with scraper-specific config
        config = dict(scraper_config.get(scraper_name, {}))

        # Get the first active search profile for scraper-level filtering
        searches = self.config.get("searches", [])
        for search in searches:
            if search.get("active", False):
                # Merge search criteria into scraper config
                config["areas"] = search.get("areas", [])
                config["min_price"] = search.get("min_price", 0)
                config["max_price"] = search.get("max_price")
                config["min_beds"] = search.get("min_beds", 0)
                config["max_beds"] = search.get("max_beds")
                config["property_types"] = search.get("property_types", [])
                break

        return config

    def fetch_all(self) -> list[Listing]:
        """Fetch listings from all enabled scrapers concurrently.

        Returns:
            Combined list of Listing objects from all scrapers.
        """
        if not self.scrapers:
            self.logger.warning("No scrapers to run")
            return []

        all_listings: list[Listing] = []

        with ThreadPoolExecutor(max_workers=len(self.scrapers)) as executor:
            # Submit all scraper jobs
            futures = {
                executor.submit(self._safe_fetch, scraper): scraper.name
                for scraper in self.scrapers
            }

            # Collect results as they complete
            for future in as_completed(futures):
                source = futures[future]
                try:
                    listings = future.result(timeout=120)
                    self.logger.info(f"{source}: found {len(listings)} listings")
                    all_listings.extend(listings)
                except TimeoutError:
                    self.logger.error(f"{source}: timed out after 120 seconds")
                except Exception as e:
                    self.logger.error(f"{source} failed: {e}")

        self.logger.info(f"Total: fetched {len(all_listings)} listings from {len(self.scrapers)} sources")
        return all_listings

    def _safe_fetch(self, scraper) -> list[Listing]:
        """Safely fetch listings from a scraper with error handling.

        Args:
            scraper: Scraper instance to fetch from.

        Returns:
            List of listings, empty list on error.
        """
        try:
            return scraper.fetch_listings()
        except Exception as e:
            self.logger.error(f"Error in {scraper.name} scraper: {e}")
            return []

    def process_new_listings(self) -> list[Listing]:
        """Fetch all listings, filter, and save new ones to database.

        Returns:
            List of new listings that passed filters.
        """
        # Fetch from all sources
        all_listings = self.fetch_all()

        new_listings: list[Listing] = []
        total_count = len(all_listings)
        new_count = 0
        filtered_count = 0

        for listing in all_listings:
            try:
                # Convert to dict for database storage
                listing_dict = listing.to_dict()

                # Try to add to database (returns True if new)
                if self.database.add_listing(listing_dict):
                    new_count += 1

                    # Check if passes any search filters
                    if self.filter_manager.matches_any(listing):
                        new_listings.append(listing)
                        self.logger.debug(
                            f"New listing: {listing.title[:50]}... "
                            f"(€{listing.price}, {listing.bedrooms} bed)"
                        )
                    else:
                        filtered_count += 1
                        self.logger.debug(f"Filtered out: {listing.title[:50]}...")

            except Exception as e:
                self.logger.error(f"Error processing listing {listing.id}: {e}")
                continue

        passed_count = len(new_listings)
        self.logger.info(
            f"Summary: {total_count} fetched, {new_count} new, "
            f"{passed_count} passed filters, {filtered_count} filtered out"
        )

        return new_listings

    def get_stats(self) -> dict:
        """Get aggregator and database statistics.

        Returns:
            Dictionary with stats about scrapers and database.
        """
        try:
            db_stats = self.database.get_stats()
        except Exception as e:
            self.logger.error(f"Error getting database stats: {e}")
            db_stats = {}

        return {
            "scrapers": {
                "enabled": [s.name for s in self.scrapers],
                "count": len(self.scrapers),
            },
            "database": db_stats,
        }
