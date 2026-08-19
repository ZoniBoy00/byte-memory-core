"""Management handlers: forget, status, tier_move, reindex."""

import json
import time
from datetime import datetime, timezone

from bmc.config import TIER_ORDER, DB_PATH
from bmc.database import _get_db, _auto_prune
from bmc.store import _find_similar


def _parse_export_payload(args):
    payload = args.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON payload: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object or JSON string")
    if payload.get("format") != "byte-memory-core-export":
        raise ValueError("Unsupported export format")
    if payload.get("version") != 1:
        raise ValueError("Unsupported export version")
    facts = payload.get("facts")
    if not isinstance(facts, list):
        raise ValueError("Export payload must contain a facts array")
    return facts


def _handle_export(args, **kwargs):
    """Export facts as a versioned JSON envelope with optional filters."""
    conn = _get_db()
    try:
        clauses = []
        params = []
        tier = args.get("tier")
        if tier:
            if tier not in TIER_ORDER:
                return json.dumps({"status": "error", "reason": "Invalid tier"})
            clauses.append("tier=?")
            params.append(tier)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT tier, content, source, tags, importance, created_at, accessed_at, access_count, metadata "
            f"FROM facts {where} ORDER BY id",
            params,
        ).fetchall()

        query = (args.get("query") or "").strip().casefold()
        wanted_tags = {str(tag) for tag in (args.get("tags") or [])}
        facts = []
        for row in rows:
            tags = json.loads(row["tags"] or "[]")
            metadata = json.loads(row["metadata"] or "{}")
            if query and query not in row["content"].casefold():
                continue
            if wanted_tags and not wanted_tags.issubset(set(tags)):
                continue
            facts.append({
                "tier": row["tier"],
                "content": row["content"],
                "source": row["source"] or "",
                "tags": tags,
                "importance": row["importance"],
                "created_at": row["created_at"],
                "accessed_at": row["accessed_at"],
                "access_count": row["access_count"],
                "metadata": metadata,
            })

        return json.dumps({
            "status": "success",
            "format": "byte-memory-core-export",
            "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count": len(facts),
            "facts": facts,
        })
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    finally:
        conn.close()


def _handle_import(args, **kwargs):
    """Import a versioned export, deduplicating each fact before insert."""
    try:
        facts = _parse_export_payload(args)
    except ValueError as exc:
        return json.dumps({"status": "error", "reason": str(exc)})

    conn = _get_db()
    now = time.time()
    imported = 0
    deduplicated = 0
    errors = 0
    fts_rows = []
    try:
        for item in facts:
            try:
                if not isinstance(item, dict):
                    raise ValueError("fact must be an object")
                content = str(item.get("content", "")).strip()[:500]
                tier = item.get("tier", "working")
                if not content or tier not in TIER_ORDER:
                    raise ValueError("fact needs content and a valid tier")
                importance = float(item.get("importance", 0.5))
                if not 0.0 <= importance <= 1.0:
                    raise ValueError("importance must be between 0 and 1")
                tags = item.get("tags", [])
                metadata = item.get("metadata", {})
                if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                    raise ValueError("tags must be a string array")
                if not isinstance(metadata, dict):
                    raise ValueError("metadata must be an object")
                source = str(item.get("source", ""))
                created_at = float(item.get("created_at", now))
                accessed_at = float(item.get("accessed_at", 0))
                access_count = int(item.get("access_count", 0))

                dup = _find_similar(conn, content, tier)
                if dup:
                    conn.execute(
                        "UPDATE facts SET importance=?, accessed_at=MAX(accessed_at, ?), "
                        "access_count=MAX(access_count, ?), source=?, tags=?, metadata=? WHERE id=?",
                        (max(dup["importance"], importance), accessed_at, access_count,
                         source, json.dumps(tags), json.dumps(metadata), dup["id"]),
                    )
                    deduplicated += 1
                    continue

                cur = conn.execute(
                    "INSERT INTO facts (tier, content, source, tags, importance, created_at, accessed_at, access_count, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (tier, content, source, json.dumps(tags), importance, created_at,
                     accessed_at, access_count, json.dumps(metadata)),
                )
                fts_rows.append((cur.lastrowid, content))
                imported += 1
            except (TypeError, ValueError, json.JSONDecodeError):
                errors += 1

        if fts_rows:
            conn.executemany("INSERT INTO facts_fts (rowid, content) VALUES (?, ?)", fts_rows)
        conn.commit()
        for tier in TIER_ORDER:
            _auto_prune(conn, tier)
        return json.dumps({
            "status": "success",
            "imported": imported,
            "deduplicated": deduplicated,
            "errors": errors,
            "total": len(facts),
        })
    except Exception as exc:
        conn.rollback()
        return json.dumps({"status": "error", "error": str(exc)})
    finally:
        conn.close()


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
