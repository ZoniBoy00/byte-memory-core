"""Tests for v2.4.0 JSON export/import."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import bmc.config
_test_dir = Path(tempfile.mkdtemp())
bmc.config.DB_DIR = _test_dir
bmc.config.DB_PATH = _test_dir / "test.db"

from bmc.database import _get_db
from bmc.manage import _handle_export, _handle_import
from bmc.store import _handle_store


def setup_module():
    _get_db()
    _handle_store({
        "facts": ["Exportable episodic decision"],
        "tier": "episodic",
        "source": "test",
        "importance": 0.9,
        "tags": ["project", "decision"],
        "metadata": {"project": "bmc"},
    })
    _handle_store({
        "facts": ["Scratchpad experiment"],
        "tier": "scratchpad",
        "source": "test",
        "tags": ["idea"],
    })


def test_export_contains_versioned_envelope_and_filters():
    result = json.loads(_handle_export({"tier": "episodic", "tags": ["decision"]}))
    assert result["status"] == "success"
    assert result["format"] == "byte-memory-core-export"
    assert result["version"] == 1
    assert len(result["facts"]) == 1
    assert result["facts"][0]["content"] == "Exportable episodic decision"
    assert "id" not in result["facts"][0]


def test_export_query_filter():
    result = json.loads(_handle_export({"query": "scratchpad experiment"}))
    assert result["status"] == "success"
    assert any("Scratchpad experiment" in f["content"] for f in result["facts"])


def test_import_deduplicates_and_preserves_fields():
    payload = {
        "format": "byte-memory-core-export",
        "version": 1,
        "facts": [
            {
                "tier": "episodic",
                "content": "Exportable episodic decision",
                "source": "imported",
                "tags": ["project", "decision"],
                "importance": 0.95,
                "created_at": 1000.0,
                "accessed_at": 1100.0,
                "access_count": 4,
                "metadata": {"restored": True},
            },
            {
                "tier": "episodic",
                "content": "Imported new fact",
                "source": "backup",
                "tags": ["restore"],
                "importance": 0.8,
                "created_at": 1000.0,
                "accessed_at": 1000.0,
                "access_count": 2,
                "metadata": {"batch": "v2.4"},
            },
        ],
    }
    result = json.loads(_handle_import({"payload": json.dumps(payload)}))
    assert result["status"] == "success"
    assert result["imported"] == 1
    assert result["deduplicated"] == 1
    assert result["errors"] == 0

    exported = json.loads(_handle_export({"query": "Imported new fact"}))
    imported = next(f for f in exported["facts"] if f["content"] == "Imported new fact")
    assert imported["metadata"] == {"batch": "v2.4"}
    assert imported["access_count"] == 2


def test_import_rejects_invalid_payload():
    result = json.loads(_handle_import({"payload": "{\"version\": 99}"}))
    assert result["status"] == "error"
