"""Flask server for Dublin Rental Hunter."""

from flask import Flask, jsonify, request
from core.database import Database


app = Flask(__name__)
db = Database()


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@app.route("/listings", methods=["GET"])
def get_listings():
    """Get all listings."""
    # TODO: Implement listing retrieval
    return jsonify({"listings": []})


@app.route("/listings/new", methods=["GET"])
def get_new_listings():
    """Get new unnotified listings."""
    listings = db.get_new_listings()
    return jsonify({"listings": listings or []})


@app.route("/trigger-scrape", methods=["POST"])
def trigger_scrape():
    """Manually trigger a scrape."""
    # TODO: Implement manual scrape trigger
    return jsonify({"message": "Scrape triggered"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
