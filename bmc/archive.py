"""Safe O2B archival candidate selection and application."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from bmc.config import (
    O2B_ARCHIVE_MAX_AGE_DAYS,
    O2B_ARCHIVE_MIN_IMPORTANCE,
    O2B_PERMANENT_SOURCES,
)

SOURCE_DIRECTORIES = {
    "architecture": "Architecture",
    "decision": "Decisions",
    "learning": "Learnings",
    "permanent": "Permanent",
}


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
    """Return facts satisfying every configured archival safety criterion."""
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
           WHERE tier = ? AND access_count > ? AND importance >= ?"""
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
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}
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
                "metadata": metadata,
            }
        )
    return candidates


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _similarity(left: str, right: str) -> float:
    """Return token Jaccard similarity, with exact normalized matches at 1.0."""
    left_normal = _normalise(left)
    right_normal = _normalise(right)
    if left_normal == right_normal:
        return 1.0
    left_words = set(re.findall(r"[\w-]{2,}", left_normal))
    right_words = set(re.findall(r"[\w-]{2,}", right_normal))
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / len(left_words | right_words)


def _safe_slug(content: str, fact_id: int) -> str:
    words = re.findall(r"[a-z0-9]+", content.casefold())[:8]
    stem = "-".join(words)[:70].strip("-") or "fact"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:10]
    return f"{stem}-{fact_id}-{digest}.md"


def _read_markdown_facts(vault: Path) -> list[tuple[Path, str]]:
    if not vault.exists():
        return []
    return [(path, path.read_text(encoding="utf-8")) for path in vault.rglob("*.md") if path.is_file()]


def _markdown_content(document: str) -> str:
    """Extract body text while ignoring simple YAML frontmatter."""
    if document.startswith("---\n"):
        _, _, body = document[4:].partition("\n---\n")
        return body
    return document


def _render_markdown(fact: dict[str, Any], archived_at: str, relative_path: str) -> str:
    tags = ", ".join(fact.get("tags", []))
    return (
        "---\n"
        f"bmc_id: {fact['id']}\n"
        f"source: {fact['source']}\n"
        f"importance: {fact['importance']}\n"
        f"access_count: {fact['access_count']}\n"
        f"archived_at: {archived_at}\n"
        f"archived_to: o2b://{relative_path}\n"
        f"tags: [{tags}]\n"
        "---\n\n"
        f"{fact['content'].strip()}\n"
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def archive_facts(
    conn: Any,
    vault: str | Path,
    *,
    apply: bool = False,
    min_access_count: int = 5,
    min_importance: float = O2B_ARCHIVE_MIN_IMPORTANCE,
    max_age_days: int = O2B_ARCHIVE_MAX_AGE_DAYS,
    limit: int = 100,
) -> dict[str, Any]:
    """Preview or apply archival. BMC facts remain intact and get an archive reference."""
    vault_path = Path(vault).expanduser().resolve()
    candidates = find_archivable_facts(
        conn,
        min_access_count=min_access_count,
        min_importance=min_importance,
        max_age_days=max_age_days,
        limit=limit,
    )
    existing = _read_markdown_facts(vault_path)
    now = time.time()
    archived_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    actions: list[dict[str, Any]] = []

    for fact in candidates:
        directory = SOURCE_DIRECTORIES[fact["source"]]
        target = vault_path / "Brain" / directory / _safe_slug(fact["content"], fact["id"])
        match: tuple[Path, str] | None = None
        for path, document in existing:
            try:
                same_source = path.relative_to(vault_path / "Brain" / directory)
            except ValueError:
                same_source = None
            if same_source is not None and _similarity(fact["content"], _markdown_content(document)) >= 0.8:
                match = (path, document)
                break
        if match:
            path, document = match
            relative = path.relative_to(vault_path).as_posix()
            action = "update"
        else:
            path = target
            relative = path.relative_to(vault_path).as_posix()
            document = ""
            action = "create"

        actions.append({"fact_id": fact["id"], "action": action, "path": relative})
        if not apply:
            continue

        if match:
            # Update metadata and timestamp while preserving the existing body.
            content = _render_markdown(fact, archived_at, relative)
            old_body = _markdown_content(document).strip()
            if _normalise(old_body) != _normalise(fact["content"]):
                content += f"\n## Update {archived_at}\n\n{fact['content'].strip()}\n"
        else:
            content = _render_markdown(fact, archived_at, relative)
        _atomic_write(path, content)
        existing = [(p, d) for p, d in existing if p != path] + [(path, content)]

        metadata = dict(fact.get("metadata") or {})
        metadata.update({"archived_to": f"o2b://{relative}", "archived_at": archived_at})
        conn.execute("UPDATE facts SET metadata=? WHERE id=?", (json.dumps(metadata), fact["id"]))

    if apply and candidates:
        conn.commit()
    return {
        "status": "applied" if apply else "preview",
        "vault": str(vault_path),
        "count": len(candidates),
        "created": sum(a["action"] == "create" for a in actions) if apply else 0,
        "updated": sum(a["action"] == "update" for a in actions) if apply else 0,
        "actions": actions,
    }


def _handle_archive(args: dict[str, Any], **kwargs: Any) -> str:
    """Hermes tool handler for previewing or applying O2B archival."""
    from bmc.config import O2B_VAULT
    from bmc.database import _get_db

    vault = args.get("vault") or O2B_VAULT
    if not vault:
        return json.dumps({"status": "error", "reason": "O2B vault is not configured"})
    conn = _get_db()
    try:
        return json.dumps(
            archive_facts(
                conn,
                vault,
                apply=bool(args.get("apply", False)),
                min_access_count=int(args.get("min_access_count", 5)),
                min_importance=float(args.get("min_importance", O2B_ARCHIVE_MIN_IMPORTANCE)),
                max_age_days=int(args.get("max_age_days", O2B_ARCHIVE_MAX_AGE_DAYS)),
                limit=int(args.get("limit", 100)),
            )
        )
    except (TypeError, ValueError, OSError) as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    finally:
        conn.close()
