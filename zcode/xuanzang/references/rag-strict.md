# Citation-grade knowledge-base promotion

Use xuanzang as the evidence-restoration boundary upstream of chunks, embeddings, lexical indexes, knowledge cards, graphs, timelines, evidence bundles, and research-agent memory.

## Contents

- [Trust-separated retrieval](#trust-separated-retrieval)
- [ManualStrict coverage](#manualstrict-coverage)
- [Promotion objects](#promotion-objects)
- [Chunk and embedding rules](#chunk-and-embedding-rules)
- [Citation contract](#citation-contract)
- [Strict gate](#strict-gate)

## Trust-separated retrieval

Maintain separate namespaces and answer policies:

| Trust status | Retrieval role | Answer-layer rule |
| --- | --- | --- |
| `hint_only` | source discovery, alias finding, candidate recall, forensic comparison | disclose status; locate better evidence; never support a formal claim alone |
| `needs_review` | internal research assistance and review queues | disclose unresolved boundaries; avoid formal citation claims |
| `citation_grade` | trusted lexical/vector/graph retrieval and evidence packets | cite reversible anchors and respect source-use boundaries |

Store raw OCR, legacy indexes, external summaries, and old RAG artifacts as hint evidence until reviewed. Keep external research in a separate source package; it can challenge local truth and locate primary material, while local canonical evidence changes only through explicit review.

## ManualStrict coverage

Before citation promotion, semantically read every paragraph or paragraph-equivalent block that supports, constrains, qualifies, references, or is intentionally excluded from the promoted scope.

Each row must record:

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

Require a row for every canonical paragraph and every complex object that carries meaning. A section-level statement such as “all pages read” cannot replace the ledger. Mechanical inventories may verify row counts and missing fields after semantic reading.

Existing artifacts marked ready without this coverage must become `needs_review` or `invalid_or_unverified_for_ready` during migration. Preserve them as candidates and restore their trust only after corrective audit.

## Promotion objects

Promote in layers:

1. `SourcePage`: source identity, aliases, version, provenance, trust, review status, structure, anchors, and use boundary.
2. `PaperProfile` or `BookProfile`: domain, methods, objects, claims, metrics, limitations, and structure, each with source spans.
3. Evidence spans: claim/method/metric/case/boundary candidates with explicit local anchors.
4. Knowledge objects: principle, mechanism, method, case, risk, concept, event, timeline, team/person, or domain-specific cards.
5. Reasoning-leap candidates: a source-local move from premises or observations to a new framing, hypothesis, mechanism, method, or conclusion.
6. Evidence bundles: selected source-local objects plus boundaries and contradictions for a decision or research task.

Represent a reasoning-leap candidate with premise paragraph IDs, bridge/inference text, conclusion paragraph IDs, assumptions, novelty context, counterevidence, source-local boundary, and reviewer status. Keep the author's explicit reasoning separate from a downstream agent's reconstructed inference. Xuanzang supplies anchored candidates; research agents evaluate novelty and scientific value downstream.

Scripts may create inventories and candidates. Semantic agents or humans determine meaning and promotion. Every formal object must link back to SourcePage, paragraph rows, and raw evidence.

Distinguish:

- source-local statements;
- cross-source synthesis;
- external challenge evidence;
- inference by the research agent;
- unresolved conflict or missing evidence.

## Chunk and embedding rules

Generate chunks only as derived views of canonical paragraphs:

- preserve paragraph IDs and source spans;
- retain section path, page/logical-surface anchors, trust, review status, language, access tags, source revision, and valid/transaction time;
- keep tables, captions, formulas, notes, and references linked rather than flattening them invisibly;
- create exact aliases and lexical fields alongside vectors;
- hash chunk text and configuration for incremental rebuilds;
- mark chunks stale when source, canonical text, structure, or trust changes;
- prevent hint chunks from entering trusted retrieval by namespace and query policy.

Do not use embeddings to decide paragraph meaning, source eligibility, or strict readiness. Embeddings run after the relevant trust gate and remain reproducible derived artifacts.

Current `publish` writes chunks plus an `embedding_manifest.json` with `status: unembedded`, an invalidation key, trust target, tenant/workspace IDs, access tags, privacy, rights, and retention requirements. It does not call an embedding model or write a vector database.

The downstream knowledge runtime owns vector creation and authorization. It must:

- index hint and citation exports into separate namespaces/policies;
- include `package_id`, run/canonical/review revision, source hash, tenant ID, workspace ID, access tags, privacy, rights, and trust on every vector row;
- enforce tenant/workspace membership and row-level access tags at both query planning and result return;
- reject a vector whose invalidation key no longer matches the active export;
- purge vectors and cached evidence packets on a revocation tombstone, then return a deletion acknowledgement to the orchestrator.

Metadata propagation by xuanzang is not ACL enforcement. Never expose a workspace chunk merely because its embedding exists.

## Citation contract

A citation-ready answer packet needs:

```yaml
source_id: ...
source_revision: ...
package_id: ...
trust_status: citation_grade
canonical_paragraph_ids: []
raw_evidence_ids: []
page_or_surface_anchors: []
quoted_or_paraphrased_spans: []
source_use_boundary: ...
conflicts: []
review_provenance: []
```

Numerical findings, formulas, tables, figure-derived claims, and precise quotations require primary visual/native anchors. Preserve units, denominators, comparison groups, uncertainty, time, place, scale, and experimental conditions.

## Strict gate

Citation `PASS_STRICT` requires all of the following:

- source hash and package schema valid;
- all logical surfaces classified and all paginated pages accounted for;
- native/OCR/layout findings resolved for the promoted scope;
- canonical blocks and paragraphs reverse-locate to raw evidence;
- structure and boundaries semantically reviewed;
- every raw span disposed and every exclusion reasoned;
- ManualStrict paragraph coverage complete;
- figures, tables, formulas, captions, notes, references, and asset occurrences accounted for;
- source-use boundary recorded;
- reviewer provenance valid;
- zero hard blockers.

`audit/gate_report.json` carries the check-level evidence. `audit/pass_fail.json` carries the compact decision. Any warning that represents unresolved citation evidence must be a blocker for the citation target.
