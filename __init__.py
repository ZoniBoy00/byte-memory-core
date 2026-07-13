"""Byte Memory Core — local vector-indexed memory with BEAM tiers.

Provides semantic-lite search (FTS5 + TF-IDF char n-grams), importance scoring,
and three memory tiers: Working (24h), Episodic (important facts), Scratchpad
(in-progress thoughts). Integrates with o2b vault for persistent storage.

Tools:
  bmc_search    — Search across memory tiers (FTS5 + recency + importance)
  bmc_store     — Store facts into a specific tier
  bmc_remember  — Quick-save to Working tier
  bmc_forget    — Delete a fact by ID
  bmc_status    — Show memory health: counts per tier, disk usage, top facts
  bmc_tier_move — Move facts between tiers
  bmc_reindex   — Rebuild the FTS5 index from scratch
"""

import json
import math
import os
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PLUGIN_DIR = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
DB_DIR = HERMES_HOME / "byte_memory_core"
DB_PATH = DB_DIR / "store.db"
O2B_VAULT = Path("/opt/Byte Vault") if (Path("/opt/Byte Vault")).exists() else None

TIER_WEIGHTS = {
    "working": 3.0,     # Recent conversation context
    "episodic": 2.0,    # Important long-term facts
    "scratchpad": 1.0,  # In-progress / temporary notes
}
TIER_ORDER = ["working", "episodic", "scratchpad"]

# How many hours before a fact is considered "cold" (reduced score)
WORKING_TTL_HOURS = 24
EPISODIC_TTL_HOURS = 720  # ~30 days

# Max facts per tier before auto-pruning (oldest/lowest-score removed)
TIER_CAPS = {"working": 500, "episodic": 2000, "scratchpad": 300}

# Char n-gram range for semantic-lite matching
NGRAM_MIN = 2
NGRAM_MAX = 4

# ---------------------------------------------------------------------------
# Init database
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS facts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tier        TEXT NOT NULL DEFAULT 'working',
            content     TEXT NOT NULL,
            source      TEXT DEFAULT '',
            importance  REAL DEFAULT 0.5,
            created_at  REAL NOT NULL,
            accessed_at REAL NOT NULL DEFAULT 0,
            access_count INTEGER DEFAULT 0,
            metadata    TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_facts_tier ON facts(tier);
        CREATE INDEX IF NOT EXISTS idx_facts_created ON facts(created_at);
        CREATE INDEX IF NOT EXISTS idx_facts_importance ON facts(importance);

        CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
        USING fts5(content, tokenize='unicode61 tokenchars');
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# TF-IDF with char n-grams (semantic-lite matching)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Extract character n-grams from text for fuzzy matching."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9äåöæœø\s]', ' ', text)
    tokens = []
    for n in range(NGRAM_MIN, NGRAM_MAX + 1):
        for i in range(len(text) - n + 1):
            ngram = text[i:i + n]
            if ngram.strip():
                tokens.append(ngram)
    return tokens


def _tfidf_score(query_tokens: List[str], doc_tokens: List[str], idf_cache: Dict[str, float]) -> float:
    """Compute TF-IDF cosine similarity between query and document."""
    if not query_tokens or not doc_tokens:
        return 0.0

    q_counts = Counter(query_tokens)
    d_counts = Counter(doc_tokens)

    # Compute TF-IDF vectors
    q_vec = np.array([q_counts.get(t, 0) * idf_cache.get(t, 1.0) for t in query_tokens])
    d_vec = np.array([d_counts.get(t, 0) * idf_cache.get(t, 1.0) for t in query_tokens])

    # Cosine similarity
    norm_q = np.linalg.norm(q_vec)
    norm_d = np.linalg.norm(d_vec)
    if norm_q == 0 or norm_d == 0:
        return 0.0

    return float(np.dot(q_vec, d_vec) / (norm_q * norm_d))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _compute_importance_score(
    fts5_rank: float,
    recency: float,
    tier_weight: float,
    access_factor: float,
    importance: float,
) -> float:
    """Hybrid scoring: FTS5 relevance + recency + tier + access + importance."""
    score = (
        0.35 * fts5_rank +
        0.25 * recency +
        0.15 * tier_weight +
        0.10 * access_factor +
        0.15 * importance
    )
    return round(score, 4)


def _recency_score(created_at: float, hours_ago: int) -> float:
    """Score based on how recent a fact is (1.0 = just now, 0.0 = very old)."""
    age_hours = (time.time() - created_at) / 3600
    if age_hours <= 0:
        return 1.0
    # Decay curve: 1/(1 + age/threshold)
    threshold = max(hours_ago, 1)
    return 1.0 / (1.0 + age_hours / threshold)


