# Scenarios and targets

Use this reference to choose the smallest workflow that satisfies the requested evidence standard.

## Contents

- [Trust targets](#trust-targets)
- [Runtime capability states](#runtime-capability-states)
- [Source routing](#source-routing)
- [Source-bundle manifest](#source-bundle-manifest)
- [Deliverable routing](#deliverable-routing)
- [Special scenarios](#special-scenarios)
- [Profile checklist](#profile-checklist)

## Trust targets

Trust and deliverable state are separate axes.

| CLI target | Package trust status | Allowed use | Required boundary |
| --- | --- | --- | --- |
| `hint` | `hint_only` | discovery, candidate recall, triage, OCR comparison, source finding | disclose uncertainty; prevent formal claims and trusted embedding |
| `review` | `needs_review` | research assistance, internal reading, review queues, draft synthesis | preserve findings and anchors; disclose review status |
| `citation` | `citation_grade` | source-backed answers, formal knowledge objects, trusted retrieval, policy or technical evidence | `PASS_STRICT`; full semantic paragraph coverage; zero hard blockers |

Choose `citation` whenever an output may support a published claim, scientific conclusion, policy recommendation, agronomic instruction, legal/medical/safety decision, benchmark ground truth, or formal team deliverable.

`publish --target hint` exports a disclosed discovery artifact. `publish --target citation` requires citation eligibility. Exporting never upgrades package trust.

`xuanzang status PACKAGE` recomputes the **citation** gate by default. Its `evaluated_target` field makes that choice explicit, and `gate_status` reports current `PASS_STRICT` or `FAIL_REVIEW` citation eligibility even when the last restore requested `hint` or `review`. Use `xuanzang status PACKAGE --target hint` or `--target review` to recompute an operational tier; stored gate reports remain snapshots rather than authority.

## Runtime capability states

Use exactly these three labels when describing 2.0 capability:

- `v2_native`: implemented by `restore`, `review`, `status`, `publish`, `migrate-*`, or `revoke`, with v2 evidence and gates;
- `compatibility_only`: retained v1 command or artifact path; useful for migration or a draft derivative, never proof of v2 trust;
- `orchestrator_or_adapter`: an upstream, downstream, service, or plugin responsibility that the core CLI does not implement.

| Use case | State | Current boundary |
| --- | --- | --- |
| PDF, EPUB, DOCX, TXT, Markdown, HTML, raster image, image-directory restore | `v2_native` | Source-specific unsupported features remain blockers. |
| JSON/YAML ordered source bundle | `v2_native` | Use the schema below; nested depth is limited to two. |
| MOBI/AZW3 ingestion | `v2_native` when local Calibre exists | `ebook-convert` must be available and allowed; conversion provenance is retained. |
| Paddle, Tesseract, mock, sidecar, or `plugin:NAME` OCR | `v2_native` adapter seam | `mock` always blocks citation; sidecar needs exact image/provenance evidence; generic plugins are forced through anchor/provenance blockers and remain citation-blocked until an adapter supplies immutable provenance. |
| Canonical text correction, semantic review, target gates, Markdown/chunk export, embedding invalidation manifest | `v2_native` | The embedding manifest contains no vectors. |
| Bounded local corpus batch | `v2_native` | Independent per-source packages, worker bound, accounting, fail-fast drain; no distributed scheduler or global deduplication. |
| v1 and Book M1 non-destructive migration | `v2_native` migration | Imported historical PASS is downgraded and v2 review remains required. |
| Translation preparation/mock run/audit scaffold | `compatibility_only` | Existing commands are v1 mechanics; no v2 translation trust or publication gate. |
| `assemble-docx` and `reinsert-epub` | `compatibility_only` | Existing commands are v1 derivatives; they are not v2 publication exporters. |
| Remote OCR/VLM/translation execution | `orchestrator_or_adapter` | Requires an installed adapter plus explicit provider/data authorization. |
| Authenticated reviewer identity, job queues, leases, rate limits | `orchestrator_or_adapter` | CLI expected-scope flags are compare-and-reject guards, not authentication. |
| Vector generation/storage, namespace ACL enforcement, retrieval filtering | `orchestrator_or_adapter` | Consume `chunks.jsonl` and `embedding_manifest.json`; enforce every scope field downstream. |
| Physical deletion, cache/vector purge, deletion acknowledgements | `orchestrator_or_adapter` | `revoke` emits a tombstone and disables package use; downstream systems must act and acknowledge. |
| TEI, ALTO/hOCR, searchable PDF, accessibility, edition alignment, v2 DOCX/EPUB publication | `orchestrator_or_adapter` | Implement a dedicated exporter/adapter and its own validation gate before claiming support. |

Anything absent from this matrix is unavailable until the active runtime or an installed plugin proves it. Do not infer capability from a prompt, filename, or reference design.

## Source routing

Probe installed adapters with `xuanzang --help`. The current v2 runtime accepts PDF, EPUB, DOCX, TXT, Markdown, HTML, common raster images, image directories, and MOBI/AZW3 when local Calibre conversion is available. Route any additional format only through an adapter exposed by the installed runtime; otherwise make a provenance-preserving conversion and retain the original bytes.

| Source scenario | Evidence route | Required checks |
| --- | --- | --- |
| Born-digital PDF | native text; review/citation runs add page renders, while hint may skip them | font maps, reading order, missing glyphs, tables, formulas, page anchors |
| Scanned PDF | page render + coordinate OCR + independent QA or review | rotation, crop, small text, blank pages, confidence, garble, printed/PDF page mapping |
| Hybrid PDF | classify every page; route page-by-page | hidden OCR mismatch, image-only inserts, repeated layers, mixed orientations |
| Scientific paper | page/layout evidence + logical article structure | abstract, headings, equations, tables, figures, references, supplementary boundaries |
| Book or thesis | TOC-first reconstruction + page/block/paragraph ledger | front/body/back matter, chapter starts, notes, bibliography, index, plates |
| Report/manual/standard | hierarchy + numbered clauses + cross-reference objects | versions, annexes, tables, warnings, normative/informative boundaries |
| EPUB reflowable | one surface per OPF spine occurrence + DOM/assets + typed nav/NCX candidates | canonical OCF hrefs, repeated-spine ambiguity, DOM paths, notes, images, CSS-sensitive reading order; UTF-8/16 XML is parsed under a DTD/entity-deny policy |
| Fixed-layout EPUB | current v2 DOM/spine/assets plus an external renderer when visual fidelity matters | visual rendering is not native; overlays, reading order, and fonts remain blockers until an adapter supplies evidence |
| DOCX | native OOXML story extraction | paragraphs/tables, footnotes/endnotes/comments, headers/footers, tracked deletions, equations, text boxes, and embedded objects |
| Other office document | provenance-preserving conversion or installed adapter | retain original hash, converter version, loss report, and source-to-rendition relation |
| Image bundle | ordered manifest + one image surface per file | file order, duplicates, orientation, missing frames, EXIF, OCR/layout |
| MOBI/AZW3/legacy DOC | convert through a named tool; retain hash and conversion manifest | DRM/permission, converter version, lost features, source-to-rendition relation |
| HTML/TXT/Markdown | logical native blocks; use `--preserve-source` when exact original bytes are required | current line/DOM anchoring is limited; verify encoding, includes, linked assets, and generated/navigation residue |
| Multi-file work or supplement bundle | JSON/YAML bundle manifest | source role, edition, order, hashes, missing members, rights; never silently concatenate |
| Existing page-aligned OCR | sidecar against retained page images or Book M1 migration | exact image hash, locator, bbox, engine/version, page/span crosswalk, provenance review |
| Existing clean Markdown without source crosswalk | restore only as its own text source or quarantine as hint | it cannot inherit the unseen original's citation authority |
| Encrypted, damaged, DRM, unsafe, or unauthorized | quarantine | reason, owner, access decision, no silent bypass |

Handwriting, ancient vertical text, rare glyphs, RTL layouts, dense mathematics, music notation, chemical structures, maps, and diagram-only pages require specialist adapters or explicit preprocessing/review when the installed runtime lacks that feature. Multi-frame TIFF is expanded into ordered image surfaces, while every frame still needs orientation, OCR, and semantic review. Preserve original visual evidence and transformation provenance even when text recovery remains unresolved.

## Source-bundle manifest

Passing a `.json`, `.yaml`, or `.yml` source to `restore` means that file is a bundle manifest. It must contain a non-empty `sources` list. JSON works without an optional parser; YAML requires PyYAML.

```yaml
bundle_id: work-supplements-2026             # optional metadata
work_identity:                               # optional, retained as metadata
  title: Example work
rights:                                      # optional, retained as metadata
  basis: user_supplied_private
sources:
  - locator: main.pdf                        # required; relative to this manifest by default
    order: 10                                # integer; default 0, then locator sorts ties
    source_id: main                          # optional; unique safe ID, max 128 chars
    source_role: primary                     # optional; default primary
    expected_sha256: "..."                   # optional content/graph digest assertion
    edition: first                           # optional; different editions in one canonical are blocked
  - locator: supplements/images              # an image directory is valid
    order: 20
    source_id: supplement_figures
    source_role: supplement
```

The runtime prefixes surface, evidence, block, asset-occurrence, and TOC candidate IDs with `source_id`, then preserves member hash and role. `source_role` is carried into primary-anchor checks; use `primary` only for a source eligible to support primary claims.

Bundle safety and identity rules:

- Locators are confined to the manifest directory by default. `--allow-external-bundle-sources` is an explicit caller authorization; a manifest cannot grant itself filesystem access.
- Missing members, duplicate/unsafe `source_id`, symlinked sources, hash mismatch, or nesting deeper than two stops restore.
- A nested bundle's `expected_sha256` is its graph digest, not merely the manifest-file hash.
- The bundle source hash binds the manifest bytes plus ordered member digests. Changing the manifest, a member, order, role, or expected digest creates a different identity/policy outcome.
- Multiple declared `edition` values create `cross_edition_merge_forbidden`. Restore editions as independent packages and align them downstream.
- A bundle can combine a primary work and supplements. It cannot silently turn a secondary/reference member into a primary anchor.

## Deliverable routing

| Deliverable | Minimum trust | Runtime state | Additional work |
| --- | --- | --- | --- |
| Source inventory or discovery index | `hint_only` | `v2_native` | isolate from trusted indexes and expose status |
| Hint or citation Markdown/chunks | target-dependent | `v2_native` | `publish` emits Markdown, JSONL chunks, gate snapshot, export manifest, and unembedded invalidation manifest |
| Vector retrieval index | target-dependent | `orchestrator_or_adapter` | vectorize downstream; separate hint/trusted namespaces and enforce tenant/workspace/access tags at query time |
| Knowledge cards/pages/claims | `citation_grade` for formal use | `orchestrator_or_adapter` | anchor every promoted statement; preserve claim/method/metric/boundary distinctions |
| Translation draft | `needs_review` | `compatibility_only` in current CLI | stable source units, terminology, mechanical validation, and a future v2 deliverable gate |
| Publication translation | source `citation_grade` plus deliverable semantic audit | `orchestrator_or_adapter` | current mock/audit commands cannot establish this state |
| EPUB/DOCX publication | source target plus deliverable validation | `compatibility_only` commands; v2 exporter absent | assets, links, notes, navigation, accessibility, package validity |
| Dataset/evaluation ground truth | `citation_grade` | `orchestrator_or_adapter` | reviewer provenance, immutable release snapshot, leakage policy |
| Archive/TEI/hOCR/ALTO or diplomatic transcription | target-dependent | `orchestrator_or_adapter` | dedicated exporter; preserve line/column order, glyph variants, corrections, and raw visual anchors |
| Searchable PDF/accessibility layer | source target plus deliverable validation | `orchestrator_or_adapter` | dedicated exporter; verify OCR overlay coordinates, reading order, language, and reviewed alt text |
| Cross-edition alignment | each edition restored independently | `orchestrator_or_adapter` | export relations between stable paragraphs; never merge edition canonicals |

The current v2 `publish` command emits anchored Markdown, chunks, an embedding invalidation manifest, a gate snapshot, and an export manifest. It does not create vectors. DOCX/EPUB and translation commands remain compatibility-only. Other formats require a separately implemented exporter that consumes the evidence package and records its own validation.

## Special scenarios

### Batch corpus

Run `xuanzang batch SOURCE_DIR --out-root CORPUS_BUILD --target hint --workers N` for bounded local compilation. Inventory and deduplicate before restore, run a representative canary stratified by source type and difficulty, and keep per-source packages and gates. Review `batch_results.jsonl` plus `batch_manifest.json`; a corpus-level average cannot promote failed members. Rerun chosen packages at review/citation evidence tier before semantic promotion.

### Incremental or revised source

Use `--accept-source-update` to create a new source revision and run while preserving prior run directories. The current CLI binds the new head so old review projections cannot authorize it; it does not compute a structural-delta report, reuse changed-source blocks across runs, or update an external stale-artifact registry. Downstream consumers compare source/run/canonical/review revisions and export invalidation keys.

### Editions and normalization

Restore each edition as an independent package. Link corresponding paragraphs through a derived alignment artifact. For archives, ancient texts, or historically significant spelling, retain a `diplomatic` transcription and place any normalized form in a separate text variant with an explicit decision. The normalized form never overwrites glyph, line, column, or source-order evidence.

### Team review

Bind decisions to the expected package revision. Record reviewer identity, role, reason, evidence, timestamp, and supersession. Route conflicting decisions to a named resolution queue.

### Multi-tenant service

`--privacy workspace` requires `--workspace-id`; `--privacy tenant` requires `--tenant-id`. Propagate tenant, workspace, privacy, access tags, rights, and retention fields to every run and export. The core CLI records and compares scope. Authentication, authorization, workspace membership, vector namespace/row ACLs, remote-provider policy, and deletion acknowledgements belong to the trusted orchestrator and storage systems.

### External research

Store external material as a separate source with its own provenance. Use it to challenge, compare, or locate primary sources. Keep local source truth unchanged until a review decision explicitly incorporates supported evidence.

### Module boundary

Author search, bibliographic identity resolution, rights acquisition, and downloading belong upstream. Vector databases, user memory, answer generation, and team chat belong downstream. Xuanzang begins with acquired source bytes or an authorized source bundle and ends with a trust-labelled evidence/export package. Preserve these boundaries in platform orchestration.

## Profile checklist

Before `restore`, record:

```yaml
requested_target: hint | review | citation
document_kind: ...
source_family: ...
tenant_id: ...
workspace_id: ...
privacy: local_only | workspace | tenant
access_tags: []
rights_basis: ...
languages: []
expected_layouts: []
required_objects: [text, tables, figures, formulas, notes]
allowed_local_adapters: []
allowed_remote_providers: []
deliverables: []
retention_policy: ...
```

Complete scope only when every field affecting routing, authorization, or trust is explicit.
