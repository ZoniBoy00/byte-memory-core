"""TF-IDF computation with character n-gram tokenization + multi-source search."""

import json
import math
import os
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from bmc.tokenize import tokenize
from bmc.config import TIER_ORDER, O2B_VAULT, HONCHO_API, HONCHO_WORKSPACE


def _search_o2b(query: str, limit: int = 5) -> List[dict]:
    """Search o2b vault via CLI and parse results."""
    if not O2B_VAULT or not os.path.isdir(O2B_VAULT):
        return []

    try:
        bun_path = os.path.expanduser("~/.bun/bin/bun")
        env = os.environ.copy()
        env["PATH"] = f"{os.path.expanduser('~/.bun/bin')}:{env.get('PATH', '')}"

        result = subprocess.run(
            ["o2b", "search", "--vault", O2B_VAULT, query],
            capture_output=True, text=True, timeout=15, env=env,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []

        entries = []
        for block in result.stdout.strip().split("\n\n"):
            lines = block.strip().split("\n")
            if not lines:
                continue

            first = lines[0]
            match = re.match(r'\[\d+\]\s+(.+?)\s+•\s+([\d.]+)', first)
            if not match:
                continue

            path = match.group(1).strip()
            score = float(match.group(2))

            # Extract content preview
            content = ""
            for line in lines[1:]:
                line = line.strip()
                if line.startswith("---") or line.startswith("line "):
                    continue
                if line:
                    content += line + "\n"

            entries.append({
                "source": "o2b",
                "content": path,
                "preview": content.strip()[:200],
                "score": round(score, 4),
                "url": f"file://{O2B_VAULT}/{path}",
            })

        return entries[:limit]

    except Exception:
        return []


def _search_honcho(query: str, limit: int = 5) -> List[dict]:
    """Search Honcho memory provider via local API."""
    if not HONCHO_API or not HONCHO_WORKSPACE:
        return []
    try:
        import urllib.request
        import urllib.error

        data = json.dumps({"query": query, "limit": limit}).encode()
        req = urllib.request.Request(
            f"{HONCHO_API}/v3/workspaces/{HONCHO_WORKSPACE}/peers/user/search",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            results = json.loads(resp.read())

        if not results or not isinstance(results, list):
            return []

        entries = []
        for r in results[:limit]:
            content = r.get("content") or r.get("text") or r.get("message") or str(r)
            score = r.get("score") or r.get("relevance") or 0.5
            entries.append({
                "source": "honcho",
                "content": str(content)[:300],
                "detail": r.get("session_id", ""),
                "score": round(float(score), 4),
            })
        return entries

    except Exception:
        return []


def _tfidf_score(
    query_tokens: List[str],
    doc_tokens: List[str],
    idf_cache: Dict[str, float],
) -> float:
    """Cosine similarity between query and document using TF-IDF vectors.

    Only n-grams present in the query are evaluated, making this fast
    even for large document collections.
    """
    if not query_tokens or not doc_tokens:
        return 0.0

    q_counts = Counter(query_tokens)
    d_counts = Counter(doc_tokens)

    q_vec = np.array([
        q_counts.get(t, 0) * idf_cache.get(t, 1.0) for t in query_tokens
    ])
    d_vec = np.array([
        d_counts.get(t, 0) * idf_cache.get(t, 1.0) for t in query_tokens
    ])

    norm_q = np.linalg.norm(q_vec)
    norm_d = np.linalg.norm(d_vec)
    if norm_q == 0 or norm_d == 0:
        return 0.0

    return float(np.dot(q_vec, d_vec) / (norm_q * norm_d))


def _build_idf_cache(conn) -> Dict[str, float]:
    """Build inverse-document-frequency cache from all stored facts.

    IDF = log((N + 1) / (df + 1)) + 1  (smooth IDF, never zero).
    """
    rows = conn.execute("SELECT content FROM facts").fetchall()
    if not rows:
        return {}

    num_docs = len(rows)
    doc_freq: Counter = Counter()
    for row in rows:
        for t in set(tokenize(row["content"])):
            doc_freq[t] += 1

    return {
        term: math.log((num_docs + 1) / (df + 1)) + 1.0
        for term, df in doc_freq.items()
    }


def _handle_search(args, **kwargs):
    """Search across memory sources using hybrid FTS5 + TF-IDF."""
    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps({"status": "empty", "results": []})

    limit = min(args.get("limit", 5), 20)
    sources = args.get("sources", ["bmc", "o2b"])
    tiers = args.get("tiers", TIER_ORDER)
    min_score = args.get("min_score", 0.0)

    from bmc.database import _get_db
    from bmc.scoring import compute_importance_score, recency_score, access_factor
    from bmc.config import TIER_WEIGHTS, TIER_TTL_HOURS

    all_results = []

    # 1) Search BMC local database
    if "bmc" in sources:
        conn = _get_db()
        try:
            query_tokens = tokenize(query)
            idf_cache = _build_idf_cache(conn)

            for tier in tiers:
                if tier not in TIER_ORDER:
                    continue

                safe_query = query.replace('"', '""')
                fts_rows = conn.execute(
                    """SELECT f.id, f.tier, f.content, f.source, f.importance,
                              f.created_at, f.accessed_at, f.access_count, rank
                       FROM facts_fts
                       JOIN facts f ON facts_fts.rowid = f.id
                       WHERE facts_fts MATCH ?
                         AND f.tier = ?
                       ORDER BY rank
                       LIMIT ?""",
                    (safe_query, tier, limit * 2),
                ).fetchall()

                if not fts_rows:
                    fallback = conn.execute(
                        """SELECT id, tier, content, source, importance,
                                  created_at, accessed_at, access_count
                           FROM facts
                           WHERE tier = ?
                           ORDER BY importance DESC, created_at DESC
                           LIMIT ?""",
                        (tier, limit),
                    ).fetchall()

                    for row in fallback:
                        doc_tokens = tokenize(row["content"])
                        tfidf = _tfidf_score(query_tokens, doc_tokens, idf_cache)
                        if tfidf > 0.05:
                            f5 = tfidf * 0.8
                            ttl = TIER_TTL_HOURS.get(tier, 24)
                            rec = recency_score(row["created_at"], ttl)
                            acc = access_factor(row["accessed_at"], row["access_count"])
                            tw = TIER_WEIGHTS.get(tier, 1.0)
                            score = compute_importance_score(f5, rec, tw, acc, row["importance"])
                            if score >= min_score:
                                all_results.append({
                                    "source": "bmc",
                                    "tier": row["tier"],
                                    "content": row["content"],
                                    "detail": row["source"],
                                    "score": round(score, 4),
                                    "id": row["id"],
                                })
                else:
                    for row in fts_rows:
                        fts5_rank = max(0.0, min(1.0, (-(row[8] or 0)) / 10.0 + 0.5))
                        doc_tokens = tokenize(row["content"])
                        tfidf = _tfidf_score(query_tokens, doc_tokens, idf_cache)
                        ttl = TIER_TTL_HOURS.get(tier, 24)
                        rec = recency_score(row["created_at"], ttl)
                        acc = access_factor(row["accessed_at"], row["access_count"])
                        tw = TIER_WEIGHTS.get(tier, 1.0)
                        score = compute_importance_score(max(fts5_rank, tfidf * 0.7), rec, tw, acc, row["importance"])
                        if score >= min_score:
                            all_results.append({
                                "source": "bmc",
                                "tier": row["tier"],
                                "content": row["content"],
                                "detail": row["source"],
                                "score": round(score, 4),
                                "id": row["id"],
                            })

                # Update access counters for BMC results
                bmc_results = [r for r in all_results if r["source"] == "bmc"]
                for r in bmc_results:
                    conn.execute(
                        "UPDATE facts SET accessed_at=?, access_count=access_count+1 WHERE id=?",
                        (time.time(), r["id"]),
                    )
                conn.commit()

        finally:
            conn.close()

    # 2) Search o2b vault
    if "o2b" in sources:
        o2b_results = _search_o2b(query, limit)
        for r in o2b_results:
            all_results.append(r)

    # 3) Search Honcho
    if "honcho" in sources:
        honcho_results = _search_honcho(query, limit)
        for r in honcho_results:
            all_results.append(r)

    # Sort all results by score descending
    all_results.sort(key=lambda x: x["score"], reverse=True)
    all_results = all_results[:limit * 3]


    if not all_results:
        return json.dumps({"status": "success", "query": query, "results": []})

    return json.dumps({
        "status": "success",
        "query": query,
        "sources_searched": sources,
        "total_results": len(all_results),
        "results": all_results,
    })
