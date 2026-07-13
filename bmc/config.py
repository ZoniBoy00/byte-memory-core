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

# External search sources
O2B_VAULT = os.environ.get("O2B_VAULT_PATH", "")
"""Path to o2b vault directory. Set via env var or leave empty to disable."""

HONCHO_API = os.environ.get("HONCHO_API_URL", "")
"""Honcho API base URL (e.g. http://localhost:8000). Empty = disabled."""

HONCHO_WORKSPACE = os.environ.get("HONCHO_WORKSPACE_ID", "")
"""Honcho workspace ID. Required when HONCHO_API is set."""
