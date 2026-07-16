# Xuanzang 2.1 release checklist

This checklist is the release authority for the 2.1 repository. Numeric goal-loop or prompt-protocol self-scores cannot satisfy any item below.

Keep three decisions separate:

1. library/CLI release readiness;
2. trusted local pilot readiness;
3. public multi-tenant service readiness.

A green library release does not authorize a public service. A passing package gate applies only to the exact source, run, canonical revision, review revision, target, and artifact hashes in that package.

## A. Source and release identity

- [ ] `pyproject.toml` and `src/xuanzang/__init__.py` report the same `2.1.x` version.
- [ ] The release commit is recorded and the worktree contains no unintended generated packages, sources, translations, page images, or provider responses.
- [ ] `git diff --check` passes.
- [ ] The source distribution and wheel build from a clean checkout.
- [ ] A fresh environment can install the built artifact and run `xuanzang --version` and `xuanzang --help`.
- [ ] [Release notes](release_notes_2.0.md) identify schema/pipeline changes, migrations, compatibility commands, and known blockers, and their validation snapshot is refreshed for the signed commit.

Suggested evidence:

```bash
git diff --check
python -m build
python -m venv /tmp/xuanzang-release-venv
/tmp/xuanzang-release-venv/bin/python -m pip install dist/xuanzang_skill-2.1.*.whl
/tmp/xuanzang-release-venv/bin/xuanzang --version
/tmp/xuanzang-release-venv/bin/xuanzang --help
```

Do not glob-install when multiple candidate wheels exist; select the intended artifact explicitly and record its SHA-256.

## B. Automated validation

- [ ] The complete test suite passes in a clean supported Python environment.
- [ ] Tests run with third-party pytest plugin autoload disabled in developer environments where global plugins can contaminate results.
- [ ] `python -m compileall -q src tests zcode scripts` passes.
- [ ] `python scripts/security_scan.py` passes.
- [ ] The Codex skill and ZCode skill pass their metadata/skill validators.
- [ ] `python zcode/xuanzang/scripts/xuanzang_zcode_cli.py check-env` succeeds without printing secret values.
- [ ] GitHub CI passes on the release commit.

