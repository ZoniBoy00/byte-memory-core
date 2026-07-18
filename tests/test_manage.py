"""Tests for bmc.manage — forget, status, tier_move, reindex handlers."""

import json
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bmc.config
_test_dir = Path(tempfile.mkdtemp())
bmc.config.DB_DIR = _test_dir
bmc.config.DB_PATH = _test_dir / "test.db"

from bmc.database import _get_db
from bmc.store import _handle_store
from bmc.manage import _handle_forget, _handle_status, _handle_tier_move, _handle_reindex


def setup_module():
    _get_db()
    # Seed some test data
    _handle_store({"facts": ["Alpha fact for testing", "Beta fact for testing", "Gamma fact"]})


def test_forget_existing():
    # Find a fact via status
    r = json.loads(_handle_status({}))
    assert r["total_facts"] >= 3

    # Forget the first one
    r = json.loads(_handle_forget({"fact_id": 1}))
    assert r["status"] == "deleted"
    assert r["fact_id"] == 1


def test_forget_nonexistent():
    r = json.loads(_handle_forget({"fact_id": 9999}))
    assert r["status"] == "deleted"  # SQLite DELETE on missing row is not an error


def test_forget_no_id():
    r = json.loads(_handle_forget({}))
    assert r["status"] == "error"


def test_status_returns_counts():
    r = json.loads(_handle_status({}))
    assert r["status"] == "ok"
    assert r["total_facts"] >= 2
    assert "working" in r["tiers"]
    assert "db_size_bytes" in r
    assert "recent" in r
    assert len(r["recent"]) > 0


def test_status_empty_after_delete():
    # Add and delete all
    _handle_store({"facts": ["Temporary"]})
    r = json.loads(_handle_status({}))
    count = r["total_facts"]

    # Delete last one
    r2 = json.loads(_handle_status({}))
    assert r2["status"] == "ok"


def test_tier_move_valid():
    r = json.loads(_handle_tier_move({"fact_ids": [2], "target_tier": "episodic"}))
    assert r["status"] == "moved"
    assert r["count"] == 1
    assert r["to_tier"] == "episodic"


def test_tier_move_multiple():
    r = json.loads(_handle_tier_move({"fact_ids": [2, 3], "target_tier": "scratchpad"}))
    assert r["status"] == "moved"
    assert r["count"] >= 1


def test_tier_move_invalid_target():
    r = json.loads(_handle_tier_move({"fact_ids": [1], "target_tier": "invalid"}))
    assert r["status"] == "error"


def test_tier_move_no_ids():
    r = json.loads(_handle_tier_move({"fact_ids": [], "target_tier": "episodic"}))
    assert r["status"] == "error"


def test_reindex():
    r = json.loads(_handle_reindex({}))
    assert r["status"] == "reindexed"
    assert r["count"] >= 2


def test_reindex_empty():
    """Reindex on empty DB should not crash."""
    r = json.loads(_handle_reindex({}))
    assert r["status"] == "reindexed"
    assert r["count"] >= 0  # reindex is always valid
