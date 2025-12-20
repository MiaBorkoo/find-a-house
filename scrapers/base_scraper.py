"""Base scraper class for rental property websites."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseScraper(ABC):
    """Abstract base class for all rental scrapers."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.base_url = config.get("base_url", "")

    @abstractmethod
    def scrape(self) -> List[Dict[str, Any]]:
        """Scrape rental listings from the website.

        Returns:
            List of dictionaries containing rental listing data.
        """
        pass

    @abstractmethod
    def parse_listing(self, listing_data: Any) -> Dict[str, Any]:
        """Parse a single listing into a standardized format.

        Args:
            listing_data: Raw listing data from the website.

        Returns:
            Dictionary with standardized listing fields.
        """
        pass

    def get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for requests."""
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
