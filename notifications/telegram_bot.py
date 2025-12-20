"""Telegram bot for sending rental notifications."""

import os
from typing import Dict, Any


class TelegramNotifier:
    """Send notifications via Telegram bot."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    def send_notification(self, listing: Dict[str, Any]) -> bool:
        """Send a Telegram notification for a new listing.

        Args:
            listing: The rental listing to notify about.

        Returns:
            True if notification was sent successfully.
        """
        if not self.bot_token or not self.chat_id:
            print("Telegram credentials not configured")
            return False

        message = self._format_message(listing)
        # TODO: Implement Telegram API call
        return True

    def _format_message(self, listing: Dict[str, Any]) -> str:
        """Format a listing into a Telegram message."""
        return f"""
🏠 *New Rental Listing*

*{listing.get('title', 'N/A')}*

💰 Price: €{listing.get('price', 'N/A')}/month
📍 Location: {listing.get('location', 'N/A')}
🛏 Bedrooms: {listing.get('bedrooms', 'N/A')}

🔗 [View Listing]({listing.get('url', '')})
"""
