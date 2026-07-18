"""Tests for bmc.store — store and remember handlers."""

import json
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Override DB path before importing anything
import bmc.config
_test_dir = Path(tempfile.mkdtemp())
bmc.config.DB_DIR = _test_dir
bmc.config.DB_PATH = _test_dir / "test.db"

from bmc.database import _get_db
from bmc.store import _handle_store, _handle_remember


def setup_module():
    _get_db()  # create schema


def test_store_single_fact():
    r = json.loads(_handle_store({
        "facts": ["Hello world"],
        "tier": "working",
        "source": "test",
        "importance": 0.7,
    }))
    assert r["status"] == "stored"
    assert r["count"] == 1
    assert r["tier"] == "working"
    assert len(r["facts"]) == 1
    assert r["facts"][0]["content"] == "Hello world"


def test_store_multiple_facts():
    facts = [f"Fact {i}" for i in range(5)]
    r = json.loads(_handle_store({
        "facts": facts,
        "tier": "episodic",
        "source": "batch",
    }))
    assert r["status"] == "stored"
    assert r["count"] == 5


def test_store_respects_max_10():
    facts = [f"Fact {i}" for i in range(20)]
    r = json.loads(_handle_store({
        "facts": facts,
        "tier": "scratchpad",
    }))
    assert r["status"] == "stored"
    assert r["count"] == 10  # clamped


def test_store_empty_facts():
    r = json.loads(_handle_store({"facts": []}))
    assert r["status"] == "error"


def test_store_invalid_tier_fallsback_to_working():
    r = json.loads(_handle_store({
        "facts": ["test"],
        "tier": "invalid_tier",
    }))
    assert r["status"] == "stored"
    assert r["tier"] == "working"


def test_store_truncates_long_facts():
    long_fact = "x" * 1000
    r = json.loads(_handle_store({"facts": [long_fact]}))
    assert r["status"] == "stored"
    # Content should be truncated to 500
    assert len(r["facts"][0]["content"]) == 500


def test_remember_defaults():
    r = json.loads(_handle_remember({"fact": "Quick note"}))
    assert r["status"] == "stored"
    assert r["tier"] == "working"
    assert r["count"] == 1


def test_remember_with_source():
    r = json.loads(_handle_remember({
        "fact": "Context from chat",
        "source": "telegram",
    }))
    assert r["status"] == "stored"
    assert r["facts"][0]["content"] == "Context from chat"


def test_remember_empty():
    r = json.loads(_handle_remember({"fact": ""}))
    assert r["status"] == "error"


def test_store_special_chars():
    """Store facts with special characters that could affect FTS5."""
    r = json.loads(_handle_store({
        "facts": ["test with 'single quotes' and \"double quotes\" and AND OR NOT"],
        "tier": "working",
    }))
    assert r["status"] == "stored"


def test_store_finnish_chars():
    """Finnish text with special characters should store fine."""
    r = json.loads(_handle_store({
        "facts": ["Mä hoidan — tämä on ääkköstesti: åäö ÅÄÖ"],
        "tier": "episodic",
    }))
    assert r["status"] == "stored"
