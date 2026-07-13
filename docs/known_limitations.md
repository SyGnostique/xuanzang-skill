# Known limitations and deployment boundary

This document describes the current 2.0 implementation. A limitation stays a blocker until code, tests, operational evidence, and the relevant gate prove otherwise.

## Candidate posture: trusted local pilot after acceptance

The 2.0 implementation is designed for a controlled local pilot when all of the following hold. The repository has not yet completed the real authorized restore → review → publish → revoke canary, independent agricultural-domain sampling, maintainer release signature, or GitHub release-commit evidence required by `release_checklist.md`; until those are recorded, call it a local-pilot candidate rather than an accepted pilot:

- sources are supplied and authorized by a named operator;
- source files and packages remain on trusted local or explicitly controlled storage;
- resource ceilings are lowered to match the host and the input is inspected before conversion;
- OCR/VLM sidecars and optional engines are treated as evidence, with page/image anchors reviewed;
- every citation-grade paragraph receives ManualStrict semantic and paragraph-level coverage;
- assets, tables, equations, captions, structure, exclusions, and source-use boundaries receive applicable decisions;
- `xuanzang status` at its default citation target returns both `citation_grade` and `PASS_STRICT` for the current revision;
- downstream embeddings and caches are rebuilt or invalidated from the export manifest key;
- revocation is manually propagated and acknowledged by every downstream store.

The pilot still requires operator judgment. Automated extraction can prepare review work; it cannot certify source meaning.

## Blocked posture: public multi-tenant service

The repository must not be deployed directly as a public, unsupervised, or high-concurrency multi-tenant backend. The package metadata and expected-scope checks do not provide a security boundary.

Missing production controls include:

- authenticated users, service identities, sessions, and tenant membership;
- authorization before source access, review assignment, retrieval, export, and revocation;
- orchestrator-signed reviewer context exposed through the service interface;
- tenant-isolated object storage, database row-level security, vector namespaces, and cache keys;
- upload quarantine, malware/content scanning, MIME verification, decompression budgets across every container format, and DRM/encryption policy;
- durable job queues, idempotency records, leases, cancellation, backpressure, quotas, and fair scheduling;
- encrypted transport/storage, key management, secret rotation, and provider egress controls;
- append-only central audit logs, security monitoring, incident response, backups, and tested disaster recovery;
- retention schedulers, legal hold, export inventory, verified deletion, and per-system revocation acknowledgements;
- rate limits, abuse controls, billing/metering, service-level objectives, and capacity/load evidence;
- multi-tenant penetration testing and privacy/compliance review.

For `privacy=workspace` or `privacy=tenant`, strict semantic gates require an `orchestrator_verified` reviewer attestation with matching scope and review session. The public CLI currently creates `local_self_asserted` semantic decisions, so it cannot independently produce a valid workspace/tenant citation-grade review. A trusted service adapter must supply `ReviewerContext` after authentication and authorization.

## Extraction limitations by source type

### PDF

- Native-text PDF pages in `hint` runs may skip full-page rendering for fast corpus discovery. Such a run is blocked from citation promotion until restored at review/citation evidence tier with required page renditions.
- Reading order comes from PyMuPDF blocks and OCR evidence; multi-column pages, marginalia, rotated inserts, footnotes, and overlays can require manual canonical correction.
- Mixed native-text and visual regions are flagged for reconciliation; the runtime does not fully segment and independently OCR every visual subregion.
- Tables, equations, figures, and captions require object/asset review. Extraction does not guarantee a publication-quality structural transcription.
- PDF page-level failed-run checkpoint reuse exists. Equivalent granular checkpoints are not implemented for every other format or processing stage.
- Encrypted, malformed, unusually large, or adversarial PDFs require an external quarantine/sandbox policy before parsing.

### OCR and sidecars

- PaddleOCR and Tesseract are optional local dependencies; availability, language packs, model versions, and accuracy vary by host.
- `ocr=auto` chooses from installed adapters. It does not benchmark multiple engines and select a globally optimal result.
- The mock adapter is test evidence only and can never establish citation-grade OCR.
- Sidecar and plugin output must carry valid page-image identity and coordinates. Claimed Unlimited-OCR/VLM provenance is not trusted without review. The generic plugin seam currently remains citation-blocked because it does not materialize an immutable producer manifest.
- Confidence thresholds do not replace visual comparison, especially for names, numbers, formulas, references, historical glyphs, and rare scientific terminology.

### EPUB

- EPUB restoration creates one surface per OPF spine occurrence, preserves itemref metadata, canonicalizes nav/NCX targets from their referring documents, and separates primary/auxiliary navigation candidates. Visual-only or fixed-layout surfaces remain blocked until a real hashed rendition is attached by a future renderer path.
- EPUB XML accepts valid UTF-8/UTF-16 while enforcing a conservative DTD/entity-deny policy. Multiple rootfile renditions require prior explicit selection. Complex CSS layout, scripts, media overlays, SVG internals, MathML, footnote semantics, and non-spine resources may still need specialist review.
- Archive validation rejects traversal, symlinks, size/ratio abuse, duplicate/case/Unicode-canonical collisions, and file/directory prefix collisions. Public upload handling still needs a separate sandbox, malware scanning, and active-content policy.
- `reinsert-epub` is a v1 compatibility path based on stable XHTML text-node ordering. It is outside the v2 citation publication contract and is not a general EPUB round-trip guarantee.