def _access_factor(accessed_at: float, access_count: int) -> float:
    """Score based on access patterns."""
    recency = _recency_score(accessed_at, 72)  # 3-day half-life
    frequency = min(access_count / 20.0, 1.0)
    return 0.6 * recency + 0.4 * frequency


# ---------------------------------------------------------------------------
# IDF cache builder
# ---------------------------------------------------------------------------

def _build_idf_cache(conn: sqlite3.Connection) -> Dict[str, float]:
    """Build IDF cache from all stored facts for TF-IDF scoring."""
    rows = conn.execute("SELECT content FROM facts").fetchall()
    if not rows:
        return {}

    num_docs = len(rows)
    doc_freq: Counter = Counter()
    for row in rows:
        tokens = set(_tokenize(row["content"]))
        for t in tokens:
            doc_freq[t] += 1

    idf = {}
    for term, df in doc_freq.items():
        idf[term] = math.log((num_docs + 1) / (df + 1)) + 1.0
    return idf


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

SCHEMA_SEARCH = {
    "name": "bmc_search",
    "description": (
        "Search across memory tiers (Working/Episodic/Scratchpad) using hybrid "
        "FTS5 + semantic-lite matching. Returns ranked results with scores. "
        "Use this to find stored facts, past decisions, and context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — natural language or keywords",
            },
            "tiers": {
                "type": "array",
                "items": {"type": "string", "enum": TIER_ORDER},
                "description": "Which tiers to search (default: all)",
            },
            "limit": {
                "type": "integer",
                "description": "Max results per tier (default: 5)",
            },
            "min_score": {
                "type": "number",
                "description": "Minimum hybrid score (0-1) to include (default: 0)",
            },
        },
        "required": ["query"],
    },
}

SCHEMA_STORE = {
    "name": "bmc_store",
    "description": (
        "Store facts into a specific memory tier. Working = recent context (auto-pruned after 24h). "
        "Episodic = important long-term facts. Scratchpad = in-progress/temporary notes. "
        "Use for saving important context for future searches."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Facts to store (each up to 500 chars)",
            },
            "tier": {
                "type": "string",
                "enum": TIER_ORDER,
                "description": "Target tier (default: working)",
            },
            "source": {
                "type": "string",
                "description": "Where this came from (e.g., 'task-reflection', 'correction', 'discovery')",
            },
            "importance": {
                "type": "number",
                "description": "Importance 0.0-1.0 (default: 0.5 for working, 0.8 for episodic)",
            },
        },
        "required": ["facts"],
    },
}

SCHEMA_REMEMBER = {
    "name": "bmc_remember",
    "description": (
        "Quick-save a single fact to Working tier without complex options. "
        "Use for fast 'muistiin' saves during conversation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "What to remember",
            },
            "source": {
                "type": "string",
                "description": "Context (default: 'manual')",
            },
        },
        "required": ["fact"],
    },
}

SCHEMA_FORGET = {
    "name": "bmc_forget",
    "description": "Delete a specific fact by its ID. Irreversible.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact_id": {
                "type": "integer",
                "description": "ID of the fact to delete",
            },
        },
        "required": ["fact_id"],
    },
}

SCHEMA_STATUS = {
    "name": "bmc_status",
    "description": "Show memory health: count per tier, recent activity, disk usage, top facts.",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

SCHEMA_TIER_MOVE = {
    "name": "bmc_tier_move",
    "description": "Move facts between tiers. Promote working → episodic for long-term retention, or demote episodic → scratchpad.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Fact IDs to move",
            },
            "target_tier": {
                "type": "string",
                "enum": TIER_ORDER,
                "description": "Target tier",
            },
        },
        "required": ["fact_ids", "target_tier"],
    },
}

