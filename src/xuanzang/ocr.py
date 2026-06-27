from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .utils import cjk_ratio, read_jsonl, write_json


def audit_ocr(package: Path, lang: str | None = None) -> dict[str, Any]:
    blocks = read_jsonl(package / 'ledger' / 'source_blocks.jsonl')
    engines = Counter((b.get('ocr_engine') or 'text_layer') for b in blocks)
    cjk_values = [float(b.get('cjk_ratio') if b.get('cjk_ratio') is not None else cjk_ratio(b.get('text', ''))) for b in blocks if b.get('text')]
    low_cjk = [b.get('block_id') for b in blocks if b.get('text') and cjk_ratio(b.get('text', '')) < 0.15 and lang == 'zh']
    garbled = []
    for b in blocks:
        text = b.get('text', '')
        if '\ufffd' in text or (text and sum(1 for ch in text if not ch.isalnum() and not ch.isspace() and not ('\u4e00' <= ch <= '\u9fff')) / max(1, len(text)) > 0.45):
            garbled.append(b.get('block_id'))
    fallback = engines.get('fallback_tesseract', 0)
    avg_cjk = sum(cjk_values) / len(cjk_values) if cjk_values else 0.0
    blockers = []
    if lang == 'zh' and avg_cjk < 0.25:
        blockers.append('low_cjk_ratio')
    if lang == 'zh' and fallback > max(1, int(len(blocks) * 0.05)):
        blockers.append('fallback_tesseract_overuse')
    if garbled:
        blockers.append('ocr_garble')
    audit = {
        'status': 'PASS' if not blockers else 'FAIL_REVIEW',
        'language': lang,
        'block_count': len(blocks),
        'engine_counts': dict(engines),
        'cjk_ratio_avg': avg_cjk,
        'low_cjk_blocks': low_cjk[:50],
        'suspected_garbled_blocks': garbled[:50],
        'hard_blockers': blockers,
    }
    write_json(package / 'audit' / 'ocr_audit.json', audit)
    (package / 'audit' / 'ocr_audit.md').write_text(
        f"# OCR Audit\n\n- status: {audit['status']}\n- language: {lang}\n- block_count: {len(blocks)}\n- cjk_ratio_avg: {avg_cjk:.4f}\n- engine_counts: {dict(engines)}\n- hard_blockers: {blockers}\n",
        encoding='utf-8',
    )
    return audit
