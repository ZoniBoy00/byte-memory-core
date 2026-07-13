"""TF-IDF computation with character n-gram tokenization."""

import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

from bmc.tokenize import tokenize
from bmc.config import TIER_ORDER


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
    """Search across memory tiers using hybrid FTS5 + TF-IDF."""
    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps({"status": "empty", "results": []})

    limit = min(args.get("limit", 5), 20)
    tiers = args.get("tiers", TIER_ORDER)
    min_score = args.get("min_score", 0.0)

    from bmc.database import _get_db
    from bmc.scoring import compute_importance_score, recency_score, access_factor
    from bmc.config import TIER_WEIGHTS, TIER_TTL_HOURS

    conn = _get_db()
    try:
        query_tokens = tokenize(query)
        idf_cache = _build_idf_cache(conn)
        results = []

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
                # TF-IDF fallback: score recent facts by n-gram similarity
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
                            results.append({
                                "id": row["id"],
                                "tier": row["tier"],
                                "content": row["content"],
                                "source": row["source"],
                                "score": score,
                                "created": datetime.fromtimestamp(row["created_at"], tz=timezone.utc).isoformat(),
                                "accessed": row["access_count"],
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
                        results.append({
                            "id": row["id"],
                            "tier": row["tier"],
                            "content": row["content"],
                            "source": row["source"],
                            "score": score,
                            "created": datetime.fromtimestamp(row["created_at"], tz=timezone.utc).isoformat(),
                            "accessed": row["access_count"],
                        })

            # Sort by score, take top N
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
            "results": results,
        })

    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    finally:
        conn.close()
