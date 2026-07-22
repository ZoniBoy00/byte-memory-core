"""Store & remember handlers."""

import json
import time
from datetime import datetime, timezone

from bmc.config import TIER_ORDER, DEFAULT_IMPORTANCE
from bmc.database import _get_db, _auto_prune
from bmc.tokenize import tokenize


def _find_similar(conn, fact, tier, threshold=0.80):
    """Check if a similar fact already exists using FTS5 + TF-IDF.

    Returns the existing fact dict if similarity > threshold, else None.
    """
    from bmc.search import _tfidf_score, _build_idf_cache

    query_tokens = tokenize(fact)
    if not query_tokens:
        return None

    idf_cache = _build_idf_cache(conn)

    fts5_terms = [w for w in fact.split() if len(w) >= 2]
    if fts5_terms:
        safe_query = " AND ".join(fts5_terms)
        try:
            rows = conn.execute(
                """SELECT f.id, f.tier, f.content, f.source, f.importance,
                          f.created_at, f.accessed_at, f.access_count
                   FROM facts_fts
                   JOIN facts f ON facts_fts.rowid = f.id
                   WHERE facts_fts MATCH ?
                     AND f.tier = ?
                   ORDER BY rank
                   LIMIT 5""",
                (safe_query, tier),
            ).fetchall()
        except Exception:
            rows = []
    else:
        rows = []

    if not rows:
        rows = conn.execute(
            """SELECT id, tier, content, source, importance,
                      created_at, accessed_at, access_count
               FROM facts
               WHERE tier = ?
               ORDER BY importance DESC, created_at DESC
               LIMIT 20""",
            (tier,),
        ).fetchall()

    for row in rows:
        doc_tokens = tokenize(row["content"])
        score = _tfidf_score(query_tokens, doc_tokens, idf_cache)
        if score >= threshold:
            return {
                "id": row["id"],
                "content": row["content"],
                "access_count": row["access_count"],
                "importance": row["importance"],
                "score": score,
            }

    return None


def _auto_promote(conn):
    """Auto-promote Working facts to Episodic when access_count > 3."""
    promoted = conn.execute(
        """UPDATE facts SET tier='episodic', importance=MAX(importance, 0.8)
           WHERE tier='working' AND access_count > 3
           RETURNING id, content""",
    ).fetchall()

    if promoted:
        conn.commit()


def _handle_store(args, **kwargs):
    """Store facts into a specific tier."""
    facts = args.get("facts", [])
    tier = args.get("tier", "working")
    source = args.get("source", "")
    importance = args.get("importance", DEFAULT_IMPORTANCE.get(tier, 0.5))

    if not facts:
        return json.dumps({"status": "error", "reason": "No facts provided"})
    if tier not in TIER_ORDER:
        tier = "working"

    now = time.time()
    conn = _get_db()
    try:
        stored = []
        fts5_rows = []  # batch for bulk insert
        for fact in facts[:10]:
            fact = (fact or "").strip()[:500]
            if not fact:
                continue

            # Deduplication check
            dup = _find_similar(conn, fact, tier)
            if dup:
                merged_imp = max(dup["importance"], importance)
                conn.execute(
                    "UPDATE facts SET access_count=access_count+1, importance=?, accessed_at=?, source=? WHERE id=?",
                    (merged_imp, now, source, dup["id"]),
                )
                stored.append({"id": dup["id"], "content": dup["content"], "tier": tier, "dedup": True})
                continue

            # New fact
            cur = conn.execute(
                "INSERT INTO facts (tier, content, source, importance, created_at, accessed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (tier, fact, source, importance, now, now),
            )
            fid = cur.lastrowid
            fts5_rows.append((fid, fact))
            stored.append({"id": fid, "content": fact, "tier": tier})

        # Bulk FTS5 insert
        if fts5_rows:
            conn.executemany(
                "INSERT INTO facts_fts (rowid, content) VALUES (?, ?)",
                fts5_rows,
            )

        conn.commit()

        # Auto-promote working to episodic
        _auto_promote(conn)

        # Auto-prune if over cap
        _auto_prune(conn, tier)

        return json.dumps({
            "status": "stored",
            "count": len(stored),
            "tier": tier,
            "facts": stored,
        })

    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    finally:
        conn.close()


def _handle_remember(args, **kwargs):
    """Quick-save a single fact to the Working tier."""
    fact = (args.get("fact") or "").strip()
    if not fact:
        return json.dumps({"status": "error", "reason": "No fact provided"})

    return _handle_store({
        "facts": [fact],
        "tier": "working",
        "source": args.get("source", "manual"),
        "importance": DEFAULT_IMPORTANCE["working"],
    })
