from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .contracts import PIPELINE_VERSION, RestorePolicy, RestoreRequest
from .extractors import ExtractionResult
from .gates import evaluate_gates
from .restoration import _project_active_run, _write_run
from .utils import (
    append_jsonl,
    copytree_no_follow,
    ensure_dir,
    package_lock,
    read_json,
    read_jsonl,
    sha256_file,
    sha256_path,
    sha256_text,
    utc_now,
    write_json,
    write_jsonl,
)


def _ev_id(source_sha: str, page_id: str, engine: str, ordinal: int, text: str) -> str:
    return f'ev_{sha256_text(f"{source_sha}|{page_id}|{engine}|{ordinal}|{text}")[:16]}'


def _legacy_evidence(source_sha: str, page_id: str, ordinal: int, block: dict[str, Any]) -> dict[str, Any]:
    text = str(block.get('text', ''))
    engine = str(block.get('ocr_engine') or block.get('source_type') or 'legacy_unknown')
    evidence_id = _ev_id(source_sha, page_id, engine, ordinal, text)
    return {
        'evidence_id': evidence_id,
        'page_id': page_id,
        'ordinal': ordinal,
        'engine': engine,
        'engine_version': None,
        'text': text,
        'text_sha256': sha256_text(text),
        'bbox': block.get('bbox', []),
        'coordinate_space': 'legacy',
        'confidence': block.get('ocr_confidence'),
        'block_kind': block.get('block_kind', 'text_candidate'),
        'metadata': {'legacy_block_id': block.get('block_id'), 'legacy_record': block},
    }


def _canonical(ev: dict[str, Any], legacy_id: str | None = None) -> dict[str, Any]:
    return {
        'block_id': legacy_id or f"blk_{sha256_text(ev['evidence_id'])[:16]}",
        'page_id': ev['page_id'], 'evidence_id': ev['evidence_id'], 'text': ev['text'],
        'bbox': ev.get('bbox', []), 'coordinate_space': ev.get('coordinate_space'),
        'block_kind': ev.get('block_kind'), 'selection_status': 'legacy_selected_unverified',
        'selection_reason': 'migrated_without_reinterpreting_legacy_evidence',
    }


def _commit_migration(
    *, out: Path, source_path: Path, source_sha: str, result: ExtractionResult,
    run_id: str, migration_report: dict[str, Any], legacy_snapshot: Path | None = None,
    copy_external_page_assets: bool = False,
) -> dict[str, Any]:
    out = out.resolve()
    if (out / 'package_manifest.json').exists():
        manifest = read_json(out / 'package_manifest.json')
        if manifest.get('migration', {}).get('migration_id') == migration_report['migration_id']:
            gate = evaluate_gates(out, target='citation')
            return {'status': 'already_migrated', 'package': str(out), 'gate_status': gate['public_status'], 'evaluation_status': gate['status'], 'trust_status': gate['trust_status']}
        raise ValueError('output package already exists with a different identity')
    ensure_dir(out / 'runs')
    ensure_dir(out / 'history')
    staging = ensure_dir(out / '.staging')
    work = Path(tempfile.mkdtemp(prefix=f'{run_id}.', dir=str(staging)))
    if legacy_snapshot:
        copytree_no_follow(legacy_snapshot, work / 'legacy' / 'v1_snapshot')
    if copy_external_page_assets:
        copied = ensure_dir(work / 'assets' / 'migration_pages')
        for page in result.pages:
            locator = page.get('page_image_path')
            if not locator:
                continue
            source_asset = Path(str(locator))
            if not source_asset.is_absolute() or not source_asset.is_file():
                continue
            digest = sha256_file(source_asset)
            target = copied / f'{digest}{source_asset.suffix.lower()}'
            if not target.exists():
                shutil.copy2(source_asset, target, follow_symlinks=False)
            page['page_image_path'] = str(target.relative_to(work))
            page['page_image_sha256'] = digest
    policy = RestorePolicy(target='review', ocr='none')
    request = RestoreRequest(source=source_path, out=out, policy=policy)
    write_json(work / 'migration_report.json', migration_report)
    _write_run(work, source_path, source_sha, run_id, request, result)
    run_dir = out / 'runs' / run_id
    os.replace(work, run_dir)
    if legacy_snapshot:
        snapshot_source = run_dir / 'legacy' / 'v1_snapshot'
        snapshot_view = out / 'legacy' / 'v1_snapshot'
        for member in sorted(snapshot_source.rglob('*')):
            target = snapshot_view / member.relative_to(snapshot_source)
            if member.is_dir():
                ensure_dir(target)
            elif member.is_file():
                ensure_dir(target.parent)
                os.link(member, target)
    manifest = {
        'package_version': 2, 'pipeline_version': PIPELINE_VERSION,
        'package_id': f'pkg_{source_sha[:20]}',
        'source': {'path': str(source_path), 'sha256': source_sha, 'format': result.source_format},
        'scope': {
            'privacy': 'local_only', 'tenant_id': None, 'workspace_id': None,
            'rights_basis': 'user_supplied_private', 'retention_policy': 'workspace_default',
            'access_tags': [],
        },
        'active_run_id': run_id,
        'active_run_manifest_sha256': sha256_file(run_dir / 'run_manifest.json'),
        'runs': [run_id], 'trust_status': 'needs_review',
        'canonical_revision': sha256_file(run_dir / 'ledger' / 'canonical_blocks.jsonl')[:20],
        'review_revision': '0', 'updated_at': utc_now(),
        'lifecycle': {'state': 'active'},
        'migration': {'migration_id': migration_report['migration_id'], 'status': 'complete', 'report': 'audit/migration_report.json'},
    }
    _project_active_run(out, run_dir, preserve_review_state=False)
    (out / 'ledger' / 'review_decisions.jsonl').touch(exist_ok=True)
    manifest['review_ledger_sha256'] = sha256_file(out / 'ledger' / 'review_decisions.jsonl')
    write_json(out / 'package_manifest.json', manifest)
    write_json(out / 'audit' / 'migration_report.json', migration_report)
    write_jsonl(out / 'audit' / 'migration_id_crosswalk.jsonl', migration_report.get('id_crosswalk', []))
    append_jsonl(out / 'history' / 'events.jsonl', {'event': 'migration_committed', 'migration_id': migration_report['migration_id'], 'at': utc_now()})
    gate = evaluate_gates(out, target='citation')
    return {'status': 'migrated', 'package': str(out), 'gate_status': gate['public_status'], 'evaluation_status': gate['status'], 'trust_status': gate['trust_status'], 'migration_report': migration_report}


