# Roadmap — byte-memory-core

Goals and plans for upcoming versions. Listed by priority — top to bottom.

## v2.2.0 — Auto-promote & deduplicate ✅

- [x] **Auto-promotion** — when a Working fact is frequently accessed (access_count > 3), automatically promote it to Episodic tier. Prevents accidental loss of important context. (Implemented in `_auto_promote`, called during store + maint)
- [x] **Deduplication** — before storing a fact, check FTS5 for an existing match using TF-IDF. If a high-similarity fact exists (>80% score), update its access_count and importance instead of creating a duplicate. (Implemented in `_find_similar`)
- [x] **Auto-reindex** — `bmc-maintain` cron triggers FTS5 reindex weekly via `.last_reindex` marker file. Prevents silent performance degradation on large databases.
- [x] **Bulk store optimisation** — FTS5 rows are now inserted via `executemany` batch instead of one at a time.

## v2.3.0 — Tags & metadata

- [ ] **Tags** — optional `tags` field per fact, e.g. `["project", "fix", "config"]`
- [ ] **Tag-filtered search** — `bmc_search` supports a `tags` filter parameter
- [ ] **Metadata dict** — a free-form `metadata` field for extra context (project name, conversation ID, etc.)

## v2.4.0 — Export / Import

- [ ] **`bmc_export`** — export facts as JSON, filterable by tier / tag / query
- [ ] **`bmc_import`** — import facts from JSON, with dedup check during import
- [ ] **Automated backup** — integrated into `bmc-maintain` script: daily export to `~/.hermes/backups/bmc/`

## v2.5.0 — O2B archival

Archival bridge from BMC → open-second-brain vault. Facts must meet **all three criteria** to qualify: Episodic tier, access_count > 5, and a `source` tag marked for permanence.

- [ ] **Three-criteria archiving filter** — a fact is archived only when: (a) it is in the Episodic tier, (b) it has been re-accessed at least 5 times (access_count > 5), and (c) its `source` is one of the permanent markers (`learning`, `architecture`, `permanent`, `decision`). Prevents one-off high-importance noise from polluting the long-term archive.
- [ ] **Source-tag → o2b directory mapping** — `source=architecture` writes to `/Brain/Architecture/`, `source=learning` to `/Brain/Learnings/`, etc. Configurable mapping in plugin config, so the o2b vault stays organised without guesswork.
- [ ] **Dedup before archive write** — before writing a new learning to o2b, search for existing content on the same topic. If a match is found, update it (bump timestamp, merge wording) instead of creating a duplicate. Prevents the vault from filling with 15 versions of the same insight.
- [ ] **Archive reference link** — before deletion, the fact keeps a reference like `"archived_to": "o2b://path/to/file.md"`
- [ ] **Configurable threshold** — `config.py` gets min-importance and max-age settings for archival

## v2.6.0 — User experience

- [ ] **`bmc_notify`** — cron alert: "You have 5 facts expiring today" before auto-prune runs
- [ ] **Grouped results** — `bmc_search` returns results grouped by tier
- [ ] **Score breakdown** — each result includes a component breakdown (FTS5 share, recency, tier weight, etc.)

## Infrastructure

- [ ] **CI tests on GitHub Actions** — all 45 tests run on every push
- [ ] **Type stubs** — `.pyi` files for all modules
- [ ] **Benchmark** — test that measures search speed and memory usage

---

*Suggestions and PRs welcome.*
