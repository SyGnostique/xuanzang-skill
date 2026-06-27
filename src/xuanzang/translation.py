from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import ensure_dir, read_json, write_json
from .validate import validate_translation


def prep_translation(package: Path, target: str = 'zh-CN') -> dict[str, Any]:
    prep = ensure_dir(package / 'translation_prep')
    toc = read_json(package / 'toc' / 'canonical_toc.json') if (package / 'toc' / 'canonical_toc.json').exists() else {'items': []}
    (prep / '01_project_translation_brief.md').write_text(f"# Project Translation Brief\n\n- target_language: {target}\n- workflow: xuanzang strict unit-preserving translation\n", encoding='utf-8')
    (prep / '03_structural_argument_map.md').write_text('# Structural Argument Map\n\nGenerated scaffold. Fill with semantic reading before real translation.\n', encoding='utf-8')
    lines = ['# Semantic Chapter Briefs', '']
    for item in toc.get('items', []):
        lines += [f"## {item['order']:02d} {item['title']}", f"- section_type: {item.get('section_type')}", '- role: TODO semantic reading required for real books.', '']
    (prep / '04_semantic_chapter_briefs.md').write_text('\n'.join(lines), encoding='utf-8')
    (prep / '05_style_guide.md').write_text('# Style Guide\n\nUse precise target-language literary nonfiction unless project policy says otherwise.\n', encoding='utf-8')
    (prep / '06_terminology_policy.md').write_text('# Terminology Policy\n\nApproved terms must remain stable. Unresolved terms go to translator queries.\n', encoding='utf-8')
    (prep / '07_format_reinsertion_policy.md').write_text('# Format Reinsertion Policy\n\nPreserve every unit ID and image marker exactly. Reinsert by stored source anchor.\n', encoding='utf-8')
    (prep / '08_translation_qa_gates.md').write_text('# Translation QA Gates\n\nReject missing units, duplicate units, moved image markers, summaries, and invented notes.\n', encoding='utf-8')
    (prep / '09_prompt_pack.md').write_text('# Prompt Pack\n\nSystem: translate faithfully, preserve units and image markers, do not summarize.\n', encoding='utf-8')
    (prep / '11_global_book_summary_for_prompts.md').write_text('# Whole-Book Summary\n\nContext scaffold. Fill with semantic summary before real model translation.\n', encoding='utf-8')
    (prep / 'approved_glossary.csv').write_text('source_term,target_term,notes\n', encoding='utf-8')
    jobs = ensure_dir(prep / 'deepseek_jobs')
    for chapter in sorted((package / 'chapters_md').glob('chapter_*.md')):
        idx = chapter.stem.split('_')[-1]
        (jobs / f'translate_chapter_{idx}.md').write_text(
            '# Translation Job\n\nPreserve unit IDs and image markers exactly.\n\n' + chapter.read_text(encoding='utf-8'), encoding='utf-8'
        )
    manifest = {'status': 'PASS', 'target_language': target, 'chapter_jobs': len(list(jobs.glob('*.md'))), 'hard_blockers': []}
    write_json(prep / 'deepseek_jobs_manifest.json', manifest)
    return manifest


def run_mock_translation(package: Path, run_id: str = 'mock_v1') -> dict[str, Any]:
    run_dir = ensure_dir(package / 'translation_runs' / run_id)
    ensure_dir(run_dir / 'translated_md')
    ensure_dir(run_dir / 'raw_responses')
    ensure_dir(run_dir / 'prompts')
    for chapter in sorted((package / 'chapters_md').glob('chapter_*.md')):
        out_lines = []
        for line in chapter.read_text(encoding='utf-8').splitlines():
            if line.startswith('[') and '] ' in line:
                uid, text = line.split('] ', 1)
                out_lines.append(f'{uid}] 译文：{text}')
            elif line.startswith('[[IMAGE '):
                out_lines.append(line)
        idx = chapter.stem.split('_')[-1]
        (run_dir / 'translated_md' / f'chapter_{idx}.md').write_text('\n'.join(out_lines) + '\n', encoding='utf-8')
        write_json(run_dir / 'raw_responses' / f'chapter_{idx}.response.json', {'provider': 'mock', 'chapter': idx})
    run_state = {'run_id': run_id, 'provider': 'mock', 'model': 'mock-unit-preserver', 'temperature': 0, 'status': 'TRANSLATED'}
    write_json(run_dir / 'run_state.json', run_state)
    validate_translation(package, run_dir)
    return run_state


def semantic_audit_scaffold(package: Path, run_id: str) -> dict[str, Any]:
    run_dir = package / 'translation_runs' / run_id
    lines = ['# Manual Semantic Audit', '', f'Run: `{run_id}`', '', 'Method: source-facing unit review required for real translations. Mock translations are not publication-accepted semantic output.', '']
    for unit_file in sorted((package / 'translation_units').glob('chapter_*.json')):
        data = read_json(unit_file)
        lines += [f"## Chapter {data['chapter_index']:03d}: {data.get('title','')}", '', 'Status: `PASS_WITH_MOCK_LIMITATION`', '', 'Findings:', '- Mechanical preservation validated; semantic acceptance requires human/LLM source-facing audit for real books.', '']
    ensure_dir(run_dir / 'audit')
    (run_dir / 'audit' / 'manual_semantic_audit.md').write_text('\n'.join(lines), encoding='utf-8')
    result = {'status': 'PASS_WITH_MOCK_LIMITATION', 'chapters': len(list((package / 'translation_units').glob('chapter_*.json'))), 'hard_blockers': []}
    write_json(run_dir / 'audit' / 'semantic_audit_status.json', result)
    return result
