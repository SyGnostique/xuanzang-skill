---
name: xuanzang
description: Compile books, papers, reports, and document bundles into versioned, auditable evidence packages. Use for PDF, EPUB, DOCX, HTML/text/Markdown, raster-image or image-bundle, convertible MOBI/AZW3, or existing-OCR restoration; native-text, scanned, hybrid, OCR-damaged, multilingual, image-heavy, table/formula/footnote-heavy, or structurally dirty documents; citation-grade knowledge-base preparation; TOC and reading-order reconstruction; ManualStrict paragraph coverage; compatibility-only legacy translation or EPUB/DOCX derivative assessment; corpus migration; or team review where silent omission, unsupported repair, lost provenance, or false PASS is unacceptable.
---

# 玄奘 2.0

Treat xuanzang as an **evidence compiler**. Restore a source into a revisioned evidence package, preserve every raw observation, resolve structure and text through traceable decisions, and publish only to the trust level proved by the package.

## Core contract

1. Choose the requested target before processing: `hint`, `review`, or `citation`.
2. Bind the package to source bytes, identity, rights, tenant/workspace, configuration, and run provenance.
3. Preserve raw renditions, page/surface images, text variants, geometry or DOM anchors, assets, and review history append-only.
4. Make canonical text a reviewed selection with reversible source spans. Never overwrite raw evidence.
5. Require full semantic and paragraph-equivalent coverage before `citation_grade`.
6. Treat tables, formulas, figures, captions, notes, indexes, references, and exclusions as first-class evidence.
7. Let hard blockers override scores. Emit only `PASS_STRICT` or `FAIL_REVIEW` for citation eligibility; treat hint readiness as a separate disclosed state.
8. Make reruns resumable and revision-aware. Source or configuration changes invalidate downstream artifacts without deleting prior revisions.

## Run the v2 workflow

Inspect the installed interface first:

```bash
xuanzang --version
xuanzang --help
```

If `xuanzang` is absent from `PATH`, install the repository with `pip install -e /path/to/xuanzang-skill` or run `PYTHONPATH=/path/to/xuanzang-skill/src python3 -m xuanzang.cli ...`.

Restore through the deepest internal stage required by the target:

```bash
xuanzang restore SOURCE \
  --out PACKAGE \
  --target review \
  --ocr auto \
  --lang LANGUAGE \
  --transcription source \
  --max-pages 10000 \
  --max-total-pixels 10000000000 \
  --max-source-bytes 21474836480 \
  --resume
```

Choose `--target` from `hint`, `review`, or `citation`; choose `--ocr` from `auto`, `none`, `paddle`, `tesseract`, `mock`, `sidecar`, or `plugin:NAME`. Use `--document-kind` when a domain or structural profile is known. Add `--sidecar FILE` with `--ocr sidecar`. A usable sidecar row needs a page locator, four-number render-pixel bbox, exact page-image SHA-256, engine/version provenance, and later typed provenance review. `auto` may select only adapters proven available in the run manifest; missing OCR capability must create a blocker.

Use `--transcription source|diplomatic|normalized|both` explicitly for archives, editions, normalization, and multilingual work. `--privacy workspace` requires `--workspace-id`; `--privacy tenant` requires `--tenant-id`. Use repeatable `--access-tag`, rights, and retention options as downstream policy metadata. Read [operations-and-migration.md](references/operations-and-migration.md) before changing resource ceilings, accepting source updates, enabling external bundle paths, or operating a shared service.

For a large paper directory, create independent fast hint packages first:

```bash
xuanzang batch PAPERS_DIR --out-root CORPUS_BUILD \
  --target hint --ocr auto --workers 4
```

Native-text PDF pages in hint mode skip full-page rendering; OCR-required pages still render. The batch ledger records completed, failed, and fail-fast-cancelled jobs. Upgrade selected packages through a review/citation restore before ManualStrict promotion.

Inspect durable state and unresolved work:

```bash
xuanzang status PACKAGE
```

`status` defaults to recomputing citation eligibility and reports `evaluated_target`. `PASS_STRICT` means the current active package is citation-grade; `FAIL_REVIEW` can coexist with a separately usable hint/review snapshot. Use `--target hint` or `--target review` only to check that operational tier explicitly.

Apply explicit, revision-bound review decisions:

```bash
xuanzang review PACKAGE \
  --decisions DECISIONS_FILE \
  --expected-revision REVIEW_REVISION \
  --expected-tenant-id TENANT \
  --expected-workspace-id WORKSPACE
```

Pass only the expected scope fields present on the package. These flags compare metadata and fail closed; they do not authenticate the reviewer. Workspace/tenant semantic review needs a trusted orchestrator-supplied verified `ReviewerContext`. Follow the complete executable page, paragraph, asset, object, structure, source-boundary, canonical-correction, supersession, and typed-resolution schemas in [evidence-package.md](references/evidence-package.md). Apply canonical corrections and paragraph semantic decisions in separate review revisions.

Publish an eligible derivative without changing package trust:

