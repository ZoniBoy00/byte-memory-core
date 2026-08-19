"""
byte-memory-core — maintenance script.

Runs periodic maintenance:
1. Prune expired Scratchpad facts (7-day TTL)
2. Prune low-importance Working facts past TTL
3. Compact the database (VACUUM)

Designed to run as a no_agent Hermes cronjob.
Outputs a one-line status; empty output = nothing to do.
"""

import json
import sqlite3
import time
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from bmc.manage import _handle_export

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
DB_PATH = HERMES_HOME / "byte_memory_core" / "store.db"
BACKUP_DIR = HERMES_HOME / "backups" / "bmc"
BACKUP_RETENTION_DAYS = 14

# TTL hours per tier
TIER_TTL = {"working": 24, "episodic": 720, "scratchpad": 168}
# Max facts per tier
TIER_CAP = {"working": 500, "episodic": 2000, "scratchpad": 300}


def _write_daily_backup() -> str:
    """Write one atomic JSON backup and prune backups beyond retention."""
    result = json.loads(_handle_export({}))
    if result.get("status") != "success":
        raise RuntimeError(result.get("error") or result.get("reason") or "export failed")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target = BACKUP_DIR / f"bmc-{day}.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    os.replace(temp, target)

    cutoff = time.time() - BACKUP_RETENTION_DAYS * 86400
    removed = 0
    for backup in BACKUP_DIR.glob("bmc-*.json"):
        if backup != target and backup.stat().st_mtime < cutoff:
            backup.unlink()
            removed += 1
    return f"backup: {target.name}" + (f", removed {removed} old" if removed else "")


def maintain() -> str:
    if not DB_PATH.exists():
        return ""  # No DB yet, nothing to do

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    now = time.time()
    total_purged = 0
    messages: list[str] = []

    for tier, ttl in TIER_TTL.items():
        cutoff = now - ttl * 3600

        # Count expired
        expired = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE tier=? AND created_at < ?",
            (tier, cutoff),
        ).fetchone()[0]

        if expired > 0:
            # Delete from facts
            conn.execute(
                "DELETE FROM facts WHERE tier=? AND created_at < ?",
                (tier, cutoff),
            )
            # Clean FTS
            conn.execute(
                "DELETE FROM facts_fts WHERE rowid NOT IN (SELECT id FROM facts)"
            )
            total_purged += expired
            messages.append(f"{tier}: {expired} expired")

        # Enforce cap
        count = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE tier=?", (tier,)
        ).fetchone()[0]
        cap = TIER_CAP.get(tier, 500)
        if count > cap:
            excess = count - cap
            conn.execute(
                """DELETE FROM facts WHERE id IN (
                    SELECT id FROM facts
                    WHERE tier=?
                    ORDER BY importance ASC, created_at ASC
                    LIMIT ?
                )""",
                (tier, excess),
            )
            conn.execute(
                "DELETE FROM facts_fts WHERE rowid NOT IN (SELECT id FROM facts)"
            )
            total_purged += excess
            messages.append(f"{tier}: {excess} cap-pruned")

    # Auto-promote Working → Episodic for frequently accessed facts
    auto_promoted = conn.execute(
        """UPDATE facts SET tier='episodic', importance=MAX(importance, 0.8)
           WHERE tier='working' AND access_count > 3
           RETURNING id"""
    ).fetchall()
    if auto_promoted:
        messages.append(f"auto-promoted {len(auto_promoted)} facts to episodic")

    conn.commit()

    # Weekly FTS5 reindex (every 7 days)
    reindex_marker = HERMES_HOME / "byte_memory_core" / ".last_reindex"
    reindex_interval = 7 * 24 * 3600
    now_ts = time.time()
    if not reindex_marker.exists() or (now_ts - reindex_marker.stat().st_mtime) > reindex_interval:
        conn.execute("DELETE FROM facts_fts")
        rows = conn.execute("SELECT id, content FROM facts").fetchall()
        for row in rows:
            conn.execute(
                "INSERT INTO facts_fts (rowid, content) VALUES (?, ?)",
                (row[0], row[1]),
            )
        conn.commit()
        reindex_marker.parent.mkdir(parents=True, exist_ok=True)
        reindex_marker.touch()
        messages.append(f"fts5 reindexed ({len(rows)} facts)")

    # VACUUM if we removed significant data (> 10% of rows)
    remaining = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    if total_purged > 50 and remaining > 0:
        conn.execute("VACUUM")
        messages.append(f"vacuumed ({remaining} remaining)")

    conn.close()

    try:
        messages.append(_write_daily_backup())
    except Exception as exc:
        messages.append(f"backup failed: {exc}")

    if not messages:
        return ""  # Silent — nothing to report

    summary = "; ".join(messages)
    print(f"[bmc-maintain] {summary}")
    return summary


if __name__ == "__main__":
    maintain()
