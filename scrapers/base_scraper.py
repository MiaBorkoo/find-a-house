"""Base scraper class for rental property websites."""

import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Listing:
    """Standardized rental listing data structure."""

    id: str
    source: str
    title: str
    price: int  # Monthly rent in euros, 0 if unknown
    bedrooms: int  # 0 for studio
    bathrooms: int = 1
    property_type: str = ""
    area: str = ""
    address: str = ""
    url: str = ""
    image_url: str = ""
    description: str = ""
    features: list = field(default_factory=list)
    contact_email: str = ""
    contact_phone: str = ""
    posted_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert listing to dictionary.

        Returns:
            Dictionary with all listing fields.
        """
        data = asdict(self)
        # Convert datetime to ISO string for JSON serialization
        if self.posted_at:
            data["posted_at"] = self.posted_at.isoformat()
        return data

    @staticmethod
    def generate_id(source: str, original_id: str) -> str:
        """Generate a unique listing ID.

        Args:
            source: The source website (e.g., 'daft', 'myhome').
            original_id: The original ID from the source website.

        Returns:
            Combined ID in format '{source}_{original_id}'.
        """
        return f"{source}_{original_id}"


class BaseScraper(ABC):
    """Abstract base class for all rental scrapers."""

    # Word to number mapping for bedroom extraction
    WORD_TO_NUM = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }

    def __init__(self, config: dict):
        """Initialize the scraper.

        Args:
            config: Scraper configuration dictionary.
        """
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.rate_limit_seconds = config.get("rate_limit_seconds", 2)

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the scraper name.

        Returns:
            Human-readable name of the scraper.
        """
        pass

    @abstractmethod
    def fetch_listings(self) -> list[Listing]:
        """Fetch rental listings from the website.

        Returns:
            List of Listing objects.
        """
        pass

    def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        self.logger.debug(f"Rate limiting: sleeping {self.rate_limit_seconds} seconds")
        time.sleep(self.rate_limit_seconds)

    def _normalize_price(self, price_str: str) -> int:
        """Extract monthly rent from price string.

        Handles formats like:
        - "€1,800 per month"
        - "€1800/mo"
        - "1,800 EUR"
        - "€450 per week"

        Args:
            price_str: Raw price string from listing.

        Returns:
            Monthly rent as integer, 0 if cannot parse.
        """
        if not price_str:
            return 0

        price_str = price_str.lower()

        # Check if it's a weekly price
        is_weekly = any(w in price_str for w in ["per week", "/week", "pw", "p/w", "weekly"])

        # Extract all digits and join them
        digits = re.findall(r"\d+", price_str.replace(",", ""))
        if not digits:
            return 0

        try:
            # Take the first number found (the main price)
            price = int("".join(digits[:1]))

            # If there are multiple digit groups, the price might be split (e.g., "1" and "800")
            # Check if the first number is suspiciously small
            if price < 100 and len(digits) > 1:
                price = int(digits[0] + digits[1])

            # Convert weekly to monthly
            if is_weekly:
                price = int(price * 4.33)

            return price
        except (ValueError, IndexError):
            return 0

    def _normalize_area(self, area_str: str) -> str:
        """Normalize area/location string.

        Args:
            area_str: Raw area string.

        Returns:
            Cleaned and normalized area string.
        """
        if not area_str:
            return ""

        # Strip whitespace
        area = area_str.strip()

        # Handle "Co. Dublin" -> "Dublin"
        area = re.sub(r"\bCo\.?\s*", "", area, flags=re.IGNORECASE)

        # Remove extra whitespace
        area = " ".join(area.split())

        # Title case
        area = area.title()

        return area

    def _extract_bedrooms(self, text: str) -> int:
        """Extract number of bedrooms from text.

        Handles patterns like:
        - "2 bed"
        - "2-bed"
        - "2 bedroom"
        - "two bed"
        - "studio"

        Args:
            text: Text to search for bedroom count.

        Returns:
            Number of bedrooms (0 for studio, -1 if cannot determine).
        """
        if not text:
            return -1

        text = text.lower()

        # Check for studio first
        if re.search(r"\bstudio\b", text):
            return 0

        # Look for numeric patterns: "2 bed", "2-bed", "2 bedroom"
        match = re.search(r"(\d+)\s*[-\s]?\s*bed(?:room)?s?\b", text)
        if match:
            return int(match.group(1))

        # Look for word patterns: "two bed", "three bedroom"
        for word, num in self.WORD_TO_NUM.items():
            if re.search(rf"\b{word}\s*[-\s]?\s*bed(?:room)?s?\b", text):
                return num

        return -1

    def get_headers(self) -> dict[str, str]:
        """Get HTTP headers for requests.

        Returns:
            Dictionary of HTTP headers.
        """
        return {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IE,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }
