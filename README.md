# 玄奘 xuanzang-skill 2.2

`xuanzang-skill` rebuilds source documents into source-faithful, noise-free, correctly chaptered Markdown with complete figures/tables, machine-readable JSONL, and reverse-locatable evidence. Its primary contract is an auditable chain from source bytes to surfaces, evidence blocks, canonical paragraphs, semantic and visual structure decisions, gates, revision-bound exports, and independent local acceptance.

Version 2.2 makes local-strict reconstruction the default agent workflow, reserves Markdown H1 for the book title and H2/H3 for source structure, adds an independent `verify-local-strict` command, and turns prior structural/OCR/media/publication failures into an explicit regression registry. It is not a public multi-tenant service; see [Known limitations](docs/known_limitations.md), [2.0 release notes](docs/release_notes_2.0.md), [2.1 release notes](docs/release_notes_2.1.md), and [2.2 release notes](docs/release_notes_2.2.md).

The recovered interaction scope, provenance limitation, retained requirements, and failure-family mapping are recorded in the [2.2 history audit](docs/xuanzang_2.2_history_audit.md).

## Trust model

The runtime keeps three concerns separate:

- extraction records what parsers and OCR engines observed;
- semantic review records human or semantic-agent decisions without rewriting raw evidence;
- gates derive `hint_only`, `needs_review`, or `citation_grade` from the current package and review head.

File presence, a previous score, fluent text, OCR confidence, or an old `PASS_STRICT` cannot promote a package. `xuanzang status` recomputes the citation gate from current evidence each time and reports `evaluated_target: citation`; use `--target hint` or `--target review` for an explicitly scoped operational check.

## Safety

Do not commit copyrighted books, private papers, extracted source text, page images, translated books, raw provider responses, generated evidence packages, or API keys. Use synthetic or public-domain fixtures in tests.

Remote OCR, VLM, translation, or model calls require separate user authorization and provider-retention review. The built-in `auto`, Paddle, Tesseract, mock, and sidecar paths are local interfaces; a sidecar remains evidence that must pass anchor and provenance review.

## Install

Python 3.11 or later is recommended.

```bash
python -m pip install -e .
xuanzang --version
xuanzang --help
```

PDF support uses PyMuPDF. Image inputs use Pillow. OCR engines are optional and selected only when installed or explicitly configured. MOBI/AZW3 conversion requires a local `ebook-convert` executable.

## Core workflow: restore → status → review → publish → verify-local-strict

### 1. Restore

Create a version-2 evidence package. This example keeps source material local and requests a review-ready extraction:

```bash
xuanzang restore path/to/source.pdf \
  --out packages/source \
  --target review \
  --ocr auto \
  --privacy local_only \
  --rights-basis user_supplied_private \
  --retention-policy workspace_default
```

Supported inputs are PDF, EPUB, DOCX, TXT, Markdown, HTML, common raster images and image directories, MOBI/AZW3 through local conversion, and JSON/YAML source-bundle manifests. Use `--max-pages`, `--max-total-pixels`, and `--max-source-bytes` to lower resource ceilings for untrusted or unusually large inputs.

### Semantic and visual structure review

For dirty, scanned, multi-column, image-heavy, or structurally ambiguous books, extracted candidates are evidence inputs rather than an automatic final structure. Follow the ordered protocol in [`skills/xuanzang/assets/prompt_templates/README.md`](skills/xuanzang/assets/prompt_templates/README.md): whole-book architecture, visual TOC discovery and transcription, canonical TOC, hierarchy/materialization adjudication, candidate assessment, exact boundaries, media affiliation, exhaustive section audit, independent reverse audit, and evidence-bounded revision.

Use a vision-capable model when printed layout, typography, multi-column order, page imagery, or media affiliation affects the decision. Every accepted structure must still be submitted through revision-bound v2 `structure` review decisions and pass the current citation gate. Prompt output, confidence, or a numeric score has no independent trust authority.

The protocol covers monographs, edited collections, lectures, interviews, catalogues, bilingual books, critical editions, notes/index-heavy books, Chinese scans, dirty EPUBs, and sources without a reliable printed TOC.

Useful restore variants:

