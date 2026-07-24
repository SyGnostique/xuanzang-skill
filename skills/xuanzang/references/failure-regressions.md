# Xuanzang Failure Regressions

This registry turns prior rebuild failures into mandatory checks. When a matching symptom appears, fix the earliest evidence layer and run the listed proof. Do not relax a hard gate globally.

| Failure class | Historical symptom | Required detection/proof |
|---|---|---|
| False structural PASS | Entire book became one chapter; short prose, bylines, captions, or running headers became headings | Whole-book canonical TOC; every candidate dispositioned; exact paragraph partition; reverse TOC audit |
| Partial TOC | Only first printed Contents page was read | Visual inventory of every TOC page; one reconciled transcription across all pages |
| Spine/page-as-chapter | EPUB spine files or PDF pages became chapters | Semantic architecture plus canonical body anchors; no source-container-only chapter |
| Offset drift | Fixed printed-to-PDF page offset failed later | Per-node anchor evidence; no global offset as sole boundary authority |
| Native text corruption | `soundscape` became `sound scape`; words were joined/split by OCR repair | Native DOM text hash retained; OCR repair forbidden on native route; round-trip regression |
| Broad paragraph joins | Thousands of line joins hid sentence damage or fused sections | Repair only reviewed OCR spans; source reconstruction for every text chunk; no global join allowlist |
| Wrong OCR language | Chinese scan used English OCR; Tesseract received `en` instead of `eng` | Adapter language mapping test; run manifest engine/language evidence; visual sample audit |
| OCR contention | Paddle workers stalled or exceeded local capacity | Disk/memory/process admission; bounded workers; resumable per-page ledger |
| Missing scanned PDF pages | Born-digital PDF contained full-image pages that native extraction skipped | Per-page route classification; supplemental OCR merged by page hash |
| Incomplete visual audit | ffmpeg concat/contact sheet showed only first image in a group | Numbered contact sheets or page renders proving every page is visible |
| Vector figure loss | `page.get_images()` missed pure-vector figures | Vector-region extraction test; figure captions and graphics both represented |
| Single-column split | Correct reading order was replaced by left/right halves | Visual layout classification and source-order reconstruction audit |
| Multi-column flattening | Index/table columns read across rows | Geometry plus semantic continuity; visual region order fixture |
| Empty/duplicate sections | Mechanical tree emitted empty nodes or duplicate title | Exactly one H1; H2/H3 only; empty-leaf check; canonical heading sequence validation |
| Callout-as-chapter | “PIP #...” or similar callouts materialized as chapters | Object classification and container policy; callout remains object/prose |
| TOC residue | Printed Contents and EPUB nav both appeared as body | Navigation/reference-only classification; no duplicate structural projection |
| Index fragmentation | Index entry split into word, page, and range fragments | Index object/entry representation; visual reading-order audit |
| Flattened tables | A 24x7 grid was visible but row/column relations were lost | Typed cell matrix; Markdown table rendering; expected/rendered table object equality |
| Duplicate-cell mapping | Equal `<td><p>16:9</p></td>` values mapped to the first column via `list.index` | Position-based DOM enumeration fixture with repeated equal cells |
| Caption-image drift | Correct caption linked to unrelated nearby paragraph/image | Independent asset occurrence plus evidence-backed relation; unsupported relation blocks |
| Asset order drift | Caption-linked and unlinked figures were reordered | Immutable occurrence order; exact-once publication order equality |
| Cover/logo omission | Visual assets existed outside body chunks | Active asset coverage and exact-once visual chunk/reference proof |
| Source text as Markdown | Literal `# of Shots` became a heading | Escape source-origin Markdown structure; headings emitted only from reviewed structure |
| Hidden EPUB text leak | CSS-hidden navigation/alternate content entered output | Visibility audit and zero hidden DOM path chunks |
| Stale parent invariant | Joined parent text masked corrected child blocks | Rebuild projections from immutable raw blocks and active correction head |
| Stale object override | Old table/caption text replaced current canonical sentence | Current canonical revision wins; object relation never mutates canonical prose |
| Backmatter loss | Notes, bibliography, glossary, appendix, or index disappeared | Semantic-type ledger and complete source accounting |
| Furniture pollution | Copyright, biographies, duplicate Contents, promo copy polluted citation output | `reference_only`/excluded source accounting; active `used` projection only |
| False old PASS | Previous gate/export was copied after source or config changed | Source/run/canonical/review identity equality and all artifact hashes |
| Score as authority | High numeric score hid unresolved local blockers | Scores optional; only package gate plus local acceptance can complete |
| Scorer process failure | 300-second timeout, oversized dossier, quota 403, schema/validator errors | Preserve `process_failure`; no content verdict; local workflow continues independently |
| Parallel writer interference | Multiple tasks changed package scripts/state across scope | One materialization writer per package; proposal-only reviewers; isolated work roots |

## Universal repair rule

For every regression:

1. reproduce on a minimal fixture or the exact affected evidence;
2. identify extraction, canonicalization, structure, relation, materialization, or publication as the earliest faulty layer;
3. repair that layer narrowly;
4. add a deterministic test that fails before the repair;
5. rerun package gate, publication validation, and local acceptance;
6. never convert a book-specific exception into a universal suppression rule.
