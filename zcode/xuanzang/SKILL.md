---
name: xuanzang
description: |
  Rebuild PDF, EPUB, DOCX, HTML, Markdown/text, images, MOBI/AZW3, OCR sidecars, or whole book directories into source-faithful, noise-free, correctly chaptered Markdown with complete figures/tables, machine-readable JSONL, and reverse-locatable evidence for GLM ZCode/OpenClaw.
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

# 玄奘 Local Strict 2.2 for GLM ZCode / OpenClaw

Produce source-faithful, noise-free, correctly chaptered Markdown with complete figures/tables, machine-readable sidecars, and reverse-locatable evidence. Xuanzang is an evidence compiler, not a converter-and-cleaner.

All commands go through:

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py ...
```

## When to Use

Use this skill for document/book rebuild, cleanup, TOC/hierarchy recovery, OCR repair, reading-order repair, image/table preservation, citation-grade ingestion, or directory-wide reconstruction where silent omission or false PASS is unacceptable.

## Setup

Install the shared implementation or set `XUANZANG_REPO`:

```bash
pip install -e /path/to/xuanzang-skill
export XUANZANG_REPO=/path/to/xuanzang-skill
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py check-env
```

## Mandatory Restrictions

1. Preserve raw source observations and append-only decisions.
2. Preserve native EPUB/DOCX/HTML text; OCR repair applies only to OCR evidence.
3. Reconstruct the whole-book architecture and complete visual TOC before boundaries.
4. Account for every surface, paragraph, asset, object, note, reference, appendix, and index.
5. Exactly one H1 is the book title; materialized structure is H2/H3 only.
6. Every published text or visual chunk must reverse-locate to immutable evidence.
7. One materialization writer owns each package; parallel agents produce proposals only.
8. A score, readable Markdown, `REVIEW_READY`, or an old PASS file cannot complete a book.
9. Completion requires the current package gate, publication validation, and `local_strict_acceptance.json` to pass.
10. Do not call a scorer by default.

## Semantic and Visual Protocol

Read `references/local-strict-workflow.md`, `references/failure-regressions.md`, `references/prompt-protocol.md`, `assets/prompt_templates/README.md`, `references/toc-first-segmentation.md`, and `references/book-type-variants.md`.

Use `assets/prompt_templates/local_strict_rebuild.prompt.md` as the controller and run the required reconstruction passes in order. Treat all prompt results as review proposals. Bind accepted canonical TOC, hierarchy, boundaries, media affiliations, and `document_title` through revision-bound decisions.

Preserve immutable source order when caption-linked and unlinked figures coexist. Block unsupported caption relations. Coverage is artifact-appropriate: review all evidence, retain `reference_only` and `excluded` records in the package, and publish only the active `used` citation subset.

## CLI Reference

Restore:

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py restore SOURCE \
  --out PACKAGE \
  --target citation \
  --ocr auto \
  --lang LANGUAGE \
  --privacy local_only \
  --transcription source \
  --max-pages 10000 \
  --max-total-pixels 10000000000 \
  --max-source-bytes 21474836480 \
  --resume
```

Inspect active blockers, apply current-revision decisions, publish, and verify:

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py status PACKAGE --target citation
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py review PACKAGE \
  --decisions DECISIONS.json \
  --expected-revision REVIEW_REVISION
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py publish PACKAGE \
  --target citation --out EXPORT
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py verify-local-strict PACKAGE \
  --export EXPORT
```

For a directory, create independent package/export paths per source hash, process serially by default, continue after individual failures, and write a corpus summary. Do not put an export inside its package.

Use `hint` or `review` only when explicitly requested as an intermediate result. Migration and compatibility commands remain available through the wrapper, but historical v1 passes cannot establish v2 trust.

## Error Handling

On failure, inspect the earliest evidence layer, repair extraction or submit a narrow revision-bound decision, run the matching entry in `references/failure-regressions.md`, then recompute, republish to a clean directory, and rerun local acceptance.

Never weaken a gate, edit derived Markdown, hand-edit hashes, copy an old pass file, apply a broad allowlist, or invent missing text/structure/media relations. Preserve partial evidence and return the exact blocker and next safe action.

## Optional Formal Scoring

Only when the user explicitly requests it, use `references/score-feedback-learning.md` and `assets/prompt_templates/score_feedback_learning.prompt.md`. First run a schema transport smoke test and output-validator self-test, require provider-compatible explicit types, preserve orchestration errors as `process_failure`, and keep scoring artifacts outside the restorable package. Formal scoring evaluates informational body content; publication furniture is outside formal scoring. Scores remain non-authoritative.

## Security Notes

- Keep copyrighted/private source text, images, OCR, packages, and exports local unless the user explicitly authorizes a provider and data boundary.
- Never print or store credentials in evidence artifacts.
- Quarantine encrypted, DRM-protected, malformed, unsafe, or unauthorized inputs.
- Use public-domain or synthetic fixtures for shared tests.

## References

- `references/evidence-package.md`: package and decision schemas.
- `references/pdf-ocr.md`: PDF/OCR/layout/vector/rotation routing.
- `references/toc-first-segmentation.md`: canonical TOC and boundaries.
- `references/book-type-variants.md`: architecture-specific rules.
- `references/semantic-audit.md`: paragraph/object coverage.
- `references/reinsertion.md`: Markdown/JSONL publication.
- `references/operations-and-migration.md`: batch, resume, resources, and migration.
- `references/rag-strict.md`: downstream retrieval.
- `references/translation-workflow.md`: explicit translation tasks only.
- `references/score-feedback-learning.md`: explicitly requested scorer feedback only.

## Response Format

Report per source: source path/hash, package path/revision, export path, gate/trust status, publication validation, local acceptance, blocker codes, unresolved counts, adapter evidence, and next safe action. For directories, add total/pass/fail/skipped counts and one row per source. Never call partial output finished.