Reference commands:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python -m compileall -q src tests zcode scripts
python scripts/security_scan.py
python zcode/xuanzang/scripts/xuanzang_zcode_cli.py check-env
```

Record the date, commit, Python version, dependency lock or environment, command, exit code, and full test count. An old count copied from `audit/v1_score_summary.md` is invalid evidence.

## C. V2 package-contract canaries

Use synthetic or public-domain fixtures. At minimum, exercise the applicable canaries below from a clean package path:

- [ ] born-digital PDF with native text and at least one asset;
- [ ] scanned PDF through an installed OCR adapter or attested sidecar;
- [ ] mixed native/visual PDF that produces and then resolves the reconciliation blocker;
- [ ] EPUB with multiple/textless/repeated spine occurrences, nested typed nav and NCX, UTF-8/UTF-16 XML, visual/fixed-layout blockers, repeated asset occurrence, missing resources, and archive-path safety cases;
- [ ] DOCX with paragraphs, tables, header/footer, footnote/endnote/comment stories, and a complex-object blocker;
- [ ] TXT, Markdown, and HTML logical surfaces;
- [ ] image directory plus a multi-frame image, EXIF rotation, page/pixel ceilings, and decompression-bomb rejection;
- [ ] JSON/YAML bundle with roles/order/hashes plus external-path rejection;
- [ ] MOBI/AZW3 success when `ebook-convert` is installed and explicit failure when unavailable;
- [ ] changed-source rejection and `--accept-source-update` source-revision path;
- [ ] deterministic identical-run reuse and intentional `--new-run` behavior;
- [ ] PDF failed-run `--resume` checkpoint path;
- [ ] bounded `batch` accounting, including fail-fast cancellation/drain and fast native-PDF hint routing;
- [ ] v1 and Book M1 migration without inherited trust or OCR rerun.

For every successful restore, verify:

- [ ] `package_version=2`, source SHA, active run, policy fingerprint, and scope are bound in manifests;
- [ ] every required run artifact exists and matches the immutable artifact digest/root in `run_manifest.json`;
- [ ] top-level active projections match their committed run artifacts before review-derived projections;
- [ ] surfaces, evidence blocks, canonical blocks, paragraphs, assets, objects, TOC candidates, and extraction audit are present as applicable;
- [ ] raw observations retain engine/version, source locator, coordinate space, and content hash;
- [ ] source spans reverse-locate canonical paragraphs to raw evidence;
- [ ] no previous package's reviewed projections leak into a new source/run head;
- [ ] failed input leaves diagnosable failed-run evidence without activating partial output;
- [ ] package paths, bundle paths, archive members, active run IDs, and binary evidence cannot escape their allowed roots.
- [ ] ZIP duplicate, casefold, NFC/NFD, full-casefold, file/directory-prefix, symlink, traversal, size, and compression-ratio cases fail before unsafe extraction.

## D. Target-specific gates

Run each gate against the current package; do not inspect or copy an older generic pass file.

### Hint target

- [ ] `xuanzang publish PACKAGE --target hint --out OUT` succeeds only when the hint gate has no hard extraction/integrity/lifecycle blocker.
- [ ] The export manifest and chunks say `hint_only` and do not imply citation readiness.
- [ ] `audit/gates/hint.json` and `audit/pass_fail_hint.json` identify the exact evaluation.

### Review target

- [ ] A restored evidence package can report `REVIEW_READY` only when the review-target extraction/integrity checks pass.
- [ ] Review-ready status is never presented as semantic completion or citation authority.

### Citation target: the true package gate

`PASS_STRICT` requires all applicable checks below for the current head:

- [ ] package schema, source identity, lifecycle state, rights basis, and scope validate;
- [ ] source/run artifacts, projections, review ledger chain, canonical revision, paragraph/TOC/boundary projection hashes, binary evidence, and scope/run binding pass integrity checks;
- [ ] every surface is accounted for and extraction findings have typed, verified resolution evidence;
- [ ] mock evidence is absent from citation authority;
- [ ] sidecar/plugin evidence has source-image anchors and immutable provenance that the gate verifies; a plugin cannot opt out by omitting adapter flags;
- [ ] every canonical block/span is assigned exactly once with no gap, overlap, or orphan;
- [ ] every paragraph has a valid current-revision semantic decision;
- [ ] every paragraph decision has `source_id`, `sourcepage_path`, role, semantic summary, all candidate arrays including reasoning leaps, `used_in_card`, use/exclusion reason, and `requires_primary_anchor`;
- [ ] every reasoning-leap host, premise paragraph, and conclusion paragraph has disposition `used`, so citation export cannot contain dangling paragraph IDs;
- [ ] primary-anchor requirements are met by primary-source evidence;
- [ ] every asset occurrence has a semantic disposition and usable bytes/anchor when retained;
- [ ] every table, equation, figure, caption, and other complex object has the required representation and relation review;
- [ ] multi-surface/EPUB structure dispositions every TOC candidate, maps every used candidate and boundary, contains a non-empty canonical TOC, partitions paragraphs exactly once in source order (including mid-surface boundaries), materializes `structure_path`, and has hash-bound projections;
- [ ] a semantic source-use boundary exists;
- [ ] semantic reviewer provenance satisfies the package privacy scope;
- [ ] the recomputed result is `trust_status=citation_grade`, `public_status=PASS_STRICT`, and contains zero hard blockers.

Required current evidence:

```text
PACKAGE/audit/gates/citation.json
PACKAGE/audit/pass_fail_citation.json
PACKAGE/package_manifest.json
PACKAGE/ledger/review_decisions.jsonl
PACKAGE/runs/<active_run_id>/run_manifest.json
```

The convenience files `audit/gate_report.json` and `audit/pass_fail.json` are acceptable only when their `target`/`derived_from` points to the current citation evaluation. Prefer the target-specific paths above.

## E. Review transaction and conflict tests

- [ ] A valid multi-decision batch appends atomically and increments the review revision once.
- [ ] Any invalid decision rejects the entire batch without a partial ledger append.
- [ ] stale `--expected-revision` fails.
- [ ] wrong expected tenant/workspace fails before reading or writing protected review state.
- [ ] silent overwrite fails; a replacement names the prior decision in `supersedes`.
- [ ] source SHA, active run, and canonical revision conflicts fail.
- [ ] canonical correction, variant selection, contiguous join, exact split, and contiguous same-surface reorder preserve raw source spans.
- [ ] canonical edits and paragraph/structure decisions cannot share a batch.
- [ ] changing canonical revision invalidates stale paragraph decisions until re-reviewed.
- [ ] tampering with the review ledger or hash chain causes the gate to fail.
- [ ] self-asserted resolution strings cannot clear a bad source-image hash, invalid bbox, missing asset, absent rendered rendition, or unbound producer claim.

## F. Publish and downstream contract

- [ ] citation publication fails before `PASS_STRICT` and succeeds after it for the same head;
- [ ] output is outside the evidence package;
- [ ] Markdown and chunks contain anchors and trust metadata appropriate to the target;
- [ ] citation chunks retain claim, method, metric, boundary, reasoning-leap candidates and reviewed structure paths;
- [ ] every paragraph ID referenced by an exported reasoning leap resolves to a paragraph present in the same revision-bound citation export;
- [ ] the export manifest binds package/source/run/canonical/review revisions and artifact hashes;
- [ ] the exported gate report hash matches the manifest;
- [ ] `embedding_manifest.json` is `unembedded`, carries the chunks hash and invalidation key, and does not claim vectors exist;
- [ ] scope, rights, retention, access tags, and source-use boundary propagate to the export;
- [ ] a downstream ingestion can reject stale or mismatched hashes and purge by package/revision/invalidation key;
- [ ] no output claims translation, EPUB/DOCX round-trip, or vector indexing as a v2 capability.

## G. Revocation and retention

- [ ] `xuanzang revoke` requires a non-empty reason and can enforce expected review/scope values;
- [ ] the package lifecycle becomes `revoked` and status reports the lifecycle blocker;
- [ ] later restore into the same identity, review, hint publish, and citation publish are rejected;
- [ ] `audit/revocation_tombstone.json` binds package/source/run/canonical/review/scope and has a stable `revocation_id`;
- [ ] an optional tombstone copy is required to be outside the package;
- [ ] repeated revoke is idempotent and returns the existing tombstone;
- [ ] pilot operators demonstrate deletion/quarantine and acknowledgement in every configured vector store, cache, export store, review queue, replica, and backup policy;
- [ ] documentation states that the CLI emits instructions and does not perform downstream deletion.

## H. Compatibility and migration boundary

- [ ] README labels `ledger`, `toc`, `split`, `clean`, `validate`, translation commands, DOCX assembly, and EPUB reinsertion as v1 compatibility-only.
- [ ] mock translation cannot be described as semantic or publication translation.
- [ ] v1 `PASS_STRICT`, goal-loop scores, chapter edits, and translation audits are historical metadata only after migration.
- [ ] migration writes a report and ID crosswalk and begins at `needs_review` until current v2 gates pass.
- [ ] migrated packages begin with an empty v2 review ledger; legacy manual material remains snapshot evidence rather than silently promoted decisions.
- [ ] OCR reuse is supported by source/page/sidecar crosswalk evidence; unsupported or ambiguous mappings remain blockers.
- [ ] `toc`/`split` refuse to mutate any reviewed v2 package; compatibility proposals on an unreviewed package cannot survive immutable-projection checks without a restoring re-projection.

## I. Documentation and security review

- [ ] README commands match `xuanzang --help`.
- [ ] Known limitations distinguish trusted local pilot from public multi-tenant no-go.
- [ ] Package, review, publish, migration, and revocation schemas are documented without claiming unimplemented services.
- [ ] No absolute private paths, private source excerpts, secrets, or copyrighted fixtures appear in committed docs/tests/audits.
- [ ] dependency and archive/parser attack surfaces receive a security review appropriate to the release scope;
- [ ] license and third-party dependency obligations are reviewed;
- [ ] threat model covers malicious documents, UTF-16 DTD/entity payloads, Unicode-canonical ZIP collisions, archive traversal/bombs, symlinks, parser vulnerabilities, local conversion, provider egress, tampered artifacts, and cross-scope access.

## J. Release decisions

### Library/CLI 2.0

- [ ] Sections A–I pass for the implemented source/feature matrix.
- [ ] Any skipped format or optional adapter is explicitly excluded from the release claim.
- [ ] A named maintainer signs the release evidence with commit and artifact hashes.

### Trusted local pilot

- [ ] Library/CLI release is accepted.
- [ ] Pilot source rights, storage, users, host limits, backup, retention, escalation, and downstream stores are enumerated.
- [ ] A real, authorized canary package completes restore → status → review → publish → revoke with recorded evidence.
- [ ] ManualStrict review quality is independently sampled by a domain expert; the runtime's mechanical gate is not treated as proof of scientific correctness.
- [ ] Rollback and disk-pressure recovery are rehearsed.

### Public multi-tenant service

- [ ] Keep status **NO-GO** while any production control in [known_limitations.md](known_limitations.md) is missing.
- [ ] Require a separate service threat model, architecture review, tenant-isolation tests, authorization tests, deletion/retention evidence, load/capacity tests, observability, incident response, and compliance review.
- [ ] Require authenticated orchestrator reviewer context; package metadata or CLI expected-scope flags cannot substitute for it.

The public multi-tenant section is currently a blocking checklist, not a statement of delivered capability.

## K. Semantic/visual structure prompt protocol

- [x] Whole-book architecture analysis does not prematurely finalize a TOC.
- [x] Visual TOC discovery and transcription cover complete page runs, reading order, bylines, wraps, and uncertainty.
- [x] Canonical TOC separates display title, normalized match title, type, parent, output area, and materialization.
- [x] Boundary candidate assessment explicitly classifies running headers, TOC residue, prose mentions, captions, and OCR noise.
- [x] Exact boundary resolution uses inclusive starts, exclusive ends, neighboring semantic context, and source evidence.
- [x] Media affiliation protects image, caption, byline, epigraph, credit, and source-relative order.
- [x] Post-split semantic audit reviews every section; reverse audit independently reconstructs the output TOC.
- [x] Revision is evidence-bounded and requires dependent audit reruns.
- [x] Prompt-stage scoring enforces 98 for implementation advancement while explicitly having no v2 package-trust authority.
- [x] Book-type variants cover monographs, collections, lectures, interviews, catalogues, bilingual books, critical editions, reference-heavy books, Chinese scans, and dirty EPUBs.
- [x] Codex and ZCode prompt/reference copies are byte-identical and contract-tested.
- [ ] An authorized real-book structure review records prompt proposals as revision-bound v2 `structure` decisions and passes the current citation gate.
