"""Scraper for Daft.ie rental listings using curl_cffi for browser impersonation."""

import json
import logging
import re
from typing import Optional

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper, Listing


class DaftScraper(BaseScraper):
    """Scraper for Daft.ie website using curl_cffi for browser impersonation."""

    BASE_URL = "https://www.daft.ie"

    @property
    def name(self) -> str:
        """Return the scraper name."""
        return "daft"

    def __init__(self, config: dict):
        """Initialize the scraper with a session."""
        super().__init__(config)
        # Use curl_cffi session with Chrome impersonation
        self.session = curl_requests.Session(impersonate="chrome")

    def fetch_listings(self) -> list[Listing]:
        """Fetch rental listings from Daft.ie.

        Returns:
            List of Listing objects from Daft.ie.
        """
        listings = []

        # Fetch multiple pages of Dublin listings
        for page in range(1, 4):  # Pages 1-3
            try:
                page_listings = self._fetch_page(page)
                listings.extend(page_listings)

                if len(page_listings) == 0:
                    break  # No more results

                self._rate_limit()
            except Exception as e:
                self.logger.error(f"Error fetching page {page}: {e}")
                break

        self.logger.info(f"Fetched {len(listings)} total listings from Daft.ie")
        return listings

    def _fetch_page(self, page: int) -> list[Listing]:
        """Fetch a single page of listings.

        Args:
            page: Page number.

        Returns:
            List of Listing objects.
        """
        listings = []

        try:
            url = self._build_search_url(page)
            self.logger.debug(f"Fetching: {url}")

            headers = {
                "Referer": f"{self.BASE_URL}/",
                "Sec-Fetch-Site": "same-origin",
            }

            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            listings = self._extract_listings_from_html(response.text)
            self.logger.debug(f"Found {len(listings)} listings on page {page}")

        except curl_requests.RequestsError as e:
            self.logger.error(f"Network error fetching page {page}: {e}")
        except Exception as e:
            self.logger.error(f"Error fetching page {page}: {e}")

        return listings

    def _build_search_url(self, page: int = 1) -> str:
        """Build search URL for Dublin rentals.

        Args:
            page: Page number.

        Returns:
            Search URL.
        """
        # Base Dublin search URL
        url = f"{self.BASE_URL}/property-for-rent/dublin"

        params = []

        # Price range
        min_price = self.config.get("min_price")
        max_price = self.config.get("max_price")
        if min_price:
            params.append(f"rentalPrice_from={min_price}")
        if max_price:
            params.append(f"rentalPrice_to={max_price}")

        # Bedroom range
        min_beds = self.config.get("min_beds")
        max_beds = self.config.get("max_beds")
        if min_beds is not None:
            params.append(f"numBeds_from={min_beds}")
        if max_beds is not None:
            params.append(f"numBeds_to={max_beds}")

        # Page number
        if page > 1:
            params.append(f"page={page}")

        if params:
            url += "?" + "&".join(params)

        return url

    def _extract_listings_from_html(self, html: str) -> list[Listing]:
        """Extract listing data from HTML page.

        Args:
            html: Raw HTML content.

        Returns:
            List of Listing objects.
        """
        listings = []

        try:
            soup = BeautifulSoup(html, "lxml")

            # Try to find __NEXT_DATA__ JSON (Next.js)
            next_data = soup.find("script", id="__NEXT_DATA__")
            if next_data and next_data.string:
                try:
                    data = json.loads(next_data.string)
                    props = data.get("props", {}).get("pageProps", {})

                    # Look for listings in various possible locations
                    listings_data = (
                        props.get("listings") or
                        props.get("results") or
                        props.get("searchResults", {}).get("listings") or
                        []
                    )

                    for item in listings_data:
                        # Unwrap from 'listing' key if present
                        listing_data = item.get("listing", item) if isinstance(item, dict) else item
                        listing = self._parse_json_listing(listing_data)
                        if listing:
                            listings.append(listing)

                    if listings:
                        return listings

                except (json.JSONDecodeError, TypeError, KeyError) as e:
                    self.logger.debug(f"Error parsing __NEXT_DATA__: {e}")

            # Fallback: Parse HTML directly
            listings = self._parse_html_listings(soup)

        except Exception as e:
            self.logger.error(f"Error extracting listings: {e}")

        return listings

    def _parse_json_listing(self, data: dict) -> Optional[Listing]:
        """Parse a listing from JSON data.

        Args:
            data: Listing JSON data.

        Returns:
            Listing object or None.
        """
        try:
            # Extract ID - must be numeric
            listing_id = data.get("id") or data.get("listingId")
            if not listing_id or not str(listing_id).isdigit():
                return None
            listing_id = str(listing_id)

            # Extract price - handle strings like "From €250 per week" or "€1,500 per month"
            price = 0
            price_data = data.get("price") or data.get("monthlyPrice") or ""
            if isinstance(price_data, dict):
                price = price_data.get("amount", 0)
            elif isinstance(price_data, (int, float)):
                price = int(price_data)
            elif isinstance(price_data, str):
                price = self._normalize_price(price_data)
                # Convert weekly to monthly if needed
                if "week" in price_data.lower() and price > 0:
                    price = int(price * 4.33)  # ~4.33 weeks per month

            # Extract bedrooms - handle string like "1 bed" or "Studio"
            bedrooms = 0
            bed_data = data.get("numBedrooms") or data.get("bedrooms") or ""
            if isinstance(bed_data, (int, float)):
                bedrooms = int(bed_data)
            elif isinstance(bed_data, str):
                if "studio" in bed_data.lower():
                    bedrooms = 0
                else:
                    bed_match = re.search(r"(\d+)", bed_data)
                    if bed_match:
                        bedrooms = int(bed_match.group(1))

            # Extract bathrooms
            bath_data = data.get("numBathrooms") or data.get("bathrooms") or 1
            bathrooms = int(bath_data) if isinstance(bath_data, (int, float)) else 1

            # Build URL from seoFriendlyPath or daftShortcode
            url = data.get("seoFriendlyPath") or ""
            if not url:
                shortcode = data.get("daftShortcode") or listing_id
                url = f"/for-rent/property-to-rent/{shortcode}"
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"

            # Extract image from media.images array
            image_url = ""
            media = data.get("media", {})
            if isinstance(media, dict):
                images = media.get("images", [])
                if images and isinstance(images, list):
                    first_img = images[0]
                    if isinstance(first_img, dict):
                        # Prefer larger image sizes
                        image_url = (
                            first_img.get("size720x480") or
                            first_img.get("size600x600") or
                            first_img.get("size400x300") or
                            first_img.get("url") or
                            ""
                        )

            # Extract title/address
            title = data.get("title") or data.get("seoTitle") or ""

            # Extract area from address
            area = self._extract_area_from_address(title)

            return Listing(
                id=Listing.generate_id("daft", listing_id),
                source="daft",
                title=title,
                price=price,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                property_type=data.get("propertyType", ""),
                area=area,
                address=title,
                url=url,
                image_url=image_url,
                description=data.get("description", ""),
            )

        except Exception as e:
            self.logger.debug(f"Error parsing JSON listing: {e}")
            return None

    def _extract_area_from_address(self, address: str) -> str:
        """Extract area from address string.

        Args:
            address: Address string.

        Returns:
            Area name.
        """
        if not address:
            return "Dublin"

        address_lower = address.lower()

        # Look for Dublin postal codes
        match = re.search(r"dublin\s*(\d+w?)", address_lower)
        if match:
            return f"Dublin {match.group(1).upper()}"

        # Known areas
        areas = [
            "Rathmines", "Ranelagh", "Portobello", "Drumcondra",
            "Phibsborough", "Smithfield", "Stoneybatter", "Dundrum",
            "Stillorgan", "Blackrock", "Dun Laoghaire", "Sandymount",
            "Ballsbridge", "Clontarf", "Glasnevin", "Terenure",
        ]

        for area in areas:
            if area.lower() in address_lower:
                return area

        return "Dublin"

    def _parse_html_listings(self, soup: BeautifulSoup) -> list[Listing]:
        """Parse listings from HTML when JSON is not available.

        Args:
            soup: BeautifulSoup object.

        Returns:
            List of Listing objects.
        """
        listings = []

        # Try various selectors for property cards
        card_selectors = [
            "[data-testid='results'] li",
            ".SearchPage__Result",
            "[data-testid='listing-card']",
            ".PropertyCardContainer",
            "li[data-testid]",
        ]

        cards = []
        for selector in card_selectors:
            cards = soup.select(selector)
            if cards:
                self.logger.debug(f"Found {len(cards)} cards with selector: {selector}")
                break

        for card in cards:
            try:
                listing = self._parse_html_card(card)
                if listing:
                    listings.append(listing)
            except Exception as e:
                self.logger.debug(f"Error parsing card: {e}")
                continue

        return listings

    def _parse_html_card(self, card) -> Optional[Listing]:
        """Parse a single property card from HTML.

        Args:
            card: BeautifulSoup element.

        Returns:
            Listing object or None.
        """
        try:
            # Find link
            link = card.find("a", href=True)
            if not link:
                return None

            url = link.get("href", "")
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"

            if not url or "/property-for-rent/" not in url:
                return None

            # Extract ID from URL
            listing_id = self._extract_id_from_url(url)
            if not listing_id:
                return None

            # Extract title
            title_elem = card.find(["h2", "h3"]) or link
            title = title_elem.get_text(strip=True) if title_elem else ""

            # Extract area from title
            area = self._extract_area_from_address(title)

            # Extract price
            price = 0
            price_elem = card.find(string=re.compile(r"€"))
            if price_elem:
                price = self._normalize_price(str(price_elem))
            else:
                price_elem = card.find(attrs={"data-testid": re.compile(r"price")})
                if price_elem:
                    price = self._normalize_price(price_elem.get_text())

            # Extract bedrooms
            bedrooms = 0
            bed_elem = card.find(string=re.compile(r"\d+\s*bed", re.I))
            if bed_elem:
                bedrooms = self._extract_bedrooms(str(bed_elem))
                if bedrooms == -1:
                    bedrooms = 0

            # Extract image
            image_url = ""
            img = card.find("img")
            if img:
                image_url = img.get("src") or img.get("data-src") or ""

            return Listing(
                id=Listing.generate_id("daft", listing_id),
                source="daft",
                title=title,
                price=price,
                bedrooms=bedrooms,
                bathrooms=1,
                property_type="",
                area=area,
                address=title,
                url=url,
                image_url=image_url,
                description="",
            )

        except Exception as e:
            self.logger.debug(f"Error parsing HTML card: {e}")
            return None

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extract listing ID from URL.

        Args:
            url: Listing URL.

        Returns:
            ID string or None.
        """
        if not url:
            return None

        # Try to find numeric ID
        match = re.search(r"/(\d+)/?(?:\?|$)", url)
        if match:
            return match.group(1)

        # Use last path segment
        parts = url.rstrip("/").split("/")
        if parts:
            return parts[-1]

        return None
