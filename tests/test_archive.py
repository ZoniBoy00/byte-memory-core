"""Tests for safe O2B archival candidate selection."""

import sqlite3
import time

from bmc.archive import find_archivable_facts


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE facts (
            id INTEGER PRIMARY KEY, tier TEXT, content TEXT, source TEXT,
            tags TEXT, importance REAL, created_at REAL, accessed_at REAL,
            access_count INTEGER, metadata TEXT
        )"""
    )
    return conn


def _insert(conn, *, fid, tier="episodic", source="learning", tags="[]",
            importance=0.8, access_count=6, created_at=None):
    now = time.time() if created_at is None else created_at
    conn.execute(
        "INSERT INTO facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fid, tier, f"Fact {fid}", source, tags, importance, now, now, access_count, "{}"),
    )
    conn.commit()


def test_requires_all_three_safety_criteria():
    conn = _db()
    _insert(conn, fid=1)  # eligible
    _insert(conn, fid=2, tier="working")
    _insert(conn, fid=3, access_count=5)
    _insert(conn, fid=4, source="conversation")

    result = find_archivable_facts(conn)

    assert [fact["id"] for fact in result] == [1]
    assert result[0]["source"] == "learning"


def test_accepts_permanent_source_tag():
    conn = _db()
    _insert(conn, fid=1, source="", tags='["project", "source:architecture"]')

    result = find_archivable_facts(conn)

    assert len(result) == 1
    assert result[0]["source"] == "architecture"


def test_respects_importance_and_age_filters():
    conn = _db()
    now = time.time()
    _insert(conn, fid=1, importance=0.4)
    _insert(conn, fid=2, created_at=now - 10 * 86400)

    result = find_archivable_facts(
        conn, min_importance=0.5, max_age_days=7
    )

    assert result == []


def test_limit_is_applied_before_return():
    conn = _db()
    for fid in range(1, 4):
        _insert(conn, fid=fid, importance=0.9 - fid / 100)

    result = find_archivable_facts(conn, limit=2)

    assert len(result) == 2
    assert [fact["id"] for fact in result] == [1, 2]