def _migrate_v1_locked(old: Path, out: Path, source_override: Path | None = None) -> dict[str, Any]:
    old = old.resolve()
    manifest = read_json(old / 'package_manifest.json')
    if manifest.get('package_version') == 2:
        raise ValueError('source package is already version 2')
    inventory_path = old / 'source' / 'source_inventory.json'
    inventory = read_json(inventory_path) if inventory_path.exists() else manifest.get('source', {})
    declared_source_path = Path(inventory.get('source_path') or manifest.get('source', {}).get('source_path') or old)
    declared_source_sha = str(inventory.get('source_sha256') or manifest.get('source', {}).get('source_sha256') or '')
    identity_status = 'legacy_declared_unverified'
    identity_findings = []
    if source_override is not None:
        source_path = source_override.resolve()
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        source_sha = sha256_path(source_path)
        identity_status = 'verified_from_explicit_source'
        if re.fullmatch(r'[0-9a-f]{64}', declared_source_sha) and declared_source_sha != source_sha:
            identity_findings.append('legacy_declared_source_sha_mismatch')
    else:
        source_path = declared_source_path
        if re.fullmatch(r'[0-9a-f]{64}', declared_source_sha):
            source_sha = declared_source_sha
        else:
            raise ValueError(
                'legacy source identity is not a valid sha256; provide --source to recompute it'
            )
    source_format = str(inventory.get('format') or 'legacy_v1')
    blocks = read_jsonl(old / 'ledger' / 'source_blocks.jsonl')
    images = read_jsonl(old / 'ledger' / 'image_blocks.jsonl')
    page_keys = []
    for block in blocks:
        key = block.get('page') if block.get('page') is not None else f"spine_{block.get('spine_index', 1)}"
        if key not in page_keys:
            page_keys.append(key)
    pages = []
    page_map = {}
    for ordinal, key in enumerate(page_keys, start=1):
        page_id = f'page_{int(key):04d}' if isinstance(key, int) else str(key).zfill(10)
        page_map[str(key)] = page_id
        pages.append({'page_id': page_id, 'surface_id': page_id, 'ordinal': ordinal, 'source_page': key if isinstance(key, int) else None, 'status': 'extracted', 'route': 'legacy_v1', 'quality_flags': ['legacy_unverified']})
    result = ExtractionResult(source_format, {'source_sha256': source_sha, 'legacy_inventory': inventory}, pages=pages)
    crosswalk = [
        {'legacy_kind': 'surface', 'legacy_id': str(key), 'v2_kind': 'surface', 'v2_id': page_map[str(key)]}
        for key in page_keys
    ]
    for ordinal, block in enumerate(blocks, start=1):
        key = block.get('page') if block.get('page') is not None else f"spine_{block.get('spine_index', 1)}"
        page_id = page_map[str(key)]
        ev = _legacy_evidence(source_sha, page_id, ordinal, block)
        result.evidence_blocks.append(ev)
        result.canonical_blocks.append(_canonical(ev, block.get('block_id')))
        crosswalk.append({'legacy_kind': 'source_block', 'legacy_id': block.get('block_id'), 'v2_kind': 'evidence_block', 'v2_id': ev['evidence_id']})
    for image in images:
        key = image.get('page') if image.get('page') is not None else f"spine_{image.get('spine_index', 1)}"
        result.assets.append({
            'asset_id': image.get('image_id') or f"asset_{sha256_text(json.dumps(image, sort_keys=True))[:16]}",
            'occurrence_id': f"occ_{sha256_text(json.dumps(image, sort_keys=True))[:16]}",
            'page_id': page_map.get(str(key)), 'kind': 'legacy_image', 'legacy_record': image,
            'review_status': 'unreviewed', 'exists': image.get('exists'),
        })
        crosswalk.append({'legacy_kind': 'image_block', 'legacy_id': image.get('image_id'), 'v2_kind': 'asset_occurrence', 'v2_id': result.assets[-1]['occurrence_id']})
    result.blockers.append({'kind': 'legacy_v1_requires_v2_semantic_review'})
    if identity_status != 'verified_from_explicit_source':
        result.blockers.append({'kind': 'legacy_source_identity_unverified'})
    if any('mock' in str(row.get('ocr_engine', '')).lower() for row in blocks):
        result.blockers.append({'kind': 'mock_ocr_in_legacy_package'})
    files = sorted(p for p in old.rglob('*') if p.is_file() and '.git' not in p.parts)
    known_prefixes = {'package_manifest.json', 'source', 'ledger', 'toc', 'chapters_md', 'translation_units', 'sections', 'audit', 'translation_runs', 'translation_prep'}
    mapped, preserved = [], []
    for path in files:
        rel = str(path.relative_to(old))
        root = rel.split('/', 1)[0]
        (mapped if root in known_prefixes else preserved).append(rel)
    migration_id = f"mig_v1_{sha256_text(source_sha + str(old))[:16]}"
    report = {
        'migration_id': migration_id, 'source_package': str(old), 'source_sha256': source_sha,
        'source_identity_status': identity_status, 'source_identity_findings': identity_findings,
        'status_downgrades': ['legacy PASS_STRICT -> v2 needs_review', 'legacy automatic TOC/boundaries -> proposal'],
        'file_accounting': {'mapped': mapped, 'preserved': preserved, 'quarantined': [], 'total': len(files)},
        'record_counts': {'source_blocks': len(blocks), 'image_blocks': len(images), 'surfaces': len(pages)},
        'id_crosswalk': crosswalk,
        'first_required_v2_stage': 'manual_semantic_review', 'blockers': result.blockers,
    }
    return _commit_migration(out=out, source_path=source_path, source_sha=source_sha, result=result, run_id=f'migration_{migration_id}', migration_report=report, legacy_snapshot=old)


