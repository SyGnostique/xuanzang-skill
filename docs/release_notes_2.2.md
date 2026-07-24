# Xuanzang 2.2 release notes

Xuanzang 2.2 makes the user-facing final artifact—not an intermediate evidence package or score—the default contract.

## Added

- Outcome-first Codex and ZCode skills for full single-book and directory rebuilds.
- A local controller prompt and executable local-strict workflow.
- A failure-regression registry distilled from prior structural, OCR, reading-order, table, image, publication, and false-PASS incidents.
- `xuanzang verify-local-strict PACKAGE --export EXPORT`, which independently verifies package/export identity, hashes, gates, Markdown hierarchy, reverse-locatable chunks, assets, and objects.
- A repository-local Codex CLI wrapper that works without installing a console entry point.
- A reviewed `document_title` projection for the final book H1.

## Changed

- Citation Markdown always reserves exactly one H1 for the book title.
- Materialized source structure renders as H2/H3; deeper hierarchy remains in machine-readable `structure_path`.
- External/formal scoring is optional and never a completion authority.
- Final completion requires the current citation gate, publication validation, and local strict acceptance to agree.

## Compatibility

Existing packages can still recompute their historical gates and publish through the v2 interface. A legacy export without a reviewed `document_title` or the new Markdown contract will not pass 2.2 local strict acceptance until it is re-reviewed and republished.
