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

PLUGIN_DIR = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
DB_DIR = HERMES_HOME / "byte_memory_core"
DB_PATH = DB_DIR / "store.db"

TIER_WEIGHTS = {"working": 3.0, "episodic": 2.0, "scratchpad": 1.0}
TIER_ORDER = ["working", "episodic", "scratchpad"]
WORKING_TTL_HOURS = 24
EPISODIC_TTL_HOURS = 720
TIER_CAPS = {"working": 500, "episodic": 2000, "scratchpad": 300}
NGRAM_MIN = 2
NGRAM_MAX = 4


def _get_db() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tier TEXT NOT NULL DEFAULT 'working',
            content TEXT NOT NULL,
            source TEXT DEFAULT '',
            importance REAL DEFAULT 0.5,
            created_at REAL NOT NULL,
            accessed_at REAL NOT NULL DEFAULT 0,
            access_count INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_facts_tier ON facts(tier);
        CREATE INDEX IF NOT EXISTS idx_facts_created ON facts(created_at);
        CREATE INDEX IF NOT EXISTS idx_facts_importance ON facts(importance);
        CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(content);
    """)
    conn.commit()
    return conn


def _tokenize(text: str) -> List[str]:
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    tokens = []
    for n in range(NGRAM_MIN, NGRAM_MAX + 1):
        for i in range(len(text) - n + 1):
            ngram = text[i:i + n]
            if ngram.strip():
                tokens.append(ngram)
    return tokens


def _tfidf_score(query_tokens, doc_tokens, idf_cache):
    if not query_tokens or not doc_tokens:
        return 0.0
    q_counts = Counter(query_tokens)
    d_counts = Counter(doc_tokens)
    q_vec = np.array([q_counts.get(t, 0) * idf_cache.get(t, 1.0) for t in query_tokens])
    d_vec = np.array([d_counts.get(t, 0) * idf_cache.get(t, 1.0) for t in query_tokens])
    nq = np.linalg.norm(q_vec)
    nd = np.linalg.norm(d_vec)
    if nq == 0 or nd == 0:
        return 0.0
    return float(np.dot(q_vec, d_vec) / (nq * nd))


def _compute_importance_score(fts5_rank, recency, tier_weight, access_factor, importance):
    return round(0.35 * fts5_rank + 0.25 * recency + 0.15 * tier_weight + 0.10 * access_factor + 0.15 * importance, 4)


def _recency_score(created_at, hours_ago=24):
    age_hours = (time.time() - created_at) / 3600
    if age_hours <= 0:
        return 1.0
    return 1.0 / (1.0 + age_hours / max(hours_ago, 1))


def _access_factor(accessed_at, access_count):
    recency = _recency_score(accessed_at, 72)
    freq = min(access_count / 20.0, 1.0)
    return 0.6 * recency + 0.4 * freq


def _build_idf_cache(conn):
    rows = conn.execute("SELECT content FROM facts").fetchall()
    if not rows:
        return {}
    num_docs = len(rows)
    doc_freq = Counter()
    for row in rows:
        for t in set(_tokenize(row["content"])):
            doc_freq[t] += 1
    return {term: math.log((num_docs + 1) / (df + 1)) + 1.0 for term, df in doc_freq.items()}


SCHEMA_SEARCH = {
    "name": "bmc_search",
    "description": "Search across memory tiers using hybrid FTS5 + semantic-lite matching.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "tiers": {"type": "array", "items": {"type": "string", "enum": TIER_ORDER}, "description": "Tiers to search"},
            "limit": {"type": "integer", "description": "Max results"},
            "min_score": {"type": "number", "description": "Minimum score 0-1"},
        },
        "required": ["query"],
    },
}

SCHEMA_STORE = {
    "name": "bmc_store",
    "description": "Store facts into a specific memory tier.",
    "parameters": {
        "type": "object",
        "properties": {
            "facts": {"type": "array", "items": {"type": "string"}, "description": "Facts to store"},
            "tier": {"type": "string", "enum": TIER_ORDER, "description": "Target tier"},
            "source": {"type": "string", "description": "Source context"},
            "importance": {"type": "number", "description": "Importance 0.0-1.0"},
        },
        "required": ["facts"],
    },
}

SCHEMA_REMEMBER = {
    "name": "bmc_remember",
    "description": "Quick-save to Working tier.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "What to remember"},
            "source": {"type": "string", "description": "Context"},
        },
        "required": ["fact"],
    },
}

SCHEMA_FORGET = {
    "name": "bmc_forget",
    "description": "Delete a fact by ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact_id": {"type": "integer", "description": "Fact ID to delete"},
        },
        "required": ["fact_id"],
    },
}

SCHEMA_STATUS = {
    "name": "bmc_status",
    "description": "Show memory health stats.",
    "parameters": {"type": "object", "properties": {}},
}

SCHEMA_TIER_MOVE = {
    "name": "bmc_tier_move",
    "description": "Move facts between tiers.",
    "parameters": {
        "type": "object",
        "properties": {
            "fact_ids": {"type": "array", "items": {"type": "integer"}, "description": "Fact IDs to move"},
            "target_tier": {"type": "string", "enum": TIER_ORDER, "description": "Target tier"},
        },
        "required": ["fact_ids", "target_tier"],
    },
}

SCHEMA_REINDEX = {
    "name": "bmc_reindex",
    "description": "Rebuild FTS5 search index.",
    "parameters": {"type": "object", "properties": {}},
}


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
            safe_query = query.replace('"', '""')
            fts_rows = conn.execute(
                "SELECT f.id, f.tier, f.content, f.source, f.importance, "
                "f.created_at, f.accessed_at, f.access_count, rank "
                "FROM facts_fts JOIN facts f ON facts_fts.rowid = f.id "
                "WHERE facts_fts MATCH ? AND f.tier = ? ORDER BY rank LIMIT ?",
                (safe_query, tier, limit * 2),
            ).fetchall()

            if not fts_rows:
                # Fallback: get recent facts and score by TF-IDF alone
                fallback = conn.execute(
                    "SELECT id, tier, content, source, importance, created_at, accessed_at, access_count FROM facts WHERE tier=? ORDER BY created_at DESC LIMIT ?",
                    (tier, limit),
                ).fetchall()
                for row in fallback:
                    tfidf = _tfidf_score(query_tokens, _tokenize(row["content"]), idf_cache)
                    if tfidf > 0.05:  # Only include if there's some similarity
                        fts5_rank = tfidf * 0.8
                        rec = _recency_score(row["created_at"], WORKING_TTL_HOURS if tier == "working" else EPISODIC_TTL_HOURS)
                        acc = _access_factor(row["accessed_at"], row["access_count"])
                        score = _compute_importance_score(fts5_rank, rec, TIER_WEIGHTS.get(tier, 1.0), acc, row["importance"])
                        if score >= min_score:
                            results.append({"id": row["id"], "tier": row["tier"], "content": row["content"],
                                "source": row["source"], "score": score,
                                "created": datetime.fromtimestamp(row["created_at"], tz=timezone.utc).isoformat(),
                                "accessed": row["access_count"]})
            else:
                fts5_rank = max(0.0, min(1.0, (-row[8] if row[8] else 0.5) / 10.0 + 0.5))
                tfidf = _tfidf_score(query_tokens, _tokenize(row["content"]), idf_cache)
                rec = _recency_score(row["created_at"], WORKING_TTL_HOURS if tier == "working" else EPISODIC_TTL_HOURS)
                acc = _access_factor(row["accessed_at"], row["access_count"])
                score = _compute_importance_score(max(fts5_rank, tfidf * 0.7), rec, TIER_WEIGHTS.get(tier, 1.0), acc, row["importance"])
                if score >= min_score:
                    results.append({
                        "id": row["id"], "tier": row["tier"], "content": row["content"],
                        "source": row["source"], "score": score,
                        "created": datetime.fromtimestamp(row["created_at"], tz=timezone.utc).isoformat(),
                        "accessed": row["access_count"],
                    })
            results.sort(key=lambda x: x["score"], reverse=True)
            results = results[:limit]
            for r in results:
                conn.execute("UPDATE facts SET accessed_at=?, access_count=access_count+1 WHERE id=?", (time.time(), r["id"]))
            conn.commit()
        return json.dumps({"status": "success", "query": query, "results": results})
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
        return json.dumps({"status": "error", "reason": "No facts"})
    if tier not in TIER_ORDER:
        tier = "working"
    now = time.time()
    conn = _get_db()
    try:
        stored = []
        for fact in [f.strip()[:500] for f in facts[:10] if f.strip()]:
            cur = conn.execute("INSERT INTO facts (tier,content,source,importance,created_at,accessed_at) VALUES (?,?,?,?,?,?)",
                               (tier, fact, source, importance, now, now))
            fid = cur.lastrowid
            conn.execute("INSERT INTO facts_fts (rowid,content) VALUES (?,?)", (fid, fact))
            stored.append({"id": fid, "content": fact, "tier": tier})
        conn.commit()
        _auto_prune(conn, tier)
        return json.dumps({"status": "stored", "count": len(stored), "tier": tier, "facts": stored})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        conn.close()


def _handle_remember(args, **kwargs):
    fact = (args.get("fact") or "").strip()
    if not fact:
        return json.dumps({"status": "error", "reason": "No fact"})
    return _handle_store({"facts": [fact], "tier": "working", "source": args.get("source", "manual"), "importance": 0.5})


def _handle_forget(args, **kwargs):
    fid = args.get("fact_id")
    if not fid:
        return json.dumps({"status": "error", "reason": "No fact_id"})
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
        for t in TIER_ORDER:
            row = conn.execute("SELECT COUNT(*), AVG(importance) FROM facts WHERE tier=?", (t,)).fetchone()
            cnt = row[0] if row else 0
            tiers[t] = {"count": cnt, "avg_importance": round(row[1], 2) if row and row[1] else 0}
            total += cnt
        recent = conn.execute("SELECT content, tier, created_at FROM facts ORDER BY created_at DESC LIMIT 5").fetchall()
        db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
        return json.dumps({
            "status": "ok", "total_facts": total, "tiers": tiers,
            "db_size_bytes": db_size,
            "db_size_human": f"{db_size/1024:.1f} KB" if db_size < 1024*1024 else f"{db_size/1024/1024:.1f} MB",
            "recent": [{"content": r[0][:80], "tier": r[1], "created": datetime.fromtimestamp(r[2], tz=timezone.utc).isoformat()} for r in recent],
        })
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        conn.close()


def _handle_tier_move(args, **kwargs):
    fact_ids = args.get("fact_ids", [])
    target = args.get("target_tier", "")
    if not fact_ids or target not in TIER_ORDER:
        return json.dumps({"status": "error", "reason": "Invalid"})
    conn = _get_db()
    try:
        moved = sum(conn.execute("UPDATE facts SET tier=? WHERE id=?", (target, fid)).rowcount for fid in fact_ids)
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
            conn.execute("INSERT INTO facts_fts (rowid, content) VALUES (?, ?)", (row[0], row[1]))
        conn.commit()
        return json.dumps({"status": "reindexed", "count": len(rows)})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    finally:
        conn.close()


def _auto_prune(conn, tier):
    cap = TIER_CAPS.get(tier, 500)
    count = conn.execute("SELECT COUNT(*) FROM facts WHERE tier=?", (tier,)).fetchone()[0]
    if count <= cap:
        return
    excess = count - cap
    conn.execute("DELETE FROM facts WHERE id IN (SELECT id FROM facts WHERE tier=? ORDER BY importance ASC, created_at ASC LIMIT ?)", (tier, excess))
    conn.execute("DELETE FROM facts_fts WHERE rowid IN (SELECT id FROM facts WHERE tier=? ORDER BY importance ASC, created_at ASC LIMIT ?)", (tier, excess))
    conn.commit()


def register(ctx):
    ctx.register_tool(name="bmc_search", toolset="byte_memory_core", schema=SCHEMA_SEARCH, handler=_handle_search)
    ctx.register_tool(name="bmc_store", toolset="byte_memory_core", schema=SCHEMA_STORE, handler=_handle_store)
    ctx.register_tool(name="bmc_remember", toolset="byte_memory_core", schema=SCHEMA_REMEMBER, handler=_handle_remember)
    ctx.register_tool(name="bmc_forget", toolset="byte_memory_core", schema=SCHEMA_FORGET, handler=_handle_forget)
    ctx.register_tool(name="bmc_status", toolset="byte_memory_core", schema=SCHEMA_STATUS, handler=_handle_status)
    ctx.register_tool(name="bmc_tier_move", toolset="byte_memory_core", schema=SCHEMA_TIER_MOVE, handler=_handle_tier_move)
    ctx.register_tool(name="bmc_reindex", toolset="byte_memory_core", schema=SCHEMA_REINDEX, handler=_handle_reindex)
