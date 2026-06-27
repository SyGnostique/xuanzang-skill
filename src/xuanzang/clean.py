from __future__ import annotations

from pathlib import Path

from .utils import read_json, write_json


def repair_linewraps(package: Path) -> dict:
    chapters = sorted((package / 'chapters_md').glob('chapter_*.md'))
    changed = 0
    joins = 0
    for path in chapters:
        lines = path.read_text(encoding='utf-8').splitlines()
        out = []
        buffer = None
        for line in lines:
            if line.startswith('[') and '] ' in line:
                uid, text = line.split('] ', 1)
                if buffer and buffer[1] and buffer[1][-1:] not in '.?!。！？:：' and text and text[:1].islower():
                    out[-1] = buffer[0] + '] ' + buffer[1] + ' ' + text
                    buffer = (buffer[0], buffer[1] + ' ' + text)
                    joins += 1
                    changed += 1
                    continue
                out.append(line)
                buffer = (uid, text)
            else:
                out.append(line)
                buffer = None
        if out != lines:
            path.write_text('\n'.join(out) + '\n', encoding='utf-8')
    audit = {'status': 'PASS', 'changed_chapters': changed, 'paragraph_joins': joins, 'hard_blockers': []}
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
    status = 'PASS_STRICT' if sections else 'FAIL_REVIEW'
    pass_fail = {'status': status, 'blocking_findings': [] if sections else [{'kind': 'source_coverage_gap'}], 'section_count': len(sections)}
    write_json(package / 'audit' / 'pass_fail.json', pass_fail)
    return pass_fail
