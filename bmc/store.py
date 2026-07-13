"""Store & remember handlers."""

import json
import time
from datetime import datetime, timezone

from bmc.config import TIER_ORDER, DEFAULT_IMPORTANCE
from bmc.database import _get_db, _auto_prune


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
        for fact in facts[:10]:
            fact = (fact or "").strip()[:500]
            if not fact:
                continue

            cur = conn.execute(
                "INSERT INTO facts (tier, content, source, importance, created_at, accessed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (tier, fact, source, importance, now, now),
            )
            fid = cur.lastrowid
            conn.execute(
                "INSERT INTO facts_fts (rowid, content) VALUES (?, ?)", (fid, fact)
            )
            stored.append({"id": fid, "content": fact, "tier": tier})

        conn.commit()
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
