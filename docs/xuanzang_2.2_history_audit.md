# Xuanzang 2.2 interaction-history audit

## Scope reviewed

The 2.2 redesign used the recovered local task/session history and the current repository state:

- full master rollout `019f6b57-ae4d-7132-97c4-73a4a209960d` (20 turn contexts, including compacted history and implementation iterations);
- recovered antecedent rollouts `019d596d-41c0-71b1-9f2b-08de1d0b49de` and `019d1877-921c-7af0-a4ee-f758e089adad`;
- current Skill, prompt pack, references, runtime, gates, publisher, tests, ZCode adapter, and existing export contracts;
- Chronicle/memory summaries used to cross-check prior scoring, blocker, proposal-merge, and package-export incidents.

The two antecedent rollouts are recovered summaries rather than their missing original verbatim event streams. The full master rollout retains their method summary and later failure/repair history; 2.2 does not claim access to bytes that are no longer present.

## Requirements retained

- Evidence compiler, not conversion followed by global cleanup.
- Whole-book architecture and full visual TOC before boundaries.
- Exact inclusive starts/exclusive ends and complete paragraph/surface partition.
- Native text remains native; OCR repair is evidence-specific.
- Informational frontmatter/backmatter survives.
- Figures, vector graphics, captions, tables, formulas, code, links, and callouts are first-class.
- Single H1 book title, H2 materialized source divisions, H3 source subsections.
- Machine-readable chunks/assets/objects and reverse source reconstruction.
- Hard blockers override confidence and scores.
- One materialization writer per package.
- Current local package/export evidence is the only completion authority.

## Failure families converted to regressions

The detailed registry is in `skills/xuanzang/references/failure-regressions.md`. It covers:

- false or collapsed TOCs, false headings, hidden real headings, page/spine-as-chapter, and offset drift;
- broad paragraph joins, native-text OCR corruption, wrong OCR language, OCR contention, and mixed PDF routes;
- incomplete contact sheets, vector-figure loss, wrong column order, and visual-only page omission;
- empty/duplicate sections, callout-as-chapter, TOC residue, index fragmentation, and backmatter loss;
- flattened/repeated-cell tables, caption-image drift, asset order drift, and cover/logo omission;
- stale parent/object projections, publication-furniture leakage, copied old PASS files, scorer/process failures, and parallel-writer interference.

## 2.2 closure

The skill now makes local strict reconstruction the default, external scoring optional, and final acceptance executable through:

```bash
xuanzang verify-local-strict PACKAGE --export EXPORT
```

The command verifies active identity/revision, gate state, artifact hashes, Markdown hierarchy, reverse-locatable chunks, asset exact-once coverage, and object counts. It never promotes a package and cannot override unresolved evidence.
