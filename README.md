# Byte Memory Core — BEAM-tiered local memory for Hermes

> **Local vector-indexed memory with Working/Episodic/Scratchpad tiers.**  
> Semantic-lite search (FTS5 + char n-gram TF-IDF), importance scoring, and auto-archival.  
> Integrates with o2b or any Hermes knowledge vault.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Agent](https://img.shields.io/badge/Hermes%20Agent-plugin-0891b2)](https://hermes-agent.nousresearch.com/)

---

## 🧠 What It Is

`byte-memory-core` adds a **local, persistent, tiered memory** to Hermes Agent. It stores facts in SQLite with FTS5 indexing, scores them by relevance + recency + importance, and automatically prunes old low-value data. No cloud, no vector database, no GPU needed.

### BEAM Memory Tiers

| Tier | Weight | TTL | Cap | Use Case |
|------|--------|-----|-----|----------|
| **Working** 🔄 | 3× | 24h | 500 facts | Recent conversation context, temporary notes |
| **Episodic** 📚 | 2× | 30 days | 2000 facts | Important learnings, decisions, preferences |
| **Scratchpad** 📝 | 1× | — | 300 facts | In-progress thoughts, follow-ups, half-baked ideas |

Tiers are **scored differently** — Working favours recency, Episodic favours importance, Scratchpad is lightweight storage. Facts auto-prune when they exceed tier caps (oldest+lowest-score removed first).

### Search That Actually Works

Hybrid search combining **three signals**:

1. **FTS5 (SQLite full-text search)** — fast keyword matching with BM25 ranking
2. **Char n-gram TF-IDF** — catches typos, partial matches, and related terms without an ML model
3. **Recency + frequency** — facts you've accessed recently or often rank higher

Results are blended into a single score (0–1) and sorted by relevance.

---

## 📦 Installation

### 1. Clone into Hermes plugins

```bash
cd ~/.hermes/plugins
git clone https://github.com/ZoniBoy00/byte-memory-core.git
```

### 2. Enable the plugin

```bash
hermes plugins enable byte-memory-core
```

Restart Hermes or start a new session.

### 3. Verify it's working

```
bmc_status
```

You should see empty tiers, ready to fill.

---

## 🛠️ Tools

### `bmc_store` — Store facts

```json
{
  "facts": [
    "QBox-resurssit kannattaa tarkistaa GitHubista, luottaa vanhoihin listoihin",
    "time-gap plugin lisää aikatietoisuuden Hermekseen"
  ],
  "tier": "episodic",
  "source": "task-reflection",
  "importance": 0.85
}
```

### `bmc_search` — Find facts

```json
{
  "query": "QBox resources outdated lists",
  "tiers": ["working", "episodic"],
  "limit": 5
}
```

Returns ranked results with scores, tier, and access stats.

### `bmc_remember` — Quick save

```json
{
  "fact": "Tarkista QBox-resurssit GitHubista ennen luottamista",
  "source": "conversation"
}
```

Saves to Working tier with one line.

### `bmc_forget` — Delete a fact

```json
{"fact_id": 42}
```

### `bmc_tier_move` — Promote or demote

```json
{
  "fact_ids": [1, 2, 3],
  "target_tier": "episodic"
}
```

Great for promoting working → episodic after you confirm a finding.

### `bmc_status` — Memory dashboard

No arguments. Returns counts per tier, average importance, recent facts, DB size.

### `bmc_reindex` — Rebuild search index

Run after bulk imports or if search seems off.

---

## 🔧 Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Hermes Agent                       │
│  ┌──────────────────────────────────────────────┐   │
│  │         byte-memory-core plugin               │   │
│  │                                              │   │
│  │  ┌─────────┐  ┌─────────┐  ┌────────────┐   │   │
│  │  │ Working  │  │Episodic │  │ Scratchpad  │   │   │
│  │  │ (24h)    │  │(30d)    │  │ (notes)     │   │   │
│  │  └────┬─────┘  └────┬────┘  └──────┬─────┘   │   │
│  │       │              │              │          │   │
│  │  ┌────┴──────────────┴──────────────┴────┐     │   │
│  │  │      SQLite + FTS5 + numpy TF-IDF      │     │   │
│  │  └───────────────────┬────────────────────┘     │   │
│  └──────────────────────┼──────────────────────────┘   │
│                         │                              │
│              ┌──────────▼──────────┐                   │
│              │   o2b Brain vault   │                   │
│              │  (persistent store)  │                   │
│              └─────────────────────┘                   │
└─────────────────────────────────────────────────────┘
```

### Scoring formula

```
score = 0.35 × FTS5_rank
      + 0.25 × recency
      + 0.15 × tier_weight
      + 0.10 × access_factor
      + 0.15 × importance
```

### Dependencies

- **Python 3.11+** (sqlite3 with FTS5)
- **numpy** — lightweight TF-IDF computation
- Zero external services, zero network required at inference time

---

## 🚀 Workflow Ideas

### Daily context retention
```
bmc_store(tier="working", facts=["vaihdoin 500W PSU:n -> 850W", "uus GPU tulossa tiistaina"])
→ Stays relevant for 24 hours, then drops off
```

### Project knowledge promotion
```
# After completing a task:
bmc_store(tier="episodic", facts=[learnings], source="task-X", importance=0.9)
→ Persists for 30 days, always scores high
```

### Quick todo / follow-up
```
bmc_remember("tarkista se homma mitä puhuttiin siitä pluginista")
→ Lands in scratchpad, won't clutter working/episodic
```

---

## 📄 License

MIT — free to use, modify, share. Attribution appreciated.

---

*Built for Hermes Agent. Part of the Byte AI assistant ecosystem.*
