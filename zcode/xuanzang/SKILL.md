---
name: xuanzang
description: |
  Strict book reconstruction and translation-engineering skill for GLM ZCode/OpenClaw agents.
  Use for EPUB, PDF, OCR-damaged, scanned, image-heavy, note-heavy, index-heavy, or structurally dirty books that need no-omission extraction, semantic TOC reconstruction, chapter splitting, image preservation, RAG PASS_STRICT audits, translation prompt preparation, semantic translation audit, or DOCX/EPUB reinsertion.
metadata:
  openclaw:
    requires:
      env: []
      bins:
        - python3
    emoji: "📚"
    source: https://github.com/SyGnostique/xuanzang-skill/tree/main/zcode/xuanzang
    homepage: https://github.com/SyGnostique/xuanzang-skill
---

# 玄奘 xuanzang for GLM ZCode / OpenClaw

Use this skill when source fidelity, chapter structure, OCR quality, image anchors, and translation audit matter more than speed.

**Scripts are in:** `{SKILL_DIR}/scripts/`

## When to Use

Trigger for tasks such as:

- Extract every chapter from a dirty EPUB/PDF without omissions.
- Reconstruct a semantic TOC before splitting chapters.
- Preserve images, captions, notes, indexes, and source anchors for later translation or reinsertion.
- Clean OCR/RAG text with PASS_STRICT / FAIL_REVIEW gates.
- Prepare translation prompts with whole-book summary, chapter briefs, terminology, style, and format policy.
- Audit translation by source unit instead of sampling.
- Assemble DOCX or reinsert translated text back into EPUB while preserving image positions.

## Core Rule

Create a source ledger before chapter splitting. Reconstruct the logical TOC before trusting EPUB spine, PDF pages, OCR lines, or filenames. Preserve unit IDs and image markers through translation. Advance only when the active loop scores at least 98 and has no hard blocker.

## Dependencies

Python packages are declared by the repository `pyproject.toml`.

```bash
pip install -e /path/to/xuanzang-skill
```

If this skill directory is copied outside the repository, set:

```bash
export XUANZANG_REPO=/path/to/xuanzang-skill
```

Optional GLM/Zhipu model calls may use:

```bash
export ZHIPU_API_KEY="your_key"
```

`ZHIPU_API_KEY` is optional for local ledger, split, validation, mock translation, and reinsertion commands. Never write API keys into source files, prompts, audit logs, or committed config.

## Security Notes

- Do not commit copyrighted source books, extracted full text, translations, raw model responses, API keys, or generated private packages.
- Read model keys only from environment variables or agent-managed secret config.
- Do not silently summarize, omit, reorder, or invent text to make a book pass validation.
- If OCR or semantic boundaries are low-confidence, return FAIL_REVIEW and preserve evidence.
- For GLM/ZCode usage, prefer fixed scripts in `{SKILL_DIR}/scripts/` over ad hoc shell fragments.

## Mandatory Restrictions

1. Use `python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py ...` as the execution entrypoint.
2. Do not bypass ledger, TOC, split, and validation stages for dirty books.
3. Do not mark mock translation as publication-ready semantic PASS.
4. Do not add book-specific verifier exemptions to hide OCR or structure defects.
5. Do not send private book text to a remote model unless the user has explicitly authorized that provider call.

## Setup Check

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py check-env
```

Expected output is JSON with `ok: true`, Python version, discovered repo root, xuanzang version, and whether `ZHIPU_API_KEY` is present.

## Standard Workflow

### 1. Inspect and Create Source Ledger

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py ledger \
  /path/to/book.epub \
  --out /path/to/package
```

For PDF/OCR, include language when known:

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py ledger \
  /path/to/book.pdf \
  --out /path/to/package \
  --lang zh
```

### 2. Reconstruct TOC Semantically

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py toc /path/to/package
```

Before resolving hard books, read `references/toc-first-segmentation.md` and inspect all TOC candidates as evidence. Use GLM semantic reasoning for the canonical TOC; scripts provide evidence and deterministic storage, not the final judgment for difficult structures.

### 3. Split Chapters

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py split /path/to/package
```

Inspect `toc/boundary_candidates.json` and `toc/chapter_boundary_map.json` for low-confidence boundaries.

### 4. RAG Strict Cleaning

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py clean /path/to/package
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py validate /path/to/package --strict
```

PASS_STRICT requires no source coverage gap, OCR corruption, low-confidence boundary, false-pass issue, missing image, corrupted title tree, or active structure blocker.

### 5. Translation Preparation

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py prep-translation /path/to/package --target zh-CN
```

Then complete the semantic artifacts in `translation_prep/`: whole-book summary, chapter briefs, style guide, terminology policy, prompt pack, and QA gates. Professional translation preparation is semantic work; do not rely on scaffolds alone.

### 6. Translation Run and Audit

Local smoke test:

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py translate /path/to/package --provider mock --run-id mock_v1
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py audit-translation /path/to/package --run-id mock_v1
```

For real GLM/Zhipu translation, use the prepared prompt jobs and user-approved provider settings. The output must preserve every source unit ID and every image marker exactly, then pass mechanical validation and source-facing semantic audit.

### 7. Assemble Deliverables

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py assemble-docx /path/to/package --run-id mock_v1 --out /path/to/book.docx
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py reinsert-epub /path/to/package --run-id mock_v1 --out /path/to/book.epub
```

## CLI Reference

```bash
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py check-env
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py inspect SOURCE [--out DIR]
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py ledger SOURCE --out PACKAGE [--ocr auto|mock|none] [--lang LANG]
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py toc PACKAGE
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py split PACKAGE
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py clean PACKAGE
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py validate PACKAGE [--strict]
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py prep-translation PACKAGE [--target zh-CN]
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py translate PACKAGE [--provider mock] [--run-id RUN]
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py audit-translation PACKAGE [--run-id RUN]
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py assemble-docx PACKAGE --run-id RUN --out DOCX
python3 {SKILL_DIR}/scripts/xuanzang_zcode_cli.py reinsert-epub PACKAGE --run-id RUN --out EPUB
```

## Response Format

Commands print compact Python/JSON-like status to stdout and write durable audit files into the package directory:

- `audit/source_integrity.json`
- `audit/ocr_audit.json`
- `toc/canonical_toc.json`
- `toc/chapter_boundary_map.json`
- `audit/split_coverage.json`
- `audit/pass_fail.json`
- `translation_prep/deepseek_jobs_manifest.json`
- `translation_runs/<run_id>/audit/final_translation_run_audit.json`
- `translation_runs/<run_id>/audit/semantic_audit_status.json`

## Error Handling

- `xuanzang package is not importable`: install the repo with `pip install -e` or set `XUANZANG_REPO`.
- `unsupported source format`: convert MOBI/AZW3 to EPUB first, then rerun ledger.
- `FAIL_REVIEW`: inspect blocking findings and repair OCR, TOC, boundaries, images, or translation units before advancing.
- Missing `ZHIPU_API_KEY`: only blocks user-approved GLM/Zhipu remote model calls, not local mechanical commands.

## Load References

- Read `references/goal-mode.md` before staged goal loops.
- Read `references/toc-first-segmentation.md` before splitting dirty EPUB/PDF/OCR books.
- Read `references/pdf-ocr.md` before OCR or Chinese scanned-book work.
- Read `references/rag-strict.md` before PASS_STRICT / FAIL_REVIEW work.
- Read `references/translation-workflow.md` before prompt preparation or model translation.
- Read `references/semantic-audit.md` before meaning-level review or revision.
- Read `references/reinsertion.md` before DOCX or EPUB assembly.
