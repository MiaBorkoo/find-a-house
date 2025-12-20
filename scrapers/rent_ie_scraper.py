"""Scraper for Rent.ie rental listings using RSS feeds."""

import logging
import re
from datetime import datetime
from typing import Optional

import feedparser
from dateutil import parser as date_parser

from scrapers.base_scraper import BaseScraper, Listing


class RentIeScraper(BaseScraper):
    """Scraper for Rent.ie website using RSS feeds."""

    BASE_FEED_URL = "https://www.rent.ie/rss"

    # Area name to URL slug mapping
    AREA_SLUGS = {
        "dublin 2": "dublin-2",
        "dublin 4": "dublin-4",
        "dublin 6": "dublin-6",
        "dublin 8": "dublin-8",
        "dublin 1": "dublin-1",
        "dublin 3": "dublin-3",
        "dublin 5": "dublin-5",
        "dublin 7": "dublin-7",
        "dublin 9": "dublin-9",
        "dublin 10": "dublin-10",
        "dublin 11": "dublin-11",
        "dublin 12": "dublin-12",
        "dublin 13": "dublin-13",
        "dublin 14": "dublin-14",
        "dublin 15": "dublin-15",
        "dublin 16": "dublin-16",
        "dublin 17": "dublin-17",
        "dublin 18": "dublin-18",
        "dublin 20": "dublin-20",
        "dublin 22": "dublin-22",
        "dublin 24": "dublin-24",
        "dublin city centre": "dublin-city-centre",
        "rathmines": "rathmines",
        "ranelagh": "ranelagh",
        "portobello": "portobello",
        "drumcondra": "drumcondra",
        "phibsborough": "phibsborough",
        "smithfield": "smithfield",
        "stoneybatter": "stoneybatter",
        "dundrum": "dundrum",
        "stillorgan": "stillorgan",
        "blackrock": "blackrock",
        "dun laoghaire": "dun-laoghaire",
        "sandymount": "sandymount",
        "ballsbridge": "ballsbridge",
        "clontarf": "clontarf",
        "glasnevin": "glasnevin",
        "terenure": "terenure",
        "harold's cross": "harolds-cross",
        "harolds cross": "harolds-cross",
        "ringsend": "ringsend",
        "grand canal": "grand-canal-dock",
        "ifsc": "ifsc",
    }

    @property
    def name(self) -> str:
        """Return the scraper name."""
        return "rent_ie"

    def _get_feed_urls(self) -> list[str]:
        """Generate RSS feed URLs based on configured areas.

        Returns:
            List of RSS feed URLs to fetch.
        """
        urls = set()
        areas = self.config.get("areas", [])
        include_rooms = self.config.get("include_rooms", False)

        for area in areas:
            slug = self._area_to_slug(area)
            if slug:
                # Houses/apartments to let
                urls.add(f"{self.BASE_FEED_URL}/houses-to-let/dublin/{slug}/")

                # Rooms to rent (if enabled)
                if include_rooms:
                    urls.add(f"{self.BASE_FEED_URL}/rooms-to-rent/dublin/{slug}/")

        # Always include general Dublin feed as fallback
        urls.add(f"{self.BASE_FEED_URL}/houses-to-let/dublin/")

        self.logger.debug(f"Generated {len(urls)} feed URLs")
        return list(urls)

    def _area_to_slug(self, area: str) -> str:
        """Convert area name to URL slug.

        Args:
            area: Area name (e.g., "Dublin 2", "Rathmines").

        Returns:
            URL-friendly slug (e.g., "dublin-2", "rathmines").
        """
        area_lower = area.lower().strip()

        # Check known mappings first
        if area_lower in self.AREA_SLUGS:
            return self.AREA_SLUGS[area_lower]

        # Generic conversion: lowercase, replace spaces with hyphens
        slug = area_lower.replace(" ", "-")
        slug = re.sub(r"[^a-z0-9-]", "", slug)  # Remove special chars
        slug = re.sub(r"-+", "-", slug)  # Collapse multiple hyphens

        return slug

    def fetch_listings(self) -> list[Listing]:
        """Fetch rental listings from Rent.ie RSS feeds.

        Returns:
            List of Listing objects from Rent.ie.
        """
        # Use dict to deduplicate by URL
        listings_by_url: dict[str, Listing] = {}

        feed_urls = self._get_feed_urls()

        for url in feed_urls:
            try:
                feed_listings = self._parse_feed(url)
                for listing in feed_listings:
                    if listing.url and listing.url not in listings_by_url:
                        listings_by_url[listing.url] = listing

                self._rate_limit()

            except Exception as e:
                self.logger.error(f"Error fetching feed {url}: {e}")
                continue

        listings = list(listings_by_url.values())
        self.logger.info(f"Fetched {len(listings)} unique listings from Rent.ie")
        return listings

    def _parse_feed(self, url: str) -> list[Listing]:
        """Parse a single RSS feed.

        Args:
            url: RSS feed URL.

        Returns:
            List of Listing objects from the feed.
        """
        listings = []

        self.logger.debug(f"Fetching feed: {url}")
        feed = feedparser.parse(url)

        # Check for parse errors
        if feed.bozo:
            self.logger.warning(f"Feed parse warning for {url}: {feed.bozo_exception}")
            # Continue anyway, partial data may still be available

        for entry in feed.entries:
            try:
                listing = self._parse_entry(entry)
                if listing:
                    listings.append(listing)
            except Exception as e:
                self.logger.warning(f"Error parsing entry: {e}")
                continue

        self.logger.debug(f"Parsed {len(listings)} listings from {url}")
        return listings

    def _parse_entry(self, entry) -> Optional[Listing]:
        """Parse a single feed entry into a Listing.

        Args:
            entry: feedparser entry object.

        Returns:
            Listing object, or None if parsing fails.
        """
        # Extract URL
        url = getattr(entry, "link", "") or ""
        if not url:
            return None

        # Extract ID from entry.id or URL
        entry_id = self._extract_id(entry, url)
        if not entry_id:
            return None

        # Get basic fields
        title = getattr(entry, "title", "") or ""
        summary = entry.get("summary", "") or entry.get("description", "") or ""

        # Parse posted date
        posted_at = self._parse_date(entry)

        # Extract price from title or description
        price = self._extract_price(title, summary)

        # Extract bedrooms from title or description
        bedrooms = self._extract_bedrooms(f"{title} {summary}")
        if bedrooms == -1:
            bedrooms = 0

        # Extract area from title or categories
        area = self._extract_area(entry, title)

        # Try to extract image from content or media
        image_url = self._extract_image(entry)

        return Listing(
            id=Listing.generate_id("rent_ie", entry_id),
            source="rent_ie",
            title=title,
            price=price,
            bedrooms=bedrooms,
            bathrooms=1,  # RSS doesn't typically include this
            property_type=self._extract_property_type(title, summary),
            area=self._normalize_area(area),
            address="",  # Not typically in RSS
            url=url,
            image_url=image_url,
            description=self._clean_html(summary),
            features=[],  # Not typically in RSS
            posted_at=posted_at,
        )

    def _extract_id(self, entry, url: str) -> Optional[str]:
        """Extract unique ID from entry or URL.

        Args:
            entry: feedparser entry object.
            url: Entry URL.

        Returns:
            Unique ID string, or None if not found.
        """
        # Try entry.id first
        entry_id = getattr(entry, "id", None)
        if entry_id:
            # If it's a URL, extract the path
            if entry_id.startswith("http"):
                match = re.search(r"/(\d+)/?", entry_id)
                if match:
                    return match.group(1)
                # Use last path segment
                parts = entry_id.rstrip("/").split("/")
                if parts:
                    return parts[-1]
            return str(entry_id)

        # Extract from URL
        if url:
            match = re.search(r"/(\d+)/?", url)
            if match:
                return match.group(1)

            # Use last path segment as fallback
            parts = url.rstrip("/").split("/")
            if parts:
                return parts[-1]

        return None

    def _parse_date(self, entry) -> Optional[datetime]:
        """Parse publication date from entry.

        Args:
            entry: feedparser entry object.

        Returns:
            datetime object, or None if parsing fails.
        """
        date_str = None

        # Try different date fields
        for field in ["published", "updated", "created"]:
            date_str = getattr(entry, field, None)
            if date_str:
                break

        if not date_str:
            return None

        try:
            return date_parser.parse(date_str)
        except (ValueError, TypeError) as e:
            self.logger.debug(f"Could not parse date '{date_str}': {e}")
            return None

    def _extract_price(self, title: str, description: str) -> int:
        """Extract price from title or description.

        Args:
            title: Entry title.
            description: Entry description.

        Returns:
            Monthly rent as integer, 0 if not found.
        """
        text = f"{title} {description}"

        # Look for euro prices: €1,800, €1800, 1,800 EUR, etc.
        patterns = [
            r"€\s*([\d,]+)",
            r"([\d,]+)\s*(?:EUR|euro)",
            r"([\d,]+)\s*(?:per month|p/m|pcm|pm)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                price_str = match.group(1).replace(",", "")
                try:
                    return int(price_str)
                except ValueError:
                    continue

        # Fallback to base class method
        return self._normalize_price(text)

    def _extract_area(self, entry, title: str) -> str:
        """Extract area from entry categories or title.

        Args:
            entry: feedparser entry object.
            title: Entry title.

        Returns:
            Area name string.
        """
        # Try categories first
        categories = getattr(entry, "tags", []) or []
        for tag in categories:
            term = getattr(tag, "term", "") or ""
            if term and "dublin" in term.lower():
                return term

        # Try to extract from title
        # Look for "in Dublin X" or "Dublin X" pattern
        match = re.search(r"(?:in\s+)?(Dublin\s*\d+|Dublin\s+City\s+Centre)", title, re.IGNORECASE)
        if match:
            return match.group(1)

        # Look for known areas in title
        title_lower = title.lower()
        for area in self.AREA_SLUGS.keys():
            if area in title_lower:
                return area.title()

        return "Dublin"

    def _extract_property_type(self, title: str, description: str) -> str:
        """Extract property type from title or description.

        Args:
            title: Entry title.
            description: Entry description.

        Returns:
            Property type string.
        """
        text = f"{title} {description}".lower()

        if "studio" in text:
            return "studio"
        elif "apartment" in text or "apt" in text:
            return "apartment"
        elif "house" in text:
            return "house"
        elif "flat" in text:
            return "flat"
        elif "duplex" in text:
            return "duplex"
        elif "room" in text:
            return "room"

        return ""

    def _extract_image(self, entry) -> str:
        """Extract image URL from entry.

        Args:
            entry: feedparser entry object.

        Returns:
            Image URL string, or empty string if not found.
        """
        # Try media_content
        media = getattr(entry, "media_content", []) or []
        for m in media:
            url = m.get("url", "")
            if url:
                return url

        # Try enclosures
        enclosures = getattr(entry, "enclosures", []) or []
        for enc in enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("href", "") or enc.get("url", "")

        # Try to extract from content/summary
        content = getattr(entry, "content", [{}])[0].get("value", "") if hasattr(entry, "content") else ""
        summary = getattr(entry, "summary", "") or ""

        for text in [content, summary]:
            match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', text)
            if match:
                return match.group(1)

        return ""

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags from text.

        Args:
            text: Text potentially containing HTML.

        Returns:
            Cleaned text.
        """
        if not text:
            return ""

        # Remove HTML tags
        clean = re.sub(r"<[^>]+>", " ", text)

        # Decode common entities
        clean = clean.replace("&nbsp;", " ")
        clean = clean.replace("&amp;", "&")
        clean = clean.replace("&lt;", "<")
        clean = clean.replace("&gt;", ">")
        clean = clean.replace("&quot;", '"')

        # Collapse whitespace
        clean = " ".join(clean.split())

        return clean.strip()
