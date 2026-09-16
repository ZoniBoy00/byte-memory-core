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

### `bmc_export` — Export facts

Create a versioned JSON export, optionally filtered by tier, tags, or content query:

```json
{
  "tier": "episodic",
  "tags": ["project"],
  "query": "backup"
}
```

The export deliberately omits internal database IDs so it can be restored safely into another BMC database.

### `bmc_import` — Import facts

Import the JSON string or object returned by `bmc_export`. Facts are validated and deduplicated before insertion:

```json
{
  "payload": "<bmc_export JSON>"
}
```

The result reports `imported`, `deduplicated`, and `errors` counts.

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

### `bmc_archive` — Archive to O2B

Preview eligible Episodic facts before writing them to an Open Second Brain vault. Eligibility requires `access_count > 5` and a permanent source (`learning`, `architecture`, `permanent`, or `decision`). Preview is the default:

```json
{"limit": 25}
```

Set `apply: true` to write Markdown files below `Brain/Architecture/`, `Brain/Decisions/`, `Brain/Learnings/`, or `Brain/Permanent/`. The action is non-destructive: BMC facts remain stored and receive an `archived_to` metadata reference. Configure the default vault with `O2B_VAULT`; `O2B_ARCHIVE_MIN_IMPORTANCE` and `O2B_ARCHIVE_MAX_AGE_DAYS` provide optional safety thresholds.

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

## Changelog

### v2.5.0 — O2B archival (September 2026)
- **`bmc_archive`** — Safe preview/apply archival of eligible Episodic facts to an O2B Markdown vault.
- **Three safety criteria** — Requires `access_count > 5` and a permanent source marker; configurable importance and age thresholds are available.
- **Source organization** — Writes to source-specific Brain directories and atomically updates files.
- **Deduplication and references** — Updates similar same-source documents and preserves `o2b://` references in both Markdown frontmatter and BMC metadata.
- **Non-destructive** — Archive runs never delete the original BMC fact.

### v2.4.0 — Export / Import (August 2026)
- **`bmc_export`** — Versioned JSON exports with tier, tag, and content filters.
- **`bmc_import`** — Validated imports with content deduplication and restore statistics.
- **Automated backups** — `bmc-maintain` writes an atomic daily backup to `~/.hermes/backups/bmc/` and retains the latest 14 days.

### v2.3.0 — Tags & metadata (July 2026)
- **Tags** — Optional `tags` field per fact (JSON array), e.g. `["project:gzw-tools", "fix", "config"]`
- **Tag-filtered search** — `bmc_search` accepts a `tags` filter parameter for targeted queries
- **Metadata dict** — Free-form `metadata` field per fact for extra context (project name, session ID, model used, etc.)
- **Backward compatible** — Existing facts get empty defaults; all tools continue to work unchanged
- **DB migration** — Auto-adds `tags` column if upgrading from v2.2.0

### v2.2.0 — Auto-promote & deduplicate (July 2026)
- **Auto-promotion** — Working facts with `access_count > 3` are automatically promoted to Episodic tier, preventing loss of important context before TTL expiry
- **Deduplication** — Before storing a new fact, checks FTS5 + TF-IDF for existing matches. If similarity >80%, updates access_count and importance instead of creating a duplicate
- **Auto-reindex** — Weekly FTS5 index rebuild via `bmc-maintain` cron, triggered by `.last_reindex` marker file
- **Bulk store optimisation** — FTS5 rows use batch `executemany` instead of one-at-a-time inserts

### v2.1.0 — Tier moves & local search (July 2026)
- `bmc_tier_move` tool for manual promote/demote between tiers
- Multi-source search (BMC + o2b + Honcho)
- Hybrid FTS5 + TF-IDF ranking with importance scoring

### v2.0.0 — Initial BEAM release
- Three-tier memory: Working, Episodic, Scratchpad
- FTS5 full-text search with n-gram TF-IDF fallback
- Auto-pruning, WAL journaling, importance scoring

---

## Tests

```bash
python3 -m pytest tests/ -v
```

49 tests covering tokenization, scoring, store, manage, export/import, and full integration.

---

## License

MIT — free to use, modify, and share.

*Built for Hermes Agent. Part of the Byte AI assistant ecosystem.*
