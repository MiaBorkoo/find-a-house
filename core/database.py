"""Database module for storing and managing rental listings."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)


class Database:
    """SQLite database for storing rental listings and contact history."""

    def __init__(self, db_path: str = "data/rentals.db"):
        """Initialize the database.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database, creating tables if they don't exist."""
        # Create data directory if it doesn't exist
        db_dir = Path(self.db_path).parent
        if not db_dir.exists():
            db_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created database directory: {db_dir}")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Create listings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    original_id TEXT,
                    title TEXT,
                    price INTEGER,
                    bedrooms INTEGER,
                    bathrooms INTEGER,
                    property_type TEXT,
                    area TEXT,
                    address TEXT,
                    url TEXT UNIQUE,
                    image_url TEXT,
                    description TEXT,
                    features TEXT,
                    contact_email TEXT,
                    contact_phone TEXT,
                    posted_at TIMESTAMP,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notified_at TIMESTAMP,
                    contacted_at TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    notes TEXT
                )
            """)

            # Create contacts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id TEXT REFERENCES listings(id),
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    email_to TEXT,
                    email_subject TEXT,
                    status TEXT DEFAULT 'sent',
                    notes TEXT
                )
            """)

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_listings_source
                ON listings(source)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_listings_first_seen
                ON listings(first_seen_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_listings_notified
                ON listings(notified_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_contacts_listing
                ON contacts(listing_id)
            """)

            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections.

        Yields:
            SQLite connection with row factory set for dict-like access.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def listing_exists(self, listing_id: str) -> bool:
        """Check if a listing already exists in the database.

        Args:
            listing_id: The unique listing ID (format: {source}_{original_id}).

        Returns:
            True if listing exists, False otherwise.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM listings WHERE id = ?",
                (listing_id,)
            )
            exists = cursor.fetchone() is not None
            logger.debug(f"Listing {listing_id} exists: {exists}")
            return exists

    def add_listing(self, listing: dict) -> bool:
        """Add a new listing to the database.

        Args:
            listing: Dictionary containing listing data. Must include 'id' or
                    'source' and 'original_id' to construct the ID.

        Returns:
            True if listing was added (new), False if it already existed.
        """
        # Construct ID if not provided
        listing_id = listing.get("id")
        if not listing_id:
            source = listing.get("source", "unknown")
            original_id = listing.get("original_id", "")
            listing_id = f"{source}_{original_id}"

        # Check if already exists
        if self.listing_exists(listing_id):
            logger.debug(f"Listing {listing_id} already exists, skipping")
            return False

        # Convert features list to JSON string if present
        features = listing.get("features")
        if isinstance(features, list):
            features = json.dumps(features)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO listings (
                    id, source, original_id, title, price, bedrooms, bathrooms,
                    property_type, area, address, url, image_url, description,
                    features, contact_email, contact_phone, posted_at, is_active, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                listing_id,
                listing.get("source"),
                listing.get("original_id"),
                listing.get("title"),
                listing.get("price"),
                listing.get("bedrooms"),
                listing.get("bathrooms"),
                listing.get("property_type"),
                listing.get("area"),
                listing.get("address"),
                listing.get("url"),
                listing.get("image_url"),
                listing.get("description"),
                features,
                listing.get("contact_email"),
                listing.get("contact_phone"),
                listing.get("posted_at"),
                listing.get("is_active", True),
                listing.get("notes"),
            ))
            conn.commit()
            logger.info(f"Added new listing: {listing_id} - {listing.get('title', 'No title')}")
            return True

    def mark_notified(self, listing_id: str) -> None:
        """Mark a listing as notified.

        Args:
            listing_id: The unique listing ID.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE listings SET notified_at = ? WHERE id = ?",
                (datetime.now().isoformat(), listing_id)
            )
            conn.commit()
            logger.info(f"Marked listing as notified: {listing_id}")

    def mark_contacted(self, listing_id: str, email_to: str, subject: str) -> None:
        """Mark a listing as contacted and log the contact.

        Args:
            listing_id: The unique listing ID.
            email_to: Email address the inquiry was sent to.
            subject: Subject line of the email.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Update listing
            cursor.execute(
                "UPDATE listings SET contacted_at = ? WHERE id = ?",
                (datetime.now().isoformat(), listing_id)
            )

            # Add contact record
            cursor.execute("""
                INSERT INTO contacts (listing_id, email_to, email_subject)
                VALUES (?, ?, ?)
            """, (listing_id, email_to, subject))

            conn.commit()
            logger.info(f"Marked listing as contacted: {listing_id} -> {email_to}")

    def get_listing(self, listing_id: str) -> Optional[dict]:
        """Get a single listing by ID.

        Args:
            listing_id: The unique listing ID.

        Returns:
            Dictionary with listing data, or None if not found.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM listings WHERE id = ?", (listing_id,))
            row = cursor.fetchone()

            if row is None:
                logger.debug(f"Listing not found: {listing_id}")
                return None

            listing = dict(row)

            # Parse features JSON if present
            if listing.get("features"):
                try:
                    listing["features"] = json.loads(listing["features"])
                except json.JSONDecodeError:
                    pass

            return listing

    def get_recent_listings(self, hours: int = 24) -> list[dict]:
        """Get listings first seen within the specified time period.

        Args:
            hours: Number of hours to look back (default 24).

        Returns:
            List of listing dictionaries.
        """
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM listings
                WHERE first_seen_at >= ?
                ORDER BY first_seen_at DESC
            """, (cutoff,))

            listings = []
            for row in cursor.fetchall():
                listing = dict(row)
                if listing.get("features"):
                    try:
                        listing["features"] = json.loads(listing["features"])
                    except json.JSONDecodeError:
                        pass
                listings.append(listing)

            logger.debug(f"Found {len(listings)} listings in the last {hours} hours")
            return listings

    def get_uncontacted_listings(self) -> list[dict]:
        """Get listings that have been notified but not yet contacted.

        Returns:
            List of listing dictionaries.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM listings
                WHERE notified_at IS NOT NULL
                  AND contacted_at IS NULL
                  AND is_active = TRUE
                ORDER BY first_seen_at DESC
            """)

            listings = []
            for row in cursor.fetchall():
                listing = dict(row)
                if listing.get("features"):
                    try:
                        listing["features"] = json.loads(listing["features"])
                    except json.JSONDecodeError:
                        pass
                listings.append(listing)

            logger.debug(f"Found {len(listings)} uncontacted listings")
            return listings

    def get_stats(self) -> dict[str, Any]:
        """Get database statistics.

        Returns:
            Dictionary with counts for total, notified, and contacted listings.
        """
        cutoff_24h = (datetime.now() - timedelta(hours=24)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Total listings
            cursor.execute("SELECT COUNT(*) FROM listings")
            total_all = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM listings WHERE first_seen_at >= ?",
                (cutoff_24h,)
            )
            total_24h = cursor.fetchone()[0]

            # Notified listings
            cursor.execute(
                "SELECT COUNT(*) FROM listings WHERE notified_at IS NOT NULL"
            )
            notified_all = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM listings WHERE notified_at >= ?",
                (cutoff_24h,)
            )
            notified_24h = cursor.fetchone()[0]

            # Contacted listings
            cursor.execute(
                "SELECT COUNT(*) FROM listings WHERE contacted_at IS NOT NULL"
            )
            contacted_all = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM listings WHERE contacted_at >= ?",
                (cutoff_24h,)
            )
            contacted_24h = cursor.fetchone()[0]

            # Active listings
            cursor.execute(
                "SELECT COUNT(*) FROM listings WHERE is_active = TRUE"
            )
            active = cursor.fetchone()[0]

            stats = {
                "total": {
                    "all_time": total_all,
                    "last_24h": total_24h,
                },
                "notified": {
                    "all_time": notified_all,
                    "last_24h": notified_24h,
                },
                "contacted": {
                    "all_time": contacted_all,
                    "last_24h": contacted_24h,
                },
                "active": active,
            }

            logger.debug(f"Database stats: {stats}")
            return stats