def migrate_v1(old: Path, out: Path, source: Path | None = None) -> dict[str, Any]:
    if old.is_symlink():
        raise ValueError('legacy package root cannot be a symlink')
    old_resolved, out_resolved = old.resolve(), out.resolve()
    if old_resolved == out_resolved or old_resolved in out_resolved.parents or out_resolved in old_resolved.parents:
        raise ValueError('migration input and output must not contain one another')
    source_resolved = source.resolve() if source is not None else None
    if source_resolved is not None and (
        source_resolved == out_resolved
        or (source_resolved.is_dir() and source_resolved in out_resolved.parents)
        or out_resolved in source_resolved.parents
    ):
        raise ValueError('migration source and output must not overlap')
    with package_lock(out_resolved):
        unexpected = [
            p.name for p in out_resolved.iterdir()
            if p.name != '.xuanzang.lock' and not p.name.startswith('.xuanzang.lock.stale.')
        ]
        if unexpected and not (out_resolved / 'package_manifest.json').exists():
            raise ValueError(f'refusing to migrate into a non-empty directory: {sorted(unexpected)}')
        return _migrate_v1_locked(old_resolved, out_resolved, source_override=source_resolved)


def _migrate_book_m1_locked(ocr_root: Path, source: Path, book_id: str, out: Path, *, copy_assets: bool = False) -> dict[str, Any]:
    ocr_root, source = ocr_root.resolve(), source.resolve()
    source_sha = sha256_file(source)

    def legacy_member(locator: Any, record_path: Path, *, label: str) -> Path | None:
        if not locator:
            return None
        raw = Path(str(locator)).expanduser()
        candidates = [raw] if raw.is_absolute() else [record_path.parent / raw, ocr_root / raw]
        candidate = next((path for path in candidates if path.exists()), candidates[0]).resolve()
        if candidate != ocr_root and ocr_root not in candidate.parents:
            raise ValueError(f'Book M1 {label} escapes ocr_root: {locator}')
        unresolved = next((path for path in candidates if path.exists()), candidates[0])
        if unresolved.is_symlink():
            raise ValueError(f'Book M1 {label} cannot be a symlink: {locator}')
        return candidate

    page_jsons = sorted(ocr_root.glob('chunks/*/pages/page_*.json'))
    records = []
    for path in page_jsons:
        try:
            row = read_json(path)
        except Exception:
            continue
        if str(row.get('book_m0_id')) == book_id:
            row['_json_path'] = str(path)
            records.append(row)
    by_page: dict[int, dict[str, Any]] = {}
    for row in records:
        page_num = int(row['page_num'])
        prior = by_page.get(page_num)
        if prior is not None:
            if sha256_file(Path(prior['_json_path'])) != sha256_file(Path(row['_json_path'])):
                raise ValueError(f'conflicting Book M1 records for page {page_num}')
            continue
        by_page[page_num] = row
    if not by_page:
        raise ValueError(f'no Book M1 pages found for {book_id}')
    result = ExtractionResult('book_m1_migration', {'source_sha256': source_sha, 'book_m0_id': book_id, 'ocr_root': str(ocr_root)})
    crosswalk = []
    for ordinal, page_num in enumerate(sorted(by_page), start=1):
        row = by_page[page_num]
        page_id = f'page_{page_num:04d}'
        record_path = Path(row['_json_path']).resolve()
        image = legacy_member(row.get('image_path'), record_path, label='image_path')
        image_ref = str(image) if image else None
        image_exists = bool(image and image.is_file())
        page = {
            'page_id': page_id, 'surface_id': page_id, 'ordinal': ordinal, 'source_page': page_num,
            'status': 'extracted' if row.get('status') == 'paddleocr_complete' else 'unresolved',
            'route': 'legacy_book_m1_paddle', 'page_image_path': image_ref,
            'page_image_sha256': sha256_file(image) if image_exists else None,
            'quality_flags': list(row.get('tesseract_double_check_reasons', [])),
            'legacy_json_path': row['_json_path'], 'chunk_id': row.get('chunk_id'),
        }
        if not image_exists:
            page['quality_flags'].append('book_m1_image_missing')
            result.blockers.append({'kind': 'book_m1_image_missing', 'page_id': page_id})
        paddle = row.get('paddleocr', {})
        if paddle.get('mean_score') is not None and float(paddle['mean_score']) < 0.90:
            page['quality_flags'].append('low_ocr_confidence_unresolved')
        result.pages.append(page)
        crosswalk.append({'legacy_kind': 'page_json', 'legacy_id': row['_json_path'], 'v2_kind': 'surface', 'v2_id': page_id})
        for line_index, line in enumerate(paddle.get('lines', []), start=1):
            text = str(line.get('text', '')).strip()
            if not text:
                continue
            bbox = line.get('box') or []
            bbox_valid = bool(
                isinstance(bbox, list) and len(bbox) in {4, 8}
                and all(isinstance(value, (int, float)) for value in bbox)
            )
            if not bbox_valid:
                result.blockers.append({'kind': 'legacy_ocr_bbox_invalid', 'page_id': page_id, 'line_index': line_index})
            ev = {
                'evidence_id': _ev_id(source_sha, page_id, 'paddle_book_m1', line_index, text),
                'page_id': page_id, 'ordinal': line_index, 'engine': 'paddle_book_m1',
                'engine_version': paddle.get('model'), 'text': text, 'text_sha256': sha256_text(text),
                'bbox': bbox, 'coordinate_space': 'render_pixels',
                'confidence': line.get('score'), 'block_kind': 'text_candidate',
                'metadata': {'legacy_line_index': line.get('line_index'), 'legacy_json_path': row['_json_path']},
            }
            result.evidence_blocks.append(ev)
            result.canonical_blocks.append(_canonical(ev))
            crosswalk.append({'legacy_kind': 'paddle_line', 'legacy_id': f"{row['_json_path']}#{line.get('line_index', line_index)}", 'v2_kind': 'evidence_block', 'v2_id': ev['evidence_id']})
        tess = row.get('tesseract_double_check') or {}
        tess_path = legacy_member(tess.get('text_path'), record_path, label='tesseract text_path')
        if tess_path and tess_path.is_file():
            text = tess_path.read_text(encoding='utf-8', errors='replace').strip()
            if text:
                result.evidence_blocks.append({
                    'evidence_id': _ev_id(source_sha, page_id, 'tesseract_book_m1', 1, text),
                    'page_id': page_id, 'ordinal': 1, 'engine': 'tesseract_book_m1', 'engine_version': None,
                    'text': text, 'text_sha256': sha256_text(text), 'bbox': [], 'coordinate_space': 'page',
                    'confidence': None, 'block_kind': 'text_candidate',
                    'metadata': {'legacy_text_path': str(tess_path), 'alternate_variant_only': True},
                })
    chunks: dict[str, dict[str, Any]] = {}
    for row in records:
        chunks.setdefault(str(row.get('chunk_id')), row)
    result.toc_candidates = [
        {
            'candidate_id': f'legacy_{chunk_id}', 'text': row.get('chunk_title'), 'source': 'legacy_visual_chapter_plan',
            'page': row.get('page_num'), 'score': None, 'status': 'legacy_unverified',
        }
        for chunk_id, row in chunks.items()
    ]
    expected_page_count = None
    try:
        import fitz
        with fitz.open(str(source)) as source_document:
            expected_page_count = source_document.page_count
    except Exception:
        pass
    expected_pages = set(range(1, expected_page_count + 1)) if expected_page_count is not None else set()
    missing_pages = sorted(expected_pages - set(by_page))
    extra_pages = sorted(set(by_page) - expected_pages) if expected_pages else []
    if missing_pages or extra_pages:
        result.blockers.append({
            'kind': 'book_m1_page_coverage_gap', 'missing_pages': missing_pages, 'extra_pages': extra_pages,
        })
    result.blockers.extend([
        {'kind': 'legacy_book_m1_requires_manualstrict'},
        {'kind': 'legacy_chapter_boundaries_require_v2_structure_review'},
    ])
    migration_id = f"mig_book_m1_{sha256_text(source_sha + book_id)[:16]}"
    report = {
        'migration_id': migration_id, 'source_sha256': source_sha, 'book_m0_id': book_id,
        'ocr_rerun_count': 0, 'page_count': len(result.pages), 'evidence_block_count': len(result.evidence_blocks),
        'source_page_count': expected_page_count, 'missing_pages': missing_pages, 'extra_pages': extra_pages,
        'tesseract_sidecar_count': sum(1 for e in result.evidence_blocks if e['engine'] == 'tesseract_book_m1'),
        'copy_assets': copy_assets, 'status_downgrades': ['Book M1 pass -> v2 needs_review'],
        'first_required_v2_stage': 'manual_semantic_review', 'blockers': result.blockers,
        'file_accounting': {'mapped_page_jsons': len(records), 'quarantined': [], 'preserved_external_assets': not copy_assets},
        'id_crosswalk': crosswalk,
    }
    return _commit_migration(
        out=out, source_path=source, source_sha=source_sha, result=result,
        run_id=f'migration_{migration_id}', migration_report=report,
        copy_external_page_assets=copy_assets,
    )


def migrate_book_m1(ocr_root: Path, source: Path, book_id: str, out: Path, *, copy_assets: bool = False) -> dict[str, Any]:
    ocr_resolved, source_resolved, out_resolved = ocr_root.resolve(), source.resolve(), out.resolve()
    if out_resolved == ocr_resolved or ocr_resolved in out_resolved.parents or out_resolved in ocr_resolved.parents:
        raise ValueError('Book M1 input and output must not contain one another')
    if (
        source_resolved == out_resolved or source_resolved in out_resolved.parents
        or out_resolved in source_resolved.parents
    ):
        raise ValueError('Book M1 source and output must not overlap')
    with package_lock(out_resolved):
        unexpected = [
            p.name for p in out_resolved.iterdir()
            if p.name != '.xuanzang.lock' and not p.name.startswith('.xuanzang.lock.stale.')
        ]
        if unexpected and not (out_resolved / 'package_manifest.json').exists():
            raise ValueError(f'refusing to migrate into a non-empty directory: {sorted(unexpected)}')
        return _migrate_book_m1_locked(
            ocr_resolved, source_resolved, book_id, out_resolved, copy_assets=copy_assets,
        )
