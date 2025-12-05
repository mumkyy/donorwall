import os
import sqlite3
from contextlib import contextmanager

from passlib.hash import pbkdf2_sha256

DB_PATH = os.getenv("DATABASE_PATH", "donors.db")

# Defaults for the settings table.
SETTINGS_DEFAULTS = {
    "background_image": "default.jpg",
    "font_size": 24,
    "scroll_speed": 50,
    "google_sheet_id": os.getenv("GOOGLE_SHEET_ID", ""),
    "donor_website": os.getenv("DONOR_WEBSITE_URL", ""),
    "font_color": "#FFFFFF",
    "scroll_direction": "up",
    "scroll_position": "center",
    "scroll_width": 300,
    "scroll_height": 500,
}

# Columns we expect the settings table to have (name, type).
SETTINGS_COLUMNS = [
    ("background_image", "TEXT"),
    ("font_size", "INTEGER"),
    ("scroll_speed", "INTEGER"),
    ("google_sheet_id", "TEXT"),
    ("donor_website", "TEXT"),
    ("font_color", "TEXT"),
    ("scroll_direction", "TEXT"),
    ("scroll_position", "TEXT"),
    ("scroll_width", "INTEGER"),
    ("scroll_height", "INTEGER"),
]


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_settings_schema(cursor):
    """
    Make sure the settings table has all required columns, adding them if missing.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            background_image TEXT,
            font_size INTEGER,
            scroll_speed INTEGER,
            google_sheet_id TEXT,
            donor_website TEXT,
            font_color TEXT,
            scroll_direction TEXT,
            scroll_position TEXT,
            scroll_width INTEGER,
            scroll_height INTEGER
        )
        """
    )

    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(settings)").fetchall()}
    for column_name, column_type in SETTINGS_COLUMNS:
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE settings ADD COLUMN {column_name} {column_type}")

    cursor.execute(
        """
        INSERT OR IGNORE INTO settings
        (id, background_image, font_size, scroll_speed, google_sheet_id, donor_website,
         font_color, scroll_direction, scroll_position, scroll_width, scroll_height)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            SETTINGS_DEFAULTS["background_image"],
            SETTINGS_DEFAULTS["font_size"],
            SETTINGS_DEFAULTS["scroll_speed"],
            SETTINGS_DEFAULTS["google_sheet_id"],
            SETTINGS_DEFAULTS["donor_website"],
            SETTINGS_DEFAULTS["font_color"],
            SETTINGS_DEFAULTS["scroll_direction"],
            SETTINGS_DEFAULTS["scroll_position"],
            SETTINGS_DEFAULTS["scroll_width"],
            SETTINGS_DEFAULTS["scroll_height"],
        ),
    )

    # Backfill defaults for any NULL columns on the settings row.
    for column_name, default_value in SETTINGS_DEFAULTS.items():
        cursor.execute(
            f"UPDATE settings SET {column_name} = COALESCE({column_name}, ?) WHERE id = 1",
            (default_value,),
        )


def init_db():
    """
    Initialize the SQLite database with necessary tables
    and a default admin user if none exist.
    """
    with get_db() as conn:
        c = conn.cursor()

        # Donors table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS donors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                amount REAL
            )
            """
        )

        # Settings table (background image, font, scroll, data source URLs)
        _ensure_settings_schema(c)

        # Users table (for admin, etc.)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0
            )
            """
        )
        # Create a default admin if none exist
        c.execute("SELECT COUNT(*) FROM users")
        if c.fetchone()[0] == 0:
            default_password = os.getenv("ADMIN_DEFAULT_PASSWORD", "change-me-please")
            default_admin_password = pbkdf2_sha256.hash(default_password)
            c.execute(
                """
                INSERT INTO users (username, password_hash, is_admin)
                VALUES (?, ?, ?)
                """,
                ("admin", default_admin_password, 1),
            )
