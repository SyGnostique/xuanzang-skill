---
name: xuanzang
description: |
  Compile books, papers, reports, and document bundles into versioned, auditable evidence packages for GLM ZCode/OpenClaw. Use for PDF, EPUB, DOCX, HTML/text/Markdown, image-bundle, or convertible MOBI/AZW3 restoration; native-text, scan, hybrid, OCR-damaged, multilingual, table/formula/footnote-heavy, or structurally dirty content; citation-grade knowledge-base preparation; ManualStrict paragraph coverage; compatibility-only legacy translation or EPUB/DOCX derivative assessment; corpus migration; or team review where provenance and omission gates matter.
metadata:
  openclaw:
    requires:
      env: []
      bins:
        - python3
    emoji: "📚"
    source: https://github.com/SyGnostique/xuanzang-skill/tree/main/zcode/xuanzang
    homepage: https://github.com/SyGnostique/xuanzang-skill
---

# 玄奘 2.0 for GLM ZCode / OpenClaw

Use xuanzang as an **evidence compiler**. Restore each source into a revisioned package, preserve raw observations, apply traceable semantic decisions, and publish only the trust level proved by current gates.

All commands must go through:

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py ...
```

## Setup

Install the shared implementation:

```bash
pip install -e /path/to/xuanzang-skill
```

For a separately copied adapter, set:

```bash
export XUANZANG_REPO=/path/to/xuanzang-skill
```

Verify discovery without printing secrets:

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py check-env
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py --help
```

## Mandatory Restrictions

1. Choose `hint`, `review`, or `citation` before processing.
2. Bind source hash, package version, policy, adapter evidence, privacy, and run ID.
3. Keep raw evidence and manual decisions append-only.
4. Make canonical text reversible to native/OCR blocks and geometry or DOM/XML anchors.
5. Require ManualStrict semantic coverage for every paragraph-equivalent block before `citation_grade`.
6. Account for every table, formula, figure, caption, note, reference, index entry, and asset occurrence in scope.
7. Let hard blockers force `FAIL_REVIEW`; a score or mock result cannot override them.
8. Resume by revision and preserve prior runs.

## CLI Reference

### Restore, review, and publish

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py restore SOURCE \
  --out PACKAGE \
  --target review \
  --ocr auto \
  --lang LANGUAGE \
  --privacy local_only \
  --transcription source \
  --max-pages 10000 \
  --max-total-pixels 10000000000 \
  --max-source-bytes 21474836480 \
  --resume
```

Choose `--target` from `hint`, `review`, or `citation`; choose `--ocr` from `auto`, `none`, `paddle`, `tesseract`, `mock`, `sidecar`, or `plugin:NAME`. For precomputed OCR/VLM evidence, add `--ocr sidecar --sidecar FILE`. Every usable sidecar row needs a page locator, four-number render-pixel bbox, exact page-image SHA-256, engine/version provenance, and later typed provenance review. Model names in the references describe optional integration roles; this adapter does not bundle or call them automatically.

Use `--transcription source|diplomatic|normalized|both` explicitly for archives, editions, normalization, and multilingual work. `--privacy workspace` requires `--workspace-id`; `--privacy tenant` requires `--tenant-id`. Repeat `--access-tag` as needed and record rights/retention policy. Read `references/operations-and-migration.md` before changing resource ceilings, accepting source updates, enabling external bundle paths, or operating a shared service.

For a large paper directory, create independent fast hint packages first:

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py batch PAPERS_DIR \
  --out-root CORPUS_BUILD --target hint --ocr auto --workers 4
```

Native-text PDF pages in hint mode skip full-page rendering; OCR-required pages still render. The batch ledger records completed, failed, and fail-fast-cancelled jobs. Upgrade selected packages through a review/citation restore before ManualStrict promotion.

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py status PACKAGE
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py review PACKAGE \
  --decisions DECISIONS.jsonl \
  --expected-revision REVIEW_REVISION \
  --expected-tenant-id TENANT \
  --expected-workspace-id WORKSPACE
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py publish PACKAGE \
  --target citation \
  --out OUTPUT \
  --expected-tenant-id TENANT \
  --expected-workspace-id WORKSPACE
