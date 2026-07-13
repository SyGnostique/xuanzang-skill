# Translation workflow

Treat translation as a deliverable layered on a source evidence package. Source trust and translation/publication validation remain separate states.

## Current runtime boundary

The 2.0-native runtime stops at evidence-package restoration/review and `publish` Markdown/chunk export. `prep-translation`, `translate --provider mock`, `audit-translation`, `assemble-docx`, and `reinsert-epub` are **compatibility-only v1 commands**. They may exercise unit/format mechanics or preserve an old automation path. They do not consume the complete v2 decision contract, do not create a v2 translation revision, do not establish semantic translation PASS, and cannot raise source or deliverable trust.

Use the remainder of this file as the specification for a future v2 translation adapter and gate. Until such an implementation writes a revision-bound translation ledger, complete unit map, provider provenance, semantic decisions, publication validation, and immutable export manifest, report the result as a draft compatibility derivative.

## Contents

- [Eligibility](#eligibility)
- [Preparation](#preparation)
- [Stable unit mapping](#stable-unit-mapping)
- [Provider execution](#provider-execution)
- [Mechanical and semantic gates](#mechanical-and-semantic-gates)
- [Special translation scenarios](#special-translation-scenarios)

## Eligibility

- Use `needs_review` source packages for clearly marked draft translation and review assistance.
- Require source `citation_grade` before publication translation, exact quotation translation, or any deliverable that claims complete source fidelity.
- Keep translation state such as `prepared`, `translated`, `semantically_reviewed`, and `publication_validated` outside `trust_status`.

A mechanically valid target cannot elevate source trust.

## Preparation

Create and review:

- project brief and intended audience;
- whole-document argument/structure map;
- chapter or section briefs;
- style and register guide;
- terminology policy and approved glossary;
- names, titles, transliteration, units, dates, quotations, and citation policy;
- table, formula, note, caption, index, and image-marker policy;
- ambiguity and source-anomaly register;
- provider/privacy boundary;
- QA gates and escalation route;
- prompt/job manifest bound to package revision.

Derive context from canonical paragraphs and structure. Keep source-use boundaries, uncertainty, and known OCR defects visible to the translator.

## Stable unit mapping

Assign stable source unit IDs from canonical paragraphs or smaller source spans. Preserve the source ledger through every target revision.

Support fluent target segmentation with explicit mappings:

```yaml
target_segment_id: tgt_...
source_unit_ids: [src_001, src_002]
target_text: ...
translator_run_id: ...
terminology_decisions: []
format_markers: []
review_status: ...
```

One source unit per target line remains a useful strict compatibility mode. When fluency requires merging or splitting, record a complete many-to-many mapping; never drop or silently reorder source units.

Preserve image occurrences, captions, notes, formulas, cross-references, quotations, citations, and structural markers by ID. Translation units must not become the only copy of canonical source text.

## Provider execution

Before any remote call:

1. Confirm provider authorization for the source privacy and copyright class.
2. Record provider, model/version, endpoint class, region if relevant, prompt pack hash, parameters, timestamp, and retry policy.
3. Send the minimum authorized context.
4. Store responses in protected run artifacts; keep secrets outside prompts, files, and logs.
5. Make retries idempotent by job ID and preserve earlier outputs.

The local `mock` provider proves v1 formatting mechanics only. It always blocks publication and semantic PASS and does not constitute a v2 provider adapter.

## Mechanical and semantic gates

Mechanical validation checks:

- every expected source unit mapped;
- no extra, missing, or duplicate unit IDs;
- source order preserved or explicitly mapped;
- every image/format marker present;
- headings, notes, citations, links, formulas, and table structure retained;
- output encoding and syntax valid.

Semantic audit checks:

- no omission or invented meaning;
- claims, causal strength, modality, uncertainty, negation, comparison, and scope preserved;
- terms, names, quantities, units, dates, and citations correct;
- ethical, political, technical, and disciplinary terms retain their force;
- captions, notes, tables, equations, index terms, and cross-unit dependencies translated consistently;
- revisions justified by source units and recorded.

Require full unit coverage for publication. Sampling can prioritize draft review, while the status remains `needs_review`.

## Special translation scenarios

- **Multilingual source:** label source language per unit; route code-switching and quotations through language-specific terminology.
- **RTL/vertical scripts:** preserve direction and visual anchor; validate output layout separately.
- **Poetry, literary style, or oral history:** record interpretive decisions and variants; keep literal anchors available.
- **Scientific and technical text:** protect equations, symbols, nomenclature, taxonomies, standards, and measurement conditions.
- **Index:** translate entries after body terminology stabilizes; rebuild locators against final pagination.
- **New edition:** map unchanged source units to prior approved translations, then re-audit changed and context-dependent units.
- **Team translation:** assign terminology and chapter ownership, centralize decision logs, and resolve cross-chapter drift before publication.
