"""SQLite database initialization and access layer for ArtScope."""

import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "artscope.db")


def get_connection(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db(db_path=None):
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path=None):
    """Create all tables if they don't exist."""
    with get_db(db_path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS artists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                nationality TEXT,
                birth_year INTEGER,
                death_year INTEGER,
                medium TEXT,
                education TEXT,
                first_seen_date TEXT,
                first_seen_source TEXT,
                tags TEXT,
                instagram_handle TEXT,
                image_url TEXT,
                wikipedia_url TEXT,
                slug TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(name, birth_year)
            );

            CREATE TABLE IF NOT EXISTS auction_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist_id INTEGER NOT NULL,
                title TEXT,
                medium TEXT,
                dimensions TEXT,
                sale_date TEXT,
                auction_house TEXT NOT NULL,
                lot_number TEXT,
                estimate_low REAL,
                estimate_high REAL,
                hammer_price REAL,
                currency TEXT DEFAULT 'USD',
                hammer_price_usd REAL,
                sold INTEGER DEFAULT 1,
                sale_url TEXT,
                image_url TEXT,
                source_id TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (artist_id) REFERENCES artists(id),
                UNIQUE(auction_house, source_id)
            );

            CREATE TABLE IF NOT EXISTS price_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist_id INTEGER NOT NULL,
                signal_type TEXT NOT NULL,
                signal_date TEXT,
                source TEXT,
                details TEXT,
                url TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (artist_id) REFERENCES artists(id)
            );

            CREATE TABLE IF NOT EXISTS trend_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist_id INTEGER NOT NULL,
                period TEXT NOT NULL,
                avg_price REAL,
                median_price REAL,
                num_sales INTEGER DEFAULT 0,
                price_change_pct REAL,
                sell_through_rate REAL,
                estimate_beat_rate REAL,
                signal_count INTEGER DEFAULT 0,
                composite_score REAL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (artist_id) REFERENCES artists(id),
                UNIQUE(artist_id, period)
            );

            CREATE TABLE IF NOT EXISTS scrape_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                started_at TEXT DEFAULT (datetime('now')),
                finished_at TEXT,
                status TEXT DEFAULT 'running',
                records_found INTEGER DEFAULT 0,
                records_new INTEGER DEFAULT 0,
                error_message TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_auction_artist ON auction_results(artist_id);
            CREATE INDEX IF NOT EXISTS idx_auction_date ON auction_results(sale_date);
            CREATE INDEX IF NOT EXISTS idx_auction_price ON auction_results(hammer_price_usd);
            CREATE INDEX IF NOT EXISTS idx_auction_house ON auction_results(auction_house);
            CREATE INDEX IF NOT EXISTS idx_trend_artist ON trend_scores(artist_id);
            CREATE INDEX IF NOT EXISTS idx_trend_period ON trend_scores(period);
            CREATE INDEX IF NOT EXISTS idx_trend_score ON trend_scores(composite_score);
            CREATE INDEX IF NOT EXISTS idx_signal_artist ON price_signals(artist_id);

            CREATE TABLE IF NOT EXISTS artist_colors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist_id INTEGER NOT NULL,
                hex_color TEXT NOT NULL,
                percentage REAL NOT NULL,
                rank INTEGER NOT NULL,
                created_at TEXT,
                FOREIGN KEY (artist_id) REFERENCES artists(id),
                UNIQUE(artist_id, rank)
            );

            CREATE INDEX IF NOT EXISTS idx_artist_colors_artist ON artist_colors(artist_id);
        """)
    print(f"Database initialized at {db_path or DB_PATH}")


def find_or_create_artist(db, name, **kwargs):
    """Find an artist by name or create a new one. Returns artist id."""
    row = db.execute(
        "SELECT id FROM artists WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone()
    if row:
        return row["id"]

    cols = ["name"] + list(kwargs.keys())
    vals = [name] + list(kwargs.values())
    placeholders = ", ".join(["?"] * len(vals))
    col_names = ", ".join(cols)
    cursor = db.execute(
        f"INSERT INTO artists ({col_names}) VALUES ({placeholders})", vals
    )
    return cursor.lastrowid


def insert_auction_result(db, artist_id, **kwargs):
    """Insert an auction result, skipping duplicates."""
    kwargs["artist_id"] = artist_id
    cols = list(kwargs.keys())
    vals = list(kwargs.values())
    placeholders = ", ".join(["?"] * len(vals))
    col_names = ", ".join(cols)
    try:
        db.execute(
            f"INSERT OR IGNORE INTO auction_results ({col_names}) VALUES ({placeholders})",
            vals,
        )
        return True
    except sqlite3.IntegrityError:
        return False


if __name__ == "__main__":
    init_db()
