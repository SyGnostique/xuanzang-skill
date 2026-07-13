from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .utils import ensure_dir, read_json, read_jsonl, write_json

SECTION_KEYWORDS = {
    'frontmatter': ['cover', 'title page', 'copyright', 'dedication', 'epigraph', 'contents', 'timeline', 'maps', '序', '目录'],
    'notes': ['notes', '注释', 'endnotes'],
    'bibliography': ['bibliography', 'references', 'works cited', '参考文献', '书目'],
    'index': ['index', '索引'],
    'acknowledgements': ['acknowledgements', 'acknowledgments', '致谢'],
    'glossary': ['glossary', 'characters', '术语', '人物'],
    'gallery': ['gallery', 'plates', 'illustrations', '图录', '插图'],
}


def classify_section(title: str) -> str:
    low = title.lower()
    for typ, keys in SECTION_KEYWORDS.items():
        if any(k in low or k in title for k in keys):
            return typ
    if re.match(r'^(part|book)\s+[ivxlcdm0-9]+\b', low) or re.match(r'^第[一二三四五六七八九十百0-9]+[部篇卷]', title):
        return 'part_divider'
    return 'body_chapter'


def harvest_toc_candidates(package: Path) -> dict[str, Any]:
    blocks = read_jsonl(package / 'ledger' / 'source_blocks.jsonl')
    seed_path = package / 'toc' / 'toc_candidates_seed.json'
    candidates = []
    if seed_path.exists():
        candidates.extend(read_json(seed_path).get('candidates', []))
    seen = {c.get('block_id') for c in candidates if c.get('block_id')}
    for b in blocks:
        text = b.get('normalized_text') or b.get('text', '')
        if not text or b.get('block_id') in seen:
            continue
        short = len(text) <= 90
        heading_signal = bool(re.match(r'^(chapter|part|book|section|introduction|conclusion|notes|bibliography|index)\b', text, re.I))
        numbered = bool(re.match(r'^([0-9]+\.|[IVXLCDM]+\.|第[一二三四五六七八九十百0-9]+[章节部篇])', text))
        if short and (heading_signal or numbered or b.get('block_kind') in {'heading_candidate', 'structure_candidate'}):
            candidates.append({
                'candidate_id': f'toc_cand_{len(candidates)+1:05d}',
                'text': text,
                'source': 'ledger_heading_signal',
                'block_id': b.get('block_id'),
                'page': b.get('page'),
                'spine_index': b.get('spine_index'),
                'href': b.get('href'),
                'score': 0.75,
                'evidence': [b.get('block_id')],
            })
    result = {'candidates': candidates, 'candidate_count': len(candidates)}
    write_json(package / 'toc' / 'toc_candidates.json', result)
    return result


def build_canonical_toc(package: Path) -> dict[str, Any]:
    cand_path = package / 'toc' / 'toc_candidates.json'
    if not cand_path.exists():
        harvest_toc_candidates(package)
    candidates = read_json(cand_path).get('candidates', [])
    blocks = read_jsonl(package / 'ledger' / 'source_blocks.jsonl')
    if not candidates and blocks:
        first = blocks[0]
        candidates = [{'text': 'Body', 'block_id': first['block_id'], 'source': 'fallback_first_block', 'score': 0.5, 'evidence': [first['block_id']]}]
    items = []
    used_titles = set()
    for c in candidates:
        title = ' '.join(str(c.get('text', '')).split())
        if not title or title.lower() in used_titles:
            continue
        used_titles.add(title.lower())
        typ = classify_section(title)
        # Mechanical signals create proposals only. A high numeric heuristic must
        # never masquerade as semantic TOC review.
        confidence = min(float(c.get('score', 0.5)), 0.95)
        if c.get('semantic_reviewed') is True:
            confidence = 1.0
        items.append({
            'toc_id': f'toc_{len(items)+1:03d}',
            'order': len(items) + 1,
            'level': 1,
            'title': title,
            'normalized_title': re.sub(r'^[0-9]+\.\s*', '', title),
            'section_type': typ,
            'expected_start_cues': [title, re.sub(r'^[0-9]+\.\s*', '', title)],
            'expected_end_before': None,
            'source_evidence': c.get('evidence', []),
            'candidate_block_id': c.get('block_id'),
            'confidence': confidence,
            'notes': 'Generated from harvested TOC candidates; replace with LLM semantic TOC for hard real books.'
        })
    for i, item in enumerate(items[:-1]):
        item['expected_end_before'] = items[i + 1]['title']
    unresolved = [i for i in items if i['confidence'] < 1.0]
    result = {'items': items, 'toc_confidence': 'reviewed' if not unresolved else 'review', 'unresolved': unresolved}
    write_json(package / 'toc' / 'canonical_toc.json', result)
    blockers = ['low_confidence_toc'] if unresolved or not items else []
    audit = {'status': 'PASS' if not blockers else 'FAIL_REVIEW', 'item_count': len(items), 'hard_blockers': blockers}
    write_json(package / 'audit' / 'toc_validation.json', audit)
    return result
