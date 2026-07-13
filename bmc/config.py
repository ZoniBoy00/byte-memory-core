"""Configuration constants for byte-memory-core."""

from pathlib import Path
import os

# Database
HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
DB_DIR = HERMES_HOME / "byte_memory_core"
DB_PATH = DB_DIR / "store.db"

# Tier definitions
TIER_ORDER = ["working", "episodic", "scratchpad"]

TIER_WEIGHTS = {
    "working": 3.0,      # Recent conversation context: highest priority
    "episodic": 2.0,     # Important long-term facts: medium priority
    "scratchpad": 1.0,   # Temporary notes: baseline
}

# Per-tier time-to-live (hours) before recency score decays
TIER_TTL_HOURS = {
    "working": 24,      # 1 day
    "episodic": 720,    # ~30 days
    "scratchpad": 168,  # ~7 days
}

# Maximum facts per tier before auto-pruning
TIER_CAPS = {
    "working": 500,
    "episodic": 2000,
    "scratchpad": 300,
}

# Char n-gram range for TF-IDF tokenization
NGRAM_MIN = 2
NGRAM_MAX = 4

# Default importance values per tier
DEFAULT_IMPORTANCE = {
    "working": 0.5,
    "episodic": 0.8,
    "scratchpad": 0.3,
}
