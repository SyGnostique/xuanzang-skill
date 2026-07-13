# Structure and boundary reconstruction

Treat file order, PDF pages, EPUB spine, OCR lines, embedded navigation, parser headings, typography, and repeated headers as evidence. Build the logical document structure from converging signals.

## Contents

- [Candidate layers](#candidate-layers)
- [Canonical structure](#canonical-structure)
- [Boundary resolution](#boundary-resolution)
- [Document-specific patterns](#document-specific-patterns)
- [Acceptance checks](#acceptance-checks)

## Candidate layers

Collect structure candidates without promoting them:

- visible TOC pages and their printed locators;
- EPUB nav/NCX and OPF spine;
- PDF bookmarks/outlines;
- DOCX heading styles and outline levels;
- heading-like text, numbering, typography, indentation, whitespace, and page position;
- recurring running headers/footers;
- article-section conventions;
- bibliography, notes, index, glossary, annex, plate, and appendix cues;
- model-generated hierarchy proposals with engine/configuration provenance.

Store candidate text, source anchor, candidate role, evidence signals, contradictions, and review status. Confidence must come from observable signals. A regex match, parser tag, or fallback candidate cannot receive synthetic high confidence.

Separate occurrences on TOC pages from corresponding headings in the body. A directory title match cannot establish a chapter start.

## Canonical structure

Build a semantic tree that can represent:

```text
document
├── frontmatter
│   ├── title/copyright
│   ├── preface/introduction
│   └── contents/lists
├── body
│   ├── part
│   │   ├── chapter
│   │   │   └── section/subsection
│   │   └── interlude/plate
│   └── article clauses or report sections
└── backmatter
    ├── appendices
    ├── notes
    ├── bibliography/references
    ├── glossary
    └── index
```

Each canonical node needs stable ID, order, level, title, normalized title, section type, source evidence, expected start/end cues, inclusion policy, and review decision. Preserve untitled structural regions with explicit IDs instead of forcing headings.

## Boundary resolution

For every node:

1. Generate all plausible start candidates outside TOC/navigation residue.
2. Compare title, numbering, typography, local context, printed page, bookmark/nav destination, and surrounding hierarchy.
3. Record the selected start and evidence.
4. Derive the end from the next reviewed sibling or explicit closing cue.
5. Validate monotonic order, permitted nesting, and source-span coverage.
6. Record excluded or reference-only spans with reasons.

The boundary map must identify the first and last contributing block/span, page or logical surface, confidence signals, decision provenance, warnings, and any intentionally shared object. Repeated running headers, page numbers, captions, table headers, figure labels, and TOC residue must remain classified outside body headings.

Do not merge line wraps or split paragraphs by editing text files independently from the ledger. Update canonical paragraph spans and keep original blocks intact.

## Document-specific patterns

### Scientific papers

Use article structure even when no visible TOC exists: title/metadata, abstract, keywords, introduction, methods, results, discussion, conclusions, acknowledgements, declarations, references, supplementary material. Preserve journal furniture separately from article content.

### Books and theses

Reconcile printed TOC, printed page numbers, PDF indices, and body headings. Model frontmatter Roman numerals, page-number offsets, plates, chapter epigraphs, endnotes, bibliography, and index as explicit regions.

### Reports, manuals, and standards

Preserve numbered clause hierarchy, warnings, normative/informative annexes, cross-references, revision history, and repeated template headers. Do not flatten clauses into generic chapters.

### EPUB and HTML

Preserve href and DOM paths. A spine item can contain multiple chapters, while a chapter can span multiple spine items. Resolve logical boundaries independently from file boundaries.

### DOCX

Use heading styles as candidates and inspect direct formatting, list numbering, tables, headers/footers, text boxes, footnotes/endnotes, and section breaks. Retain OOXML anchors when available.

### Image bundles and scans

Establish file/page order before OCR. Use visible page numbers, catchwords, folios, and sequence metadata. Route ambiguous or missing pages to review.

## Acceptance checks

The executable v2 structure decision dispositions every current TOC candidate; maps every `used` candidate into a canonical TOC item; maps every TOC item to a unique boundary; and partitions the active ordered `paragraph_ids` exactly once. Each boundary records a non-empty `structure_path`, the ordered unique `surface_ids` derived from its paragraphs, and any explicitly assigned `textless_surface_ids`. Every textless surface is assigned once. Two adjacent boundaries may share a paragraph-bearing surface when the logical change occurs mid-page or within one EPUB spine item.

Require:

- every in-scope source span assigned exactly once, intentionally shared with an explicit relation, or excluded with reason;
- no unintended overlap or gap between sibling boundaries;
- body starts supported by body evidence;
- TOC and body discrepancies recorded rather than silently repaired;
- frontmatter, body, backmatter, notes, bibliography, index, and supplements represented;
- reading order validated for multicolumn and mixed visual layouts;
- all low-confidence or contradictory boundaries resolved for `citation_grade`;
- all canonical paragraphs inherit stable structure IDs and reversible anchors;
- structure decision recorded as a semantic review before citation promotion.

Any unresolved TOC, TOC/body mismatch affecting scope, low-confidence boundary, unassigned span, or overlapping span forces citation `FAIL_REVIEW`.
