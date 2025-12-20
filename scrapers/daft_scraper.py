"""Scraper for Daft.ie rental listings using daftlistings library."""

import logging
import re
from typing import Optional

import requests
from daftlistings import Daft, Location, SearchType, PropertyType

from scrapers.base_scraper import BaseScraper, Listing


class DaftScraper(BaseScraper):
    """Scraper for Daft.ie website using daftlistings library."""

    @property
    def name(self) -> str:
        """Return the scraper name."""
        return "daft"

    def fetch_listings(self) -> list[Listing]:
        """Fetch rental listings from Daft.ie.

        Returns:
            List of Listing objects from Daft.ie.
        """
        listings = []
        areas = self.config.get("areas", [])

        # If no areas specified, do a general Dublin search
        if not areas:
            areas = ["Dublin"]

        for area in areas:
            try:
                area_listings = self._search_area(area)
                listings.extend(area_listings)
                self._rate_limit()
            except Exception as e:
                self.logger.error(f"Error searching area '{area}': {e}")
                continue

        self.logger.info(f"Fetched {len(listings)} total listings from Daft.ie")
        return listings

    def _search_area(self, area: str) -> list[Listing]:
        """Search for listings in a specific area.

        Args:
            area: Area name to search (e.g., "Dublin 2", "Rathmines").

        Returns:
            List of Listing objects for the area.
        """
        listings = []

        try:
            daft = Daft()

            # Set custom User-Agent to avoid blocks
            daft.set_headers({
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36"
            })

            # Set search type to residential rent
            daft.set_search_type(SearchType.RESIDENTIAL_RENT)

            # Try to find matching Location enum
            location = self._get_location(area)
            if location:
                daft.set_location(location)
            else:
                # Use string location as fallback
                daft.set_location(area)

            # Set price range from config
            min_price = self.config.get("min_price")
            max_price = self.config.get("max_price")
            if min_price:
                daft.set_min_price(min_price)
            if max_price:
                daft.set_max_price(max_price)

            # Set bedroom range from config
            min_beds = self.config.get("min_beds")
            max_beds = self.config.get("max_beds")
            if min_beds is not None:
                daft.set_min_beds(min_beds)
            if max_beds is not None:
                daft.set_max_beds(max_beds)

            # Execute search
            self.logger.debug(f"Searching Daft.ie for area: {area}")
            results = daft.search(max_pages=2)

            for result in results:
                try:
                    listing = self._parse_result(result, area)
                    if listing:
                        listings.append(listing)
                except (AttributeError, TypeError, ValueError) as e:
                    self.logger.warning(f"Error parsing listing: {e}")
                    continue

            self.logger.debug(f"Found {len(listings)} listings in {area}")

        except requests.RequestException as e:
            self.logger.error(f"Network error searching Daft.ie for '{area}': {e}")
        except AttributeError as e:
            self.logger.error(f"API error (daftlistings may need update): {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error searching Daft.ie for '{area}': {e}")

        return listings

    def _get_location(self, area: str) -> Optional[Location]:
        """Try to find a matching Location enum value.

        Args:
            area: Area name string.

        Returns:
            Location enum value if found, None otherwise.
        """
        # Normalize area name to match enum format
        # e.g., "Dublin 2" -> "DUBLIN_2", "Rathmines" -> "RATHMINES"
        normalized = area.upper().replace(" ", "_").replace("-", "_")

        # Remove "CO." prefix if present
        normalized = re.sub(r"^CO\.?\s*_?", "", normalized)

        try:
            return Location[normalized]
        except KeyError:
            # Try some common variations
            variations = [
                normalized,
                f"DUBLIN_{normalized}",
                normalized.replace("DUBLIN_", ""),
            ]

            for var in variations:
                try:
                    return Location[var]
                except KeyError:
                    continue

            self.logger.debug(f"No Location enum found for '{area}', using string")
            return None

    def _parse_result(self, result, area: str) -> Optional[Listing]:
        """Parse a daftlistings result into a Listing object.

        Args:
            result: Result object from daftlistings search.
            area: The area that was searched.

        Returns:
            Listing object, or None if parsing fails.
        """
        # Extract listing ID from daft_link or use result.id
        listing_id = self._extract_id(result)
        if not listing_id:
            self.logger.warning("Could not extract listing ID, skipping")
            return None

        # Get price
        price_str = getattr(result, "price", "") or ""
        price = self._normalize_price(str(price_str))

        # Get bedrooms
        bedrooms = getattr(result, "bedrooms", None)
        if bedrooms is None or bedrooms == "":
            title = getattr(result, "title", "") or ""
            bedrooms = self._extract_bedrooms(title)
            if bedrooms == -1:
                bedrooms = 0

        # Get bathrooms
        bathrooms = getattr(result, "bathrooms", None)
        if bathrooms is None or bathrooms == "":
            bathrooms = 1

        # Get images
        images = getattr(result, "images", []) or []
        image_url = images[0] if images else ""

        # Get other fields safely
        title = getattr(result, "title", "") or ""
        daft_link = getattr(result, "daft_link", "") or ""

        # Try to get additional fields that may exist
        property_type = ""
        try:
            property_type = getattr(result, "property_type", "") or ""
        except Exception:
            pass

        address = ""
        try:
            address = getattr(result, "address", "") or ""
        except Exception:
            pass

        description = ""
        try:
            description = getattr(result, "description", "") or ""
        except Exception:
            pass

        # Build features list
        features = []
        try:
            facilities = getattr(result, "facilities", []) or []
            features.extend(facilities)
        except Exception:
            pass

        return Listing(
            id=Listing.generate_id("daft", listing_id),
            source="daft",
            title=title,
            price=price,
            bedrooms=int(bedrooms) if bedrooms else 0,
            bathrooms=int(bathrooms) if bathrooms else 1,
            property_type=str(property_type),
            area=self._normalize_area(area),
            address=address,
            url=daft_link,
            image_url=image_url,
            description=description,
            features=features,
        )

    def _extract_id(self, result) -> Optional[str]:
        """Extract listing ID from result.

        Args:
            result: Result object from daftlistings.

        Returns:
            Listing ID string, or None if not found.
        """
        # Try result.id first
        result_id = getattr(result, "id", None)
        if result_id:
            return str(result_id)

        # Try to extract from daft_link
        # e.g., "https://www.daft.ie/for-rent/apartment-.../1234567"
        daft_link = getattr(result, "daft_link", "") or ""
        if daft_link:
            # Extract the numeric ID from the URL
            match = re.search(r"/(\d+)/?$", daft_link)
            if match:
                return match.group(1)

            # Try to get any unique identifier from the URL
            # Use last path segment as fallback
            parts = daft_link.rstrip("/").split("/")
            if parts:
                return parts[-1]

        return None
