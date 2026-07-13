"""Unit tests for importance scoring."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bmc.scoring import compute_importance_score, recency_score, access_factor


def test_recency_score_fresh():
    """Brand-new fact scores ~1.0."""
    score = recency_score(time.time(), ttl_hours=24)
    assert 0.9 <= score <= 1.0, f"Fresh fact should score near 1.0 (got {score})"


def test_recency_score_old():
    """Very old fact scores near 0."""
    score = recency_score(0, ttl_hours=24)  # epoch = very old
    assert 0.0 <= score < 0.1, f"Old fact should score near 0 (got {score})"


def test_access_factor_recent():
    """Recently accessed fact scores higher."""
    high = access_factor(time.time(), 5)
    low = access_factor(0, 0)
    assert high > low, "Recent access should score higher"


def test_access_factor_frequent():
    """Frequently accessed fact scores higher."""
    frequent = access_factor(time.time(), 20)
    rare = access_factor(time.time(), 1)
    assert frequent >= rare, "Frequent access should score >= rare access"


def test_importance_score_range():
    """Score should be between 0 and 1 (or slightly above with tier boost)."""
    score = compute_importance_score(0.5, 0.5, 1.0, 0.5, 0.5)
    assert 0.0 <= score <= 2.0, f"Score {score} should be in reasonable range"


def test_importance_score_high_relevance():
    """High relevance + recent + high importance = higher score."""
    high = compute_importance_score(1.0, 1.0, 3.0, 1.0, 1.0)
    low = compute_importance_score(0.0, 0.0, 1.0, 0.0, 0.0)
    assert high > low, "High signals should score higher"
