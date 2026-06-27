# TOC-First Segmentation

Do not trust EPUB spine, PDF pages, OCR lines, or file names as chapters. Treat them as evidence.

Build `toc/toc_candidates.json`, reconstruct `toc/canonical_toc.json`, generate `toc/boundary_candidates.json`, resolve `toc/chapter_boundary_map.json`, then split deterministically.

Low-confidence TOC items or boundaries block PASS_STRICT. Running headers, page numbers, captions, and TOC residue must not become headings.
