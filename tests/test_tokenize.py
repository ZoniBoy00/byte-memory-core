"""Unit tests for n-gram tokenization."""

import os
import sys
import tempfile

# Point to plugin root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bmc.tokenize import tokenize


def test_tokenize_basic():
    """Simple text produces n-grams."""
    result = tokenize("hello")
    assert len(result) > 0, "Should produce tokens"
    assert all(isinstance(t, str) for t in result), "All should be strings"


def test_tokenize_lowercase():
    """Tokens are lowercased."""
    result = tokenize("HELLO")
    assert all(t.islower() for t in result), "All should be lowercase"


def test_tokenize_special_chars():
    """Special characters are stripped."""
    result = tokenize("hello-world!")
    for t in result:
        assert "-" not in t, "Hyphens should be removed"
        assert "!" not in t, "Exclamation should be removed"


def test_tokenize_ngram_range():
    """N-grams cover the configured range (2-4)."""
    result = tokenize("python")
    # "py", "yp", "th", "ho", "on" (2-grams) + "pyt", "yth", "tho", "hon" (3-grams) + ...
    lengths = set(len(t) for t in result)
    assert 2 <= min(lengths) and max(lengths) <= 4, \
        f"N-gram lengths {lengths} should be between 2 and 4"


def test_tokenize_semantic_similarity():
    """Similar words should share n-grams for fuzzy matching.
    
    'tarkistaa' and 'tarkistus' share 'tark', 'arki', 'rkis', 'kist' etc.
    """
    a = set(tokenize("tarkistaa"))
    b = set(tokenize("tarkistus"))
    overlap = a & b
    assert len(overlap) > 0, \
        f"Similar words should share n-grams (got {len(overlap)} shared)"


def test_tokenize_empty():
    """Empty string returns empty list."""
    assert tokenize("") == []
    assert tokenize("   ") == []


def test_tokenize_single_char():
    """Single characters produce no n-grams below minimum."""
    # 'a' has length 1, n-grams start at 2 — should be empty
    result = tokenize("a")
    assert result == [], f"Single char should produce no tokens (got {result})"
