"""ntfy.sh sender for push notifications."""

import logging
import os
import time
from urllib.parse import quote

import requests


class NtfySender:
    """Send push notifications via ntfy.sh."""

    def __init__(self, config: dict):
        """Initialize ntfy sender.

        Args:
            config: Full application configuration.
        """
        self.logger = logging.getLogger(self.__class__.__name__)

        # Get ntfy config
        ntfy_config = config.get("ntfy", {})

        # Topic from env var or config
        self.topic = os.getenv("NTFY_TOPIC") or ntfy_config.get("topic", "")
        if not self.topic:
            self.logger.warning("No ntfy topic configured!")

        # Server URL
        self.server = ntfy_config.get("server", "https://ntfy.sh")
        self.url = f"{self.server}/{self.topic}"

        # Priority for notifications
        self.priority = ntfy_config.get("priority", "high")

        # Server info for action URLs
        server_config = config.get("server", {})
        self.server_port = server_config.get("port", 5151)
        self.server_host = os.getenv("SERVER_HOST") or server_config.get("host", "localhost")

        self.logger.info(f"ntfy configured: {self.server}/{self.topic}")

    def send_listing(self, listing: dict, server_base_url: str = None) -> bool:
        """Send a notification for a new listing with action buttons.

        Args:
            listing: Listing dictionary with property details.
            server_base_url: Base URL of our server for action buttons (optional).

        Returns:
            True if notification sent successfully.
        """
        if not self.topic:
            self.logger.error("Cannot send: no ntfy topic configured")
            return False

        try:
            # Format title
            price = listing.get("price", 0)
            bedrooms = listing.get("bedrooms", "?")
            title = f"🏠 €{price}/mo - {bedrooms} bed"

            # Format message body
            message_lines = [
                listing.get("title", "New Listing"),
                "",
                f"📍 {listing.get('area', 'Dublin')}",
                f"🛏️ {listing.get('bedrooms', '?')} bed | 🚿 {listing.get('bathrooms', 1)} bath",
                f"💰 €{price}/month",
                f"📦 {listing.get('source', 'unknown')}",
                "",
                listing.get("url", ""),
            ]
            message = "\n".join(message_lines)

            # Build headers
            headers = {
                "Title": title,
                "Priority": self.priority,
                "Tags": "house,dublin",
            }

            # Add action buttons
            listing_url = listing.get("url", "")
            listing_id = listing.get("id", "")

            if server_base_url and listing_id:
                # View listing + Send email buttons
                actions = (
                    f"view, View Listing, {listing_url}; "
                    f"http, 📧 Send Email, {server_base_url}/email/{listing_id}, method=POST, clear=true"
                )
                headers["Actions"] = actions
            elif listing_url:
                # Just view button
                headers["Actions"] = f"view, View Listing, {listing_url}"

            # Click action opens listing URL
            if listing_url:
                headers["Click"] = listing_url

            # Send notification
            response = requests.post(
                self.url,
                data=message.encode("utf-8"),
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                self.logger.info(f"Sent notification for: {listing.get('title', '')[:50]}")
                return True
            else:
                self.logger.error(f"ntfy error {response.status_code}: {response.text}")
                return False

        except requests.Timeout:
            self.logger.error("ntfy request timed out")
            return False
        except requests.RequestException as e:
            self.logger.error(f"ntfy request failed: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error sending listing notification: {e}")
            return False

    def send_batch(self, listings: list[dict], server_base_url: str = None) -> int:
        """Send multiple listings with rate limiting.

        Args:
            listings: List of listing dictionaries.
            server_base_url: Base URL of our server for action buttons (optional).

        Returns:
            Count of successfully sent notifications.
        """
        if not listings:
            return 0

        success_count = 0

        try:
            # Send summary first if many listings
            if len(listings) > 5:
                self.send_alert(
                    f"🏠 {len(listings)} new listings found!",
                    "Sending individual notifications...",
                    priority="default"
                )
                time.sleep(1)

            # Send each listing
            for listing in listings:
                if self.send_listing(listing, server_base_url):
                    success_count += 1

                # Rate limit: 1 second between sends
                time.sleep(1)

        except Exception as e:
            self.logger.error(f"Error in batch send: {e}")

        self.logger.info(f"Batch send complete: {success_count}/{len(listings)} successful")
        return success_count

    def send_alert(self, title: str, message: str, priority: str = "default") -> bool:
        """Send a plain alert message.

        Args:
            title: Notification title.
            message: Notification body.
            priority: Notification priority (min, low, default, high, urgent).

        Returns:
            True if sent successfully.
        """
        if not self.topic:
            self.logger.error("Cannot send: no ntfy topic configured")
            return False

        try:
            headers = {
                "Title": title,
                "Priority": priority,
                "Tags": "bell",
            }

            response = requests.post(
                self.url,
                data=message.encode("utf-8"),
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                self.logger.info(f"Sent alert: {title}")
                return True
            else:
                self.logger.error(f"ntfy error {response.status_code}: {response.text}")
                return False

        except requests.RequestException as e:
            self.logger.error(f"Failed to send alert: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error sending alert: {e}")
            return False

    def send_stats(self, stats: dict) -> bool:
        """Send daily stats summary.

        Args:
            stats: Statistics dictionary from database.

        Returns:
            True if sent successfully.
        """
        try:
            total = stats.get("total", {})
            notified = stats.get("notified", {})
            contacted = stats.get("contacted", {})

            message_lines = [
                f"📊 Last 24 hours:",
                f"  • New listings: {total.get('last_24h', 0)}",
                f"  • Notified: {notified.get('last_24h', 0)}",
                f"  • Contacted: {contacted.get('last_24h', 0)}",
                "",
                f"📈 All time:",
                f"  • Total listings: {total.get('all_time', 0)}",
                f"  • Active: {stats.get('active', 0)}",
            ]
            message = "\n".join(message_lines)

            return self.send_alert(
                "📊 Dublin Rental Hunter Stats",
                message,
                priority="low"
            )

        except Exception as e:
            self.logger.error(f"Error sending stats: {e}")
            return False

    def test(self) -> bool:
        """Send a test notification.

        Returns:
            True if test notification sent successfully.
        """
        return self.send_alert(
            "🏠 Dublin Rental Hunter",
            "Dublin Rental Hunter is connected! 🎉\n\nYou will receive notifications when new listings match your criteria.",
            priority="default"
        )
