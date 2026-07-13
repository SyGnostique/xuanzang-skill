from __future__ import annotations

from pathlib import Path

from .utils import read_json, write_json, write_jsonl


def repair_linewraps(package: Path) -> dict:
    chapters = sorted((package / 'chapters_md').glob('chapter_*.md'))
    proposals = []
    for path in chapters:
        lines = path.read_text(encoding='utf-8').splitlines()
        out = []
        buffer = None
        for line in lines:
            if line.startswith('[') and '] ' in line:
                uid, text = line.split('] ', 1)
                if buffer and buffer[1] and buffer[1][-1:] not in '.?!。！？:：' and text and text[:1].islower():
                    proposals.append({
                        'kind': 'linewrap_join_candidate', 'chapter': path.name,
                        'left_unit': buffer[0].lstrip('['), 'right_unit': uid.lstrip('['),
                        'proposed_text': buffer[1] + ' ' + text,
                        'status': 'needs_semantic_review',
                    })
                out.append(line)
                buffer = (uid, text)
            else:
                out.append(line)
                buffer = None
    write_jsonl(package / 'audit' / 'linewrap_proposals.jsonl', proposals)
    audit = {
        'status': 'FAIL_REVIEW' if proposals else 'PASS',
        'changed_chapters': 0, 'paragraph_joins': 0,
        'proposed_joins': len(proposals),
        'hard_blockers': ['linewrap_semantic_review_missing'] if proposals else [],
        'note': 'v2 never mutates source units from a mechanical linewrap heuristic',
    }
    write_json(package / 'audit' / 'cleaning_audit.json', audit)
    return audit


def build_rag_structure(package: Path) -> dict:
    chapters = sorted((package / 'chapters_md').glob('chapter_*.md'))
    sections = []
    sections_dir = package / 'sections'
    sections_dir.mkdir(exist_ok=True)
    for i, ch in enumerate(chapters, start=1):
        text = ch.read_text(encoding='utf-8')
        title = text.splitlines()[0].lstrip('# ').strip() if text.splitlines() else f'Chapter {i}'
        sec_id = f'sec_{i:03d}'
        out = sections_dir / f'{sec_id}.md'
        out.write_text(text, encoding='utf-8')
        sections.append({'section_id': sec_id, 'title': title, 'path': str(out.relative_to(package)), 'type': 'body'})
    structure = {'sections': sections, 'section_count': len(sections)}
    write_json(package / 'structure.json', structure)
    blockers = []
    if not sections:
        blockers.append({'kind': 'source_coverage_gap'})
    required_audits = ['source_integrity.json', 'toc_validation.json', 'boundary_validation.json', 'split_coverage.json', 'cleaning_audit.json']
    for name in required_audits:
        path = package / 'audit' / name
        if not path.exists():
            blockers.append({'kind': 'missing_required_audit', 'path': f'audit/{name}'})
            continue
        audit = read_json(path)
        if audit.get('status') not in {'PASS', 'PASS_STRICT'}:
            blockers.append({'kind': 'upstream_audit_not_pass', 'path': f'audit/{name}', 'status': audit.get('status')})
    blockers.append({'kind': 'semantic_review_missing', 'message': 'mechanical cleaning cannot grant PASS_STRICT'})
    pass_fail = {'status': 'FAIL_REVIEW', 'blocking_findings': blockers, 'section_count': len(sections)}
    write_json(package / 'audit' / 'pass_fail.json', pass_fail)
    return pass_fail
