---
name: xuanzang
description: Rebuild PDF, EPUB, DOCX, HTML, Markdown/text, images, MOBI/AZW3, OCR sidecars, or whole book directories into source-faithful, noise-free, correctly chaptered Markdown with complete figures/tables, machine-readable JSONL, and reverse-locatable evidence. Use whenever the user asks to clean, reconstruct, rebuild, ingest, split, audit, or publish books/documents and silent omission, OCR corruption, false headings, broken reading order, lost media, or false PASS is unacceptable.
---

# 玄奘 Local Strict 2.2

Produce one thing by default: **Markdown that is source-faithful, noise-free, structurally accurate, visually complete, machine-readable, and reverse-locatable to immutable source evidence.**

Xuanzang is an evidence compiler, not a converter-and-cleaner. Never “improve” the final Markdown directly and never infer success from readability, a score, or an old PASS file.

## Default behavior

When the user supplies a source and output location, execute the complete workflow without asking them to operate intermediate commands:

1. inventory and preflight;
2. restore immutable evidence;
3. reconstruct the whole-book architecture and canonical TOC;
4. resolve exact boundaries, reading order, text, objects, and media;
5. apply revision-bound semantic decisions;
6. recompute the citation gate;
7. publish the current active revision;
8. run independent local-strict acceptance;
9. repair from evidence and repeat until `PASS_STRICT`, or report the exact irreducible blocker.

For a directory, process every supported book as an independent package. Use one materialization writer per book, isolate work roots, continue past one book’s failure, and emit a corpus summary. Do not let parallel reviewers write package state; they may only produce proposals that the single writer validates and merges.

The default target is `citation`. `hint` and `review` are intermediate states, never the requested deliverable unless the user explicitly asks for them.

## Non-negotiable output contract

- `document.md` has exactly one H1 book title.
- Materialized chapters/essays/lectures/interviews are H2; real source subsections are H3. Final structural headings are H2/H3 only.
- Deeper logical hierarchy remains in `structure_path` and sidecars; do not emit H4–H6.
- Preserve source wording. Native EPUB/DOCX/HTML text never passes through OCR repair.
- OCR repair is evidence-specific, narrow, reversible, and reviewed; never apply global prose joins or word-splitting heuristics to native text.
- Distinguish frontmatter, body, notes, bibliography, glossary, appendix, gallery, acknowledgments, and index. Do not silently drop informational backmatter.
- Publication furniture may be source-accounted or `reference_only`; it must not leak into citation output merely to improve coverage.
- Tables are real table objects and render as Markdown tables when the source relationship is tabular.
- Figures, vector graphics, captions, credits, callouts, formulas, and code are first-class objects with exact source order and affiliation.
- Every published text chunk has immutable source spans and a source reconstruction; every visual chunk has an occurrence, page anchor, file hash, and source locator.
- Every source block, surface, asset, and object ends as `used`, `reference_only`, `excluded` with reason, or unresolved. Unresolved required evidence forces `FAIL_REVIEW`.
- A current `PASS_STRICT` package plus a passing `local_strict_acceptance.json` is the only completion proof.

## Execute the local-strict workflow

First read:

1. [local-strict-workflow.md](references/local-strict-workflow.md)
2. [failure-regressions.md](references/failure-regressions.md)
3. [prompt-protocol.md](references/prompt-protocol.md)
4. [the ordered prompt index](assets/prompt_templates/README.md)
5. the source-specific reference listed below.

Use [local_strict_rebuild.prompt.md](assets/prompt_templates/local_strict_rebuild.prompt.md) as the controlling contract. The specialized prompts are evidence passes beneath it, not optional suggestions.

Preflight the installed runtime and source:

```bash
xuanzang --version
xuanzang --help
xuanzang inspect SOURCE
df -h OUTPUT_PARENT
```

If `xuanzang` is absent, use the bundled repository-local wrapper; it resolves the implementation without installation:

```bash
python3 {SKILL_DIR}/scripts/xuanzang_local_cli.py --version
```

Use the same wrapper in place of `xuanzang` for every later command when the console entry point is unavailable.

Restore into a package path separate from the final export:

```bash
xuanzang restore SOURCE \
  --out PACKAGE \
  --target citation \
  --ocr auto \
  --lang LANGUAGE \
  --transcription source \
  --max-pages 10000 \
  --max-total-pixels 10000000000 \
  --max-source-bytes 21474836480 \
  --resume
```

