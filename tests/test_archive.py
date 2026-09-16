"""Tests for safe O2B archival candidate selection."""

import json
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


def test_preview_does_not_write_or_change_metadata(tmp_path):
    from bmc.archive import archive_facts

    conn = _db()
    _insert(conn, fid=1)
    result = archive_facts(conn, tmp_path, apply=False)

    assert result["status"] == "preview"
    assert result["created"] == 0
    assert list(tmp_path.rglob("*.md")) == []
    assert conn.execute("SELECT metadata FROM facts WHERE id=1").fetchone()[0] == "{}"


def test_apply_writes_markdown_and_reference(tmp_path):
    from bmc.archive import archive_facts

    conn = _db()
    _insert(conn, fid=1, source="architecture", tags='["design"]')
    result = archive_facts(conn, tmp_path, apply=True)

    assert result["status"] == "applied"
    assert result["created"] == 1
    files = list((tmp_path / "Brain" / "Architecture").glob("*.md"))
    assert len(files) == 1
    document = files[0].read_text()
    assert "bmc_id: 1" in document
    assert "archived_to: o2b://Brain/Architecture/" in document
    metadata = json.loads(conn.execute("SELECT metadata FROM facts WHERE id=1").fetchone()[0])
    assert metadata["archived_to"].startswith("o2b://Brain/Architecture/")


def test_apply_deduplicates_existing_archive(tmp_path):
    from bmc.archive import archive_facts

    conn = _db()
    _insert(conn, fid=1, source="learning")
    first = archive_facts(conn, tmp_path, apply=True)
    second = archive_facts(conn, tmp_path, apply=True)

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["updated"] == 1
    assert len(list(tmp_path.rglob("*.md"))) == 1
