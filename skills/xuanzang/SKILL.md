---
name: xuanzang
description: Strict book reconstruction, OCR, TOC-first chapter segmentation, RAG cleaning, translation preparation, LLM translation validation, semantic audit, and EPUB/DOCX reinsertion. Use when working with EPUB, PDF, MOBI-derived, scanned, OCR-damaged, image-heavy, note-heavy, index-heavy, or structurally dirty books that require no-omission extraction, semantic table-of-contents reconstruction, chapter splitting, image preservation, translation prompts, PASS_STRICT audits, or publication-style reinsertion.
---

# 玄奘 xuanzang

Use this skill for strict book workflows where source fidelity matters more than speed.

## Rule

Create a source ledger before chapter splitting. Reconstruct the logical TOC before trusting file boundaries. Preserve unit IDs and image markers through translation. Advance only when the active loop scores at least 98 with no hard blockers.

## Workflow

1. Inspect source and create a package with `xuanzang ledger`.
2. Build TOC candidates and canonical TOC with `xuanzang toc`.
3. Resolve boundaries and split chapters with `xuanzang split`.
4. For RAG, run `xuanzang clean` and `xuanzang validate --strict`.
5. For translation, run `xuanzang prep-translation`, `xuanzang translate`, and `xuanzang audit-translation`.
6. Assemble outputs with `xuanzang assemble-docx` or `xuanzang reinsert-epub`.
7. Record loop scores and stop if any loop is below 98.

## Load References

- Read `references/goal-mode.md` before running a staged goal loop.
- Read `references/toc-first-segmentation.md` before splitting dirty EPUB, PDF, or OCR books.
- Read `references/pdf-ocr.md` before OCR or Chinese scanned-book work.
- Read `references/rag-strict.md` before PASS_STRICT / FAIL_REVIEW work.
- Read `references/translation-workflow.md` before preparing prompts or running model translation.
- Read `references/semantic-audit.md` before meaning-level review or revision.
- Read `references/reinsertion.md` before DOCX or EPUB assembly.

## Safety

Do not commit copyrighted source books, extracted full text, translations, raw model responses, or API keys. Use synthetic or public-domain fixtures for tests.
