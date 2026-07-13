# Export, reinsertion, and publication

Treat every output as a derivative bound to a package revision, trust decision, export specification, and validation report. Publishing cannot raise source trust.

## Current runtime boundary

`xuanzang publish` is the only v2-native exporter. It emits anchored Markdown, `chunks.jsonl`, a gate snapshot, an export manifest, and an `embedding_manifest.json` that declares invalidation/namespace requirements but contains no vectors.

`assemble-docx` and `reinsert-epub` are compatibility-only v1 commands. They do not prove that v2 canonical/paragraph decisions, complete object relations, translation semantics, accessibility, or publication validation were applied. Treat their outputs as draft derivatives or migration fixtures. A production v2 DOCX/EPUB exporter must implement and test the contracts below before it can claim publication eligibility.

## Contents

- [Export manifest](#export-manifest)
- [Knowledge and interchange exports](#knowledge-and-interchange-exports)
- [DOCX assembly](#docx-assembly)
- [EPUB reinsertion](#epub-reinsertion)
- [Publication validation](#publication-validation)

## Export manifest

Every export should record:

```yaml
export_id: ...
export_kind: markdown | jsonl | retrieval | docx | epub | translation | other
package_id: ...
package_revision: ...
active_run_id: ...
source_sha256: ...
requested_target: hint | citation
trust_status: ...
gate_status: ...
specification_hash: ...
files: []
checksums: {}
created_at: ...
limitations: []
```

Fail citation export when the active revision lacks `PASS_STRICT`. Include visible status and limitations in hint exports.

For current v2 `publish`, verify `document.md`, `chunks.jsonl`, `embedding_manifest.json`, exported gate report, their SHA-256 values, `spec_sha256`, package/run/canonical/review revisions, source-use boundary, review-decision IDs, and scope. Vector generation and ACL enforcement occur downstream.

## Knowledge and interchange exports

For Markdown, JSONL, retrieval, or dataset output:

- preserve paragraph IDs, evidence IDs, page/logical-surface anchors, structure path, source revision, trust, reviewer provenance, access tags, and use boundary;
- keep tables, formulas, figures, captions, notes, and relations as structured objects or linked assets;
- hash content and configuration;
- use stable filenames derived from source/package identity;
- separate hint and citation-grade namespaces;
- emit a machine-readable manifest and schema version;
- verify every exported anchor against the active package.

Derived chunks and embeddings remain regenerable. Keep canonical evidence in the package.

## DOCX assembly

Assemble from reviewed canonical structure and target units:

- follow canonical section order;
- map heading levels deterministically;
- preserve paragraphs and explicit unit/source anchors in metadata or sidecar;
- insert image occurrences at reviewed locations;
- reconstruct captions, tables, notes, references, and links;
- preserve list numbering, emphasis, superscript/subscript, RTL direction, and language tags where supported;
- package fonts only when licensing permits;
- generate index locators after final pagination.

DOCX pagination can differ from the source. Describe citation anchors using source pages/surfaces, not regenerated page numbers.

## EPUB reinsertion

Use stored href and DOM/anchor mappings. Replace reviewed target nodes by exact anchor or unit ID. Avoid fuzzy text matching for publication output.

Preserve:

- mimetype and container requirements;
- OPF metadata, manifest, spine, and bindings;
- EPUB nav/NCX and landmarks;
- XHTML namespaces and validity;
- CSS, fonts, media, and relative paths;
- images, SVG, MathML, alt text, and captions;
- anchors, hrefs, note references/backlinks, and cross-references;
- language and direction attributes;
- accessibility semantics.

When the target structure intentionally differs, record an explicit source-to-target mapping and rebuild navigation from the reviewed target tree.

## Publication validation

Validate mechanically and visually:

- package/schema validity;
- file checksums and no missing assets;
- exact unit/source mapping;
- image occurrence count and position;
- navigation, links, notes, citations, and cross-references;
- table/formula rendering and captions;
- language, direction, encoding, fonts, and accessibility;
- representative page/screen rendering across readers;
- no source text leakage when output scope is restricted;
- no secrets, temporary files, or raw provider responses;
- output opens in at least one independent reader/editor appropriate to the format.

Publication validation is a deliverable gate. A valid EPUB/DOCX can still carry `needs_review` source or translation content; label it as a draft. A publication-grade deliverable requires source eligibility, complete target semantic audit, and output validation together.
