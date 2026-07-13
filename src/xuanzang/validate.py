from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .utils import ensure_dir, read_json, read_jsonl, write_json

UNIT_RE = re.compile(r'^\[(c\d{3}_u\d{4})\]\s*(.*)$')
IMAGE_RE = re.compile(r'^\[\[IMAGE\s+([^\]]+)\]\]')


def validate_package(package: Path, strict: bool = False) -> dict[str, Any]:
    manifest_path = package / 'package_manifest.json'
    if manifest_path.exists() and read_json(manifest_path).get('package_version') == 2:
        from .gates import evaluate_gates
        return evaluate_gates(package, target='citation' if strict else 'hint')
    problems = []
    required = ['package_manifest.json', 'ledger/source_blocks.jsonl', 'audit/source_integrity.json']
    for rel in required:
        if not (package / rel).exists():
            problems.append({'kind': 'missing_required_artifact', 'path': rel})
    source_blocks = read_jsonl(package / 'ledger' / 'source_blocks.jsonl')
    if not source_blocks:
        problems.append({'kind': 'source_coverage_gap', 'message': 'source block ledger is empty'})
    if strict:
        required_audits = ['source_integrity.json', 'ocr_audit.json', 'toc_validation.json', 'boundary_validation.json', 'split_coverage.json', 'cleaning_audit.json']
        for name in required_audits:
            path = package / 'audit' / name
            if not path.exists():
                problems.append({'kind': 'missing_required_audit', 'path': f'audit/{name}'})
                continue
            upstream = read_json(path)
            if upstream.get('status') not in {'PASS', 'PASS_STRICT'}:
                problems.append({'kind': 'upstream_audit_not_pass', 'path': f'audit/{name}', 'status': upstream.get('status')})
        semantic = package / 'audit' / 'manual_semantic_coverage.json'
        if not semantic.exists() or read_json(semantic).get('status') != 'PASS':
            problems.append({'kind': 'semantic_review_missing'})
    audit = {'status': 'PASS' if not problems else 'FAIL_REVIEW', 'problems': problems, 'source_blocks': len(source_blocks)}
    write_json(package / 'audit' / 'validation.json', audit)
    return audit


def parse_translated_units(path: Path) -> tuple[list[str], list[str]]:
    unit_ids = []
    images = []
    if not path.exists():
        return unit_ids, images
    for line in path.read_text(encoding='utf-8').splitlines():
        m = UNIT_RE.match(line)
        if m:
            unit_ids.append(m.group(1))
        if IMAGE_RE.match(line):
            images.append(line.strip())
    return unit_ids, images


def validate_translation(package: Path, run_dir: Path, chapter_index: int | None = None) -> dict[str, Any]:
    unit_files = sorted((package / 'translation_units').glob('chapter_*.json'))
    validations = ensure_dir(run_dir / 'validations')
    chapter_reports = []
    for uf in unit_files:
        data = read_json(uf)
        idx = int(data['chapter_index'])
        if chapter_index and idx != chapter_index:
            continue
        expected_units = [u['unit_id'] for u in data.get('units', [])]
        expected_images = [img.get('marker') for img in data.get('images', [])]
        translated = run_dir / 'translated_md' / f'chapter_{idx:03d}.md'
        got_units, got_images = parse_translated_units(translated)
        problems = []
        if got_units != expected_units:
            missing = [u for u in expected_units if u not in got_units]
            extra = [u for u in got_units if u not in expected_units]
            duplicate = sorted({u for u in got_units if got_units.count(u) > 1})
            problems.append({'kind': 'unit_id_mismatch', 'missing': missing, 'extra': extra, 'duplicate': duplicate})
        if got_images != expected_images:
            problems.append({'kind': 'image_marker_mismatch', 'expected': expected_images, 'got': got_images})
        report = {'chapter_index': idx, 'status': 'PASS' if not problems else 'FAIL_REVIEW', 'source_units': len(expected_units), 'translated_units': len(got_units), 'source_images': len(expected_images), 'translated_images': len(got_images), 'problems': problems}
        write_json(validations / f'chapter_{idx:03d}.validation.json', report)
        chapter_reports.append(report)
    totals = {
        'chapters': len(chapter_reports),
        'pass': sum(1 for r in chapter_reports if r['status'] == 'PASS'),
        'source_units': sum(r['source_units'] for r in chapter_reports),
        'translated_units': sum(r['translated_units'] for r in chapter_reports),
        'source_images': sum(r['source_images'] for r in chapter_reports),
        'translated_images': sum(r['translated_images'] for r in chapter_reports),
    }
    status = 'PASS' if totals['chapters'] == totals['pass'] else 'FAIL_REVIEW'
    final = {'status': status, 'totals': totals, 'chapters': chapter_reports}
    write_json(run_dir / 'audit' / 'final_translation_run_audit.json', final)
    ensure_dir(run_dir / 'audit')
    lines = ['# Final Translation Run Audit', '', f"- status: {status}"] + [f"- {k}: {v}" for k, v in totals.items()]
    (run_dir / 'audit' / 'final_translation_run_audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return final
