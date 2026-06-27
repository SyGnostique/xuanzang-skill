# 玄奘 xuanzang-skill

`xuanzang-skill` is a strict book reconstruction and translation-engineering workflow for damaged EPUB, PDF, OCR, RAG, and publication tasks.

It is not a black-box translator. It turns books into auditable ledgers, reconstructs semantic TOCs, preserves text units and image anchors, validates translation outputs, and assembles EPUB/DOCX deliverables without silent omissions.

## Safety

Do not commit copyrighted books, extracted source text, translated books, API keys, raw model responses, or generated packages. The repository is configured to ignore common private book and translation artifacts.

## Quickstart

```bash
pip install -e .
xuanzang --help
```

Create a package from an EPUB or PDF:

```bash
xuanzang ledger path/to/book.epub --out packages/book
xuanzang toc packages/book
xuanzang split packages/book
xuanzang validate packages/book --strict
```

Run translation preparation and a mock translation validation path:

```bash
xuanzang prep-translation packages/book --target zh-CN
xuanzang translate packages/book --provider mock --run-id mock_v1
xuanzang audit-translation packages/book --run-id mock_v1
xuanzang assemble-docx packages/book --run-id mock_v1 --out book.docx
```

## Core rule

Scripts prove mechanical integrity. LLM or human semantic review resolves structure, meaning, terminology, and revision decisions. A fluent result is not accepted unless source coverage, unit preservation, image preservation, and semantic audit gates pass.

## Modes

- `RAG strict`: reconstruct clean Markdown sections with PASS_STRICT / FAIL_REVIEW gates.
- `Translation`: prepare prompt context, preserve units/images, validate model output, audit semantics, and reinsert.
- `OCR`: create page/block ledgers with engine provenance and CJK/fallback quality gates.

## Status

v1.0 provides a tested local skeleton and strict workflow implementation with synthetic fixtures. Real-world difficult books may still require semantic review and provider-specific LLM calls.
