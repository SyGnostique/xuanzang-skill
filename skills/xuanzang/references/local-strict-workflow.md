# Local Strict Rebuild Workflow

This is the executable agent workflow for turning one source or a directory of books into the final Xuanzang deliverable. The workflow is fail-closed and local-first. It does not depend on a formal scorer.

## 1. Completion definition

A book is complete only when:

1. the active evidence package recomputes to `PASS_STRICT` and `citation_grade`;
2. every required review domain is resolved against the current source/run/canonical revision;
3. citation publish succeeds;
4. `publication_validation.json` is `PASS`;
5. `xuanzang verify-local-strict PACKAGE --export EXPORT` writes `PASS_STRICT`;
6. the export contains the exact current source hash, run ID, canonical revision, and review revision.

Readable Markdown, a complete-looking TOC, `REVIEW_READY`, an old export, or a numeric score is not completion.

## 2. Corpus layout

Use separate package and export roots:

```text
OUTPUT_ROOT/
  _packages/
    SOURCE_SLUG.sha256_SOURCE12/
  books/
    SOURCE_SLUG.sha256_SOURCE12/
      document.md
      chunks.jsonl
      assets.jsonl
      objects.jsonl
      assets/
      manifest.json
      gate_report.json
      publication_validation.json
      embedding_manifest.json
      local_strict_acceptance.json
  corpus_summary.json
  corpus_summary.md
```

Do not put an export inside its package. Do not reuse one package for two source hashes. Process books serially by default; OCR subprocesses may use bounded internal parallelism only after disk/memory admission.

## 3. Inventory and admission

1. Resolve source and output to absolute paths.
2. Enumerate supported inputs deterministically: PDF, EPUB, DOCX, TXT, Markdown, HTML, raster images/image directories, MOBI/AZW3 with local Calibre, and JSON/YAML bundles.
3. Exclude generated output roots, hidden temporary files, and duplicate source identities.
4. Record source byte size and SHA-256 before work.
5. Check free disk, page/pixel/source-byte ceilings, installed OCR/conversion capabilities, language packs, and privacy/rights boundary.
6. Refuse a run whose source and output overlap destructively.

For every skipped source, record an explicit reason in the corpus summary.

## 4. Restore immutable evidence

Run `restore --target citation --transcription source --resume`. Treat restore output as evidence, not as final text.

Inspect:

- `package_manifest.json` and active run manifest;
- surface/page ledger and source order;
- evidence engines and coordinate systems;
- native/OCR/visual routes per page;
- OCR warnings, mixed visual regions, rotations, and language mapping;
- source inventory, EPUB nav/NCX/DOM/CSS visibility, PDF outline, and extracted assets;
- object candidates for tables, figures, captions, equations, code, links, callouts, notes, and indexes.

Never run OCR cleanup on source-native EPUB/DOCX/HTML text. When OCR is required, retain page image hash, bbox/polygon, engine/version, language, and confidence for every block.

## 5. Whole-book semantic and visual reconstruction

Run the prompts in `assets/prompt_templates/README.md` in order.

### Architecture

Classify the actual source grammar before proposing chapters. A spine item, PDF page, filename, short line, font size, byline, caption, running header, or printed locator is only evidence, never a chapter by itself.

### Printed TOC

Visually inspect all candidate TOC pages. A multi-page TOC must be transcribed as one evidence set. Preserve line text and hierarchy before normalization. Reconcile printed TOC, EPUB nav/NCX, PDF outline, heading candidates, page labels, and body anchors into one canonical model.

### Boundaries

Resolve every materialized node with inclusive start and exclusive end anchors. Use previous/current/next node context and before/after blocks. Containers can be non-text-bearing. Partition all paragraphs exactly once and assign every non-excluded textless surface exactly once.

### Reading order

Decide reading order from page geometry plus semantic continuity. Do not split a normal single-column page into left/right halves. For true multi-column pages, indexes, sidebars, captions, and tables, validate order visually.

### Media and objects

Preserve immutable occurrence order. Keep an image with its real caption/credit only when source/visual evidence supports the relation. Extract vector-only PDF figures, not just raster XObjects. A table passes only when its row/column/cell relationships are machine-readable and the Markdown rendering reflects them.

## 6. Review decision construction

Use append-only, revision-bound decisions described in `evidence-package.md`.

Apply canonical corrections first. Re-read `canonical_reviewed.jsonl` and paragraph candidates. Then apply structure and semantic coverage in a later revision.

A structure decision must include:

- `document_title`: exact source title selected from title evidence;
- every surface ID in exact source order;
- every excluded noncanonical surface;
- a disposition and reason for every TOC candidate;
- every canonical TOC item with parentage, level, boundary, and source candidate links;
- every boundary with full `structure_path`, exact ordered paragraph IDs, derived surface IDs, and textless surface IDs;
- a semantic reading and evidence-grounded reason.

The book title is not a chapter path. Structure paths begin at materialized Part/Chapter/Essay/Lecture/Interview or another genuine source division.

Review every active:

- page/surface;
- paragraph;
- asset occurrence;
- object and relation;
- source-use boundary;
- typed OCR/provenance resolution.

Use `used` only for citation output, `reference_only` for retained non-citation evidence, and `excluded` only with a source-grounded reason. Do not mark ambiguity reviewed.

## 7. Materialization audit

After each `xuanzang review`:

1. recompute `status --target citation`;
2. inspect current reviewed canonical blocks and paragraphs;
3. compare structure projection with the accepted TOC/boundaries;
4. confirm each decision ID is present in the current active head;
5. verify corrected child text is not masked by a stale joined parent;
6. verify object representations do not override newer canonical text;
7. verify all used assets/objects are present and ordered.

If the stored decision did not change the active projection, repair the materializer rather than adding another assertion.

## 8. Publish and independent acceptance

Publish to a clean export directory:

```bash
xuanzang publish PACKAGE --target citation --out EXPORT
xuanzang verify-local-strict PACKAGE --export EXPORT
```

The independent verifier checks:

- active package gate and identity;
- package/export revision binding;
- required artifact existence and manifest hashes;
- exported gate and publication validation;
- exactly one nonempty H1 and no H4–H6;
- no empty leaf sections;
- chunk counts, identities, text hashes, structure paths, and reverse evidence;
- asset file hashes and exact-once references;
- object identities and counts.

Delete or quarantine a failed export before republishing. Never edit `document.md`, manifest hashes, gate JSON, or acceptance JSON to make a failure disappear.

## 9. Corpus summary

Write deterministic JSON and readable Markdown summaries containing:

- discovered source count;
- completed, failed, skipped, and unresolved counts;
- source path, source SHA-256, package, export, active revision;
- adapter/route summary;
- gate status and local acceptance status;
- blocker codes and next safe action.

The corpus is complete only when every in-scope source row is either `PASS_STRICT` or explicitly failed/skipped with a reason. “Script finished” is not equivalent to “all books passed.”
