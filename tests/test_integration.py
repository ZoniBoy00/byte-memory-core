"""Integration tests for the full plugin tool chain."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Override DB path before importing anything
import bmc.config
test_dir = Path(tempfile.mkdtemp())
bmc.config.DB_DIR = test_dir
bmc.config.DB_PATH = test_dir / "test.db"

from bmc.database import _get_db, _auto_prune
from bmc.search import _handle_search
from bmc.store import _handle_store, _handle_remember
from bmc.manage import _handle_forget, _handle_status, _handle_tier_move, _handle_reindex


def setup_module():
    _get_db()  # creates schema fresh


def test_store_and_search():
    r = json.loads(_handle_store({
        "facts": ["N-gram TF-IDF provides semantic-lite matching",
                   "FTS5 handles exact keyword search efficiently"],
        "tier": "episodic", "source": "test", "importance": 0.9,
    }))
    assert r["status"] == "stored"
    assert r["count"] == 2

    r = json.loads(_handle_search({"query": "semantic matching", "limit": 5}))
    assert r["status"] == "success"
    assert len(r["results"]) > 0


def test_remember():
    r = json.loads(_handle_remember({"fact": "Quick context save", "source": "chat"}))
    assert r["status"] == "stored"
    assert r["tier"] == "working"


def test_status():
    r = json.loads(_handle_status({}))
    assert r["status"] == "ok"
    assert r["total_facts"] >= 3


def test_forget():
    r = json.loads(_handle_search({"query": "semantic", "limit": 1}))
    if r["results"]:
        fid = r["results"][0]["id"]
        r2 = json.loads(_handle_forget({"fact_id": fid}))
        assert r2["status"] == "deleted"


def test_tier_move():
    r = json.loads(_handle_search({"query": "Quick context", "limit": 1}))
    if r["results"]:
        fid = r["results"][0]["id"]
        r2 = json.loads(_handle_tier_move({"fact_ids": [fid], "target_tier": "episodic"}))
        assert r2["status"] == "moved"


def test_reindex():
    r = json.loads(_handle_reindex({}))
    assert r["status"] == "reindexed"
    assert r["count"] >= 2


def test_store_empty():
    r = json.loads(_handle_store({"facts": []}))
    assert r["status"] == "error"


def test_search_empty():
    r = json.loads(_handle_search({"query": ""}))
    assert r["status"] == "empty"


def test_tfidf_fallback():
    r = json.loads(_handle_search({"query": "semantec matchung", "limit": 5}))
    assert r["status"] == "success"
