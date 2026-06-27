from __future__ import annotations

from pathlib import Path
from typing import Any

from .toc import build_canonical_toc, harvest_toc_candidates
from .utils import ensure_dir, read_json, read_jsonl, write_json, write_jsonl


def build_boundary_candidates(package: Path) -> dict[str, Any]:
    toc_path = package / 'toc' / 'canonical_toc.json'
    if not toc_path.exists():
        harvest_toc_candidates(package)
        build_canonical_toc(package)
    toc = read_json(toc_path)
    blocks = read_jsonl(package / 'ledger' / 'source_blocks.jsonl')
    candidates = []
    for item in toc.get('items', []):
        starts = []
        cues = [c.lower() for c in item.get('expected_start_cues', []) if c]
        for idx, b in enumerate(blocks):
            text = (b.get('normalized_text') or b.get('text', '')).strip()
            low = text.lower()
            score = 0.0
            reason = ''
            if low in cues:
                score, reason = 0.99, 'exact title match'
            elif any(cue and (cue in low or low in cue) for cue in cues):
                score, reason = 0.86, 'fuzzy title match'
            if score:
                starts.append({'block_id': b['block_id'], 'block_index': idx, 'score': score, 'reason': reason, 'window_before': [x.get('normalized_text') for x in blocks[max(0, idx-2):idx]], 'window_after': [x.get('normalized_text') for x in blocks[idx+1:idx+3]]})
        if not starts and item.get('candidate_block_id'):
            for idx, b in enumerate(blocks):
                if b.get('block_id') == item.get('candidate_block_id'):
                    starts.append({'block_id': b['block_id'], 'block_index': idx, 'score': 0.92, 'reason': 'candidate block from canonical TOC', 'window_before': [], 'window_after': []})
        candidates.append({'toc_id': item['toc_id'], 'title': item['title'], 'candidate_start_blocks': starts[:5], 'candidate_end_blocks': []})
    result = {'chapters': candidates}
    write_json(package / 'toc' / 'boundary_candidates.json', result)
    return result


def resolve_boundaries(package: Path) -> dict[str, Any]:
    cand_path = package / 'toc' / 'boundary_candidates.json'
    if not cand_path.exists():
        build_boundary_candidates(package)
    toc = read_json(package / 'toc' / 'canonical_toc.json')
    candidates = read_json(cand_path).get('chapters', [])
    blocks = read_jsonl(package / 'ledger' / 'source_blocks.jsonl')
    block_ids = [b['block_id'] for b in blocks]
    chapters = []
    low = []
    for i, item in enumerate(toc.get('items', [])):
        cand = next((c for c in candidates if c['toc_id'] == item['toc_id']), {})
        starts = cand.get('candidate_start_blocks', [])
        if starts:
            start_idx = int(starts[0]['block_index'])
            confidence = float(starts[0]['score'])
            evidence = [starts[0]['reason'], starts[0]['block_id']]
        else:
            start_idx = 0 if i == 0 else chapters[-1]['end_index_exclusive']
            confidence = 0.5
            evidence = ['fallback sequential boundary']
        if i + 1 < len(toc.get('items', [])):
            next_item = toc['items'][i + 1]
            next_cand = next((c for c in candidates if c['toc_id'] == next_item['toc_id']), {})
            next_starts = next_cand.get('candidate_start_blocks', [])
            end_idx = int(next_starts[0]['block_index']) if next_starts else len(blocks)
        else:
            end_idx = len(blocks)
        if end_idx < start_idx:
            end_idx = start_idx
            confidence = min(confidence, 0.4)
        ch = {
            'toc_id': item['toc_id'],
            'chapter_index': i + 1,
            'title': item['title'],
            'section_type': item.get('section_type', 'body_chapter'),
            'start_block_id': block_ids[start_idx] if start_idx < len(block_ids) else None,
            'end_block_id_exclusive': block_ids[end_idx] if end_idx < len(block_ids) else None,
            'start_index': start_idx,
            'end_index_exclusive': end_idx,
            'confidence': confidence,
            'evidence': evidence,
            'warnings': [] if confidence >= 0.85 else ['low_confidence_boundary'],
        }
        if confidence < 0.85:
            low.append(ch)
        chapters.append(ch)
    result = {'chapters': chapters, 'unassigned_ranges': [], 'low_confidence_boundaries': low}
    write_json(package / 'toc' / 'chapter_boundary_map.json', result)
    blockers = ['low_confidence_boundary'] if low else []
    write_json(package / 'audit' / 'boundary_validation.json', {'status': 'PASS' if not blockers else 'FAIL_REVIEW', 'chapter_count': len(chapters), 'hard_blockers': blockers})
    return result


def split_chapters(package: Path) -> dict[str, Any]:
    boundary_path = package / 'toc' / 'chapter_boundary_map.json'
    if not boundary_path.exists():
        resolve_boundaries(package)
    boundary = read_json(boundary_path)
    blocks = read_jsonl(package / 'ledger' / 'source_blocks.jsonl')
    images = read_jsonl(package / 'ledger' / 'image_blocks.jsonl')
    chapters_dir = ensure_dir(package / 'chapters_md')
    units_dir = ensure_dir(package / 'translation_units')
    total_units = 0
    total_images = 0
    split_rows = []
    for ch in boundary.get('chapters', []):
        idx = int(ch['chapter_index'])
        start = int(ch['start_index'])
        end = int(ch['end_index_exclusive'])
        ch_blocks = blocks[start:end]
        lines = [f"# {ch['title']}", '']
        units = []
        unit_no = 0
        for b in ch_blocks:
            unit_no += 1
            unit_id = f'c{idx:03d}_u{unit_no:04d}'
            text = b.get('text', '')
            lines.append(f'[{unit_id}] {text}')
            units.append({'unit_id': unit_id, 'source_block_id': b['block_id'], 'text': text, 'block_kind': b.get('block_kind'), 'dom_path': b.get('dom_path'), 'href': b.get('href'), 'page': b.get('page')})
        # Attach images whose spine/page falls inside chapter when possible. EPUB image text order is approximated in v1 skeleton.
        ch_imgs = []
        for img in images:
            if img.get('spine_index') is not None and ch_blocks and img.get('spine_index') == ch_blocks[0].get('spine_index'):
                ch_imgs.append(img)
            elif img.get('page') is not None and ch_blocks and img.get('page') == ch_blocks[0].get('page'):
                ch_imgs.append(img)
        for img in ch_imgs:
            lines.append(img['marker'])
        chapter_file = chapters_dir / f'chapter_{idx:03d}.md'
        chapter_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        write_json(units_dir / f'chapter_{idx:03d}.json', {'chapter_index': idx, 'title': ch['title'], 'section_type': ch['section_type'], 'units': units, 'images': ch_imgs})
        total_units += len(units)
        total_images += len(ch_imgs)
        split_rows.append({'chapter_index': idx, 'title': ch['title'], 'units': len(units), 'images': len(ch_imgs), 'start_block_id': ch.get('start_block_id'), 'end_block_id_exclusive': ch.get('end_block_id_exclusive')})
    audit = {'status': 'PASS', 'chapter_count': len(split_rows), 'source_blocks': len(blocks), 'assigned_blocks': total_units, 'unit_count': total_units, 'image_markers': total_images, 'hard_blockers': [] if total_units == len(blocks) else ['source_coverage_gap']}
    if audit['hard_blockers']:
        audit['status'] = 'FAIL_REVIEW'
    write_json(package / 'audit' / 'split_coverage.json', audit)
    write_json(package / 'audit' / 'chapter_split_rows.json', split_rows)
    return audit
