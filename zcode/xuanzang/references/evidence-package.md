# Evidence package contract

This file defines the durable v2 contract. Treat package files as evidence and decisions, never as disposable parser output.

## Contents

- [Package layout](#package-layout)
- [Identity and revisions](#identity-and-revisions)
- [Surface and block ledgers](#surface-and-block-ledgers)
- [Canonical paragraphs](#canonical-paragraphs)
- [Asset occurrences](#asset-occurrences)
- [Review decisions](#review-decisions)
- [States and gates](#states-and-gates)
- [Validation invariants](#validation-invariants)

## Package layout

The active runtime projects one selected run into stable top-level paths while retaining every committed run:

```text
PACKAGE/
├── package_manifest.json
├── source/source_inventory.json   # active source identity projection
├── ledger/
│   ├── surfaces.jsonl              # canonical universal surface ledger
│   ├── pages.jsonl                 # compatibility surface projection
│   ├── evidence_blocks.jsonl       # immutable native/OCR/parser observations
│   ├── canonical_blocks.jsonl      # selected block views with evidence links
│   ├── canonical_reviewed.jsonl    # optional reviewed correction projection
│   ├── paragraph_candidates.jsonl  # canonical paragraph candidates + coverage fields
│   ├── paragraph_candidates_reviewed.jsonl
│   ├── paragraph_coverage.jsonl    # materialized latest semantic coverage
│   ├── reasoning_leap_candidates.jsonl
│   ├── assets.jsonl                # asset occurrences and anchors
│   ├── objects.jsonl               # tables/equations/captions/figures
│   └── review_decisions.jsonl      # append-only semantic decisions
├── toc/
│   ├── toc_candidates.json
│   └── canonical_toc.json
├── audit/
│   ├── extraction_audit.json
│   ├── gates/{hint,review,citation}.json
│   ├── gate_report.json             # canonical/latest citation snapshot after status
│   ├── pass_fail_{target}.json
│   ├── pass_fail.json
│   ├── revocation_tombstone.json    # revoked packages only
│   ├── migration_report.json       # imported packages only
│   └── migration_id_crosswalk.jsonl
├── runs/<run_id>/
│   ├── run_manifest.json
│   ├── source_inventory.json
│   ├── source/                    # optional preserved source bytes
│   ├── ledger/
│   ├── toc/
│   ├── audit/
│   ├── assets/                     # immutable rendered/extracted binary evidence
│   └── checkpoints/                # format-dependent retry checkpoints
├── history/events.jsonl
└── legacy/v1_snapshot/             # optional protected v1 snapshot
```

Use the paths emitted by the installed runtime when it adds format-specific artifacts. Never infer readiness from file presence alone; recompute the gate.

`surfaces.jsonl` is the canonical ordered document-surface ledger. `pages.jsonl` is its compatibility projection. For PDF and image bundles a surface represents a physical page. For EPUB it represents a spine item; for DOCX, HTML, text, and Markdown it may represent a logical document story. Check `surface_kind`, `source_page`, `spine_index`, `route`, and coordinate metadata before calling an anchor a page citation.

## Identity and revisions

`package_manifest.json` must bind:

```yaml
package_version: 2
pipeline_version: ...
package_id: ...
source:
  path: ...
  sha256: ...
  format: ...
active_run_id: ...
runs: []
trust_status: hint_only | needs_review | citation_grade
updated_at: ...
canonical_revision: ...
review_revision: ...
review_ledger_sha256: ...
paragraph_projection_sha256: ...
toc_projection_sha256: ...
boundary_projection_sha256: ...
```

Each `runs/<run_id>/run_manifest.json` must record source hash, policy fingerprint, pipeline/schema versions, configuration, required artifact list, artifact digest root, external-input digests, and timestamps. Package lifecycle lives in `package_manifest.json`. Use deterministic run IDs for identical source plus policy. Use a new run for changed source, adapter configuration, or intentional reprocessing.

Preserve all committed runs. Projecting the same active head may retain its bound review projections. Switching run or source heads restores generated projections and prevents old decisions from leaking into the new head; old run directories and ledger history remain available for audit. A source hash mismatch must stop reuse unless `--accept-source-update` is explicit.

The current manifest `scope` carries `privacy`, `tenant_id`, `workspace_id`, `rights_basis`, `retention_policy`, and `access_tags`. `--privacy workspace` is invalid without `--workspace-id`; `--privacy tenant` is invalid without `--tenant-id`. Namespace creation and authorization provenance belong to the hosting orchestrator. Carry scope into every export and compare expected scope on protected calls.

## Surface and block ledgers

Every surface row needs a stable ID, order, source locator, route, state, and quality signals. Paginated sources also need the rendered image hash and printed-page mapping when available.

```yaml
surface_id: page_0042
surface_kind: pdf_page
page_id: page_0042
ordinal: 42
source_page: 42
printed_page: 27
width: 595.0
height: 842.0
rotation: 0
page_image_path: runs/RUN_ID/assets/pages/page_0042.png
page_image_sha256: ...
route: native_text | ocr | hybrid | epub_dom | docx_xml | blank_review
status: pending | extracted | blank_candidate | unresolved | quarantined | failed
quality_flags: []
```

Every evidence block is an observation from a named engine or native layer:

```yaml
evidence_id: ev_...
page_id: page_0042
ordinal: 17
engine: pdf_native | paddle | tesseract | sidecar | epub_dom | docx_xml | ...
engine_version: ...
text: ...
text_sha256: ...
bbox: [x0, y0, x1, y1]
coordinate_space: pdf_points | render_pixels | dom_path | docx_xml | text
confidence: 0.97
block_kind: text_candidate | heading_candidate | caption_candidate | table_candidate | ...
metadata: {}
```

Keep competing variants as separate evidence rows. A canonical block contains `evidence_id`, selection status, selection reason, and the source anchor. Human repair creates a decision or a new derived revision; it never mutates the observation.

For DOM/XML sources, store href/part, DOM or OOXML path, paragraph/run identifier, and character range in `metadata`. For visual sources, store bbox or polygon plus coordinate space. An anchor without its coordinate system is incomplete.

## Canonical paragraphs

A paragraph candidate may span one or more blocks. Its `source_spans` must reverse-locate every selected token to evidence:

```yaml
paragraph_id: para_...
order: 42
text: ...
text_sha256: ...
block_kind: text_candidate
source_spans:
  - page_id: page_0042
    block_id: blk_...
    evidence_id: ev_...
    bbox: [x0, y0, x1, y1]
coverage_status: unreviewed
producer:
  kind: mechanical_candidate
  pipeline_version: ...
  engine: ...
```

Canonical paragraph boundaries may join line wraps or split parser blocks, provided the mapping retains all contributing spans. Never delete the source units after a join.

Citation-grade paragraph coverage requires these semantic fields, either on the candidate plus an accepted decision or in the decision itself:

```yaml
source_id: ...
sourcepage_path: ...
paragraph_id: ...
page_anchor: ...
paragraph_role: definition | mechanism | method | metric | case | boundary | caveat | reference_only | excluded
semantic_summary: ...
claim_candidates: []
method_candidates: []
metric_candidates: []
boundary_candidates: []
reasoning_leap_candidates: []
used_in_card: true | false
use_reason: ...
exclusion_reason: ...
requires_primary_anchor: true | false
semantic_reading: true
```

Regex scans, embeddings, parsers, validators, and batch tables can check bookkeeping after semantic reading. They cannot assign paragraph meaning or citation readiness.

## Asset occurrences

Separate content identity from occurrence identity:

- `asset_id` and `asset_sha256` deduplicate shared bytes;
- `occurrence_id` identifies each location in reading order;
- page/DOM/XML anchor locates the occurrence;
- caption, body reference, table/formula structure, and review status remain explicit relations.

Every occurrence must be reviewed or deliberately excluded. A shared image used three times has one asset and three occurrence decisions. Missing bytes, missing caption relation, or missing occurrence anchor block citation promotion for the affected scope.

## Review decisions

`xuanzang review` accepts a JSON array, `{ "decisions": [...] }`, or JSONL. It validates the whole batch before the first durable write. Decisions form a hash chain and remain append-only. The latest valid `(kind, target_id)` row is active; a replacement must list the prior `decision_id` in `supersedes`.

Run with optimistic concurrency and scope guards:

```bash
xuanzang review PACKAGE \
  --decisions decisions.jsonl \
  --expected-revision REVIEW_REVISION \
  --expected-tenant-id TENANT \
  --expected-workspace-id WORKSPACE
```

Omit expected tenant/workspace only for a local package with no such scope. These flags compare caller expectations with package metadata; they do not authenticate a user.

### Common semantic fields

Use these fields on every meaning-level decision:

```yaml
kind: page | paragraph | asset | object | structure | source_boundary | canonical_block
target_id: ...
disposition: reviewed | blank_confirmed | quarantined | used | excluded | reference_only | selected | rejected
semantic_reading: true
reviewer_type: human | agent_semantic
reviewer_id: ...
reason: ...
resolves: []
resolution_evidence: []
supersedes: []
```

The runtime fills and binds `source_sha256`, `active_run_id`, `canonical_revision`, `created_at`, `policy_version`, and content-derived `decision_id` when omitted. Supplied head fields must match. Never invent `decision_id`; copy it from the accepted ledger only when superseding it.

For `privacy=workspace` or `privacy=tenant`, local CLI assertions receive `reviewer_attestation=local_self_asserted` and cannot satisfy citation reviewer provenance. A trusted service must call `apply_review(..., reviewer_context=ReviewerContext(..., verified=True))` after authenticating membership. That context writes the verified review session plus tenant/workspace binding. Authentication is outside this package format.

### Page decision and typed blocker resolution

Use `kind: page` with the exact `page_id` for citation review. `surface` is an accepted auxiliary kind but does not replace citation page accounting.

```json
{"kind":"page","target_id":"page_0007","disposition":"reviewed","semantic_reading":true,"reviewer_type":"human","reviewer_id":"reviewer-1","reason":"Compared every visible region, text variant, and page image","resolves":["sidecar_provenance_requires_review"],"resolution_evidence":[{"code":"sidecar_provenance_requires_review","method":"producer_manifest_verified","verified":true,"producer_engine":"Unlimited-OCR","producer_version":"MODEL_OR_BUILD","input_sha256":"EXACT_SIDECAR_SHA256"}]}
```

Every code in `resolves` requires a matching object in `resolution_evidence` with the same `code`, a registered `method`, and `verified: true`. Review rejects unknown code/method pairs. The gate then verifies method-specific evidence against current ledgers, hashes, canonical selections, page images, assets, run inputs, or structure decisions; the three strings alone never clear a blocker. Current registered methods are:

| Blocker code | Allowed `method` |
| --- | --- |
| `sidecar_source_image_unverified` | `source_image_hash_verified` or `replacement_evidence_selected` |
| `sidecar_provenance_requires_review` | `producer_manifest_verified` |
| `external_ocr_source_image_unverified` | `source_image_hash_verified` or `replacement_evidence_selected` |
| `external_ocr_provenance_requires_review` | `producer_manifest_verified` |
| `ocr_bbox_invalid`, `legacy_ocr_bbox_invalid` | `corrected_bbox_attached` or `block_quarantined` |
| `mixed_visual_region_requires_reconciliation` | `visual_regions_reconciled` |
| `multi_column_reading_order_requires_review` | `reading_order_verified` or `canonical_order_corrected` |
| `low_ocr_confidence_unresolved`, `weak_native_text_layer_unresolved` | `visual_transcription_verified` or `replacement_evidence_selected` |
| `tracked_changes_require_review` | `accepted_view_selected` or `alternate_variants_preserved` |
| `textbox_reading_order_requires_review` | `reading_order_verified` |
| `equation_representation_requires_review` | `visual_representation_verified` |
| `fixed_layout_requires_rendered_evidence` | `rendered_rendition_attached` |
| `visual_only_spine_requires_rendered_evidence` | `rendered_rendition_attached` |
| `epub_navigation_target_unresolved` | `navigation_target_reconciled` |
| `local_conversion_requires_review` | `source_and_rendition_compared` |
| `external_image_reference_requires_review`, `missing_image_asset` | `asset_ingested_and_hashed` or `asset_quarantined` |
| `unsafe_relationship_target` | `asset_quarantined` |
| `book_m1_image_missing` | `asset_ingested_and_hashed` or `page_quarantined` |

A typed assertion records completed verification; it cannot make a false hash, missing binary, unsupported object, or unread page valid. Repair/reingest first when evidence is wrong. Use `blank_confirmed` only after visual inspection of an intentional blank.

Method payloads are evidence-bearing: image/provenance methods use exact run-bound hashes; replacement/corrected-bbox methods list the exact `affected_evidence_ids`, prove all affected rows have left the canonical projection, and name a different valid `replacement_evidence_id` selected into it; reading-order methods provide `ordered_block_ids` equal to the materialized order; region reconciliation includes a non-empty `region_map`; rendition/asset methods name the retained `artifact_path` and SHA-256; navigation reconciliation names a current candidate, reviewed disposition, and valid surface. A loose note or unattached bbox is insufficient.

### Paragraph decision

Create one decision for every active paragraph ID. All five candidate arrays and both booleans are mandatory; arrays may be empty.

```json
{"kind":"paragraph","target_id":"para_...","disposition":"used","source_id":"SOURCE_SHA256","sourcepage_path":"xuanzang://source/SOURCE_SHA256/surface/page_0007","paragraph_role":"method","semantic_summary":"The paragraph defines the sampling and measurement procedure.","claim_candidates":[],"method_candidates":[{"text":"...","source_span_ids":["blk_..."]}],"metric_candidates":[],"boundary_candidates":[],"reasoning_leap_candidates":[],"used_in_card":false,"requires_primary_anchor":true,"semantic_reading":true,"reviewer_type":"human","reviewer_id":"reviewer-1","reason":"Retained as source-supported method evidence"}
```

Required lists are `claim_candidates`, `method_candidates`, `metric_candidates`, `boundary_candidates`, and `reasoning_leap_candidates`. Required booleans are `used_in_card` and `requires_primary_anchor`. `source_id` must equal the paragraph source ID. `sourcepage_path` must contain the paragraph's current `page_id`. `semantic_summary`, `paragraph_role`, and `reason` must be non-empty. Allowed roles are `definition`, `mechanism`, `method`, `metric`, `case`, `boundary`, `caveat`, `reference_only`, and `excluded`.

A non-empty reasoning-leap entry must contain non-empty `premises`, `premise_paragraph_ids`, `inference`, `novelty_context`, `source_local_boundary`, `uncertainty`, and `reviewer_status`; it also carries list-valued `conclusion_paragraph_ids`, `assumptions`, `counterevidence`, `alternatives`, and `testable_predictions`. The host paragraph and every ID in `premise_paragraph_ids` or `conclusion_paragraph_ids` must have disposition `used`, so citation export contains every referenced paragraph and cannot emit dangling IDs. `reviewer_status` is `candidate`, `verified`, or `rejected`. Keep a source-local candidate distinct from cross-source novelty. A `used` paragraph with `requires_primary_anchor: true` must come from a member whose `source_role` is `primary`. Use `excluded` or `reference_only` only with the semantic reason that the material is outside promoted use; keep such support as prose in `counterevidence` until a separately exported supporting-evidence ledger is available.

### Asset and complex-object decisions

Use the occurrence ID from `ledger/assets.jsonl`, never only the content-deduplicated `asset_id`:

```json
{"kind":"asset","target_id":"occ_...","disposition":"reference_only","semantic_reading":true,"reviewer_type":"human","reviewer_id":"reviewer-1","reason":"Occurrence, bytes, position, and relevance were checked; retained for navigation only"}
```

Every occurrence needs `used`, `excluded`, or `reference_only`. Exclusions and reference-only rows require a reason. An externally referenced binary cannot be promoted as `used` for citation; preserve it inside the package first.

Use the object ID from `ledger/objects.jsonl`:

```json
{"kind":"object","target_id":"obj_...","disposition":"used","representation_status":"verified","visual_verified":true,"source_verified":false,"relations_reviewed":true,"semantic_reading":true,"reviewer_type":"human","reviewer_id":"reviewer-1","reason":"Text/visual representation, caption relation, units, and source anchor were verified"}
```

Every object needs `used`, `excluded`, or `reference_only`. A used object requires `representation_status: verified`; a used table/equation also requires `visual_verified: true` or `source_verified: true`; a used caption/figure requires `relations_reviewed: true`. Excluded/reference-only objects require a reason.

### Structure and source-use boundary

For a multi-surface source or any EPUB, include every active surface ID exactly:

```json
{"kind":"structure","target_id":"canonical","disposition":"reviewed","covered_surface_ids":["page_0001","page_0002"],"candidate_dispositions":[{"candidate_id":"toc_candidate_1","disposition":"used","reason":"Verified against body structure"}],"toc_items":[{"toc_id":"toc_1","title":"Chapter 1","boundary_id":"boundary_1","source_candidate_ids":["toc_candidate_1"]}],"boundaries":[{"boundary_id":"boundary_1","title":"Chapter 1","structure_path":["Chapter 1"],"surface_ids":["page_0001","page_0002"],"paragraph_ids":["para_1","para_2","para_3"]}],"semantic_reading":true,"reviewer_type":"human","reviewer_id":"reviewer-1","reason":"Reading order, hierarchy, boundaries, and complete surface coverage were checked"}
{"kind":"source_boundary","target_id":"SOURCE_SHA256","disposition":"reviewed","text":"Permitted evidence use, citation scope, rights, and transfer limits ...","semantic_reading":true,"reviewer_type":"human","reviewer_id":"reviewer-1","reason":"Source-level use boundary recorded"}
```

The structure target must be `canonical`; the boundary target must equal the active source SHA-256. `covered_surface_ids` must exactly match active surfaces in source order. Every current TOC candidate needs a reasoned disposition, and every `used` candidate maps into a TOC item. Canonical TOC items cover every unique reviewed boundary. Boundary `paragraph_ids` must partition every active paragraph exactly once in source order, without gaps or overlap. `surface_ids` is the ordered unique projection of paragraph-bearing surfaces plus any explicit `textless_surface_ids`; every textless/blank/visual-only surface is assigned exactly once. Adjacent boundaries may share a paragraph-bearing surface when a chapter starts mid-page or several chapters live in one EPUB spine item. Every boundary needs a non-empty `structure_path`. Reviewed TOC/boundary files are hash-bound in the package manifest and their paths are materialized into paragraph/chunk projections.

### Canonical correction is a two-revision workflow

Canonical text repair accepts five `canonical_block` actions:

```json
{"kind":"canonical_block","target_id":"blk_...","action":"correct_text","corrected_text":"Reviewed text","disposition":"selected","semantic_reading":true,"reviewer_type":"human","reviewer_id":"reviewer-1","reason":"Corrected against retained page evidence"}
{"kind":"canonical_block","target_id":"blk_...","action":"select_variant","selected_evidence_id":"ev_...","disposition":"selected","semantic_reading":true,"reviewer_type":"human","reviewer_id":"reviewer-1","reason":"Selected the stronger same-surface evidence variant"}
{"kind":"canonical_block","target_id":"FIRST_BLK","action":"join_blocks","join_block_ids":["NEXT_BLK"],"corrected_text":"Optional reviewed join text","disposition":"selected","semantic_reading":true,"reviewer_type":"human","reviewer_id":"reviewer-1","reason":"Joined contiguous blocks on one surface"}
{"kind":"canonical_block","target_id":"blk_...","action":"split_block","split_texts":["First","Second"],"split_ranges":[[0,5],[5,11]],"disposition":"selected","semantic_reading":true,"reviewer_type":"human","reviewer_id":"reviewer-1","reason":"Split with exact contiguous source offsets"}
{"kind":"canonical_block","target_id":"FIRST_BLK","action":"reorder_blocks","ordered_block_ids":["FIRST_BLK","THIRD_BLK","SECOND_BLK"],"disposition":"selected","semantic_reading":true,"reviewer_type":"human","reviewer_id":"reviewer-1","reason":"Reordered a contiguous same-surface block range after column-level reading-order review"}
```

`select_variant` requires an evidence row on the same surface with the same non-empty `variant_group_id`; arbitrary same-page evidence cannot substitute for the target. Its canonical evidence changes while raw `source_spans` continue to bind the original block/evidence and offsets. `join_blocks` must target the first block and name contiguous blocks on that same surface. `split_ranges` must start at 0, remain contiguous, and cover the full raw text exactly. `reorder_blocks` must target the first source block, list each member once, cover a contiguous original range, and stay on one surface.

Do not mix canonical-block edits with paragraph or structure decisions in one batch. Apply canonical edits first with the current `--expected-revision`; read the returned/new status and regenerated `paragraph_candidates_reviewed.jsonl`; then submit later review batches for the new paragraph IDs, TOC candidates, and review revision. Prior paragraph/structure decisions belong to the old canonical revision and cannot promote the corrected projection.

## States and gates

Keep lifecycle, trust, and stage status separate:

- evidence object: `pending`, `extracted`, `needs_review`, `quarantined`, `failed`;
- trust: `hint_only`, `needs_review`, `citation_grade`;
- package lifecycle: `active` or `revoked`;
- committed run manifest: `materialized`; preserved failed-run marker: `failed_retryable`; batch job rows: `complete`, `failed`, or `cancelled`;
- public target gate: `HINT_READY`, `REVIEW_READY`, `PASS_STRICT`, or `FAIL_REVIEW`.

`audit/gates/{target}.json` contains checks, observed values, warnings, blockers, counts, and derived trust. `audit/pass_fail_{target}.json` is its compact decision. `status` defaults to citation and reports `evaluated_target`; use `--target hint` or `--target review` for an explicit operational-tier recomputation. Citation evaluation refreshes `audit/gate_report.json` plus `audit/pass_fail.json` as the canonical strict snapshot. Recompute from current evidence and decisions; never trust a copied historical pass file.

Warnings may accompany `hint_only`. Any hard blocker forces citation `FAIL_REVIEW`.

## Validation invariants

Require all applicable invariants:

1. Source identity and schema validate.
2. Every logical surface exists exactly once and has an explicit state.
3. Review/citation PDF evidence has a rendered, hashed page image; a native-text hint run may omit full-page rendering and remains ineligible for citation until upgraded.
4. Every raw block/span is accounted for as used, excluded, reference-only, or unresolved.
5. `citation_grade` contains zero unresolved in-scope spans.
6. Every canonical block and paragraph reverse-locates to raw evidence.
7. Paragraph and boundary ranges have no unintended overlap or gap.
8. Every exclusion has a semantic reason.
9. Every asset occurrence has bytes or a missing-asset blocker plus an anchor decision.
10. Every strict paragraph has semantic reading provenance and the required coverage fields.
11. A rerun with identical source and policy is a no-op or reuses the deterministic run.
12. Source or configuration changes create a new run; head bindings invalidate incompatible review authority, while downstream exports use revision/invalidation keys for stale detection.
13. Decisions survive safe reuse of the same head. Source/run/canonical changes isolate incompatible decisions, and migrations begin with an empty v2 review ledger unless current v2 review is performed.
14. Any hard blocker prevents `PASS_STRICT`.
