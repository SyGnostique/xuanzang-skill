# PDF, image, and OCR restoration

Use a page-first route for paginated sources. Preserve native text, page pixels, every OCR/layout result, and selection decisions as separate evidence.

## Contents

- [Classify before OCR](#classify-before-ocr)
- [Adapter roles](#adapter-roles)
- [Cross-page evidence](#cross-page-evidence)
- [Complex content](#complex-content)
- [Quality and review](#quality-and-review)
- [Acceptance canary](#acceptance-canary)

## Classify before OCR

Classify every PDF page and retain its coordinate transform. Review/citation runs render each page at a recorded DPI and hash the image. A born-digital `hint` run may use native text without a full-page PNG; it remains ineligible for citation until restored at review/citation evidence tier. Then route each page independently:

| Page class | Primary route | Required comparison |
| --- | --- | --- |
| native clean | native text + visual render | verify glyphs, order, assets, formulas, tables |
| scan | coordinate OCR + visual review | independent OCR or targeted manual check |
| mixed | native and OCR variants | compare missing regions and duplicated layers |
| layout-heavy | layout/table/VLM adapter + coordinate OCR | reconcile reading order with bboxes |
| blank candidate | visual confirmation | distinguish intentional blank from extraction failure |
| damaged/unsupported | quarantine or specialist adapter | retain pixels and blocker |

Record `route`, status, engine/version, confidence, bbox/polygon, coordinate space, page-image hash, language/script hints, and quality flags. A PDF text layer is useful evidence and never proof of visual completeness by itself.

## Adapter roles

The installed runtime determines which adapters are actually available. The names below define roles for integration and evaluation; they do not promise bundled models.

| Adapter role | Suitable use | Boundary |
| --- | --- | --- |
| Native PDF text | fast born-digital extraction with PDF coordinates | broken font maps, reading order, equations, and hidden OCR still need checking |
| Paddle coordinate OCR | Chinese/multilingual detection and recognition with bboxes | keep confidence and exact engine version; route low confidence to review |
| PP-Structure/layout adapter | tables, cells, columns, regions, reading order | retain cell geometry and visual page; structure output is a variant |
| PaddleOCR-VL-style adapter | complex scientific or mixed-layout page parsing | align generated text/Markdown back to coordinate evidence |
| Unlimited-OCR-style adapter | overlapping multi-page structure and continuation evidence | never select its long-window output directly as canonical text |
| Tesseract | independent QA, fallback scripts, or comparison | preserve language packs, configuration, and confidence limitations |
| Sidecar OCR | import trusted existing OCR such as Book M1 | require source/page crosswalk, engine provenance, and migration audit |
| `plugin:NAME` | installed third-party adapter seam | runtime forcibly requires exact page-image attestation and provenance review; the plugin cannot opt out |
| Mock | synthetic tests only | always block real citation and publication use |

`--ocr auto` must record the selected adapter and version. If a page requires OCR and the chosen adapter is unavailable, emit `ocr_required_but_unavailable`; never claim a silent native fallback.

Use native text when it is complete enough for the requested target. Keep OCR as a competing variant on suspicious pages. Prefer coordinate-preserving evidence for canonical anchoring even when a VLM produces cleaner Markdown.

The current sidecar seam accepts a JSON row list, a JSON object with `blocks`, or JSONL. Parsing requires a locator and valid bbox. Citation eligibility additionally requires all of the following:

- a locator: `page_id`, `page_anchor`, or integer `page` matching the active page;
- non-empty `text`;
- four numeric `bbox` values in `render_pixels` order `[x0,y0,x1,y1]`, inside the rendered page;
- `source_image_sha256` or `page_image_sha256` equal to the exact normalized/rendered page image consumed by OCR;
- producer provenance: `engine` and `engine_version` on each row, or on the JSON envelope;
- optional `confidence`, `block_kind`, `window_id`, and additional `metadata`.

```json
{"engine":"Unlimited-OCR","engine_version":"MODEL_OR_BUILD","blocks":[{"page_id":"page_0007","page_anchor":"page_0007","text":"...","bbox":[12,34,456,78],"source_image_sha256":"EXACT_RENDER_SHA256","confidence":0.97,"block_kind":"text_candidate","window_id":"w_0002","metadata":{"prompt_or_config_sha256":"..."}}]}
```

The parser rejects a missing locator or malformed bbox. Rows without producer metadata or an exact page-image hash may remain useful hint evidence, while restore records hard blockers for review/citation. Out-of-bounds geometry, mismatched hashes, and unreviewed provenance remain explicit findings. Importing a sidecar records evidence; it does not accept the external model's readiness claim.

For PDF, the page-image hash depends on `--render-dpi`. Produce the sidecar from page images rendered with that same policy, or first make a page-only evidence run, OCR its retained page images, then create a new sidecar-bound run. For image input, hash the normalized PNG stored by the extractor, not an EXIF-unrotated or differently composited original.

PDF OCR runs only on pages routed to OCR unless `--force-ocr` is set. Add `--force-ocr` when a sidecar must be imported as a competing variant on otherwise usable native-text pages.

Every affected sidecar page must resolve `sidecar_provenance_requires_review` with `method: producer_manifest_verified`, `producer_engine`, `producer_version`, and `input_sha256` equal to the run-bound sidecar digest. The gate checks these fields against retained evidence and the run manifest. Third-party plugins receive `external_ocr_*` blockers and cannot reach citation until their adapter path provides equivalent immutable provenance evidence; the current generic plugin seam does not create that manifest. If an image hash or bbox is wrong, regenerate the evidence or select a valid replacement; an assertion cannot repair immutable bad input. See `evidence-package.md` for executable resolution schemas.

Store sidecars at immutable, content-addressed paths. The run manifest binds the sidecar SHA-256 and locator. Never replace a sidecar in place. Sidecar bytes participate in the policy fingerprint; changing them creates a different deterministic run identity. Use `--new-run` only when an intentional rerun of otherwise identical inputs is required.

## Cross-page evidence

Use long-document OCR/VLM output to propose relationships that a page-local engine misses:

- paragraph continuation across a page turn;
- heading and subsection continuation;
- table continuation and repeated headers;
- footnote continuation;
- multi-page figure panels or captions;
- reading order across plates and inserts.

For an Unlimited-OCR-style adapter:

1. Use windows of 5–8 pages by default.
2. Overlap adjacent windows by at least one page.
3. Preserve explicit page separators and input image hashes.
4. Store the output as a text/structure variant with model, revision, prompt/configuration, and window ID.
5. Align every accepted relation to page-local block IDs and geometry.
6. Resolve disagreements through visual or semantic review.

Long-window output can improve structural context while downscaling can lose small print, footnotes, references, and table notes. Those regions require page-resolution evidence.

## Complex content

Represent each object and its relations explicitly:

- tables: table bbox, cells, row/column spans, repeated header, continuation link, caption, footnotes;
- formulas: visual bbox, source text/LaTeX variant, equation label, body references;
- figures/charts/maps: asset bytes, occurrence bbox, caption, panel labels, legends, axis labels, body references;
- footnotes/endnotes: marker, note body, backlink, continuation, page anchor;
- references/indexes: entry boundaries, locator tokens, intentional exclusion or retained reference-only role;
- vertical/RTL/multicolumn text: script direction, region order, line order, original polygons;
- stamps, watermarks, marginalia, handwriting: separate visual layers and explicit relevance decision.

Preserve exact numerals, signs, decimal separators, units, dates, chemical names, plot/site IDs, cultivar names, product names, superscripts, subscripts, and uncertainty marks. Record corrections; avoid silent normalization.

## Quality and review

Combine mechanical signals with semantic inspection:

- page/surface coverage;
- rendered-image success and hash stability;
- character/word error rate on gold samples;
- CJK, replacement-character, fallback-glyph, and garble rates;
- mean and tail confidence by page and region;
- engine disagreement, especially for numbers and entities;
- reading-order and heading-boundary accuracy;
- table cell, formula, caption, footnote, and reference preservation;
- reverse-location success from canonical paragraph to page/region;
- small-text, rotated-page, and low-contrast recall;
- runtime, memory, and cost per page.

Route any page with `ocr_failure`, `ocr_garble`, unresolved low confidence, missing region, unsupported layout, numeric disagreement, or coordinate gap to review. Confirm blank pages visually.

For `citation_grade`, inspect every paragraph-equivalent block that supports, constrains, qualifies, or is intentionally excluded from promoted content. OCR confidence cannot substitute for semantic reading.

## Acceptance canary

Before corpus rollout, build a rights-safe stratified set that includes:

- clean born-digital prose;
- Chinese and English scans;
- hybrid text/image pages;
- small-print notes and references;
- multicolumn scientific papers;
- dense tables and merged cells;
- equations, charts, figures, and captions;
- rotated, skewed, low-contrast, and damaged pages;
- frontmatter, TOC, body, bibliography, index, and intentional blanks;
- cross-page paragraphs and tables.

Compare at least native, primary OCR/layout, and independent QA routes where applicable. Accept an adapter only when it improves its declared role without regressing source coverage, anchors, numeric fidelity, or hard cases. Keep the prior adapter available for rollback.