```bash
xuanzang publish PACKAGE --target citation --out OUTPUT
```

Use `--target hint` only for a disclosed discovery export. Native v2 publish emits Markdown, JSONL chunks, a gate snapshot, an export manifest, and an unembedded invalidation/namespace manifest. Vector generation and ACL enforcement are downstream responsibilities.

For existing packages, use a non-destructive migration:

```bash
xuanzang migrate-v1 OLD_PACKAGE --source ORIGINAL_SOURCE --out NEW_PACKAGE
xuanzang migrate-book-m1 OCR_ROOT --source SOURCE_PDF --book-id BOOK_ID --out NEW_PACKAGE
```

Keep v1 commands only for compatibility. Their historical `PASS_STRICT`, mechanical translation PASS, or synthetic score cannot establish v2 `citation_grade`.

`prep-translation`, `translate --provider mock`, `audit-translation`, `assemble-docx`, and `reinsert-epub` remain compatibility-only v1 paths. Treat their output as a draft derivative or migration fixture. Current v2 has no translation trust gate or v2 DOCX/EPUB publication exporter.

Revoke package use and emit an idempotent downstream tombstone when authorized:

```bash
xuanzang revoke PACKAGE \
  --reason REASON \
  --expected-revision REVIEW_REVISION \
  --expected-tenant-id TENANT \
  --expected-workspace-id WORKSPACE \
  --out /outside/package/revocation.json
```

Revocation does not physically delete source bytes, exports, vectors, caches, or backups. The orchestrator must perform policy-bound deletion and collect per-system acknowledgements against `revocation_id`.

## Verify runtime capability

Treat the references as the target contract and the installed CLI/artifacts as execution evidence. Before promising completion, verify that the active runtime actually performed the required adapter, canonical correction, structure review, checkpoint/resume, migration, or exporter operation. When a required capability is absent or only scaffolded, preserve the package at `needs_review`, name the missing operation, and hand off the next safe repair. Never emulate a citation pass by editing gate files or derived Markdown.

## Execute in four phases

1. **Scope.** Select the use case, target, source family, rights boundary, privacy class, languages, adapters, and deliverable. Complete when the run profile is explicit and authorized.
2. **Restore.** Produce source identity, surfaces/pages, blocks, variants, assets, structure candidates, canonical paragraphs, and audits. Complete when every input surface and raw span has a recorded state.
3. **Review.** Resolve OCR, structure, asset, exclusion, and semantic findings through append-only decisions. Complete when all target-required paragraph coverage rows and source anchors exist.
4. **Gate and publish.** Recompute the aggregate gate, then export only an eligible target. Complete when the export records the package revision, gate decision, provenance, and limitations.

## Stop conditions

Stop promotion and return `FAIL_REVIEW` when any hard blocker remains, the package schema cannot be validated, an adapter was claimed without run evidence, a review decision targets a stale revision, or an output cannot reverse-locate its source evidence. Preserve useful partial artifacts for repair.

After review, verify that the accepted decisions are materialized in current coverage/canonical views and affect the recomputed gate. A stored decision with no supported projection is an unresolved implementation finding.

Never send private or copyrighted source text to a remote model unless the user explicitly authorizes that provider and data boundary. External OCR/VLM names in the references describe adapter roles; they do not imply bundled models or automatic network calls.

## Load references selectively

- Read [scenarios-and-targets.md](references/scenarios-and-targets.md) to select source routing, trust target, the JSON/YAML bundle schema, and the three-state runtime capability matrix.
- Read [evidence-package.md](references/evidence-package.md) before creating, reviewing, integrating, or validating package artifacts.
- Read [pdf-ocr.md](references/pdf-ocr.md) for native-text, scan, hybrid, layout, OCR, multilingual, or cross-page work.
- Read [toc-first-segmentation.md](references/toc-first-segmentation.md) for TOC, hierarchy, reading order, chapters, sections, notes, or boundaries.
- Read [rag-strict.md](references/rag-strict.md) before knowledge-base, retrieval, embedding, SourcePage, card, or citation promotion.
- Read [translation-workflow.md](references/translation-workflow.md) before translation planning or execution.
- Read [semantic-audit.md](references/semantic-audit.md) before ManualStrict coverage, semantic review, conflict resolution, or revision.
- Read [reinsertion.md](references/reinsertion.md) before Markdown/JSONL/DOCX/EPUB export or publication validation.
- Read [operations-and-migration.md](references/operations-and-migration.md) for batch corpora, resume/retry, team review, multi-tenant services, v1/Book M1 migration, or incident recovery.
- Read [goal-mode.md](references/goal-mode.md) before a staged 98+ implementation or acceptance loop.

## Report completion

Return the package path and revision, source hash, requested and achieved trust status, citation status, hard blockers, unresolved review counts, adapter evidence, lifecycle/revocation state, migration status, and export paths. Disclose `hint_only`, `needs_review`, compatibility-only output, and orchestrator-owned obligations at every answer or export layer.
