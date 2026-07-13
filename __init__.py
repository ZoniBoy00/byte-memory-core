"""Byte Memory Core — local vector-indexed memory with BEAM tiers.

Splits memory into three tiers with hybrid FTS5 + TF-IDF search,
importance scoring, and automatic pruning.
"""

from bmc.config import TIER_ORDER, TIER_CAPS, TIER_WEIGHTS
from bmc.database import _get_db, _auto_prune
from bmc.search import _tfidf_score, _build_idf_cache, _handle_search
from bmc.store import _handle_store, _handle_remember
from bmc.manage import _handle_forget, _handle_status, _handle_tier_move, _handle_reindex

SCHEMA_SEARCH = {
    "name": "bmc_search",
    "description": "Search across memory sources using hybrid FTS5 + n-gram TF-IDF. Supports local BMC database, o2b vault, and Honcho. Returns ranked, merged results.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query in natural language or keywords"},
            "sources": {"type": "array", "items": {"type": "string", "enum": ["bmc", "o2b", "honcho"]}, "description": "Sources to search (default: ['bmc', 'o2b'])"},
            "tiers": {"type": "array", "items": {"type": "string", "enum": TIER_ORDER}, "description": "BMC tiers to search (default: all)"},
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


def register(ctx):
    """Register all plugin tools with the Hermes agent."""
    ctx.register_tool(name="bmc_search", toolset="byte_memory_core", schema=SCHEMA_SEARCH, handler=_handle_search)
    ctx.register_tool(name="bmc_store", toolset="byte_memory_core", schema=SCHEMA_STORE, handler=_handle_store)
    ctx.register_tool(name="bmc_remember", toolset="byte_memory_core", schema=SCHEMA_REMEMBER, handler=_handle_remember)
    ctx.register_tool(name="bmc_forget", toolset="byte_memory_core", schema=SCHEMA_FORGET, handler=_handle_forget)
    ctx.register_tool(name="bmc_status", toolset="byte_memory_core", schema=SCHEMA_STATUS, handler=_handle_status)
    ctx.register_tool(name="bmc_tier_move", toolset="byte_memory_core", schema=SCHEMA_TIER_MOVE, handler=_handle_tier_move)
    ctx.register_tool(name="bmc_reindex", toolset="byte_memory_core", schema=SCHEMA_REINDEX, handler=_handle_reindex)
