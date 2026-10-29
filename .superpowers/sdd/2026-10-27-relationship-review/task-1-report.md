# Task 1 Report — Relationship Review Persistence

## Result

Implemented the persistence foundation in `AI-Semantic-Layer-` without changing the serving relationship rows or editing design/plan documents.

## Changes

- Added `RelationshipCandidateModel` in `src/models/db_relationships.py` and registered it through `src/models/db.py`, making the table available to app metadata and Alembic.
- Kept review candidates separate from `canonical_relationships`. The model follows the existing workflow contract for target relationship references, ordered column pairs, provenance, status, unique per-connection fingerprints, evidence, confidence, unresolved questions, actor timestamps, and revision.
- Added canonical review metadata with the existing workflow defaults and constraints. Existing canonical IDs and serving fields remain unchanged.
- Added Alembic revision `relreview20261027`, parented to the target checkout's verified former head `c02b7c2cd880`. The migration creates candidate constraints/indexes and the canonical reviewer FK. Its downgrade removes only the candidate table and added review metadata.
- Added model and SQLite migration coverage, including a legacy canonical row round trip.

## TDD and verification

- **RED:** Before implementation, the candidate-model test failed because `RelationshipCandidateModel` was absent, and the migration test failed because no relationship-review revision existed. Source-contract tests also exposed missing `target_relationship_id` and confidence-range enforcement.
- **GREEN:** Final focused model, migration, and revision-graph run: **52 passed** (`-p no:cacheprovider`).
- `python -m alembic heads`: one head, `relreview20261027`; history confirms `c02b7c2cd880 -> relreview20261027`.
- Ruff check passed; Ruff format check passed; `git diff --check` passed.
- A full-suite run completed with **1721 passed, 18 failed**. Failures were outside the relationship persistence tests, in metric proposal/workflow, chat deduplication, and LLM-settings tests. This run preceded the final source-contract alignment; the final focused suite passed after that alignment.

## Commit

Requested subject: `feat: add relationship review persistence`.
