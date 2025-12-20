"""Filter module for filtering rental listings based on search criteria."""

import logging
import re
from dataclasses import dataclass
from typing import Optional, Union

from scrapers.base_scraper import Listing


@dataclass
class MatchResult:
    """Result of a filter match check."""

    matches: bool
    reason: str = ""
    search_name: str = ""


class SearchFilter:
    """Filter for a single search profile."""

    def __init__(self, search_config: dict):
        """Initialize filter with search configuration.

        Args:
            search_config: Single search profile from config.
        """
        self.name = search_config.get("name", "Unnamed Search")
        self.active = search_config.get("active", True)

        # Price criteria
        self.min_price = search_config.get("min_price", 0)
        self.max_price = search_config.get("max_price", float("inf"))

        # Bedroom criteria
        self.min_beds = search_config.get("min_beds", 0)
        self.max_beds = search_config.get("max_beds", float("inf"))

        # Location criteria
        self.areas = [a.lower() for a in search_config.get("areas", [])]

        # Property type criteria
        self.property_types = [p.lower() for p in search_config.get("property_types", [])]

        # Feature requirements
        self.must_have = [f.lower() for f in search_config.get("must_have", [])]
        self.nice_to_have = [f.lower() for f in search_config.get("nice_to_have", [])]

        # Exclusion keywords
        self.exclude_keywords = [k.lower() for k in search_config.get("exclude_keywords", [])]

        self.logger = logging.getLogger(f"SearchFilter:{self.name}")

    def matches(self, listing: Union[Listing, dict]) -> MatchResult:
        """Check if a listing matches this search filter.

        Args:
            listing: Listing object or dictionary to check.

        Returns:
            MatchResult with match status and reason if rejected.
        """
        # Handle both Listing objects and dicts
        if isinstance(listing, Listing):
            price = listing.price
            bedrooms = listing.bedrooms
            area = listing.area.lower() if listing.area else ""
            address = listing.address.lower() if listing.address else ""
            property_type = listing.property_type.lower() if listing.property_type else ""
            title = listing.title.lower() if listing.title else ""
            description = listing.description.lower() if listing.description else ""
            features = [f.lower() for f in (listing.features or [])]
        else:
            price = listing.get("price", 0)
            bedrooms = listing.get("bedrooms", 0)
            area = (listing.get("area", "") or "").lower()
            address = (listing.get("address", "") or "").lower()
            property_type = (listing.get("property_type", "") or "").lower()
            title = (listing.get("title", "") or "").lower()
            description = (listing.get("description", "") or "").lower()
            features = [f.lower() for f in listing.get("features", [])]

        # Check price range
        if price > 0:  # Only check if price is known
            if price < self.min_price:
                return MatchResult(False, f"Price €{price} below minimum €{self.min_price}")
            if price > self.max_price:
                return MatchResult(False, f"Price €{price} above maximum €{self.max_price}")

        # Check bedrooms
        if bedrooms >= 0:  # -1 means unknown
            if bedrooms < self.min_beds:
                return MatchResult(False, f"{bedrooms} beds below minimum {self.min_beds}")
            if bedrooms > self.max_beds:
                return MatchResult(False, f"{bedrooms} beds above maximum {self.max_beds}")

        # Check area/location
        if self.areas:
            location_text = f"{area} {address}".strip()
            if not self._matches_any_area(location_text):
                return MatchResult(False, f"Location '{area or address}' not in target areas")

        # Check property type
        if self.property_types and property_type:
            if not any(pt in property_type for pt in self.property_types):
                return MatchResult(False, f"Property type '{property_type}' not in allowed types")

        # Check exclude keywords
        full_text = f"{title} {description}"
        for keyword in self.exclude_keywords:
            if keyword in full_text:
                return MatchResult(False, f"Contains excluded keyword: '{keyword}'")

        # Check must-have features
        for required in self.must_have:
            feature_text = f"{' '.join(features)} {description}"
            if required not in feature_text:
                return MatchResult(False, f"Missing required feature: '{required}'")

        # All checks passed
        return MatchResult(True, "", self.name)

    def _matches_any_area(self, location_text: str) -> bool:
        """Check if location matches any configured area.

        Args:
            location_text: Combined area and address text.

        Returns:
            True if matches any configured area.
        """
        if not self.areas:
            return True

        location_lower = location_text.lower()

        for area in self.areas:
            # Direct match
            if area in location_lower:
                return True

            # Handle "Dublin X" variations
            if area.startswith("dublin"):
                # "dublin 2" should match "dublin2", "dublin 2", "d2"
                area_num = area.replace("dublin", "").strip()
                if area_num:
                    patterns = [
                        f"dublin\\s*{area_num}\\b",
                        f"\\bd{area_num}\\b",
                    ]
                    for pattern in patterns:
                        if re.search(pattern, location_lower):
                            return True

        return False


