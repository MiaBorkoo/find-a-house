"""Flask server for Dublin Rental Hunter - handles ntfy action buttons."""

import logging
import os

from flask import Flask, jsonify, request


def create_app(database, email_sender, ntfy_sender, config):
    """Create and configure the Flask application.

    Args:
        database: Database instance for listing storage.
        email_sender: EmailSender instance for sending inquiries.
        ntfy_sender: NtfySender instance for notifications.
        config: Application configuration dictionary.

    Returns:
        Configured Flask application.
    """
    app = Flask(__name__)
    logger = logging.getLogger("FlaskServer")

    # Store dependencies
    app.database = database
    app.email_sender = email_sender
    app.ntfy_sender = ntfy_sender
    app.config["APP_CONFIG"] = config

    @app.route("/health", methods=["GET"])
    def health():
        """Health check endpoint."""
        return jsonify({"status": "ok"})

    @app.route("/email/<listing_id>", methods=["POST"])
    def send_email(listing_id):
        """Handle email send request from ntfy action button.

        Args:
            listing_id: ID of the listing to send inquiry for.

        Returns:
            JSON response with success/error status.
        """
        # Get listing from database
        listing = app.database.get_listing(listing_id)
        if not listing:
            app.ntfy_sender.send_alert("❌ Error", f"Listing {listing_id} not found")
            return jsonify({"error": "Listing not found"}), 404

        # Check if already contacted
        if listing.get("contacted_at"):
            app.ntfy_sender.send_alert(
                "ℹ️ Already Sent", f"Already emailed for: {listing['title']}"
            )
            return jsonify({"error": "Already contacted"}), 400

        # Send email
        success, message = app.email_sender.send_inquiry(listing)

        if success:
            # Mark as contacted in database
            app.database.mark_contacted(
                listing_id,
                listing.get("contact_email", "unknown"),
                f"Inquiry - {listing['title']}",
            )
            # Notify user of success
            app.ntfy_sender.send_alert(
                "✅ Email Sent!",
                f"Inquiry sent for:\n{listing['title']}\n\nTo: {listing.get('contact_email', 'N/A')}",
            )
            return jsonify({"success": True, "message": message})
        else:
            # Notify user of failure
            app.ntfy_sender.send_alert("❌ Email Failed", f"Could not send email:\n{message}")
            return jsonify({"error": message}), 500

    @app.route("/listings/recent", methods=["GET"])
    def recent_listings():
        """Get recent listings (for debugging).

        Query params:
            hours: Number of hours to look back (default: 24)

        Returns:
            JSON list of recent listings.
        """
        hours = request.args.get("hours", 24, type=int)
        listings = app.database.get_recent_listings(hours)
        return jsonify(listings)

    @app.route("/stats", methods=["GET"])
    def stats():
        """Get system stats.

        Returns:
            JSON with database statistics.
        """
        return jsonify(app.database.get_stats())

    return app


def run_server(database, email_sender, ntfy_sender, config):
    """Run the Flask server.

    Args:
        database: Database instance.
        email_sender: EmailSender instance.
        ntfy_sender: NtfySender instance.
        config: Application configuration.
    """
    app = create_app(database, email_sender, ntfy_sender, config)
    port = int(os.getenv("SERVER_PORT", config.get("server", {}).get("port", 5151)))
    host = config.get("server", {}).get("host", "0.0.0.0")

    # Use threaded=True for handling concurrent requests
    app.run(host=host, port=port, threaded=True)