```bash
# Use a page-aligned OCR/VLM sidecar. Citation use still requires anchor review.
xuanzang restore scan.pdf --out packages/scan \
  --ocr sidecar --sidecar scan.ocr.jsonl --target review

# Resume a failed run. Current page checkpoint reuse is implemented for PDF extraction.
xuanzang restore scan.pdf --out packages/scan \
  --ocr sidecar --sidecar scan.ocr.jsonl --target review --resume

# Accept changed source bytes as a new source revision in the same active package.
xuanzang restore corrected.pdf --out packages/source \
  --target review --accept-source-update
```

Identical source plus policy normally reuses the deterministic run. `--new-run` requests another run identity. A changed source is rejected unless `--accept-source-update` is explicit. Raw run artifacts are retained under `runs/<run_id>/`; top-level ledgers project the active run.

For a large paper corpus, build independent hint packages incrementally instead of one monolithic bundle:

```bash
xuanzang batch path/to/papers \
  --out-root corpus-build \
  --target hint \
  --ocr auto \
  --workers 4
```

Born-digital PDF pages in `hint` mode use native text without rendering full-page PNGs; scanned pages still render for OCR. Each source receives its own package, lock, run history, failure state, and trust marker. Promote only selected sources by rerunning their package with `--target review` or `citation`, then complete ManualStrict. Keep OCR-heavy worker counts low enough for the host.

### 2. Status

```bash
xuanzang status packages/source
```

`status` recomputes the citation gate. A new extraction will normally report `needs_review` and `FAIL_REVIEW`; that is expected. Inspect the current blockers in:

```text
packages/source/audit/gates/citation.json
packages/source/audit/pass_fail_citation.json
```

The response includes `evaluated_target: citation`. To verify an operational tier without weakening the default citation check, request it explicitly:

```bash
xuanzang status packages/source --target hint
xuanzang status packages/source --target review
```

Typical blockers cover unresolved extraction findings, unreviewed surfaces, incomplete canonical source-span coverage, missing semantic paragraph coverage, assets or complex objects without decisions, unreviewed structure, missing source-use boundary, or invalid reviewer provenance.

### 3. Review

Review every in-scope paragraph or paragraph-equivalent block by semantic reading, then submit decisions as a JSON array or JSONL file:

```bash
xuanzang review packages/source \
  --decisions review/decisions.jsonl \
  --expected-revision 0
```

The append-only review ledger binds decisions to source SHA, active run, canonical revision, reviewer identity, and supersession history. Citation review may require decisions for surfaces/pages, paragraphs, asset occurrences, complex objects, canonical structure, source-use boundary, and explicit resolutions for extraction blockers. Paragraph decisions require the complete ManualStrict semantic fields, including claim, method, metric, boundary, and reasoning-leap candidates.

For the accepted schemas and examples, read [Evidence package contract](skills/xuanzang/references/evidence-package.md). Submit canonical text corrections in a separate review batch before paragraph-semantic decisions, because corrections create a new canonical revision.

Re-run status after every material review batch:

```bash
xuanzang status packages/source
```

Only `trust_status=citation_grade` together with `gate_status=PASS_STRICT` authorizes citation publication.

### 4. Publish

Publish citation-grade Markdown, anchored chunks, a revision manifest, an embedding manifest, and the exported gate report:

```bash
xuanzang publish packages/source \
  --target citation \
  --out exports/source-citation
```

For exploration before semantic completion, publish an explicitly untrusted hint export:

```bash
xuanzang publish packages/source \
  --target hint \
  --out exports/source-hints
```

Hint output carries `hint_only` trust markers and cannot serve as citation evidence. Published chunks do not contain vectors. `embedding_manifest.json` records the chunk hash, invalidation key, trust state, and namespace requirements for a downstream embedding service. Access tags and privacy metadata are carried forward; enforcement remains the responsibility of the hosting runtime.

### 5. Verify local strict

```bash
xuanzang verify-local-strict packages/source \
  --export exports/source-citation
```

This recomputes the active citation gate and independently verifies source/run/revision identity, artifact hashes, publication invariants, the one-H1/H2-H3 Markdown contract, reverse-locatable chunks, asset hashes and exact-once references, and object counts. It writes `local_strict_acceptance.json` and exits nonzero on any failure. A book is complete only when this report is `PASS_STRICT`.

### 6. Revoke

Revoke an active package when authorization, retention, source rights, or data correctness changes:

```bash
xuanzang revoke packages/source \
  --reason "source authorization withdrawn" \
  --expected-revision 12 \
  --out exports/source-revocation.json
```

