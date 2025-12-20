"""Filter module for filtering rental listings based on criteria."""

from typing import List, Dict, Any


class ListingFilter:
    """Filter rental listings based on user-defined criteria."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.search_config = config.get("search", {})

    def filter_listings(self, listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter listings based on configured criteria.

        Args:
            listings: List of rental listings to filter.

        Returns:
            Filtered list of listings matching criteria.
        """
        filtered = []
        for listing in listings:
            if self._matches_criteria(listing):
                filtered.append(listing)
        return filtered

    def _matches_criteria(self, listing: Dict[str, Any]) -> bool:
        """Check if a listing matches the filter criteria."""
        # Check price range
        min_price = self.search_config.get("min_price", 0)
        max_price = self.search_config.get("max_price", float("inf"))
        price = listing.get("price", 0)
        if not (min_price <= price <= max_price):
            return False

        # Check bedrooms
        min_beds = self.search_config.get("min_bedrooms", 0)
        max_beds = self.search_config.get("max_bedrooms", float("inf"))
        bedrooms = listing.get("bedrooms", 0)
        if not (min_beds <= bedrooms <= max_beds):
            return False

        # TODO: Add more filter criteria (location, property type, etc.)

        return True
