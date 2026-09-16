"""Safe O2B archival candidate selection."""

from __future__ import annotations

import json
import time
from typing import Any

from bmc.config import (
    O2B_ARCHIVE_MAX_AGE_DAYS,
    O2B_ARCHIVE_MIN_IMPORTANCE,
    O2B_PERMANENT_SOURCES,
)


def _tags(value: str | list[str] | None) -> list[str]:
    """Decode a fact's tags without allowing malformed data to break a run."""
    if isinstance(value, list):
        return [str(tag) for tag in value]
    try:
        decoded = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(tag) for tag in decoded] if isinstance(decoded, list) else []


def _source_marker(source: str | None, tags: list[str]) -> str:
    """Resolve a permanent source from the source column or source:<marker> tag."""
    source_value = (source or "").strip().lower()
    if source_value in O2B_PERMANENT_SOURCES:
        return source_value
    for tag in tags:
        prefix, _, marker = tag.partition(":")
        if prefix.lower() == "source" and marker.lower() in O2B_PERMANENT_SOURCES:
            return marker.lower()
    return ""


def find_archivable_facts(
    conn: Any,
    *,
    min_access_count: int = 5,
    min_importance: float = O2B_ARCHIVE_MIN_IMPORTANCE,
    max_age_days: int = O2B_ARCHIVE_MAX_AGE_DAYS,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return facts that satisfy every configured archival safety criterion."""
    if min_access_count < 0 or limit < 1:
        return []

    params: list[Any] = ["episodic", min_access_count, min_importance]
    age_clause = ""
    if max_age_days > 0:
        age_clause = " AND created_at >= ?"
        params.append(time.time() - (max_age_days * 86400))
    params.append(limit)

    query = (
        """SELECT id, tier, content, source, tags, importance,
                  created_at, accessed_at, access_count, metadata
           FROM facts
           WHERE tier = ?
             AND access_count > ?
             AND importance >= ?"""
        + age_clause
        + """
           ORDER BY importance DESC, access_count DESC, accessed_at DESC
           LIMIT ?"""
    )
    rows = conn.execute(query, params).fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        tags = _tags(row["tags"])
        source = _source_marker(row["source"], tags)
        if not source:
            continue
        candidates.append(
            {
                "id": row["id"],
                "tier": row["tier"],
                "content": row["content"],
                "source": source,
                "tags": tags,
                "importance": row["importance"],
                "created_at": row["created_at"],
                "accessed_at": row["accessed_at"],
                "access_count": row["access_count"],
                "metadata": row["metadata"],
            }
        )
    return candidates
