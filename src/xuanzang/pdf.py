from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from .utils import cjk_ratio, ensure_dir, sha256_file, write_json, write_jsonl


def extract_pdf(source: Path, out_dir: Path, ocr: str = 'auto', lang: str | None = None, render_pages: bool = True) -> dict[str, Any]:
    source = source.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f'refusing to delete or overwrite existing package: {out_dir}')
    ensure_dir(out_dir)
    ensure_dir(out_dir / 'source')
    ensure_dir(out_dir / 'ledger')
    blocks: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    ocr_pages = []
    doc = fitz.open(str(source))
    page_images_dir = ensure_dir(out_dir / 'source' / 'page_images')
    block_counter = 0
    image_counter = 0
    for page_index, page in enumerate(doc, start=1):
        if render_pages:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pix.save(str(page_images_dir / f'page_{page_index:04d}.png'))
        text_blocks = page.get_text('blocks') or []
        extracted_any = False
        for b in text_blocks:
            if len(b) < 5:
                continue
            x0, y0, x1, y1, text = b[:5]
            text = str(text).strip()
            if not text:
                continue
            extracted_any = True
            block_counter += 1
            blocks.append({
                'block_id': f'p{page_index:04d}_b{block_counter:06d}',
                'source_type': 'pdf_text',
                'page': page_index,
                'bbox': [round(float(x0), 2), round(float(y0), 2), round(float(x1), 2), round(float(y1), 2)],
                'text': text,
                'normalized_text': ' '.join(text.split()),
                'block_kind': 'text_candidate',
                'ocr_engine': None,
                'ocr_confidence': None,
                'cjk_ratio': cjk_ratio(text),
            })
        if not extracted_any and ocr == 'mock':
            block_counter += 1
            mock_text = '模拟 OCR 文本 第%d页' % page_index if lang == 'zh' else 'Mock OCR text page %d' % page_index
            blocks.append({
                'block_id': f'p{page_index:04d}_b{block_counter:06d}',
                'source_type': 'pdf_ocr',
                'page': page_index,
                'bbox': [0, 0, round(page.rect.width, 2), round(page.rect.height, 2)],
                'text': mock_text,
                'normalized_text': mock_text,
                'block_kind': 'text_candidate',
                'ocr_engine': 'mock',
                'ocr_confidence': 1.0,
                'cjk_ratio': cjk_ratio(mock_text),
            })
            ocr_pages.append(page_index)
        elif not extracted_any and ocr in {'auto', 'paddle', 'tesseract'}:
            from .adapters import choose_ocr_adapter
            adapter = choose_ocr_adapter(ocr)
            image_path = page_images_dir / f'page_{page_index:04d}.png'
            if adapter is not None:
                for block in adapter.recognize(image_path, lang=lang, page_id=f'page_{page_index:04d}'):
                    block_counter += 1
                    blocks.append({
                        'block_id': f'p{page_index:04d}_b{block_counter:06d}',
                        'source_type': 'pdf_ocr', 'page': page_index,
                        'bbox': block.bbox, 'coordinate_space': 'render_pixels',
                        'text': block.text, 'normalized_text': ' '.join(block.text.split()),
                        'block_kind': block.block_kind, 'ocr_engine': adapter.name,
                        'ocr_confidence': block.confidence, 'cjk_ratio': cjk_ratio(block.text),
                    })
                if any(b.get('page') == page_index and b.get('source_type') == 'pdf_ocr' for b in blocks):
                    ocr_pages.append(page_index)
        for img in page.get_images(full=True):
            image_counter += 1
            images.append({
                'image_id': f'pdf_img{image_counter:05d}',
                'source_type': 'pdf',
                'page': page_index,
                'xref': img[0],
                'exists': True,
                'marker': f'[[IMAGE pdf_img{image_counter:05d} page="{page_index}"]]',
            })
    inventory = {
        'source_path': str(source),
        'source_sha256': sha256_file(source),
        'format': 'pdf',
        'pages': doc.page_count,
        'metadata': dict(doc.metadata or {}),
    }
    write_jsonl(out_dir / 'ledger' / 'source_blocks.jsonl', blocks)
    write_jsonl(out_dir / 'ledger' / 'image_blocks.jsonl', images)
    write_json(out_dir / 'source' / 'source_inventory.json', inventory)
    write_json(out_dir / 'package_manifest.json', {
        'package_version': 1,
        'created_by': 'xuanzang-skill',
        'source': inventory,
        'counts': {'text_blocks': len(blocks), 'image_blocks': len(images)},
    })
    hard = [] if blocks else ['source_coverage_gap']
    audit = {
        'status': 'PASS' if not hard else 'FAIL_REVIEW',
        'format': 'pdf',
        'pages': doc.page_count,
        'text_blocks': len(blocks),
        'image_blocks': len(images),
        'ocr_pages': ocr_pages,
        'hard_blockers': hard,
    }
    write_json(out_dir / 'audit' / 'source_integrity.json', audit)
    (out_dir / 'audit' / 'source_integrity.md').write_text(
        f"# Source Integrity\n\n- status: {audit['status']}\n- format: pdf\n- pages: {doc.page_count}\n- text_blocks: {len(blocks)}\n- image_blocks: {len(images)}\n- ocr_pages: {len(ocr_pages)}\n",
        encoding='utf-8',
    )
    return audit
