# Prompt Protocol Routing

Use the prompt assets under `../assets/prompt_templates/` for semantic and visual structure work. Start with `README.md`, which defines sequence, context bundles, confidence policy, and global invariants.

In a v2 evidence package, prompt output is a review proposal. Convert accepted TOC, hierarchy, boundary, and media-affiliation results into the executable revision-bound `structure` review decision documented in `evidence-package.md`. Recompute the target-specific gate afterward. Never edit gate files or immutable raw evidence to apply a prompt result.

## Load Rules

- Before any TOC decision: load `book_architecture.prompt.md`.
- For PDF, scans, visually complex EPUB, catalogues, or multi-column contents: load both visual TOC prompts and provide page images.
- For every dirty source: load `canonical_toc.prompt.md` and `toc_hierarchy_adjudication.prompt.md` after candidate harvesting.
- Before splitting: load candidate assessment, exact boundary resolution, and media affiliation prompts.
- After splitting: load exhaustive split audit and reverse structure audit prompts.
- On any blocker: load evidence-bounded revision, rerun dependent audits, then load stage scoring.
- After every formal score: load `score_feedback_learning.prompt.md`, preserve the raw score privately, and separate current-book repairs from sanitized generalizable proposals with regression tests.

Do not replace the protocol with a generic request such as "find the chapters" or "clean this TOC." Each role has a separate trust boundary and output artifact.

## Model Requirements

- Vision capability is required for printed TOC transcription, multi-column reading order, typography-dependent hierarchy, image-heavy books, and visually ambiguous boundaries.
- Long-context semantic capability is required for whole-TOC reconciliation and global reverse audit.
- Strict structured output is required for durable maps and evidence logs.
- A weaker or text-only model may harvest and classify obvious candidates but must not grant `PASS_STRICT` when visual evidence is required.

No model grants `PASS_STRICT` directly. Only the current v2 package gate can establish citation eligibility after accepted decisions are materialized and integrity-checked.

The next independent scorer must not inherit a desired verdict from the prior score. Provide changed artifact paths and neutral recheck requirements only.

Before formal scoring, declare the scored-content boundary. Score informational chapters, case studies, technical appendices, definitions, meaningful notes, and necessary media/objects. Do not repair or score contributor rosters, acknowledgments, dedications, publication/copyright/cataloging matter, promotional cover copy, repeated title pages, author biographies, duplicate printed Contents, or non-informational index/locator text.

## Privacy

Book text and page images may be copyrighted or private. Use local models where required, or obtain explicit user authorization before sending source content to a remote provider. Never place full source text, raw model responses, or credentials in this public repository.
