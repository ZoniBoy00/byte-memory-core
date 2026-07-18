# Byte Memory Core — BEAM-tiered local memory for Hermes Agent

> **Working · Episodic · Scratchpad** — local, persistent, tiered memory with hybrid search (FTS5 + n-gram TF-IDF), importance scoring, and automatic pruning. No cloud, no GPU, no ML models.

[![Tests](https://github.com/ZoniBoy00/byte-memory-core/actions/workflows/test.yml/badge.svg)](https://github.com/ZoniBoy00/byte-memory-core/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Agent](https://img.shields.io/badge/Hermes%20Agent-plugin-0891b2)](https://hermes-agent.nousresearch.com/)

---

## Why?

Hermes Agent's built-in memory works, but it's flat — everything is equally important. `byte-memory-core` adds **structure and intelligence**:

- **Three tiers** mimic how human memory works: working (today), episodic (important), scratchpad (ideas)
- **Hybrid search** catches what keyword search misses: typos, partial matches, and related terms via char n-gram TF-IDF
- **Auto-pruning** removes old, low-value facts before they bloat your database
- **Local-only** — SQLite + numpy, zero external services, zero network

---

## BEAM Memory Tiers

| Tier | Decay | Cap | Use Case |
|------|-------|-----|----------|
| **Working** 🔄 | 24 hours | 500 | Recent context, temporary notes |
| **Episodic** 📚 | 30 days | 2000 | Important learnings, decisions, user preferences |
| **Scratchpad** 📝 | 7 days | 300 | Half-baked ideas, follow-ups, todo items |

Each fact is scored by a hybrid of: FTS5 relevance, TF-IDF n-gram similarity, recency, access frequency, tier weight, and manual importance. Low-scoring facts are pruned first.

---

## Installation

```bash
cd ~/.hermes/plugins
git clone https://github.com/ZoniBoy00/byte-memory-core.git
hermes plugins enable byte-memory-core
```

Restart Hermes or start a new session. Verify with `bmc_status`.

---

## Tools

### `bmc_store` — Store facts

Save one or more facts to a specific tier:

```json
{
  "facts": [
    "Use FTS5 with n-gram fallback for resilient search",
    "Prefer episodic tier for long-term project knowledge"
  ],
  "tier": "episodic",
  "source": "architecture-decision",
  "importance": 0.85
}
```

### `bmc_search` — Find facts

Hybrid search across tiers — finds results even with typos:

```json
{
  "query": "ft5 ngrm fallback",
  "tiers": ["episodic"],
  "limit": 5
}
```

Returns ranked results with scores. The n-gram TF-IDF fallback activates when FTS5 returns no matches.

### `bmc_remember` — Quick save

Single-line save to Working tier for rapid context capture:

```json
{
  "fact": "The deployment config was moved to /etc/hermes/",
  "source": "conversation"
}
```

### `bmc_forget` — Delete

```json
{"fact_id": 42}
```

### `bmc_tier_move` — Promote / demote

```json
{
  "fact_ids": [1, 2, 3],
  "target_tier": "episodic"
}
```

### `bmc_status` — Dashboard

Returns counts per tier, average importance, recent entries, database size.

### `bmc_reindex` — Rebuild

Rebuilds the FTS5 index. Run after bulk imports.

---

## Example Workflows

### Capture and promote project knowledge

```
# During project work:
bmc_remember("Switched from REST to WebSocket for real-time feed")

# After confirming it's important:
# Use bmc_search to find the fact ID, then:
bmc_tier_move({"fact_ids": [42], "target_tier": "episodic"})
```

### Find context across sessions

```
# Next day, different session:
bmc_search("webscoket reel-tim")
# → Still finds "WebSocket for real-time feed" via n-gram matching
```

### Quick context handoff

```
# Before switching tasks:
bmc_remember("Mid-way through authentication refactor — SessionManager needs token refresh logic")

# Later:
bmc_search({"query": "where was I with auth", "tiers": ["working", "scratchpad"]})
```

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│              Hermes Agent                         │
│  ┌───────────────────────────────────────────┐   │
│  │          byte-memory-core plugin            │   │
│  │  ┌──────┐  ┌──────────┐  ┌────────────┐   │   │
│  │  │Work. │  │ Episodic │  │ Scratchpad  │   │   │
│  │  └──┬───┘  └────┬─────┘  └──────┬──────┘   │   │
│  │     └─────┬─────┴──────┬────────┘           │   │
│  │           │  SQLite + FTS5 + numpy          │   │
│  └───────────┴─────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

### Scoring

```
score =  0.35 × FTS5/TF-IDF relevance
        + 0.25 × recency (age decay)
        + 0.15 × tier weight
        + 0.10 × access frequency
        + 0.15 × manual importance
```

### Dependencies

- **Python 3.11+** (stdlib: sqlite3, json, re, math)
- **numpy** — lightweight TF-IDF cosine similarity

---

## Tests

```bash
python3 -m pytest tests/ -v
```

45 tests covering tokenization, scoring, store, manage, and full integration.

---

## License

MIT — free to use, modify, and share.

*Built for Hermes Agent. Part of the Byte AI assistant ecosystem.*
