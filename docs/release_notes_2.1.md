# Xuanzang 2.1 release notes

Xuanzang 2.1 adds a complete provider-neutral semantic and visual structure-review protocol to the 2.0 evidence compiler.

## Added

- Twelve ordered prompt roles for whole-book architecture, visual TOC discovery/transcription, canonical TOC reconstruction, hierarchy/materialization adjudication, candidate assessment, exact boundaries, media affiliation, exhaustive section audit, reverse audit, evidence-bounded revision, and stage scoring.
- Strict JSON contracts with evidence references, confidence discipline, unresolved states, hard blockers, and self-checks.
- Book-family guidance for monographs, edited collections, lectures, interviews, catalogues, bilingual works, critical editions, reference-heavy books, Chinese scans, dirty EPUBs, and books without a reliable printed TOC.
- Byte-identical prompt/reference assets for Codex and GLM ZCode/OpenClaw, enforced by automated tests.

## Trust boundary

Prompt outputs are semantic review proposals. They do not mutate raw evidence, grant `PASS_STRICT`, establish `citation_grade`, or replace ManualStrict review. Accepted structure decisions must be submitted through the v2 append-only review contract, bind to the active source/run/canonical/review revision, and pass the current target-specific gate.

Vision-capable remote model use requires explicit user authorization and provider-retention review. Source text and page images remain untrusted data and must never be treated as agent instructions.

## Compatibility

The v2 evidence package, restore/status/review/publish/revoke workflow, migration boundary, and compatibility-only v1 commands remain unchanged. Package schema stays at version 2.
