"""Importance scoring logic: recency, access frequency, and hybrid score."""

import time
from typing import Optional

from bmc.config import TIER_WEIGHTS, TIER_TTL_HOURS


def compute_importance_score(
    fts5_rank: float,
    recency: float,
    tier_weight: float,
    access_factor: float,
    importance: float,
) -> float:
    """Compute final relevance score from five components.

    Weights (sum = 1.0):
      35% — FTS5 / TF-IDF relevance
      25% — Recency (how fresh is the fact)
      15% — Tier weight (working > episodic > scratchpad)
      10% — Access frequency + recency of access
      15% — User-assigned importance
    """
    score = (
        0.35 * fts5_rank
        + 0.25 * recency
        + 0.15 * tier_weight
        + 0.10 * access_factor
        + 0.15 * importance
    )
    return round(score, 4)


def recency_score(created_at: float, ttl_hours: int = 24) -> float:
    """Score based on fact age. Returns 1.0 for brand-new, approaches 0.0 slowly.

    Uses a 1/(1 + age/ttl) decay curve so old facts never fully vanish.
    """
    age_hours = (time.time() - created_at) / 3600
    if age_hours <= 0:
        return 1.0
    threshold = max(ttl_hours, 1)
    return 1.0 / (1.0 + age_hours / threshold)


def access_factor(accessed_at: float, access_count: int) -> float:
    """Score based on how often and how recently a fact was accessed.

    60% recency of last access (3-day half-life)
    40% total access count (capped at 20)
    """
    r = recency_score(accessed_at, 72)
    freq = min(access_count / 20.0, 1.0)
    return 0.6 * r + 0.4 * freq
