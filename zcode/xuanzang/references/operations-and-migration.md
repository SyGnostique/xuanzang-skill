# Operations, collaboration, and migration

Use this reference for long documents, large corpora, retries, team review, services, upgrades, and recovery.

## Contents

- [Idempotent operations](#idempotent-operations)
- [Restore controls](#restore-controls)
- [Batch and resource control](#batch-and-resource-control)
- [Team and multi-tenant review](#team-and-multi-tenant-review)
- [Security and retention](#security-and-retention)
- [v1 migration](#v1-migration)
- [Book M1 migration](#book-m1-migration)
- [Recovery and rollback](#recovery-and-rollback)

## Idempotent operations

Derive a run fingerprint from source hash, package/pipeline version, policy, adapter versions/configuration, language, render settings, and document kind.

- Reuse a completed identical run.
- Use `--resume` to request continuation without rewriting committed evidence. Verify the observed granularity in run events; if the installed runtime only reuses a complete run or restarts extraction, report that limitation instead of claiming page/stage checkpoint recovery.
- Stage writes in a temporary directory and commit atomically.
- Record committed restore/reuse/head-switch, failed-run, review, migration, and lifecycle events. Gate and export reports carry their own timestamps; no central event service exists.
- Retain failed-run evidence when useful for diagnosis; keep it outside the active projection.
- Create a new run when source or policy changes.
- Bind the new head so incompatible review projections cannot promote it. Downstream exports detect staleness through run/canonical/review revisions and the embedding invalidation key; the CLI does not run a stale-artifact scheduler.
- Preserve prior run directories and append-only history for audit. Decisions remain authoritative only for their bound source, run, and canonical revision.

Manual review files are protected state. Projection or resume may refresh generated active views while preserving append-only decisions.

## Restore controls

Use the v2 surface explicitly:

```bash
xuanzang restore SOURCE --out PACKAGE \
  --target review \
  --ocr auto \
  --lang zh \
  --document-kind auto \
  --render-dpi 200 \
  --max-pages 10000 \
  --max-total-pixels 10000000000 \
  --max-source-bytes 21474836480 \
  --privacy local_only \
  --rights-basis user_supplied_private \
  --retention-policy workspace_default \
  --access-tag project:example \
  --transcription source \
  --resume
```

Operational options and consequences:

| Option | Contract |
| --- | --- |
| `--target hint|review|citation` | Selects the gate evaluated at restore completion. `status` defaults to citation and reports `evaluated_target`; pass `--target hint` or `--target review` explicitly for those tiers. |
| `--ocr auto|none|paddle|tesseract|mock|sidecar|plugin:NAME` | Explicit adapter selection; `--ocr sidecar` requires `--sidecar FILE`. |
| `--force-ocr` | Runs OCR comparison even when native text appears usable. |
| `--document-kind auto|book|paper|report|article|manuscript|archive|image_sequence` | Records routing/profile intent; it does not waive object or structure review. |
| `--render-dpi 72..600` | Binds page renders, coordinates, image hashes, and run identity. |
| `--max-pages`, `--max-total-pixels`, `--max-source-bytes` | Positive hard limits checked before/during restore; exceeding them stops the run. |
| `--transcription source|diplomatic|normalized|both` | Records text policy. Source/diplomatic preserve source form; normalization remains an explicit variant/review obligation. |
| `--privacy local_only|workspace|tenant` | `workspace` requires `--workspace-id`; `tenant` requires `--tenant-id`. |
| `--access-tag TAG` | Repeatable metadata for downstream authorization; the core CLI does not enforce retrieval ACLs. |
| `--preserve-source` | Copies a file source into the immutable run; still respect copyright/retention policy. |
| `--no-local-conversion` | Disables Calibre conversion for MOBI/AZW3. |
| `--allow-external-bundle-sources` | Explicit caller authority for bundle locators outside the manifest directory. |
| `--resume` | Reuses an identical committed run or a retry checkpoint where that extractor supports it. |
| `--new-run` | Creates an intentional new run ID for otherwise identical source/policy. |
| `--accept-source-update` | Allows changed source bytes to become a new source revision in the same package; old runs remain. |

The policy fingerprint binds all restore policy fields and sidecar bytes. Changing language, DPI, OCR, transcription, scope, rights, access tags, resource limits, or conversion policy can create a different run. Read `run_manifest.json` before claiming an operation reused prior work.

## Batch and resource control

The local v2 runtime exposes an incremental per-source batch path:

```bash
xuanzang batch SOURCE_DIR --out-root CORPUS_BUILD \
  --target hint --ocr auto --workers 4
```

It recursively selects supported files, creates an independent package per relative path, reuses package-level runs, appends `batch_results.jsonl`, and rewrites a current `batch_manifest.json`. Native-text PDFs in hint mode skip full-page rendering. `--fail-fast` cancels work that has not started and still drains/records every running or cancelled future. Use `--limit`, `--glob`, `--no-recursive`, and conservative `--workers` for canaries. Page-aligned sidecars require separate per-document restores; one shared `--sidecar` is rejected. A `plugin:NAME` adapter may use its own immutable per-document input configuration, but the CLI never treats an unrelated `--sidecar` as plugin provenance.

For a corpus:

1. inventory hashes, source families, duplicates, rights, formats, languages, and estimated difficulty;
2. select a stratified canary;
3. benchmark adapters and gates on the canary;
4. schedule per-source runs with bounded workers, timeouts, memory/GPU limits, retries, and stop conditions;
5. keep per-source packages and status;
6. aggregate progress without averaging away failures;
7. route blockers to review queues by impact and uncertainty;
8. expand only after canary acceptance.

Prefer local, staging, or offline compute for full-corpus OCR and regression. On shared or production systems, use bounded batches and explicit recovery plans. Cache page renders and content-addressed assets. Reuse existing trusted OCR through sidecar migration when the crosswalk validates.

Priority determines scheduling only. It cannot bypass restoration or semantic coverage for citation targets.

The core CLI enforces per-source page/pixel/byte ceilings and a local worker bound. Process memory, GPU quotas, per-job wall timeout, distributed cancellation, backpressure, and fair scheduling remain orchestrator controls. Test canaries locally or in staging before increasing them.

## Team and multi-tenant review

Every work item should carry:

```yaml
tenant_id: ...
workspace_id: ...
vector_namespace: ...  # orchestrator-assigned, not package authority
package_id: ...
expected_run_id: ...
target_id: ...
finding_codes: []
priority: ...
assignee: ...
reviewer_role: ...
lease_or_lock: ...
due_at: ...
```

Require optimistic concurrency: the review command rejects decisions against a stale review revision, source, active run, or canonical revision. Record reviewer ID/type, role, time, evidence, reason, and supersession. Keep conflicts visible until a named resolution decision supersedes them.

For `privacy=workspace`, always pass `--workspace-id` at restore and compare it with `--expected-workspace-id` on review, status, publish, and revoke. Compare tenant scope with `--expected-tenant-id` when present. Expected-scope flags fail closed on mismatch; they are not login, token verification, membership lookup, or role authorization.

```bash
# workspace-scoped package; add --expected-tenant-id only when tenant_id is also present
xuanzang status PACKAGE --expected-workspace-id WORKSPACE
xuanzang review PACKAGE --decisions DECISIONS --expected-revision REV --expected-workspace-id WORKSPACE
xuanzang publish PACKAGE --target citation --out OUTPUT --expected-workspace-id WORKSPACE

# tenant-scoped package
xuanzang status PACKAGE --expected-tenant-id TENANT
```

The service layer must authenticate the caller and construct a verified `ReviewerContext` before semantic review of workspace/tenant content. Apply authorization before opening source pixels/text, assigning review, calling providers, retrieving chunks, exporting, or revoking. Propagate scope metadata into every derivative.

For service/API integration, map operations to asynchronous jobs:

- `restore`: idempotency key = source hash + policy fingerprint;
- `status`: read-only package/run/gate summary;
- `review`: append decisions with expected revision;
- `publish`: hash-bound export from the current active revision. The filesystem destination can be overwritten later, so consumers verify the export manifest before ingestion.
- `revoke`: disable package use and emit an idempotent downstream tombstone.

Return run/job ID immediately for long work. Stream stage events separately from durable state. A disconnected client must be able to resume status polling without restarting work.

## Security and retention

- Keep copyrighted/private sources, page images, extracted text, translations, provider responses, and packages outside public repositories.
- Read secrets only from environment or managed secret storage; never echo values.
- Require explicit authorization before remote OCR/VLM/translation calls.
- Record provider, endpoint class, model/version, region where relevant, and data-retention policy without recording credentials.
- Enforce tenant isolation, least privilege, encryption, audit logs, deletion/retention policy, and export authorization.
- Enforce vector namespace/row ACLs at both indexing and retrieval. The core package only carries `tenant_id`, `workspace_id`, `access_tags`, privacy, rights, and retention metadata.
- Quarantine unsafe archives, encrypted/DRM material, malformed files, and unknown active content before parsing.
- Use synthetic or public-domain fixtures for tests and examples.

Revoke a package with scope and revision guards:

```bash
xuanzang revoke PACKAGE \
  --reason "authorized deletion request" \
  --expected-revision REVIEW_REVISION \
  --expected-tenant-id TENANT \
  --expected-workspace-id WORKSPACE \
  --out /outside/package/revocation.json
```

`revoke` marks the package lifecycle `revoked`, lowers trust, records an event, and writes `audit/revocation_tombstone.json`; repeated calls return the same tombstone. It does not erase source/run bytes, vectors, caches, exports, provider copies, or backups. The orchestrator must fan out the tombstone by `revocation_id`, delete or quarantine each derivative according to policy, collect per-system deletion acknowledgements, retry failures, and retain only the permitted audit record. A tombstone without those acknowledgements is a pending deletion workflow, not a deletion receipt.

## v1 migration

Run:

```bash
xuanzang migrate-v1 OLD_PACKAGE --source ORIGINAL_SOURCE --out NEW_PACKAGE
```

The current migration:

1. verifies source identity from explicit `--source`; a valid legacy-declared hash without the source remains `legacy_source_identity_unverified`, and a malformed identity is rejected;
2. preserves a no-follow, quota-bounded v1 snapshot inside the committed run and exposes an integrity-bound hard-linked compatibility view;
3. creates package version 2 in a separate non-overlapping path;
4. crosswalks surfaces, source blocks, and image occurrences;
5. imports raw text and old OCR as evidence variants;
6. records file accounting, status downgrades, blockers, and the implemented ID crosswalk;
7. retains chapters, TOC, audits, translation runs, and other legacy files in the snapshot only; they are not semantically converted or trusted;
8. sets trust to `needs_review` until v2 gates and semantic paragraph coverage pass;
9. writes `audit/migration_report.json` and `audit/migration_id_crosswalk.jsonl`;
10. recomputes gates from v2 evidence.

Never inherit v1 `PASS_STRICT`, mock translation PASS, score summaries, or hand-edited chapter files as v2 citation proof.
Migration creates an empty v2 review ledger. Legacy manual notes or decisions remain forensic snapshot material until re-entered through the current review contract.

## Book M1 migration

Run:

```bash
xuanzang migrate-book-m1 OCR_ROOT \
  --source SOURCE_PDF \
  --book-id BOOK_ID \
  --out NEW_PACKAGE
```

Use the existing page images, Paddle line-level bboxes/confidence, Tesseract comparisons, low-confidence flags, and legacy boundary proposals. Avoid re-OCR when hashes and page crosswalks validate. All page-image and Tesseract locators must remain within `OCR_ROOT`; conflicting duplicate page records are rejected. Add `--copy-assets` when the v2 run must own content-addressed page-image copies.

The current importer verifies or records:

- source PDF and Book M1 identity;
- expected page count and one-to-one page-image mapping;
- OCR-root path containment and image hashes;
- basic bbox shape plus Paddle/Tesseract evidence variants;
- low-confidence flags, missing/extra pages, and zero OCR reruns;
- legacy TOC/chapter material as unverified candidates.

It does not infer table/figure relations, promote old manual provenance, or semantically map final paragraph coverage. Those remain v2 restoration/review work.

Book M1 OCR quality and historical audits accelerate v2 restoration. Citation trust still requires v2 source-span reversibility, structure review, full semantic paragraph coverage, asset occurrence review, source-use boundary, and a fresh strict gate.

## Recovery and rollback

On failure:

1. stop new work for the affected package or adapter;
2. preserve active manifest, run directories, decisions, events, and failure evidence;
3. verify source and package hashes;
4. identify the last committed run and export;
5. isolate partial staging output;
6. repair or rerun only the failed stage/configuration;
7. recompute gates;
8. activate the repaired revision explicitly;
9. retain the prior revision for rollback;
10. record the incident and regression fixture.

Never recover by deleting the package or copying an old pass file over a new gate report.
