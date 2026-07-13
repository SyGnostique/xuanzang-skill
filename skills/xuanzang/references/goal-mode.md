# Staged goal loops

Use these loops for implementation, migration, difficult-source restoration, or release acceptance. Score every loop independently, require at least 98/100, and let any hard blocker cap the loop below passing.

## Loop sequence

| Loop | Objective | Required completion evidence |
| --- | --- | --- |
| G0 Foundation | Freeze source, target, rights, schema, configuration, and rollback boundary | source hash; package version; profile; protected paths; rollback plan |
| G1 Identity | Establish source family, revisions, aliases, duplicate relations, and tenant/workspace ownership | source inventory; hashes; identity decision; privacy/access tags |
| G2 Surfaces | Inventory every document surface and page projection | 100% surface states; paginated page states; render hashes; failures queued |
| G3 Evidence | Produce native/OCR/layout variants and asset occurrences | adapter run evidence; text variants; geometry/DOM anchors; OCR and asset audits |
| G4 Structure | Reconstruct logical hierarchy and non-overlapping boundaries | canonical TOC; boundary evidence; reading order; no unassigned source span |
| G5 Canonical | Build canonical paragraphs and complex objects with reversible anchors | paragraph ledger; source spans; tables/formulas/figures/notes linked |
| G6 Semantic | Complete ManualStrict coverage for the requested target | every paragraph-equivalent row used, excluded, reference-only, or resolved |
| G7 Gate | Aggregate all stage audits without warning-based pass | `audit/gate_report.json`; `audit/pass_fail.json`; zero hard blockers for PASS |
| G8 Deliverable | Export a v2-native Markdown/chunk derivative or explicitly scoped external/compatibility deliverable | export manifest; source revision; gate decision; checksums; capability-state disclosure; limitations |
| G9 Operations | Prove resume, idempotency, migration, collaboration, and security | no-op rerun; stale invalidation; decision concurrency check; recovery evidence |

Stop at the requested target. A `hint` run may finish with disclosed unresolved findings; a `citation` run must complete G6 and G7 with `PASS_STRICT`.

Current translation, DOCX assembly, and EPUB reinsertion commands are compatibility-only and cannot complete a v2 publication G8. Vector generation, ACL enforcement, and dedicated publication exporters belong to downstream adapters/orchestration and need their own acceptance loop.

## Score dimensions

Score only from durable evidence:

- source and surface coverage;
- anchor reversibility;
- OCR/layout fidelity;
- structure and boundary correctness;
- asset/caption/table/formula preservation;
- paragraph semantic coverage;
- review provenance and conflict handling;
- idempotency and revision integrity;
- privacy, rights, and secret handling;
- export validity and reproducibility.

Record numerator, denominator, evidence path, evaluator, and timestamp for each score. A rounded total cannot hide a failed item.

## Hard-blocker cap

Any of these conditions forces `FAIL_REVIEW` regardless of score:

- source hash mismatch or stale/tampered artifact;
- missing, unclassified, unrenderable, or quarantined-in-scope surface/page;
- required OCR unavailable, failed, garbled, or unresolved below threshold;
- unsupported source feature inside the promoted scope;
- missing image asset or occurrence anchor;
- unresolved TOC/body boundary or low-confidence boundary;
- unassigned or overlapping source span;
- paragraph coverage or anchor gap;
- exclusion without semantic reason;
- unresolved semantic review for a citation target;
- incomplete migration or schema validation failure;
- unsupported semantic fill, invented text, or silent normalization;
- stale review decision or destructive overwrite of raw/manual evidence.

## Loop record

For every loop, store:

```yaml
loop_id: G4
package_revision: ...
target: citation
status: pending | running | completed | blocked | failed | stale
score: 98.0
dimensions: []
hard_blockers: []
evidence_paths: []
open_findings: []
next_safe_action: ...
```

Advance only when the record is complete, the loop score is at least 98, and `hard_blockers` is empty.
