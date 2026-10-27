# Task 4 report

Status: implemented and verified.

## Changes

- Added `reconcile_relationships(db, db_id, raw_schema)` with added/unchanged/changed/missing counts. Qualified endpoint IDs and all ordered column pairs determine identity; constraint names are scoped evidence.
- Routed initial acquisition, re-enrichment, live FK additions, and no-column-drift sync through reconciliation. Composite FKs remain single relationships.
- Human approval/disable state, reviewer/timestamp, manually approved pairs, and rejected candidate fingerprints survive acquisition. Changed FKs become copy-on-write proposals; disappearance invalidates serving links and marks connected publications needs_review with sync-log impact IDs. Reappearance does not reactivate invalidated or disabled links.
- New physical FKs remain trusted where no connected published route could change. Connected publications force pending FK candidates. Duplicate rejected/pending candidates stay unchanged.
- Renames preserve table, column, relationship IDs and ordered pairs. Key type changes require review. Dropped endpoint metadata is retained as deprecated tombstones to prevent cascading relationship/audit-history deletion. Missing runtime columns invalidate both FK and manual links.
- Reused the Task 2 database graph lock and compare-and-swap revision claim. Acquisition locks before metadata mutation; sync invalidation expires stale reviewer revisions.
- Source snapshots refresh together with relationship changes. No-column-drift logs now include FK-only changes (the existing column fingerprint omits FKs).
- Live acquisition fails if a listed table cannot be introspected, and empty snapshots cannot authorize destructive removals. No customer-data queries added.

## Verification

- New tests initially failed collection because the reconciler did not exist; subsequent focused tests exposed unnamed-FK change handling and were fixed.
- `python -m pytest tests/test_services/test_relationship_sync.py tests/test_services/test_semantic_service.py tests/test_services/test_schema_self_healing.py tests/test_services/test_export_service.py tests/test_api/test_sync_routes.py tests/test_integration/test_canonical_flow.py tests/test_services/test_live_db_service.py -q --tb=short`: **109 passed**.
- `python -m pytest tests/test_migrations/test_relationship_review.py tests/test_services/test_relationship_review.py tests/test_services/test_relationship_publication_lock.py -q --tb=short`: **21 passed**, including preserved active-FK migration coverage.
- Ruff check and format check: all nine changed Python files clean. `git diff --check`: clean.
- Coverage includes repeat snapshots, composite mappings, same constraint name across namespaces, approved/disabled actor/time preservation, changed/rejected proposals, publication candidates, disconnected publications, missing FK/manual endpoints, column/table rename, type change, stale reviewer revision, legacy null namespaces, source refresh, export exclusion, and incomplete acquisition.

## Limits and risks

- Existing `semantic_tables` uniqueness is `(db_id, table_name)`, so the wider application still cannot store identical table names in multiple namespaces. This task avoids a schema migration; same-constraint-name coverage uses distinct table names in two namespaces. Relationship reconciliation itself uses qualified identities.
- Empty acquisition is intentionally rejected/ignored rather than treating a completely empty target as authoritative deletion. A separate explicit authoritative-empty mechanism would be needed to support that operation safely.
- Rename recognition retains the existing heuristic drift detector; no new physical rename provenance is available from Inspector.
- No real customer database or PostgreSQL concurrency process test was run. SQLite regression tests plus existing publication-lock tests cover transaction/revision behavior.
- No migration needed, no dependencies added, and `.ai-log` untouched.


## Review follow-up: physical identity, absent endpoints, and rename SQL

Addressed all three Task 4 review findings:

1. Persist a separate physical-FK fingerprint in detection evidence and compare it before serving pairs. Copy-on-write promotion carries the original physical evidence forward, while FK candidates replace it with their new evidence. An unchanged physical FK therefore preserves different human-approved pairs, reviewer/time, status, and validation.
2. Relationship validation checks endpoint tables and selected columns against the refreshed connected source snapshot. Retained tombstone metadata remains readable in review history, but absent tables/columns return structured `ABSENT_TABLE`/`ABSENT_COLUMN` errors and cannot be approved or proposed as live links. Legacy databases without a connected source snapshot retain the existing metadata validation behavior.
3. Sync regenerates stored ON expressions from the current serving endpoint IDs and ordered column IDs using SQL AST quoting. Both column and table renames update exported/stored SQL, including manually edited pairs, without changing human decisions.

Verification:

- Added focused regressions first: different human pairs, both rename expressions, and dropped-table approval all reproduced the reported failures (**4 failed, 15 passed**).
- After fixes, focused sync/healing/review suite: **34 passed**.
- Added end-to-end copy-on-write human-promotion identity preservation and retained dropped-column rejection/history tests.
- Expanded sync/semantic/self-healing/export/live-db/API/canonical-flow/relationship-review/publication-lock suite: **182 passed**.
- Ruff check and format check clean for all five modified Python files; `git diff --check` clean.

No migration or dependency added. No real customer database or real PostgreSQL concurrency process tested; `.ai-log` untouched.
