"""Filter module for filtering rental listings based on search criteria."""

import logging
import re

from scrapers.base_scraper import Listing


class ListingFilter:
    """Filter for checking if a listing matches search criteria."""

    def __init__(self, criteria: dict):
        """Initialize filter with search criteria.

        Args:
            criteria: Search criteria dictionary from config.
        """
        self.criteria = criteria
        self.name = criteria.get("name", "Unnamed")
        self.logger = logging.getLogger(f"ListingFilter:{self.name}")

        # Price criteria
        self.min_price = criteria.get("min_price", 0)
        self.max_price = criteria.get("max_price", float("inf"))

        # Bedroom criteria
        self.min_beds = criteria.get("min_beds", 0)
        self.max_beds = criteria.get("max_beds", float("inf"))

        # Location criteria
        self.areas = [a.lower() for a in criteria.get("areas", [])]

        # Property type criteria
        self.property_types = [p.lower() for p in criteria.get("property_types", [])]

        # Required features
        self.must_have = [f.lower() for f in criteria.get("must_have", [])]

        # Exclusion keywords
        self.exclude_keywords = [k.lower() for k in criteria.get("exclude_keywords", [])]

    def matches(self, listing: Listing) -> tuple[bool, str]:
        """Check if a listing matches all criteria.

        Args:
            listing: Listing to check.

        Returns:
            Tuple of (matches, reason). If matches is False, reason explains why.
        """
        # Check in order of importance
        checks = [
            self._check_price,
            self._check_bedrooms,
            self._check_area,
            self._check_exclusions,
            self._check_must_have,
        ]

        for check in checks:
            passed, reason = check(listing)
            if not passed:
                return (False, reason)

        return (True, "")

    def _check_price(self, listing: Listing) -> tuple[bool, str]:
        """Check if listing price is within range.

        Args:
            listing: Listing to check.

        Returns:
            Tuple of (passes, reason).
        """
        # If price is unknown (0), give benefit of doubt
        if listing.price == 0:
            return (True, "")

        if listing.price > self.max_price:
            return (False, f"Price €{listing.price} > max €{self.max_price}")

        if listing.price < self.min_price:
            return (False, f"Price €{listing.price} < min €{self.min_price}")

        return (True, "")

    def _check_bedrooms(self, listing: Listing) -> tuple[bool, str]:
        """Check if listing bedrooms are within range.

        Args:
            listing: Listing to check.

        Returns:
            Tuple of (passes, reason).
        """
        # If bedrooms unknown (-1), give benefit of doubt
        if listing.bedrooms < 0:
            return (True, "")

        if listing.bedrooms < self.min_beds:
            return (False, f"{listing.bedrooms} beds < min {self.min_beds}")

        if listing.bedrooms > self.max_beds:
            return (False, f"{listing.bedrooms} beds > max {self.max_beds}")

        return (True, "")

    def _check_area(self, listing: Listing) -> tuple[bool, str]:
        """Check if listing is in an allowed area.

        Args:
            listing: Listing to check.

        Returns:
            Tuple of (passes, reason).
        """
        # If no areas configured, pass all
        if not self.areas:
            return (True, "")

        # Normalize listing area
        listing_area = (listing.area or "").lower()
        listing_address = (listing.address or "").lower()
        location_text = f"{listing_area} {listing_address}"

        for area in self.areas:
            # Direct substring match
            if area in location_text:
                return (True, "")

            # Check if location text contains the area
            if location_text in area:
                return (True, "")

            # Handle Dublin variations: "D2" <-> "Dublin 2"
            if self._areas_match(area, location_text):
                return (True, "")

        return (False, f"Area '{listing.area or listing.address}' not in allowed areas")

    def _areas_match(self, config_area: str, location_text: str) -> bool:
        """Check if areas match with Dublin variations.

        Args:
            config_area: Area from config (lowercase).
            location_text: Combined area/address text (lowercase).

        Returns:
            True if areas match.
        """
        # Handle "Dublin X" variations
        dublin_match = re.match(r"dublin\s*(\d+)", config_area)
        if dublin_match:
            num = dublin_match.group(1)
            # Check for "dublin X", "dublinX", "d X", "dX"
            patterns = [
                rf"dublin\s*{num}\b",
                rf"\bd{num}\b",
                rf"\bd\s*{num}\b",
            ]
            for pattern in patterns:
                if re.search(pattern, location_text):
                    return True

        # Handle "DX" in config matching "Dublin X"
        d_match = re.match(r"d(\d+)", config_area)
        if d_match:
            num = d_match.group(1)
            if re.search(rf"dublin\s*{num}\b", location_text):
                return True

        return False

    def _check_exclusions(self, listing: Listing) -> tuple[bool, str]:
        """Check if listing contains any excluded keywords.

        Args:
            listing: Listing to check.

        Returns:
            Tuple of (passes, reason).
        """
        if not self.exclude_keywords:
            return (True, "")

        # Combine title and description
        text = f"{listing.title or ''} {listing.description or ''}".lower()

        for keyword in self.exclude_keywords:
            if keyword in text:
                return (False, f"Contains excluded keyword: '{keyword}'")

        return (True, "")

    def _check_must_have(self, listing: Listing) -> tuple[bool, str]:
        """Check if listing has all required features.

        Args:
            listing: Listing to check.

        Returns:
            Tuple of (passes, reason).
        """
        if not self.must_have:
            return (True, "")

        # Combine features and description
        features_text = " ".join(f.lower() for f in (listing.features or []))
        description = (listing.description or "").lower()
        combined = f"{features_text} {description}"

        for feature in self.must_have:
            if feature not in combined:
                return (False, f"Missing required feature: '{feature}'")

        return (True, "")


class FilterManager:
    """Manages multiple search filters."""

    def __init__(self, config: dict):
        """Initialize filter manager with configuration.

        Args:
            config: Full application configuration.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.filters: list[ListingFilter] = []

        # Load all active search criteria
        searches = config.get("searches", [])
        for criteria in searches:
            if criteria.get("active", True):
                try:
                    listing_filter = ListingFilter(criteria)
                    self.filters.append(listing_filter)
                    self.logger.info(f"Loaded filter: {listing_filter.name}")
                except Exception as e:
                    self.logger.error(f"Error loading filter: {e}")

        if not self.filters:
            self.logger.warning("No active search filters configured")

    def matches_any(self, listing: Listing) -> bool:
        """Check if a listing matches any active filter.

        Args:
            listing: Listing to check.

        Returns:
            True if listing matches at least one filter.
        """
        # If no filters configured, accept all
        if not self.filters:
            return True

        first_reason = None

        for listing_filter in self.filters:
            matches, reason = listing_filter.matches(listing)
            if matches:
                self.logger.debug(f"Listing matches filter '{listing_filter.name}'")
                return True
            elif first_reason is None:
                first_reason = f"{listing_filter.name}: {reason}"

        # Log first rejection reason
        if first_reason:
            self.logger.debug(f"Listing rejected - {first_reason}")

        return False

    def get_active_criteria_names(self) -> list[str]:
        """Get names of all active search criteria.

        Returns:
            List of filter names.
        """
        return [f.name for f in self.filters]
