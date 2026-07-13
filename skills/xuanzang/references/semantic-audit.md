# ManualStrict semantic audit

Semantic audit determines what the source says, how each paragraph functions, which evidence is eligible for promotion, and what remains uncertain. Apply it to restoration, knowledge-base promotion, translation, and publication.

## Contents

- [Audit scope](#audit-scope)
- [Paragraph coverage](#paragraph-coverage)
- [Complex-object coverage](#complex-object-coverage)
- [Decision discipline](#decision-discipline)
- [Reviewer collaboration](#reviewer-collaboration)
- [Completion](#completion)

## Audit scope

Read the complete promoted scope against the strongest available source evidence:

- page/surface images and native layers;
- OCR/layout variants and disagreements;
- canonical paragraphs and structure;
- tables, formulas, figures, captions, notes, references, indexes, and appendices;
- source metadata, version, use boundary, and anomalies;
- target translation or promoted knowledge object when applicable.

Include material that supports, constrains, qualifies, contradicts, contextualizes, or is intentionally excluded from the promoted object. Keep source-local evidence distinct from cross-source synthesis.

## Paragraph coverage

Create one semantic decision for every paragraph or paragraph-equivalent block. Use these roles:

- `definition`: establishes meaning or scope;
- `mechanism`: describes causal or functional process;
- `method`: procedure, design, material, sampling, model, or analysis;
- `metric`: quantitative result, threshold, unit, comparison, or uncertainty;
- `case`: place-, time-, population-, experiment-, or event-specific evidence;
- `boundary`: condition limiting transfer, use, or interpretation;
- `caveat`: uncertainty, limitation, contradiction, or qualification;
- `reference_only`: retained for citation navigation without promoted substantive claim;
- `excluded`: intentionally outside scope with reason.

Record a non-empty semantic summary and reason; all five lists `claim_candidates`, `method_candidates`, `metric_candidates`, `boundary_candidates`, and `reasoning_leap_candidates`; both booleans `used_in_card` and `requires_primary_anchor`; exact `source_id`; a `sourcepage_path` containing the active page/surface ID; reviewer provenance; and `semantic_reading: true`. Empty candidate lists are valid; missing lists are not.

Resolve all canonical paragraph IDs exactly once at the active revision. A paragraph can contribute to several candidate types while retaining one disposition decision.

## Complex-object coverage

Audit each occurrence, not only each asset byte:

- table title, cells, merged structure, units, footnotes, continuation, and body interpretation;
- formula symbols, labels, variables, assumptions, and body references;
- figure/chart/map panels, axes, legends, labels, caption, and claims derived from the visual;
- image occurrence position and relevance;
- note marker/body/backlink;
- reference entry and citation link;
- index entry and locator role;
- slide, worksheet, text box, comment, tracked change, or embedded object when present.

For numerical claims, compare the canonical value with visual/native evidence and retain its denominator, units, precision, uncertainty, comparison group, location, time, and scale.

## Decision discipline

Write decisions append-only and bind them to source hash and run revision. Each correction needs:

```yaml
target_id: ...
finding: ...
evidence_ids: []
decision: ...
reason: ...
reviewer_id: ...
reviewer_type: human | agent_semantic
expected_run_id: ...
created_at: ...
supersedes: ...
```

Use the source to justify repairs. Keep uncertainty explicit. Preserve acceptable model or translator style outside the corrected span. Never create plausible bridge text to conceal OCR, structure, or source gaps.

Resolve extraction blockers only with typed evidence: each code in `resolves` needs a matching `resolution_evidence` object with `code`, a concrete verification `method`, and `verified: true`. Reference the actual page/evidence/object IDs. Repair corrupt or mismatched evidence before resolution; an attestation cannot substitute for a valid source image, bbox, binary, or parser output.

Canonical repair and semantic paragraph/structure review are separate revisions. Submit `correct_text`, `select_variant`, same-surface `join_blocks`, exact-range `split_block`, or contiguous same-surface `reorder_blocks` decisions first. Then reload regenerated paragraph IDs and TOC candidates before submitting ManualStrict and structure decisions under the new review/canonical revision. Never carry old paragraph or structure decisions across a canonical change.

When engines or reviewers disagree:

1. identify the exact span or object;
2. compare the highest-resolution evidence;
3. inspect surrounding semantic context;
4. record alternatives and decision basis;
5. escalate unresolved high-impact conflict;
6. keep the package at `needs_review` until resolved.

## Reviewer collaboration

Separate roles where risk warrants it:

- mechanical operator: renders, extracts, imports, and checks schemas;
- semantic reviewer: reads and assigns meaning/coverage decisions;
- domain reviewer: verifies technical interpretation and use boundaries;
- publication reviewer: checks target-language and package output;
- gate owner: recomputes eligibility from evidence.

One person or agent may hold several roles, while every action retains role provenance. Bind decisions to an expected revision and reject stale writes. Resolve competing decisions through a named adjudicator or superseding decision.

## Completion

Citation semantic audit is complete only when:

- every canonical paragraph has a valid semantic decision;
- every raw span is accounted for;
- every exclusion/reference-only choice has a reason;
- every promoted claim, method, metric, case, mechanism, concept, theme, or boundary links to covered paragraphs;
- every meaningful complex object and occurrence is represented or explicitly excluded;
- precise numbers and visual claims have primary anchors;
- structure and source-use boundary are reviewed;
- conflicts and anomalies are resolved or promotion scope excludes them explicitly;
- reviewer provenance is valid;
- the recomputed gate has zero hard blockers.

Page counts, regex matches, schema checks, embeddings, and validators can prove bookkeeping. They cannot prove semantic completeness without the paragraph decisions above.
