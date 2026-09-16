"""Byte Memory Core — local vector-indexed memory with BEAM tiers.

Splits memory into three tiers with hybrid FTS5 + TF-IDF search,
importance scoring, and automatic pruning.
"""

import sys
from pathlib import Path
# Ensure plugin dir is on sys.path so bmc/ subpackage resolves
_plugin_dir = str(Path(__file__).resolve().parent)
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from bmc.config import TIER_ORDER, TIER_CAPS, TIER_WEIGHTS
from bmc.database import _get_db, _auto_prune
from bmc.search import _tfidf_score, _build_idf_cache, _handle_search
from bmc.store import _handle_store, _handle_remember
from bmc.archive import _handle_archive
from bmc.manage import (
    _handle_export,
    _handle_forget,
    _handle_import,
    _handle_status,
    _handle_tier_move,
    _handle_reindex,
)

SCHEMA_SEARCH = {
    "name": "bmc_search",
    "description": "Search across memory sources using hybrid FTS5 + n-gram TF-IDF. Supports local BMC database, o2b vault, and Honcho. Returns ranked, merged results.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query in natural language or keywords"},
            "sources": {"type": "array", "items": {"type": "string", "enum": ["bmc", "o2b", "honcho"]}, "description": "Sources to search (default: ['bmc', 'o2b'])"},
            "tiers": {"type": "array", "items": {"type": "string", "enum": TIER_ORDER}, "description": "BMC tiers to search (default: all)"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Filter results by tags (e.g. ['project:gzw-tools', 'fix']). Facts must have at least one matching tag."},
            "limit": {"type": "integer", "description": "Max results per source (default: 5, max: 20)"},
            "min_score": {"type": "number", "description": "Minimum score threshold 0.0-1.0 (default: 0)"},
        },
        "required": ["query"],
    },
}

SCHEMA_STORE = {
    "name": "bmc_store",
    "description": "Store one or more facts into a specific memory tier. Working = ephemeral (24h auto-prune), Episodic = long-term (30d), Scratchpad = temporary notes.",
    "parameters": {
        "type": "object",
        "properties": {
            "facts": {"type": "array", "items": {"type": "string"}, "description": "Facts to store (max 10, 500 chars each)"},
            "tier": {"type": "string", "enum": TIER_ORDER, "description": "Target tier (default: working)"},
            "source": {"type": "string", "description": "Source label (e.g. 'task-reflection', 'correction')"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags (e.g. ['project:gzw-tools', 'fix', 'config'])"},
            "metadata": {"type": "object", "description": "Free-form metadata dict for extra context (e.g. {'session_id': 'abc', 'model': 'mimo-v2.5'})"},
            "importance": {"type": "number", "description": "Importance 0.0-1.0 (default: 0.5 for working, 0.8 for episodic)"},
        },
        "required": ["facts"],
    },
}

SCHEMA_REMEMBER = {
    "name": "bmc_remember",
    "description": "Quick-save a single fact to the Working tier. Ideal for capturing context mid-conversation.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "What to remember"},
            "source": {"type": "string", "description": "Context label (default: 'manual')"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags (e.g. ['project:gzw-tools', 'fix'])"},
            "metadata": {"type": "object", "description": "Free-form metadata dict for extra context"},
        },
        "required": ["fact"],
    },
}

SCHEMA_FORGET = {
    "name": "bmc_forget",
    "description": "Permanently delete a fact by its ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact_id": {"type": "integer", "description": "ID of the fact to delete"},
        },
        "required": ["fact_id"],
    },
}

SCHEMA_EXPORT = {
    "name": "bmc_export",
    "description": "Export BMC facts as a versioned JSON document. Filter by tier, tags, or text query.",
    "parameters": {
        "type": "object",
        "properties": {
            "tier": {"type": "string", "enum": TIER_ORDER, "description": "Optional tier filter"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Require all listed tags"},
            "query": {"type": "string", "description": "Optional case-insensitive content filter"},
        },
    },
}

SCHEMA_IMPORT = {
    "name": "bmc_import",
    "description": "Import a versioned BMC JSON export with validation and deduplication.",
    "parameters": {
        "type": "object",
        "properties": {
            "payload": {"description": "Export JSON object or JSON string"},
        },
        "required": ["payload"],
    },
}

SCHEMA_STATUS = {
    "name": "bmc_status",
    "description": "Show memory health: facts per tier, average importance, recent entries, database size.",
    "parameters": {"type": "object", "properties": {}},
}

SCHEMA_TIER_MOVE = {
    "name": "bmc_tier_move",
    "description": "Move facts between tiers. Promote Working→Episodic for long-term retention, or demote Episodic→Scratchpad for deprioritization.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact_ids": {"type": "array", "items": {"type": "integer"}, "description": "Fact IDs to move"},
            "target_tier": {"type": "string", "enum": TIER_ORDER, "description": "Destination tier"},
        },
        "required": ["fact_ids", "target_tier"],
    },
}

SCHEMA_REINDEX = {
    "name": "bmc_reindex",
    "description": "Rebuild the FTS5 full-text search index. Run after bulk imports or if search results seem stale.",
    "parameters": {"type": "object", "properties": {}},
}
SCHEMA_ARCHIVE = {
    "name": "bmc_archive",
    "description": "Preview or safely archive eligible Episodic BMC facts to an O2B Markdown vault. Defaults to preview; set apply=true to write files and preserve an archived_to reference in BMC.",
    "parameters": {
        "type": "object",
        "properties": {
            "vault": {"type": "string", "description": "O2B vault root. Optional when O2B_VAULT is configured."},
            "apply": {"type": "boolean", "description": "Write archive files. Defaults to false (preview only)."},
            "min_access_count": {"type": "integer", "minimum": 0, "default": 5},
            "min_importance": {"type": "number", "minimum": 0, "maximum": 1},
            "max_age_days": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100},
        },
    },
}


def register(ctx):
    """Register all plugin tools with the Hermes agent."""
    ctx.register_tool(name="bmc_search", toolset="byte_memory_core", schema=SCHEMA_SEARCH, handler=_handle_search)
    ctx.register_tool(name="bmc_store", toolset="byte_memory_core", schema=SCHEMA_STORE, handler=_handle_store)
    ctx.register_tool(name="bmc_remember", toolset="byte_memory_core", schema=SCHEMA_REMEMBER, handler=_handle_remember)
    ctx.register_tool(name="bmc_export", toolset="byte_memory_core", schema=SCHEMA_EXPORT, handler=_handle_export)
    ctx.register_tool(name="bmc_import", toolset="byte_memory_core", schema=SCHEMA_IMPORT, handler=_handle_import)
    ctx.register_tool(name="bmc_forget", toolset="byte_memory_core", schema=SCHEMA_FORGET, handler=_handle_forget)
    ctx.register_tool(name="bmc_status", toolset="byte_memory_core", schema=SCHEMA_STATUS, handler=_handle_status)
    ctx.register_tool(name="bmc_tier_move", toolset="byte_memory_core", schema=SCHEMA_TIER_MOVE, handler=_handle_tier_move)
    ctx.register_tool(name="bmc_reindex", toolset="byte_memory_core", schema=SCHEMA_REINDEX, handler=_handle_reindex)
    ctx.register_tool(name="bmc_archive", toolset="byte_memory_core", schema=SCHEMA_ARCHIVE, handler=_handle_archive)
