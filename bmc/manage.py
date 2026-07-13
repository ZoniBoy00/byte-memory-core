"""Management handlers: forget, status, tier_move, reindex."""

import json
import time
from datetime import datetime, timezone

from bmc.config import TIER_ORDER, DB_PATH
from bmc.database import _get_db


def _handle_forget(args, **kwargs):
    """Permanently delete a fact by ID."""
    fid = args.get("fact_id")
    if not fid:
        return json.dumps({"status": "error", "reason": "No fact_id provided"})

    conn = _get_db()
    try:
        conn.execute("DELETE FROM facts WHERE id=?", (fid,))
        conn.execute("DELETE FROM facts_fts WHERE rowid=?", (fid,))
        conn.commit()
        return json.dumps({"status": "deleted", "fact_id": fid})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    finally:
        conn.close()


def _handle_status(args, **kwargs):
    """Display memory health: tier counts, averages, recent entries."""
    conn = _get_db()
    try:
        tiers = {}
        total = 0
        for t in TIER_ORDER:
            row = conn.execute(
                "SELECT COUNT(*), AVG(importance) FROM facts WHERE tier=?",
                (t,),
            ).fetchone()
            cnt = row[0] if row else 0
            tiers[t] = {
                "count": cnt,
                "avg_importance": round(row[1], 2) if row and row[1] else 0,
            }
            total += cnt

        recent = conn.execute(
            "SELECT content, tier, created_at FROM facts ORDER BY created_at DESC LIMIT 5"
        ).fetchall()

        db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
        size_human = (
            f"{db_size / 1024:.1f} KB"
            if db_size < 1024 * 1024
            else f"{db_size / 1024 / 1024:.1f} MB"
        )

        return json.dumps({
            "status": "ok",
            "total_facts": total,
            "tiers": tiers,
            "db_size_bytes": db_size,
            "db_size_human": size_human,
            "recent": [
                {
                    "content": r[0][:80],
                    "tier": r[1],
                    "created": datetime.fromtimestamp(
                        r[2], tz=timezone.utc
                    ).isoformat(),
                }
                for r in recent
            ],
        })
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    finally:
        conn.close()


def _handle_tier_move(args, **kwargs):
    """Move facts between tiers (promote / demote)."""
    fact_ids = args.get("fact_ids", [])
    target = args.get("target_tier", "")

    if not fact_ids or target not in TIER_ORDER:
        return json.dumps({"status": "error", "reason": "Invalid fact_ids or target_tier"})

    conn = _get_db()
    try:
        moved = 0
        for fid in fact_ids:
            cur = conn.execute(
                "UPDATE facts SET tier=? WHERE id=?", (target, fid)
            )
            moved += cur.rowcount
        conn.commit()
        return json.dumps({"status": "moved", "count": moved, "to_tier": target})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    finally:
        conn.close()


def _handle_reindex(args, **kwargs):
    """Rebuild the FTS5 search index from the facts table."""
    conn = _get_db()
    try:
        conn.execute("DELETE FROM facts_fts")
        rows = conn.execute("SELECT id, content FROM facts").fetchall()
        for row in rows:
            conn.execute(
                "INSERT INTO facts_fts (rowid, content) VALUES (?, ?)",
                (row[0], row[1]),
            )
        conn.commit()
        return json.dumps({"status": "reindexed", "count": len(rows)})
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    finally:
        conn.close()
