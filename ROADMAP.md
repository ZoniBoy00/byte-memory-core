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

## v2.5.0 — O2B archival (complete)

Safe archival bridge from BMC → open-second-brain vault. Facts qualify only when they are Episodic, have `access_count > 5`, and use a permanent source marker.

- [x] **Three-criteria candidate filter** — strict Episodic, access-count, and permanent-source checks; malformed tags are ignored safely.
- [x] **Source-tag → O2B directory mapping** — `architecture`, `decision`, `learning`, and `permanent` map to `Brain/Architecture`, `Brain/Decisions`, `Brain/Learnings`, and `Brain/Permanent`.
- [x] **Dry-run/apply action** — `bmc_archive` previews by default; `apply=true` is required before any Markdown or database write.
- [x] **Dedup before archive write** — same-source Markdown documents are matched using normalized content and token similarity; existing documents are updated instead of duplicated.
- [x] **Archive reference link** — applied facts retain `metadata.archived_to` and `metadata.archived_at`, while the Markdown frontmatter contains the same `o2b://` reference.
- [x] **Configurable threshold** — `O2B_ARCHIVE_MIN_IMPORTANCE`, `O2B_ARCHIVE_MAX_AGE_DAYS`, and `O2B_VAULT` are configurable environment settings; per-call overrides are supported.
- [x] **Non-destructive by design** — BMC facts are never deleted by the archive action, so references remain recoverable and repeated runs are idempotent.

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
