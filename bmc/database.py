"""Database initialization and connection management."""

import sqlite3
import time
from typing import Optional

import bmc.config


def _get_db() -> sqlite3.Connection:
    """Open (or create) the local SQLite database with FTS5 support."""
    bmc.config.DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(bmc.config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS facts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            tier         TEXT NOT NULL DEFAULT 'working',
            content      TEXT NOT NULL,
            source       TEXT DEFAULT '',
            importance   REAL DEFAULT 0.5,
            created_at   REAL NOT NULL,
            accessed_at  REAL NOT NULL DEFAULT 0,
            access_count INTEGER DEFAULT 0,
            metadata     TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_facts_tier       ON facts(tier);
        CREATE INDEX IF NOT EXISTS idx_facts_created    ON facts(created_at);
        CREATE INDEX IF NOT EXISTS idx_facts_importance ON facts(importance);

        CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
        USING fts5(content);
    """)
    conn.commit()


def _auto_prune(conn: sqlite3.Connection, tier: str) -> None:
    """Remove oldest/lowest-scored facts when a tier exceeds its cap.

    Deletion order: lowest importance first, then oldest.
    """
    cap = bmc.config.TIER_CAPS.get(tier, 500)
    count = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE tier=?", (tier,)
    ).fetchone()[0]

    if count <= cap:
        return

    excess = count - cap
    # Remove excess low-importance, old facts
    conn.execute(
        """DELETE FROM facts WHERE id IN (
            SELECT id FROM facts
            WHERE tier = ?
            ORDER BY importance ASC, created_at ASC
            LIMIT ?
        )""",
        (tier, excess),
    )
    conn.execute(
        """DELETE FROM facts_fts WHERE rowid IN (
            SELECT id FROM facts
            WHERE tier = ?
            ORDER BY importance ASC, created_at ASC
            LIMIT ?
        )""",
        (tier, excess),
    )
    conn.commit()