### DOCX

- The v2 parser reads OOXML stories including the main document, tables, headers, footers, notes, and comments when present.
- Tracked changes, field codes, text boxes, drawing-layer text, equations, relationships, and layout-dependent reading order can create blockers or incomplete semantics.
- No v2 round-trip DOCX publisher is provided. `assemble-docx` uses the v1 translation contract.

### Images and image directories

- Multi-frame images and EXIF orientation are normalized for evidence, subject to page/pixel limits.
- File ordering in an image directory must represent the intended reading order; printed-page identity and missing-page detection require review.
- Handwriting, diagrams, charts, tables, and low-resolution scans can remain unresolved after OCR.

### HTML, Markdown, and text

- HTML extraction does not reproduce browser layout, dynamic content, shadow DOM, client-side rendering, or external authenticated resources.
- Plain-text and Markdown anchors are logical text surfaces rather than physical page citations.
- Encoding recovery and historical or bidirectional scripts need manual verification.

### MOBI and AZW3

- Support depends on a locally installed Calibre `ebook-convert` command and inherits its conversion losses.
- DRM-protected or encrypted books are unsupported. The runtime must not be used to bypass access controls.

### Source bundles

- JSON/YAML bundles require correct member order, roles, and hashes. Cross-edition or secondary-source material cannot silently substitute for primary evidence.
- External paths are blocked by default; allowing them expands the trusted filesystem boundary.
- Bundle-level deduplication does not resolve contradictory editions, translations, or source authority. Those are semantic review decisions.

## Text and language limitations

- `--transcription source` and `diplomatic` preserve source glyph choices. `normalized` and `both` add a deterministic Unicode/newline-normalized evidence variant; they do not perform scholarly modernization, spelling reform, transliteration, translation, or script conversion.
- Bidirectional and mixed-script profiles are recorded, but visual reading order and mirrored punctuation still require inspection.
- Mechanical normalization remains evidence. A reviewer must select or correct the canonical representation before citation use where source meaning could change.

## Semantic review limitations

- TOC and boundary candidates are proposals. A heuristic score cannot establish semantic structure.
- ManualStrict coverage is intentionally expensive: every in-scope paragraph or equivalent block needs role, summary, candidate claims/methods/metrics/boundaries/reasoning leaps, use decision, exclusions, and anchor policy.
- The runtime validates decision shape, coverage, bindings, and provenance. It cannot prove that a reviewer understood the text or that a scientific interpretation is correct.
- Agent semantic review needs governance, calibration, disagreement handling, and human escalation outside this repository.
- Primary-source eligibility, scientific validity, retractions, conflicts between sources, and current external knowledge require separate research governance.

## Publication and retrieval limitations

- V2 publication produces Markdown, JSONL chunks, a manifest, an embedding manifest, and a gate snapshot. It does not generate embeddings or operate a vector database.
- Chunk metadata carries trust and scope requirements. Retrieval authorization, hybrid ranking, citation rendering, answer generation, and failure replay belong to the downstream knowledge-base runtime.
- Export paths can be rewritten by another invocation. Consumers must bind ingestion to manifest hashes and revision/invalidation keys rather than assuming filesystem immutability.
- Revocation marks the package and emits a tombstone. It does not delete vectors, caches, prior exports, backups, provider copies, or replicas, and it does not collect acknowledgements.
- Translation, DOCX assembly, and EPUB reinsertion remain v1 compatibility features. The bundled `mock` translation checks mechanical contracts only; it is not a semantic or publication translation.

## Scale and operations limitations

- The CLI is a synchronous local process with filesystem locking per package. There is no distributed lock, scheduler, queue, autoscaling, or cross-host transaction coordinator.
- Default resource ceilings are permissive for research work and must be tightened for each host. Large PDFs and image corpora can consume substantial CPU, RAM, disk, and OCR time.
- `xuanzang batch` provides bounded local parallel restoration, per-source packages, resumable package runs, and a corpus manifest. Corpus-level content deduplication, global search, shared review queues, cost accounting, progress dashboards, distributed scheduling, and policy-aware automatic retry are not implemented here.
- Failure recovery preserves failed run material, but operational cleanup and disk-retention policy remain manual.

## Historical audit limitation

Files in `audit/goal_loop_scores.jsonl`, `audit/v1_score_summary.md`, and `audit/zcode_adapter_score.md` are archived v1 self-assessments. Their numeric scores and old test counts are not current evidence and must not be cited as a v2 release, security, semantic, or package gate. V2 package trust comes only from a freshly recomputed `audit/gates/<target>.json`; repository release readiness follows [release_checklist.md](release_checklist.md).