Do not select an OCR engine from file extension alone. Inspect run evidence. `auto` may use only an available, recorded adapter. For PDF, classify every page as native, scanned, hybrid, visual-only, or mixed-layout before trusting extraction. Render every page needed for structure or visual audit; contact sheets must show all pages, not only the first frame of a concat group.

Run the required semantic/visual prompt sequence. Reconcile the complete TOC globally before resolving nodes. Bind accepted results through a `structure` decision containing `document_title`, every surface in source order, every TOC candidate disposition, a complete canonical TOC, and an exact paragraph/textless-surface partition. Apply canonical text corrections in a separate revision from structure decisions.

Apply decisions against the current revision:

```bash
xuanzang review PACKAGE \
  --decisions DECISIONS.json \
  --expected-revision CURRENT_REVIEW_REVISION
```

Re-read materialized projections after every review. A stored decision that does not alter the current canonical/coverage/structure view is not a repair.

Publish only after citation status passes:

```bash
xuanzang status PACKAGE --target citation
xuanzang publish PACKAGE --target citation --out EXPORT
xuanzang verify-local-strict PACKAGE --export EXPORT
```

Do not report success unless all three agree on the active package/run/revision:

- package gate: `PASS_STRICT`, `citation_grade`, zero hard blockers;
- publication validation: `PASS`;
- local strict acceptance: `PASS_STRICT`, zero failures.

## Repair loop

On failure:

1. identify the earliest evidence layer that can explain it;
2. inspect the exact page/DOM/block/bbox/asset evidence;
3. fix extraction or submit a narrow, revision-bound decision;
4. add or run the matching regression in [failure-regressions.md](references/failure-regressions.md);
5. recompute, republish to a clean export directory, and rerun acceptance.

Never repair these symptoms by weakening a verifier, editing derived Markdown, copying a previous gate file, broad allowlisting, or marking uncertain evidence “reviewed.” Parent joins cannot mask corrected child text. A table/caption/object cannot override newer canonical text. An image cannot inherit a nearby caption without visual and source-order evidence.

## Source routing

- Read [pdf-ocr.md](references/pdf-ocr.md) for PDF, scans, OCR, multilingual pages, rotation, vector figures, mixed layouts, or cross-page text.
- Read [toc-first-segmentation.md](references/toc-first-segmentation.md) for TOC, hierarchy, boundaries, containers, notes, or index structure.
- Read [book-type-variants.md](references/book-type-variants.md) after classifying anthology, interview, textbook, reference, gallery, or other architecture.
- Read [evidence-package.md](references/evidence-package.md) for decision schemas and package invariants.
- Read [semantic-audit.md](references/semantic-audit.md) for paragraph/object coverage and source-local reasoning claims.
- Read [reinsertion.md](references/reinsertion.md) for Markdown/JSONL publication.
- Read [operations-and-migration.md](references/operations-and-migration.md) for directories, resume, disk ceilings, source updates, shared operation, or migrations.
- Read [rag-strict.md](references/rag-strict.md) before downstream retrieval or embeddings.
- Read [translation-workflow.md](references/translation-workflow.md) only when translation is explicitly requested; translation is not part of local-strict reconstruction.

## External scoring is optional

Do not call a scorer by default. Scores never establish completion and must not consume time after local strict acceptance passes. If the user explicitly asks for formal scoring, keep it outside the restorable package, run a schema transport smoke test and output-validator self-test first, require provider-compatible explicit types, preserve orchestration errors as `process_failure`, and use [score-feedback-learning.md](references/score-feedback-learning.md). Coverage must be artifact-appropriate: audit all reviewed evidence but publish only the active `used` subset; preserve `reference_only` and `excluded` records in the package. Preserve immutable source order when caption-linked and unlinked figures coexist, and block any unsupported caption relation.

## Stop and report

Stop promotion, preserve partial evidence, and name the exact next safe action when:

- source bytes changed without explicit acceptance;
- required OCR/vision/conversion capability is unavailable;
- resource admission fails;
- the complete visual/TOC evidence cannot be inspected;
- a structure, paragraph, asset, object, or source-boundary decision is unresolved;
- a package or export hash/revision is stale;
- any output cannot reverse-locate to original evidence.

Report per book: source path/hash, package path/revision, export path, achieved trust, local acceptance status, hard blockers, unresolved counts, adapter evidence, and whether the result is final or partial. For a corpus, include total/pass/fail counts and one row per source. Do not describe `REVIEW_READY`, readable Markdown, or a high score as finished.
