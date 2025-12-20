"""Aggregator module for combining listings from multiple scrapers."""

from typing import List, Dict, Any
from scrapers.base_scraper import BaseScraper


class ListingAggregator:
    """Aggregates rental listings from multiple scrapers."""

    def __init__(self, scrapers: List[BaseScraper]):
        self.scrapers = scrapers

    def aggregate(self) -> List[Dict[str, Any]]:
        """Run all scrapers and aggregate results.

        Returns:
            Combined list of listings from all scrapers.
        """
        all_listings = []
        for scraper in self.scrapers:
            try:
                listings = scraper.scrape()
                all_listings.extend(listings)
            except Exception as e:
                print(f"Error scraping {scraper.__class__.__name__}: {e}")
        return all_listings

    def deduplicate(self, listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate listings based on URL.

        Args:
            listings: List of listings that may contain duplicates.

        Returns:
            Deduplicated list of listings.
        """
        seen_urls = set()
        unique_listings = []
        for listing in listings:
            url = listing.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_listings.append(listing)
        return unique_listings