The command marks the package revoked, blocks subsequent review and publication, writes `audit/revocation_tombstone.json`, and can copy that tombstone outside the package. It does not connect to vector stores, caches, export stores, or backup systems. Each downstream system must consume the tombstone, delete or quarantine matching derivatives, and record an acknowledgement against `revocation_id`.

## Evidence package

The active package contains:

```text
package_manifest.json
runs/<run_id>/run_manifest.json
ledger/surfaces.jsonl
ledger/evidence_blocks.jsonl
ledger/canonical_blocks.jsonl
ledger/paragraph_candidates.jsonl
ledger/assets.jsonl
ledger/objects.jsonl
ledger/review_decisions.jsonl
toc/toc_candidates.json
audit/extraction_audit.json
audit/gates/<target>.json
history/events.jsonl
```

Raw evidence observations remain immutable. Reviewed canonical and paragraph projections are derived revisions. Every strict paragraph must reverse-locate its full text to raw source spans without gaps, overlaps, or orphaned anchors.

## Privacy and collaboration metadata

`restore` can bind a package to `local_only`, `workspace`, or `tenant` metadata and carry workspace/tenant IDs, rights basis, retention policy, and access tags into gates and exports. `status`, `review`, `publish`, and `revoke` accept expected scope IDs to catch accidental cross-scope operations.

These checks are package-level consistency controls. The CLI has no authentication service, policy engine, row-level security, tenant-isolated object store, or orchestrator-signed reviewer identity. In particular, CLI semantic decisions are `local_self_asserted`; workspace/tenant citation gates require an authenticated orchestrator context that the public CLI does not currently expose. Do not deploy the repository directly as a public multi-tenant backend.

## Migration

Migrate an old v1 package without rerunning its OCR:

```bash
xuanzang migrate-v1 old-package \
  --source path/to/original-source \
  --out packages/migrated-v2
```

Import an AG Brain Book M1 OCR tree without rerunning OCR:

```bash
xuanzang migrate-book-m1 path/to/ocr-root \
  --source path/to/source.pdf \
  --book-id BOOK_ID \
  --out packages/book-v2
```

Migration preserves old output as historical evidence and writes an ID crosswalk. It does not inherit old strict status. Pass `--source` when migrating v1 so source identity can be recomputed; a legacy declaration alone stays blocked as unverified. Every migrated package must pass the current v2 gate and ManualStrict semantic review before citation use.

## v1 compatibility commands

The following commands remain for existing v1 translation and assembly experiments:

```text
ledger, toc, split, clean, validate,
prep-translation, translate, audit-translation,
assemble-docx, reinsert-epub
```

They are compatibility-only. The built-in translation provider is a mechanical `mock`; semantic translation and publication readiness are not established. DOCX assembly and EPUB reinsertion use the v1 package/translation contract and are outside the v2 citation publication path. New restoration workflows should use `restore`, `status`, `review`, `publish`, and `revoke`.

On an unreviewed v2 package, `toc` and `split` may write compatibility proposals and therefore invalidate the immutable top-level projection until `restore` reprojects the active run. Once any v2 review revision exists, those writers refuse to run. Use a `structure` review decision for v2 TOC/boundary work.

## GLM ZCode / OpenClaw adapter

The thin adapter in `zcode/xuanzang` calls the same local CLI:

```bash
python3 zcode/xuanzang/scripts/xuanzang_zcode_cli.py check-env
python3 zcode/xuanzang/scripts/xuanzang_zcode_cli.py --help
```

If copied outside this repository, install this package or set `XUANZANG_REPO` to the checkout. `ZHIPU_API_KEY` is optional for local operations and must only be configured for a separately reviewed, user-authorized remote-provider integration.

## Validation and release posture

Run the release checks in [docs/release_checklist.md](docs/release_checklist.md). The old 98-point goal-loop files under `audit/` are archived v1 self-scores and have no v2 gate authority.

The archived prompt-protocol score in `audit/semantic_visual_prompt_protocol_score.md` evaluates reusable prompt completeness only. It cannot promote a package, replace semantic review, or satisfy local-strict acceptance without current execution evidence.

Current acceptance target:

- trusted local pilot with named operators, controlled source rights, ManualStrict review, and per-package gate evidence, after the remaining real-canary and domain-sampling gates are recorded;
- downstream knowledge-base integration through revision-bound Markdown/chunks and an unembedded manifest;
- public or unsupervised multi-tenant deployment: blocked pending the controls listed in [Known limitations](docs/known_limitations.md).