```

Status defaults to the fail-closed citation gate and reports `evaluated_target`. Add `--target hint` or `--target review` only when checking that operational tier explicitly.

`status` defaults to recomputing citation eligibility; an explicit `--target hint|review|citation` changes the evaluated tier and appears in `evaluated_target`. Pass only expected scope fields present on the package. These flags compare package metadata and fail closed; they do not authenticate the reviewer. Workspace/tenant semantic review requires a trusted orchestrator-supplied verified `ReviewerContext`. Follow every executable review shape and the two-revision canonical-correction sequence in `references/evidence-package.md`.

Use `--target hint` only for a disclosed discovery export. Native v2 publish emits eligible Markdown/chunks, a gate snapshot, an export manifest, and an unembedded invalidation/namespace manifest. It never raises package trust. Vector generation and ACL enforcement belong downstream. A citation export requires a recomputed strict pass.

Verify that the installed runtime actually materialized required canonical corrections, structure/asset review, sidecar provenance, checkpoint recovery, and export fields. When a capability is absent or scaffold-only, retain `needs_review` and report the missing operation. Never edit a gate or derived Markdown to simulate citation readiness.

## Migrate without erasing prior work

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py migrate-v1 OLD_PACKAGE \
  --source ORIGINAL_SOURCE --out NEW_PACKAGE
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py migrate-book-m1 OCR_ROOT \
  --source SOURCE_PDF \
  --book-id BOOK_ID \
  --out NEW_PACKAGE
```

Add `--copy-assets` to Book M1 migration only when the package must own copies. Migration retains previous OCR as evidence and starts v2 trust at `needs_review`. Historical v1 strict passes, Book M1 scores, automatic TOCs, and mechanical translation passes cannot establish v2 citation trust.

## Compatibility

The v1 commands remain available for existing automation:

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py ledger SOURCE --out PACKAGE
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py toc PACKAGE
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py split PACKAGE
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py clean PACKAGE
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py validate PACKAGE --strict
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py prep-translation PACKAGE --target zh-CN
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py translate PACKAGE --provider mock --run-id RUN
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py audit-translation PACKAGE --run-id RUN
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py assemble-docx PACKAGE --run-id RUN --out DOCX
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py reinsert-epub PACKAGE --run-id RUN --out EPUB
```

Use v2 commands for new packages. Treat v1 outputs as compatibility derivatives or migration inputs.

The translation/mock/audit and DOCX/EPUB commands above are compatibility-only. They do not create v2 translation trust, semantic publication PASS, or a v2 DOCX/EPUB export. Report those results as draft derivatives.

Revoke package use and emit a downstream tombstone when authorized:

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py revoke PACKAGE \
  --reason REASON \
  --expected-revision REVIEW_REVISION \
  --expected-tenant-id TENANT \
  --expected-workspace-id WORKSPACE \
  --out /outside/package/revocation.json
```

The orchestrator must authenticate this action, purge downstream vectors/caches/exports according to policy, and collect deletion acknowledgements. `revoke` itself does not erase those systems or package run bytes.

## Security Notes

- Keep copyrighted/private books, extracted text, translations, page images, provider responses, and packages outside public repositories.
- Read provider keys only from managed environment/secret storage and never echo them.
- Require explicit user authorization before sending source content to a remote provider.
- Prefer local fixed scripts to ad hoc processing.
- Quarantine encrypted, DRM, malformed, unsafe, or unauthorized inputs.
- Use public-domain or synthetic fixtures for tests.

## Error Handling

- Preserve a failed run and return its blocker or retryable error; keep the last committed run active.
- Treat unavailable required OCR, unsupported source features, hash/revision conflicts, schema failures, and citation gate failures as explicit stops.
- Repair or rerun the affected configuration, then recompute status; never copy an earlier pass file forward.
- Read `references/operations-and-migration.md` before recovery, rollback, or bulk retry.

## When to Use References Selectively

- Read `references/scenarios-and-targets.md` to choose target, source route, JSON/YAML bundle schema, deliverable, and the three-state capability matrix.
- Read `references/evidence-package.md` for package paths, IDs, decisions, states, and invariants.
- Read `references/pdf-ocr.md` for OCR/layout/cross-page restoration.
- Read `references/toc-first-segmentation.md` for hierarchy, reading order, and boundaries.
- Read `references/rag-strict.md` before retrieval, embedding, knowledge-object, or citation promotion.
- Read `references/translation-workflow.md` before translation.
- Read `references/semantic-audit.md` before ManualStrict or meaning-level review.
- Read `references/reinsertion.md` before exports or publication validation.
- Read `references/operations-and-migration.md` for batch, resume, collaboration, service, migration, or recovery.
- Read `references/goal-mode.md` before a staged 98+ loop.

## Response Format

Report package path/revision, source hash, requested and achieved trust, citation decision, hard blockers, unresolved review counts, adapter evidence, lifecycle/revocation state, migration status, and export paths. Disclose `hint_only`, `needs_review`, compatibility-only output, and orchestrator-owned obligations in every downstream result.
