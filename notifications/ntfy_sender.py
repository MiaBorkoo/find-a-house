"""ntfy.sh sender for rental notifications."""

import os
import requests
from typing import Dict, Any


class NtfyNotifier:
    """Send notifications via ntfy.sh."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.topic = os.getenv("NTFY_TOPIC", "")
        self.server = os.getenv("NTFY_SERVER", "https://ntfy.sh")

    def send_notification(self, listing: Dict[str, Any]) -> bool:
        """Send an ntfy notification for a new listing.

        Args:
            listing: The rental listing to notify about.

        Returns:
            True if notification was sent successfully.
        """
        if not self.topic:
            print("ntfy topic not configured")
            return False

        try:
            url = f"{self.server}/{self.topic}"
            title = f"🏠 {listing.get('title', 'New Rental')}"
            message = self._format_message(listing)

            response = requests.post(
                url,
                data=message.encode("utf-8"),
                headers={
                    "Title": title,
                    "Priority": "high",
                    "Tags": "house",
                    "Click": listing.get("url", ""),
                },
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to send ntfy notification: {e}")
            return False

    def _format_message(self, listing: Dict[str, Any]) -> str:
        """Format a listing into an ntfy message."""
        return (
            f"💰 €{listing.get('price', 'N/A')}/month\n"
            f"📍 {listing.get('location', 'N/A')}\n"
            f"🛏 {listing.get('bedrooms', 'N/A')} bedrooms\n"
            f"🔗 {listing.get('url', '')}"
        )