class FilterManager:
    """Manages multiple search filters and checks listings against them."""

    def __init__(self, config: dict):
        """Initialize filter manager with configuration.

        Args:
            config: Full application configuration.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.filters: list[SearchFilter] = []

        # Load all active search profiles
        searches = config.get("searches", [])
        for search_config in searches:
            if search_config.get("active", True):
                try:
                    search_filter = SearchFilter(search_config)
                    self.filters.append(search_filter)
                    self.logger.info(f"Loaded search filter: {search_filter.name}")
                except Exception as e:
                    self.logger.error(f"Error loading search filter: {e}")

        if not self.filters:
            self.logger.warning("No active search filters configured")

    def matches_any(self, listing: Union[Listing, dict]) -> MatchResult:
        """Check if a listing matches any active search filter.

        Args:
            listing: Listing to check.

        Returns:
            MatchResult with match status. If no filters configured, returns True.
        """
        # If no filters configured, accept all listings
        if not self.filters:
            return MatchResult(True, "No filters configured", "default")

        # Check against each filter
        rejection_reasons = []

        for search_filter in self.filters:
            result = search_filter.matches(listing)
            if result.matches:
                return MatchResult(True, "", search_filter.name)
            else:
                rejection_reasons.append(f"{search_filter.name}: {result.reason}")

        # Didn't match any filter
        # Return the first rejection reason for logging
        return MatchResult(False, rejection_reasons[0] if rejection_reasons else "No match")

    def matches_all(self, listing: Union[Listing, dict]) -> list[MatchResult]:
        """Check which filters a listing matches.

        Args:
            listing: Listing to check.

        Returns:
            List of MatchResults for each filter.
        """
        results = []
        for search_filter in self.filters:
            results.append(search_filter.matches(listing))
        return results

    def get_nice_to_have_score(self, listing: Union[Listing, dict]) -> int:
        """Calculate how many nice-to-have features a listing has.

        Args:
            listing: Listing to score.

        Returns:
            Count of nice-to-have features present.
        """
        score = 0

        # Get listing features and description
        if isinstance(listing, Listing):
            features = [f.lower() for f in (listing.features or [])]
            description = listing.description.lower() if listing.description else ""
        else:
            features = [f.lower() for f in listing.get("features", [])]
            description = (listing.get("description", "") or "").lower()

        feature_text = f"{' '.join(features)} {description}"

        # Check each filter's nice-to-have list
        for search_filter in self.filters:
            for nice in search_filter.nice_to_have:
                if nice in feature_text:
                    score += 1

        return score


# Keep old class name for backward compatibility
class ListingFilter(FilterManager):
    """Deprecated: Use FilterManager instead."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.logger.warning("ListingFilter is deprecated, use FilterManager instead")

    def filter_listings(self, listings: list) -> list:
        """Filter listings - backward compatibility method."""
        return [lst for lst in listings if self.matches_any(lst).matches]
