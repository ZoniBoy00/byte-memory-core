# Roadmap — byte-memory-core

Goals and plans for upcoming versions. Listed by priority — top to bottom.

## v2.2.0 — Auto-promote & deduplicate ✅

- [x] **Auto-promotion** — when a Working fact is frequently accessed (access_count > 3), automatically promote it to Episodic tier. Prevents accidental loss of important context. (Implemented in `_auto_promote`, called during store + maint)
- [x] **Deduplication** — before storing a fact, check FTS5 for an existing match using TF-IDF. If a high-similarity fact exists (>80% score), update its access_count and importance instead of creating a duplicate. (Implemented in `_find_similar`)
- [x] **Auto-reindex** — `bmc-maintain` cron triggers FTS5 reindex weekly via `.last_reindex` marker file. Prevents silent performance degradation on large databases.
- [x] **Bulk store optimisation** — FTS5 rows are now inserted via `executemany` batch instead of one at a time.

## v2.3.0 — Tags & metadata

- [x] **Tags** — optional `tags` field per fact, e.g. `["project", "fix", "config"]`
- [x] **Tag-filtered search** — `bmc_search` supports a `tags` filter parameter
- [x] **Metadata dict** — a free-form `metadata` field for extra context (project name, conversation ID, etc.)

## v2.4.0 — Export / Import ✅

- [x] **`bmc_export`** — export facts as versioned JSON, filterable by tier / tags / content query. (Implemented in `_handle_export`)
- [x] **`bmc_import`** — validate JSON exports and deduplicate facts during import. (Implemented in `_handle_import`)
- [x] **Automated backup** — `bmc-maintain` writes an atomic daily export to `~/.hermes/backups/bmc/` and retains 14 days. (Implemented in `_write_daily_backup`)

## v2.5.0 — O2B archival (in progress)

Archival bridge from BMC → open-second-brain vault. Facts must meet **all three criteria** to qualify: Episodic tier, access_count > 5, and a `source` tag marked for permanence.

- [x] **Three-criteria candidate filter** — `bmc.archive.find_archivable_facts` returns only Episodic facts with `access_count > 5` and a permanent source marker (`learning`, `architecture`, `permanent`, `decision`). It also accepts `source:<marker>` tags and supports configurable importance, age, and result limits. No files or facts are modified.
- [ ] **Archive action and source-tag → o2b directory mapping** — write approved candidates to configurable `/Brain/Architecture/`, `/Brain/Learnings/`, etc. with an explicit apply action.
- [ ] **Dedup before archive write** — before writing a new learning to o2b, search for existing content on the same topic. If a match is found, update it (bump timestamp, merge wording) instead of creating a duplicate. Prevents the vault from filling with 15 versions of the same insight.
- [ ] **Archive reference link** — before deletion, the fact keeps a reference like `"archived_to": "o2b://path/to/file.md"`
- [x] **Configurable threshold** — `config.py` exposes `O2B_ARCHIVE_MIN_IMPORTANCE` and `O2B_ARCHIVE_MAX_AGE_DAYS`; both can be overridden with environment variables.

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
