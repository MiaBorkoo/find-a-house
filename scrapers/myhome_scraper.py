"""Scraper for MyHome.ie rental listings."""

import json
import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper, Listing


class MyHomeScraper(BaseScraper):
    """Scraper for MyHome.ie website using HTML parsing."""

    BASE_URL = "https://www.myhome.ie"
    SEARCH_URL = "https://www.myhome.ie/rentals/dublin/property-to-rent"

    @property
    def name(self) -> str:
        """Return the scraper name."""
        return "myhome"

    def fetch_listings(self) -> list[Listing]:
        """Fetch rental listings from MyHome.ie.

        Returns:
            List of Listing objects from MyHome.ie.
        """
        listings = []

        try:
            # Fetch first page
            page1_listings = self._fetch_page(1)
            listings.extend(page1_listings)

            # Fetch second page if first page was successful
            if page1_listings:
                self._rate_limit()
                page2_listings = self._fetch_page(2)
                listings.extend(page2_listings)

        except Exception as e:
            self.logger.error(f"Error fetching MyHome.ie listings: {e}")

        self.logger.info(f"Fetched {len(listings)} listings from MyHome.ie")
        return listings

    def _fetch_page(self, page: int) -> list[Listing]:
        """Fetch a single page of search results.

        Args:
            page: Page number to fetch.

        Returns:
            List of Listing objects from the page.
        """
        listings = []

        try:
            url = self._build_search_url(page)
            self.logger.debug(f"Fetching page {page}: {url}")

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IE,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            # Check if response is JSON
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                listings = self._parse_json_response(response.json())
            else:
                # Try to find embedded JSON data first
                json_listings = self._extract_json_from_html(response.text)
                if json_listings:
                    listings = json_listings
                else:
                    # Fall back to HTML parsing
                    listings = self._parse_html_response(response.text)

        except requests.RequestException as e:
            self.logger.error(f"Network error fetching page {page}: {e}")
        except Exception as e:
            self.logger.error(f"Error parsing page {page}: {e}")

        return listings

    def _build_search_url(self, page: int = 1) -> str:
        """Build search URL with configured parameters.

        Args:
            page: Page number.

        Returns:
            Complete search URL with query parameters.
        """
        params = []

        # Price range
        min_price = self.config.get("min_price")
        max_price = self.config.get("max_price")
        if min_price:
            params.append(f"minprice={min_price}")
        if max_price:
            params.append(f"maxprice={max_price}")

        # Bedroom range
        min_beds = self.config.get("min_beds")
        max_beds = self.config.get("max_beds")
        if min_beds is not None:
            params.append(f"minbeds={min_beds}")
        if max_beds is not None:
            params.append(f"maxbeds={max_beds}")

        # Page number
        if page > 1:
            params.append(f"page={page}")

        url = self.SEARCH_URL
        if params:
            url += "?" + "&".join(params)

        return url

    def _extract_json_from_html(self, html: str) -> list[Listing]:
        """Try to extract JSON data embedded in HTML.

        Many modern sites embed property data as JSON in script tags.

        Args:
            html: Raw HTML content.

        Returns:
            List of Listing objects, empty if no JSON found.
        """
        listings = []

        try:
            soup = BeautifulSoup(html, "lxml")

            # Look for JSON-LD schema data
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string)
                    if isinstance(data, list):
                        for item in data:
                            listing = self._parse_json_ld_item(item)
                            if listing:
                                listings.append(listing)
                    elif isinstance(data, dict):
                        listing = self._parse_json_ld_item(data)
                        if listing:
                            listings.append(listing)
                except (json.JSONDecodeError, TypeError):
                    continue

            # Look for __NEXT_DATA__ (Next.js sites)
            next_data = soup.find("script", id="__NEXT_DATA__")
            if next_data and next_data.string:
                try:
                    data = json.loads(next_data.string)
                    props = data.get("props", {}).get("pageProps", {})
                    properties = props.get("properties", []) or props.get("listings", [])
                    for prop in properties:
                        listing = self._parse_json_property(prop)
                        if listing:
                            listings.append(listing)
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass

            # Look for other common patterns
            for script in soup.find_all("script"):
                if not script.string:
                    continue
                # Look for window.__DATA__ or similar patterns
                match = re.search(r"window\.__(?:DATA|INITIAL_STATE|PROPS)__\s*=\s*({.*?});",
                                  script.string, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        properties = self._find_properties_in_json(data)
                        for prop in properties:
                            listing = self._parse_json_property(prop)
                            if listing:
                                listings.append(listing)
                    except (json.JSONDecodeError, TypeError):
                        continue

        except Exception as e:
            self.logger.debug(f"Error extracting JSON from HTML: {e}")

        return listings

    def _find_properties_in_json(self, data: dict, depth: int = 0) -> list[dict]:
        """Recursively find property listings in nested JSON.

        Args:
            data: JSON data to search.
            depth: Current recursion depth.

        Returns:
            List of property dictionaries.
        """
        if depth > 5:  # Prevent infinite recursion
            return []

        properties = []

        if isinstance(data, dict):
            # Check if this looks like a property
            if self._looks_like_property(data):
                properties.append(data)
            else:
                # Search nested keys
                for key in ["properties", "listings", "results", "items", "data"]:
                    if key in data:
                        value = data[key]
                        if isinstance(value, list):
                            for item in value:
                                if isinstance(item, dict) and self._looks_like_property(item):
                                    properties.append(item)
                                elif isinstance(item, dict):
                                    properties.extend(self._find_properties_in_json(item, depth + 1))
                        elif isinstance(value, dict):
                            properties.extend(self._find_properties_in_json(value, depth + 1))

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    properties.extend(self._find_properties_in_json(item, depth + 1))

        return properties

    def _looks_like_property(self, data: dict) -> bool:
        """Check if a dict looks like a property listing.

        Args:
            data: Dictionary to check.

        Returns:
            True if it appears to be a property listing.
        """
        property_keys = {"price", "bedrooms", "beds", "address", "propertyType", "url", "link"}
        return len(property_keys & set(data.keys())) >= 2

    def _parse_json_response(self, data: dict) -> list[Listing]:
        """Parse JSON API response.

        Args:
            data: Parsed JSON data.

        Returns:
            List of Listing objects.
        """
        listings = []
        properties = self._find_properties_in_json(data)

        for prop in properties:
            listing = self._parse_json_property(prop)
            if listing:
                listings.append(listing)

        return listings

    def _parse_json_ld_item(self, data: dict) -> Optional[Listing]:
        """Parse a JSON-LD schema item.

        Args:
            data: JSON-LD data.

        Returns:
            Listing object, or None if not a property.
        """
        item_type = data.get("@type", "")
        if item_type not in ["Residence", "Apartment", "House", "RealEstateListing", "Product"]:
            return None

        try:
            # Extract ID
            listing_id = data.get("identifier") or data.get("sku") or data.get("@id", "")
            if not listing_id:
                url = data.get("url", "")
                listing_id = self._extract_id_from_url(url)

            if not listing_id:
                return None

            # Extract price
            price = 0
            offers = data.get("offers", {})
            if isinstance(offers, dict):
                price_str = offers.get("price", "") or offers.get("lowPrice", "")
                price = self._normalize_price(str(price_str))

            # Extract address
            address_data = data.get("address", {})
            if isinstance(address_data, dict):
                address = address_data.get("streetAddress", "")
                area = address_data.get("addressLocality", "") or address_data.get("addressRegion", "")
            else:
                address = str(address_data)
                area = ""

            return Listing(
                id=Listing.generate_id("myhome", str(listing_id)),
                source="myhome",
                title=data.get("name", "") or data.get("description", "")[:100],
                price=price,
                bedrooms=int(data.get("numberOfRooms", 0)) or 0,
                bathrooms=int(data.get("numberOfBathroomsTotal", 1)) or 1,
                property_type=item_type.lower(),
                area=self._normalize_area(area),
                address=address,
                url=data.get("url", ""),
                image_url=data.get("image", "") if isinstance(data.get("image"), str) else "",
                description=data.get("description", ""),
            )
        except Exception as e:
            self.logger.debug(f"Error parsing JSON-LD item: {e}")
            return None

    def _parse_json_property(self, data: dict) -> Optional[Listing]:
        """Parse a property from JSON data.

        Args:
            data: Property JSON data.

        Returns:
            Listing object, or None if parsing fails.
        """
        try:
            # Extract ID
            listing_id = (
                data.get("id") or
                data.get("propertyId") or
                data.get("listingId") or
                data.get("brochureId")
            )
            if not listing_id:
                url = data.get("url") or data.get("link") or data.get("seoUrl", "")
                listing_id = self._extract_id_from_url(url)

            if not listing_id:
                return None

            # Extract price
            price = 0
            price_val = data.get("price") or data.get("rentPrice") or data.get("monthlyRent")
            if price_val:
                price = self._normalize_price(str(price_val))

            # Extract bedrooms
            bedrooms = data.get("bedrooms") or data.get("beds") or data.get("numBedrooms") or 0
            if isinstance(bedrooms, str):
                bedrooms = self._extract_bedrooms(bedrooms)
                if bedrooms == -1:
                    bedrooms = 0

            # Extract bathrooms
            bathrooms = data.get("bathrooms") or data.get("baths") or data.get("numBathrooms") or 1

            # Extract URL
            url = data.get("url") or data.get("link") or data.get("seoUrl", "")
            if url and not url.startswith("http"):
                url = f"{self.BASE_URL}{url}"

            # Extract image
            image_url = ""
            images = data.get("images") or data.get("photos") or []
            if images and isinstance(images, list) and len(images) > 0:
                first_img = images[0]
                image_url = first_img.get("url") or first_img if isinstance(first_img, str) else ""
            elif data.get("mainImage"):
                image_url = data["mainImage"]
            elif data.get("imageUrl"):
                image_url = data["imageUrl"]

            # Extract address/area
            address = data.get("address") or data.get("displayAddress") or ""
            if isinstance(address, dict):
                address = address.get("displayAddress") or address.get("line1", "")

            area = data.get("area") or data.get("county") or data.get("locality") or ""
            if not area and address:
                area = self._extract_area_from_address(address)

            return Listing(
                id=Listing.generate_id("myhome", str(listing_id)),
                source="myhome",
                title=data.get("title") or data.get("displayAddress") or address,
                price=int(price) if price else 0,
                bedrooms=int(bedrooms) if bedrooms else 0,
                bathrooms=int(bathrooms) if bathrooms else 1,
                property_type=data.get("propertyType", "").lower() if data.get("propertyType") else "",
                area=self._normalize_area(area),
                address=address if isinstance(address, str) else "",
                url=url,
                image_url=image_url,
                description=data.get("description", ""),
                features=data.get("features", []) or [],
            )
        except Exception as e:
            self.logger.debug(f"Error parsing JSON property: {e}")
            return None

    def _parse_html_response(self, html: str) -> list[Listing]:
        """Parse HTML search results page.

        Args:
            html: Raw HTML content.

        Returns:
            List of Listing objects.
        """
        listings = []

        try:
            soup = BeautifulSoup(html, "lxml")

            # Try various selectors for property cards
            card_selectors = [
                ".PropertyCard",
                ".property-card",
                "[data-testid='property-card']",
                ".PropertyListingCard",
                ".search-result",
                ".listing-card",
                "article.property",
                ".PropertyImage",  # MyHome specific
            ]

            cards = []
            for selector in card_selectors:
                cards = soup.select(selector)
                if cards:
                    self.logger.debug(f"Found {len(cards)} cards with selector: {selector}")
                    break

            # If no cards found, try finding links to property pages
            if not cards:
                cards = soup.find_all("a", href=re.compile(r"/rentals/[^/]+/\d+"))

            for card in cards:
                try:
                    listing = self._parse_property_card(card)
                    if listing:
                        listings.append(listing)
                except Exception as e:
                    self.logger.debug(f"Error parsing card: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Error parsing HTML: {e}")

        return listings

    def _parse_property_card(self, card) -> Optional[Listing]:
        """Parse a property card HTML element.

        Args:
            card: BeautifulSoup element.

        Returns:
            Listing object, or None if essential fields missing.
        """
        try:
            # Extract URL
            url = ""
            link = card.find("a", href=True) if card.name != "a" else card
            if link:
                url = link.get("href", "")
                if url and not url.startswith("http"):
                    url = f"{self.BASE_URL}{url}"

            if not url:
                return None

            # Extract ID from URL or data attribute
            listing_id = card.get("data-id") or card.get("data-property-id")
            if not listing_id:
                listing_id = self._extract_id_from_url(url)

            if not listing_id:
                return None

            # Extract title
            title = ""
            title_elem = card.find(class_=re.compile(r"title|address|heading", re.I))
            if title_elem:
                title = title_elem.get_text(strip=True)
            elif link:
                title = link.get_text(strip=True)

            # Extract price
            price = 0
            price_elem = card.find(class_=re.compile(r"price", re.I))
            if price_elem:
                price = self._normalize_price(price_elem.get_text())

            # Extract bedrooms
            bedrooms = 0
            bed_elem = card.find(class_=re.compile(r"bed", re.I))
            if bed_elem:
                bedrooms = self._extract_bedrooms(bed_elem.get_text())
                if bedrooms == -1:
                    bedrooms = 0
            else:
                # Try to find from text content
                bedrooms = self._extract_bedrooms(card.get_text())
                if bedrooms == -1:
                    bedrooms = 0

            # Extract bathrooms
            bathrooms = 1
            bath_elem = card.find(class_=re.compile(r"bath", re.I))
            if bath_elem:
                bath_text = bath_elem.get_text()
                bath_match = re.search(r"(\d+)", bath_text)
                if bath_match:
                    bathrooms = int(bath_match.group(1))

            # Extract image
            image_url = ""
            img = card.find("img")
            if img:
                image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src", "")

            # Extract area from address
            area = self._extract_area_from_address(title)

            return Listing(
                id=Listing.generate_id("myhome", str(listing_id)),
                source="myhome",
                title=title,
                price=price,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                property_type="",
                area=self._normalize_area(area),
                address=title,  # Often the title is the address
                url=url,
                image_url=image_url,
                description="",
            )
        except Exception as e:
            self.logger.debug(f"Error parsing property card: {e}")
            return None

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extract property ID from URL.

        Args:
            url: Property URL.

        Returns:
            ID string, or None if not found.
        """
        if not url:
            return None

        # Try to find numeric ID in URL
        match = re.search(r"/(\d+)/?(?:\?|$|#)", url)
        if match:
            return match.group(1)

        # Try brochure ID pattern
        match = re.search(r"brochure[/-](\d+)", url, re.I)
        if match:
            return match.group(1)

        # Use last path segment
        parts = url.rstrip("/").split("/")
        if parts:
            last = parts[-1].split("?")[0]
            if last:
                return last

        return None

    def _extract_area_from_address(self, address: str) -> str:
        """Extract area/locality from address string.

        Args:
            address: Full address string.

        Returns:
            Area name.
        """
        if not address:
            return "Dublin"

        # Look for Dublin postal codes
        match = re.search(r"Dublin\s*(\d+)", address, re.I)
        if match:
            return f"Dublin {match.group(1)}"

        # Look for known areas
        known_areas = [
            "Rathmines", "Ranelagh", "Portobello", "Drumcondra",
            "Phibsborough", "Smithfield", "Stoneybatter", "Dundrum",
            "Stillorgan", "Blackrock", "Dun Laoghaire", "Sandymount",
            "Ballsbridge", "Clontarf", "Glasnevin", "Terenure",
        ]

        address_lower = address.lower()
        for area in known_areas:
            if area.lower() in address_lower:
                return area

        # Default
        if "dublin" in address_lower:
            return "Dublin"

        return address.split(",")[0].strip() if "," in address else "Dublin"