SCHEMA_REINDEX = {
    "name": "bmc_reindex",
    "description": "Rebuild the FTS5 search index from scratch. Run after bulk imports or if search seems wrong.",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_search(args, **kwargs):
    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps({"status": "empty", "results": []})

    limit = min(args.get("limit", 5), 20)
    tiers = args.get("tiers", TIER_ORDER)
    min_score = args.get("min_score", 0.0)

    conn = _get_db()
    try:
        query_tokens = _tokenize(query)
        idf_cache = _build_idf_cache(conn)

        results = []
        for tier in tiers:
            if tier not in TIER_ORDER:
                continue

            # FTS5 search
            # Escape special FTS5 characters
            safe_query = query.replace('"', '""')
            fts_rows = conn.execute(
                """SELECT f.id, f.tier, f.content, f.source, f.importance,
                          f.created_at, f.accessed_at, f.access_count,
                          rank
                   FROM facts_fts
                   JOIN facts f ON facts_fts.rowid = f.id
                   WHERE facts_fts MATCH ?
                     AND f.tier = ?
                   ORDER BY rank
                   LIMIT ?""",
                (safe_query, tier, limit * 2),
            ).fetchall()

            for row in fts_rows:
                fts5_rank = -row["rank"] if row["rank"] else 0.5
                fts5_rank = max(0.0, min(1.0, fts5_rank / 10.0 + 0.5))

                # TF-IDF bonus
                doc_tokens = _tokenize(row["content"])
                tfidf = _tfidf_score(query_tokens, doc_tokens, idf_cache)

                recency = (
                    _recency_score(row["created_at"], WORKING_TTL_HOURS)
                    if tier == "working"
                    else _recency_score(row["created_at"], EPISODIC_TTL_HOURS)
                )
                acc = _access_factor(row["accessed_at"], row["access_count"])
                tier_w = TIER_WEIGHTS.get(tier, 1.0)

                # Boost TF-IDF when FTS5 is weak
                combined_fts = max(fts5_rank, tfidf * 0.7)

                score = _compute_importance_score(
                    combined_fts, recency, tier_w, acc, row["importance"]
                )

                if score >= min_score:
                    results.append({
                        "id": row["id"],
                        "tier": row["tier"],
                        "content": row["content"],
                        "source": row["source"],
                        "score": score,
                        "created": datetime.fromtimestamp(
                            row["created_at"], tz=timezone.utc
                        ).isoformat(),
                        "accessed": row["access_count"],
                    })

            # Sort by score and take top
            results.sort(key=lambda x: x["score"], reverse=True)
            results = results[:limit]

            # Update access counters
            for r in results:
                conn.execute(
                    "UPDATE facts SET accessed_at=?, access_count=access_count+1 WHERE id=?",
                    (time.time(), r["id"]),
                )
            conn.commit()

        return json.dumps({
            "status": "success",
            "query": query,
            "tiers_searched": tiers,
            "results": results,
        })

    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        conn.close()


def _handle_store(args, **kwargs):
    facts = args.get("facts", [])
    tier = args.get("tier", "working")
    source = args.get("source", "")
    importance = args.get("importance", 0.5 if tier == "working" else 0.8)

    if not facts:
        return json.dumps({"status": "error", "reason": "No facts provided"})

    if tier not in TIER_ORDER:
        tier = "working"

    now = time.time()
    conn = _get_db()
    try:
        stored = []
        for fact in facts[:10]:  # Max 10 at a time
            fact = (fact or "").strip()[:500]  # 500 char limit
            if not fact:
                continue

            cur = conn.execute(
                """INSERT INTO facts (tier, content, source, importance, created_at, accessed_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (tier, fact, source, importance, now, now),
            )
            fid = cur.lastrowid

            # Index into FTS5
            conn.execute("INSERT INTO facts_fts (rowid, content) VALUES (?, ?)", (fid, fact))
            stored.append({"id": fid, "content": fact, "tier": tier})

        conn.commit()
        _auto_prune(conn, tier)

        return json.dumps({
            "status": "stored",
            "count": len(stored),
            "tier": tier,
            "facts": stored,
        })

    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        conn.close()


def _handle_remember(args, **kwargs):
    fact = (args.get("fact") or "").strip()
    source = args.get("source", "manual")
    if not fact:
        return json.dumps({"status": "error", "reason": "No fact provided"})

    # Redirect to store
    return _handle_store({
        "facts": [fact],
        "tier": "working",
        "source": source,
        "importance": 0.5,
    })


def _handle_forget(args, **kwargs):
    fid = args.get("fact_id")
    if not fid:
        return json.dumps({"status": "error", "reason": "No fact_id provided"})

    conn = _get_db()
    try:
        conn.execute("DELETE FROM facts WHERE id=?", (fid,))
        conn.execute("DELETE FROM facts_fts WHERE rowid=?", (fid,))
        conn.commit()
        return json.dumps({"status": "deleted", "fact_id": fid})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        conn.close()


def _handle_status(args, **kwargs):
    conn = _get_db()
    try:
        tiers = {}
        total = 0
        for tier in TIER_ORDER:
            row = conn.execute(
                "SELECT COUNT(*) as cnt, AVG(importance) as avg_imp FROM facts WHERE tier=?",
                (tier,),
            ).fetchone()
            cnt = row["cnt"] if row else 0
            tiers[tier] = {
                "count": cnt,
                "avg_importance": round(row["avg_imp"], 2) if row and row["avg_imp"] else 0,
            }
            total += cnt

        # Recent activity
        recent = conn.execute(
            "SELECT content, tier, created_at FROM facts ORDER BY created_at DESC LIMIT 5"
        ).fetchall()

        # DB size
        db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0

        return json.dumps({
            "status": "ok",
            "total_facts": total,
            "tiers": tiers,
            "db_size_bytes": db_size,
            "db_size_human": f"{db_size / 1024:.1f} KB" if db_size < 1024 * 1024
                            else f"{db_size / 1024 / 1024:.1f} MB",
            "recent": [
                {"content": r["content"][:80], "tier": r["tier"],
                 "created": datetime.fromtimestamp(r["created_at"], tz=timezone.utc).isoformat()}
                for r in recent
            ],
            "tier_caps": TIER_CAPS,
        })

    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        conn.close()


def _handle_tier_move(args, **kwargs):
    fact_ids = args.get("fact_ids", [])
    target = args.get("target_tier", "")

    if not fact_ids or target not in TIER_ORDER:
        return json.dumps({"status": "error", "reason": "Invalid fact_ids or target_tier"})

    conn = _get_db()
    try:
        moved = 0
        for fid in fact_ids:
            cur = conn.execute("UPDATE facts SET tier=? WHERE id=?", (target, fid))
            moved += cur.rowcount
        conn.commit()
        return json.dumps({"status": "moved", "count": moved, "to_tier": target})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        conn.close()


def _handle_reindex(args, **kwargs):
    conn = _get_db()
    try:
        conn.execute("DELETE FROM facts_fts")
        rows = conn.execute("SELECT id, content FROM facts").fetchall()
        for row in rows:
            conn.execute("INSERT INTO facts_fts (rowid, content) VALUES (?, ?)",
                         (row["id"], row["content"]))
        conn.commit()
        return json.dumps({"status": "reindexed", "count": len(rows)})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Auto-prune: keep only top-N facts per tier by score
# ---------------------------------------------------------------------------

def _auto_prune(conn: sqlite3.Connection, tier: str):
    """Remove oldest/lowest-scored facts when tier exceeds cap."""
    cap = TIER_CAPS.get(tier, 500)
    count = conn.execute("SELECT COUNT(*) FROM facts WHERE tier=?", (tier,)).fetchone()[0]

    if count <= cap:
        return

    # Remove excess: keep highest-importance facts, delete oldest
    excess = count - cap
    # Delete old low-importance facts
    conn.execute(
        """DELETE FROM facts WHERE id IN (
            SELECT id FROM facts WHERE tier=?
            ORDER BY importance ASC, created_at ASC
            LIMIT ?
        )""",
        (tier, excess),
    )
    # Also remove from FTS5
    conn.execute(
        """DELETE FROM facts_fts WHERE rowid IN (
            SELECT id FROM facts WHERE tier=?
            ORDER BY importance ASC, created_at ASC
            LIMIT ?
        )""",
        (tier, excess),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def register(ctx):
    ctx.register_tool(
        name="bmc_search",
        toolset="byte_memory_core",
        schema=SCHEMA_SEARCH,
        handler=_handle_search,
    )
    ctx.register_tool(
        name="bmc_store",
        toolset="byte_memory_core",
        schema=SCHEMA_STORE,
        handler=_handle_store,
    )
    ctx.register_tool(
        name="bmc_remember",
        toolset="byte_memory_core",
        schema=SCHEMA_REMEMBER,
        handler=_handle_remember,
    )
    ctx.register_tool(
        name="bmc_forget",
        toolset="byte_memory_core",
        schema=SCHEMA_FORGET,
        handler=_handle_forget,
    )
    ctx.register_tool(
        name="bmc_status",
        toolset="byte_memory_core",
        schema=SCHEMA_STATUS,
        handler=_handle_status,
    )
    ctx.register_tool(
        name="bmc_tier_move",
        toolset="byte_memory_core",
        schema=SCHEMA_TIER_MOVE,
        handler=_handle_tier_move,
    )
    ctx.register_tool(
        name="bmc_reindex",
        toolset="byte_memory_core",
        schema=SCHEMA_REINDEX,
        handler=_handle_reindex,
    )
