# Roadmap — byte-memory-core

Goals and plans for upcoming versions. Listed by priority — top to bottom.

## v2.2.0 — Auto-promote & deduplicate

- [ ] **Auto-promotion** — when a Working fact is frequently accessed (access_count > 3), automatically promote it to Episodic tier before the 24h TTL expires. Prevents accidental loss of important context.
- [ ] **Deduplication** — before storing a fact, check FTS5 for an existing match. If a high-similarity fact exists (>80% TF-IDF score), update its access_count and importance instead of creating a duplicate.
- [ ] **Auto-reindex** — `bmc-maintain` cron triggers `bmc_reindex` weekly to keep the FTS5 index healthy. Prevents silent performance degradation on large databases.
- [ ] **Bulk store optimisation** — batch-insert FTS5 rows (currently inserts one at a time).

## v2.3.0 — Tags & metadata

- [ ] **Tags** — optional `tags` field per fact, e.g. `["project", "fix", "config"]`
- [ ] **Tag-filtered search** — `bmc_search` supports a `tags` filter parameter
- [ ] **Metadata dict** — a free-form `metadata` field for extra context (project name, conversation ID, etc.)

## v2.4.0 — Export / Import

- [ ] **`bmc_export`** — export facts as JSON, filterable by tier / tag / query
- [ ] **`bmc_import`** — import facts from JSON, with dedup check during import
- [ ] **Automated backup** — integrated into `bmc-maintain` script: daily export to `~/.hermes/backups/bmc/`

## v2.5.0 — O2B archival

- [ ] **Automatic archival** — old Episodic facts (>30d) are written to the o2b vault as Markdown files, then removed from BMC
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
