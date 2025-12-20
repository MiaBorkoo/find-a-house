"""Email sender for rental inquiry emails via SMTP."""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


class EmailSender:
    """Send rental inquiry emails via SMTP."""

    # Default templates if file not found
    DEFAULT_SUBJECT = "Rental Inquiry - {property_title}"
    DEFAULT_BODY = """Dear Landlord/Agent,

I am writing to express my interest in the property: {property_title}

I found this listing on {source} and would like to arrange a viewing.

Property link: {property_url}

Kind regards,
{user_name}
Phone: {user_phone}
Email: {user_email}
"""

    def __init__(self, config: dict):
        """Initialize email sender.

        Args:
            config: Full application configuration.
        """
        self.logger = logging.getLogger(self.__class__.__name__)

        # SMTP settings
        email_config = config.get("email", {})
        self.smtp_server = email_config.get("smtp_server", "smtp.gmail.com")
        self.smtp_port = email_config.get("smtp_port", 587)

        # Credentials from environment
        self.username = os.getenv("GMAIL_ADDRESS", "")
        self.password = os.getenv("GMAIL_APP_PASSWORD", "")

        if not self.username or not self.password:
            self.logger.warning("Gmail credentials not configured in environment")

        # User info for email signature
        user_config = config.get("user", {})
        self.user_name = user_config.get("name", "")
        self.user_phone = user_config.get("phone", "")
        self.user_email = user_config.get("email", "") or self.username

        # Load email template
        self.subject_template, self.body_template = self._load_template()

        # Rate limiting
        self.sent_count = 0
        self.max_per_hour = 20

        self.logger.info(f"Email sender configured with {self.smtp_server}:{self.smtp_port}")

    def _load_template(self) -> tuple[str, str]:
        """Load email template from file.

        Returns:
            Tuple of (subject_template, body_template).
        """
        template_path = Path(__file__).parent.parent / "config" / "email_template.txt"

        try:
            if template_path.exists():
                content = template_path.read_text()
                lines = content.strip().split("\n")

                subject = self.DEFAULT_SUBJECT
                body_lines = []
                reading_body = False

                for line in lines:
                    if line.upper().startswith("SUBJECT:"):
                        subject = line[8:].strip()
                    elif reading_body or line == "":
                        reading_body = True
                        body_lines.append(line)

                body = "\n".join(body_lines).strip()

                if body:
                    self.logger.info("Loaded email template from file")
                    return (subject, body)

        except Exception as e:
            self.logger.warning(f"Error loading template: {e}")

        self.logger.info("Using default email template")
        return (self.DEFAULT_SUBJECT, self.DEFAULT_BODY)

    def _render(self, listing: dict) -> tuple[str, str]:
        """Render email template with listing data.

        Args:
            listing: Listing dictionary with property details.

        Returns:
            Tuple of (subject, body) with placeholders replaced.
        """
        replacements = {
            "{property_title}": listing.get("title", "Property"),
            "{property_url}": listing.get("url", ""),
            "{source}": listing.get("source", "online"),
            "{user_name}": self.user_name,
            "{user_phone}": self.user_phone,
            "{user_email}": self.user_email,
        }

        subject = self.subject_template
        body = self.body_template

        for placeholder, value in replacements.items():
            subject = subject.replace(placeholder, str(value))
            body = body.replace(placeholder, str(value))

        return (subject, body)

    def send_inquiry(self, listing: dict) -> tuple[bool, str]:
        """Send rental inquiry email for a listing.

        Args:
            listing: Listing dictionary with property details.

        Returns:
            Tuple of (success, message).
        """
        # Check credentials
        if not self.username or not self.password:
            return (False, "Gmail credentials not configured")

        # Check rate limit
        if self.sent_count >= self.max_per_hour:
            return (False, f"Rate limit reached ({self.max_per_hour}/hour)")

        # Get recipient
        to_email = listing.get("contact_email")
        if not to_email:
            return (False, "No contact email available")

        # Render template
        subject, body = self._render(listing)

        # Create message
        msg = MIMEMultipart()
        msg["From"] = f"{self.user_name} <{self.username}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg["Reply-To"] = self.user_email
        msg.attach(MIMEText(body, "plain"))

        # Send via SMTP
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)

            self.sent_count += 1
            self.logger.info(f"Email sent to {to_email} for: {listing.get('title', '')[:50]}")
            return (True, f"Email sent to {to_email}")

        except smtplib.SMTPAuthenticationError:
            self.logger.error("SMTP authentication failed - check credentials")
            return (False, "Authentication failed - check Gmail app password")

        except smtplib.SMTPRecipientsRefused:
            self.logger.error(f"Recipient refused: {to_email}")
            return (False, f"Recipient refused: {to_email}")

        except smtplib.SMTPSenderRefused:
            self.logger.error("Sender refused - check your email address")
            return (False, "Sender refused - check your email address")

        except smtplib.SMTPDataError as e:
            self.logger.error(f"SMTP data error: {e}")
            return (False, f"Email rejected by server: {e}")

        except smtplib.SMTPConnectError:
            self.logger.error(f"Could not connect to {self.smtp_server}:{self.smtp_port}")
            return (False, f"Could not connect to SMTP server")

        except smtplib.SMTPException as e:
            self.logger.error(f"SMTP error: {e}")
            return (False, f"SMTP error: {e}")

        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
            return (False, str(e))

    def send_test(self) -> tuple[bool, str]:
        """Send a test email to yourself.

        Returns:
            Tuple of (success, message).
        """
        if not self.username or not self.password:
            return (False, "Gmail credentials not configured")

        # Create test message
        msg = MIMEMultipart()
        msg["From"] = f"{self.user_name} <{self.username}>"
        msg["To"] = self.username
        msg["Subject"] = "Dublin Rental Hunter - Test Email"
        msg.attach(MIMEText(
            "This is a test email from Dublin Rental Hunter.\n\n"
            "If you received this, your email configuration is working correctly!\n\n"
            f"SMTP Server: {self.smtp_server}:{self.smtp_port}\n"
            f"From: {self.user_name} <{self.username}>",
            "plain"
        ))

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)

            self.logger.info("Test email sent successfully")
            return (True, f"Test email sent to {self.username}")

        except smtplib.SMTPAuthenticationError:
            return (False, "Authentication failed - check Gmail app password")
        except Exception as e:
            self.logger.error(f"Test email failed: {e}")
            return (False, str(e))

    def reset_rate_limit(self) -> None:
        """Reset the hourly rate limit counter.

        Call this method once per hour to allow more emails.
        """
        self.sent_count = 0
        self.logger.debug("Email rate limit counter reset")

    def get_status(self) -> dict:
        """Get email sender status.

        Returns:
            Dictionary with status information.
        """
        return {
            "configured": bool(self.username and self.password),
            "smtp_server": self.smtp_server,
            "smtp_port": self.smtp_port,
            "sent_count": self.sent_count,
            "remaining": max(0, self.max_per_hour - self.sent_count),
        }
