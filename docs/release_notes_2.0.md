# Xuanzang 2.0 release-candidate notes

These notes describe the implemented 2.0 repository state. They do not sign a release commit or certify a production deployment. Final library release and trusted-local-pilot acceptance remain governed by `release_checklist.md`.

## Package and trust contract

- Adds package schema and pipeline version 2 with immutable per-run artifacts, source/policy fingerprints, artifact digests/root, active projections, source revisions, lifecycle state, and scope metadata.
- Adds target-specific `hint`, `review`, and `citation` gates. `status` defaults to citation, reports `evaluated_target`, and accepts an explicit target.
- Adds append-only, hash-chained, optimistic-concurrency review decisions bound to source SHA, active run, canonical revision, scope, and reviewer provenance.
- Adds ManualStrict paragraph coverage with claim, method, metric, boundary, and reasoning-leap candidates. Reasoning leaps carry premise/conclusion paragraph IDs, assumptions, novelty context, counterevidence, source-local boundary, uncertainty, predictions, and reviewer status; their host and referenced paragraph IDs must all be exported `used` paragraphs.
- Adds method-specific blocker resolution checks. A typed declaration cannot clear a bad image hash, missing binary, invalid bbox, absent rendition, unresolved navigation target, or unbound provenance.
- Adds reviewed TOC/boundary projections with candidate disposition coverage, exact ordered paragraph partition, mid-surface boundary support, paragraph structure paths, and manifest hash bindings.

## Inputs and extraction

- Native v2 restore routes: PDF, EPUB, DOCX, TXT, Markdown, HTML, raster images, image directories, JSON/YAML source bundles, and MOBI/AZW3 through local Calibre conversion.
- Born-digital PDF hint runs may skip full-page rendering; review/citation evidence requires page renditions. PDF extraction records native/OCR variants, assets, layout findings, checkpoints, and page-image hashes.
- EPUB creates one surface per OPF spine occurrence, preserves itemref metadata, canonicalizes nested nav/NCX targets relative to the referring document, retains typed navigation hierarchy, and accounts for blank, visual-only, missing, unsupported, and repeated spine targets.
- EPUB/DOCX ZIP validation rejects traversal, symlinks, size/ratio abuse, duplicate/case/Unicode-canonical collisions, and file/directory prefix collisions. EPUB XML accepts valid UTF-8/UTF-16 while enforcing a DTD/entity-deny policy.
- Sidecar OCR is imported under exact page-image and producer-provenance gates. Third-party `plugin:NAME` adapters are forcibly marked as requiring anchor and provenance review; the generic plugin seam remains citation-blocked until an adapter supplies immutable producer evidence.

## Operations and exports

- Adds deterministic restore/reuse, intentional `--new-run`, changed-source acceptance, PDF page checkpoint resume, local package locks, failed-run evidence, bounded directory `batch`, and fail-fast accounting.
- Adds hint/citation Markdown and JSONL chunk exports, gate snapshot, export manifest, and an unembedded downstream invalidation/namespace manifest.
- Citation chunks carry all five semantic candidate families, source spans, structure path, source/run/canonical/review revisions, trust, rights, retention, tenant/workspace, and access tags.
- Adds package revocation and downstream deletion tombstones. Downstream stores still own purge and acknowledgement.

## Migration and compatibility

- `migrate-v1` preserves a quota-bounded legacy snapshot, verifies an explicit original source when supplied, creates implemented surface/block/image crosswalks, and downgrades inherited status.
- `migrate-book-m1` reuses page-aligned OCR evidence without rerunning OCR when the current crosswalk and path checks pass. It does not import old semantic trust.
- Both migrations begin with an empty v2 review ledger; legacy manual material remains forensic snapshot evidence until reviewed under the current contract.
- `ledger`, `toc`, `split`, `clean`, `validate`, translation, DOCX assembly, and EPUB reinsertion remain compatibility-only. `toc`/`split` refuse to mutate a reviewed v2 package; compatibility writes on an unreviewed package require a subsequent restore before v2 review.

## Compatibility changes requiring operator attention

- Old `PASS_STRICT`, goal-loop scores, translation audits, hand-edited chapters, and legacy readiness labels carry no v2 gate authority.
- Structure review now requires a reasoned disposition for every current TOC candidate, at least one canonical TOC item, and non-overlapping boundaries that partition all paragraphs in source order while retaining their ordered surface projections.
- Non-empty reasoning-leap candidates use the expanded anchored schema.
- Resolution code/method pairs are registered enums and must carry evidence that the gate can independently verify.
- Visual-only/fixed-layout EPUB citation remains blocked until a renderer path materializes a hashed page rendition.

## Validation snapshot

At the time these notes were written, local automated tests, the security scan, skill validators, source/wheel builds, and a real born-digital PDF hint canary had passed. Record fresh commands, environment, commit, artifact hashes, CI URL, and counts when signing a release; copied counts in this file are not release authority.

## Remaining acceptance blockers

- No maintainer-signed release commit or hosted CI evidence has been recorded.
- The authorized real-source restore → citation review → publish → revoke canary has not been completed.
- Agricultural-domain ManualStrict quality has not yet been independently sampled for the pilot.
- Public multi-tenant controls, authenticated orchestration, tenant-isolated storage, job infrastructure, vector ACL enforcement, deletion acknowledgements, observability, incident response, and load evidence remain outside this repository and are NO-GO requirements.
