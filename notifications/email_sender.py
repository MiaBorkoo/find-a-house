"""Email sender for rental notifications."""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any
from pathlib import Path


class EmailNotifier:
    """Send notifications via email."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.smtp_server = config.get("smtp_server", "smtp.gmail.com")
        self.smtp_port = config.get("smtp_port", 587)
        self.sender_email = os.getenv("EMAIL_SENDER", "")
        self.sender_password = os.getenv("EMAIL_PASSWORD", "")
        self.recipient_email = os.getenv("EMAIL_RECIPIENT", "")
        self.template = self._load_template()

    def _load_template(self) -> str:
        """Load email template from file."""
        template_path = Path(__file__).parent.parent / "config" / "email_template.txt"
        if template_path.exists():
            return template_path.read_text()
        return "New listing: {title} - €{price} - {url}"

    def send_notification(self, listing: Dict[str, Any]) -> bool:
        """Send an email notification for a new listing.

        Args:
            listing: The rental listing to notify about.

        Returns:
            True if notification was sent successfully.
        """
        if not all([self.sender_email, self.sender_password, self.recipient_email]):
            print("Email credentials not configured")
            return False

        try:
            message = self._create_message(listing)
            # TODO: Implement SMTP sending
            return True
        except Exception as e:
            print(f"Failed to send email: {e}")
            return False

    def _create_message(self, listing: Dict[str, Any]) -> MIMEMultipart:
        """Create an email message from a listing."""
        msg = MIMEMultipart()
        msg["From"] = self.sender_email
        msg["To"] = self.recipient_email
        msg["Subject"] = f"New Rental: {listing.get('title', 'New Listing')}"

        body = self.template.format(**listing)
        msg.attach(MIMEText(body, "plain"))
        return msg
