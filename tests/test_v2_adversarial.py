from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import warnings
import zipfile
from datetime import datetime as RealDateTime, timezone
from pathlib import Path

from PIL import Image

from xuanzang.gates import RESOLUTION_METHODS


REPO = Path(__file__).resolve().parents[1]
FIXED_REVIEW_TIME = '2026-01-01T00:00:00Z'


def run_cli(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env['PYTHONPATH'] = str(REPO / 'src') + os.pathsep + env.get('PYTHONPATH', '')
    return subprocess.run(
        [sys.executable, '-m', 'xuanzang.cli', *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=check,
        env=env,
    )


def stdout_json(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout.strip().splitlines()[-1])


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows),
        encoding='utf-8',
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def make_markdown(path: Path, *, paragraphs: int = 2) -> None:
    parts = ['# Adversarial evidence chapter']
    parts.extend(
        f'Paragraph {index} preserves a distinct source-grounded claim for complete semantic review.'
        for index in range(1, paragraphs + 1)
    )
    path.write_text('\n\n'.join(parts) + '\n', encoding='utf-8')


def restore_markdown(source: Path, package: Path, *extra: str) -> dict:
    return stdout_json(run_cli(
        'restore', str(source), '--out', str(package), '--target', 'review', '--ocr', 'none', *extra,
    ))


def semantic_decisions(package: Path) -> list[dict]:
    manifest = read_json(package / 'package_manifest.json')
    source_sha = manifest['source']['sha256']
    common = {
        'semantic_reading': True,
        'reviewer_type': 'human',
        'reviewer_id': 'adversarial-fixture-reviewer',
        'created_at': FIXED_REVIEW_TIME,
    }
    decisions: list[dict] = []
    surfaces = read_jsonl(package / 'ledger' / 'surfaces.jsonl')
    for surface in surfaces:
        decisions.append({
            **common,
            'kind': 'page',
            'target_id': surface['page_id'],
            'disposition': 'reviewed',
            'reason': 'The full source surface was reviewed visually and semantically.',
        })
    for paragraph in read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl'):
        decisions.append({
            **common,
            'kind': 'paragraph',
            'target_id': paragraph['paragraph_id'],
            'disposition': 'used',
            'source_id': paragraph['source_id'],
            'sourcepage_path': f"fixture://source/{paragraph['source_id']}/{paragraph['page_id']}",
            'paragraph_role': 'definition',
            'semantic_summary': 'A source-grounded paragraph retained for citation-grade use.',
            'claim_candidates': [],
            'method_candidates': [],
            'metric_candidates': [],
            'boundary_candidates': [],
            'reasoning_leap_candidates': [],
            'used_in_card': True,
            'requires_primary_anchor': True,
            'reason': 'The paragraph supports the promoted source representation.',
        })
    if len(surfaces) > 1 or manifest['source']['format'] == 'epub':
        paragraph_ids = [
            str(row['paragraph_id'])
            for row in read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl')
        ]
        candidate_ids = [
            str(row['candidate_id'])
            for row in read_json(package / 'toc' / 'toc_candidates.json').get('candidates', [])
        ]
        decisions.append({
            **common,
            'kind': 'structure',
            'target_id': 'canonical',
            'disposition': 'reviewed',
            'covered_surface_ids': [surface['surface_id'] for surface in surfaces],
            'candidate_dispositions': [
                {'candidate_id': candidate_id, 'disposition': 'used', 'reason': 'Retained in the reviewed structure.'}
                for candidate_id in candidate_ids
            ],
            'toc_items': [{
                'toc_id': 'toc_document', 'title': 'Document', 'boundary_id': 'boundary_document',
                'source_candidate_ids': candidate_ids,
            }],
            'boundaries': [{
                'boundary_id': 'boundary_document', 'title': 'Document',
                'structure_path': ['Document'],
                'surface_ids': [surface['surface_id'] for surface in surfaces],
                'paragraph_ids': paragraph_ids,
            }],
            'reason': 'Every source surface and boundary was reviewed.',
        })
    decisions.append({
        **common,
        'kind': 'source_boundary',
        'target_id': source_sha,
        'disposition': 'reviewed',
        'text': 'Use claims anchored to this supplied source only.',
        'reason': 'The source-use boundary was reviewed.',
    })
    return decisions


def apply_decisions(package: Path, path: Path, decisions: list[dict]) -> subprocess.CompletedProcess[str]:
    write_json(path, {'decisions': decisions})
    return run_cli('review', str(package), '--decisions', str(path))


def blocker_codes(package: Path, target: str = 'citation') -> set[str]:
    return {
        str(row['code'])
        for row in read_json(package / 'audit' / 'gates' / f'{target}.json')['hard_blockers']
    }


def test_agent_semantic_visual_resolution_methods_remain_typed_and_fail_closed() -> None:
    assert RESOLUTION_METHODS['sidecar_provenance_requires_review'] == {
        'producer_manifest_verified', 'producer_manifest_cryptographically_verified',
    }
    assert RESOLUTION_METHODS['multi_column_reading_order_requires_review'] == {
        'reading_order_verified', 'canonical_order_corrected',
    }
    assert RESOLUTION_METHODS['mixed_visual_region_requires_reconciliation'] == {
        'visual_regions_reconciled',
    }
    assert RESOLUTION_METHODS['low_ocr_confidence_unresolved'] == {
        'visual_transcription_verified', 'replacement_evidence_selected',
    }
    assert RESOLUTION_METHODS['visual_only_page_requires_rendered_evidence'] == {
        'rendered_rendition_attached',
    }


def test_agent_sidecar_manifest_requires_full_cryptographic_binding(tmp_path: Path) -> None:
    image = tmp_path / 'page.png'
    Image.new('RGB', (160, 100), color=(120, 130, 140)).save(image)
    image_sha = sha256_file(image)
    sidecar = tmp_path / 'sidecar.json'
    write_json(sidecar, {
        'engine': 'Bound-OCR', 'engine_version': '7',
        'blocks': [{
            'page_id': 'page_0001', 'text': 'cryptographically bound sidecar evidence',
            'bbox': [0, 0, 120, 80], 'confidence': 0.99,
            'source_image_sha256': image_sha,
        }],
    })
    package = tmp_path / 'sidecar-package'
    stdout_json(run_cli(
        'restore', str(image), '--out', str(package), '--target', 'review',
        '--ocr', 'sidecar', '--sidecar', str(sidecar),
    ))
    manifest = read_json(package / 'package_manifest.json')
    run_manifest = read_json(package / 'runs' / manifest['active_run_id'] / 'run_manifest.json')
    surface = read_jsonl(package / 'ledger' / 'surfaces.jsonl')[0]
    producer_manifest_path = package / 'audit' / 'ocr_producer_manifest.json'
    write_json(producer_manifest_path, {
        'status': 'complete',
        'input_sha256': run_manifest['external_input_digests']['ocr_sidecar']['sha256'],
        'row_count': 1,
        'page_count': 1,
        'producers': [{'engine': 'Bound-OCR', 'versions': ['7']}],
        'pages': [{
            'page_id': 'page_0001', 'source_image_sha256': surface['page_image_sha256'],
            'row_count': 1,
        }],
    })
    decisions = semantic_decisions(package)
    page = next(row for row in decisions if row['kind'] == 'page')
    page['reviewer_type'] = 'agent_semantic'
    page.update({
        'resolves': ['sidecar_provenance_requires_review'],
        'resolution_evidence': [{
            'code': 'sidecar_provenance_requires_review',
            'method': 'producer_manifest_cryptographically_verified',
            'verified': True,
            'manifest_path': 'audit/ocr_producer_manifest.json',
            'manifest_sha256': sha256_file(producer_manifest_path),
            'input_sha256': run_manifest['external_input_digests']['ocr_sidecar']['sha256'],
        }],
    })
    apply_decisions(package, tmp_path / 'bound-review.json', decisions)
    unresolved_blocker = next((
        row for row in read_json(package / 'audit' / 'gates' / 'citation.json')['hard_blockers']
        if row['code'] == 'unresolved_extraction_finding'
    ), None)
    unresolved = unresolved_blocker['observed'] if unresolved_blocker else []
    assert not any(row['kind'] == 'sidecar_provenance_requires_review' for row in unresolved)

    producer_manifest = read_json(producer_manifest_path)
    producer_manifest['row_count'] = 2
    write_json(producer_manifest_path, producer_manifest)
    active_page = next(
        row for row in read_jsonl(package / 'ledger' / 'review_decisions_active.jsonl')
        if row['kind'] == 'page'
    )
    tampered = {
        **{key: value for key, value in page.items() if key != 'created_at'},
        'supersedes': [active_page['decision_id']],
        'resolution_evidence': [{
            **page['resolution_evidence'][0],
            'manifest_sha256': sha256_file(producer_manifest_path),
        }],
    }
    apply_decisions(package, tmp_path / 'tampered-review.json', [tampered])
    unresolved = next(
        row for row in read_json(package / 'audit' / 'gates' / 'citation.json')['hard_blockers']
        if row['code'] == 'unresolved_extraction_finding'
    )['observed']
    assert any(row['kind'] == 'sidecar_provenance_requires_review' for row in unresolved)


def test_agent_visual_verification_uses_only_active_canonical_evidence(tmp_path: Path) -> None:
    image = tmp_path / 'page.png'
    Image.new('RGB', (160, 100), color=(120, 130, 140)).save(image)
    image_sha = sha256_file(image)
    sidecar = tmp_path / 'sidecar.json'
    write_json(sidecar, {
        'engine': 'Bound-OCR', 'engine_version': '7',
        'blocks': [
            {
                'page_id': 'page_0001', 'text': 'unsupported OCR noise',
                'bbox': [110, 50, 150, 90], 'confidence': 0.01,
                'source_image_sha256': image_sha,
            },
        ],
    })
    package = tmp_path / 'sidecar-package'
    stdout_json(run_cli(
        'restore', str(image), '--out', str(package), '--target', 'review',
        '--ocr', 'sidecar', '--sidecar', str(sidecar),
    ))
    evidence = read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')
    low_evidence = next(row for row in evidence if row['confidence'] < 0.1)
    low_block = next(
        row for row in read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')
        if row['evidence_id'] == low_evidence['evidence_id']
    )
    exclusion = {
        'kind': 'canonical_block', 'target_id': low_block['block_id'],
        'action': 'exclude_block', 'disposition': 'excluded',
        'semantic_reading': True, 'reviewer_type': 'agent_semantic',
        'reviewer_id': 'adversarial-fixture-reviewer', 'created_at': FIXED_REVIEW_TIME,
        'reason': 'Full-resolution visual review confirms the low-confidence OCR block has no source glyph counterpart.',
    }
    apply_decisions(package, tmp_path / 'exclude-noise.json', [exclusion])
    surface = read_jsonl(package / 'ledger' / 'surfaces.jsonl')[0]
    active = [
        row for row in read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl')
        if row.get('canonical_disposition') != 'excluded'
    ]
    active_evidence_ids = [row['evidence_id'] for row in active]
    page = {
        'kind': 'page', 'target_id': surface['page_id'], 'disposition': 'reviewed',
        'semantic_reading': True, 'reviewer_type': 'agent_semantic',
        'reviewer_id': 'adversarial-fixture-reviewer', 'created_at': FIXED_REVIEW_TIME,
        'resolves': ['low_ocr_confidence_unresolved'],
        'resolution_evidence': [{
            'code': 'low_ocr_confidence_unresolved',
            'method': 'visual_transcription_verified', 'verified': True,
            'artifact_path': surface['page_image_path'],
            'sha256': surface['page_image_sha256'],
            'evidence_ids': active_evidence_ids,
        }],
        'reason': 'The active source text and excluded OCR noise were reviewed against the full-resolution image.',
    }
    apply_decisions(package, tmp_path / 'verify-active-evidence.json', [page])

    unresolved = next(
        row for row in read_json(package / 'audit' / 'gates' / 'citation.json')['hard_blockers']
        if row['code'] == 'unresolved_extraction_finding'
    )['observed']
    assert not any(row['kind'] == 'low_ocr_confidence_unresolved' for row in unresolved)


def test_active_review_projection_materializes_only_latest_target_decision(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=1)
    restore_markdown(source, package)
    decisions = semantic_decisions(package)
    apply_decisions(package, tmp_path / 'initial.json', decisions)
    prior = next(
        row for row in read_jsonl(package / 'ledger' / 'review_decisions_active.jsonl')
        if row['kind'] == 'page'
    )
    revised = {
        **{key: value for key, value in prior.items() if key not in {
            'decision_id', 'decision_hash', 'previous_decision_hash', 'created_at',
        }},
        'supersedes': [prior['decision_id']],
        'reason': 'A second complete semantic pass supersedes the earlier page decision.',
        'created_at': FIXED_REVIEW_TIME,
    }
    apply_decisions(package, tmp_path / 'revised.json', [revised])

    active = read_jsonl(package / 'ledger' / 'review_decisions_active.jsonl')
    page_rows = [row for row in active if row['kind'] == 'page' and row['target_id'] == prior['target_id']]
    assert len(page_rows) == 1
    assert page_rows[0]['supersedes'] == [prior['decision_id']]


def test_bundle_manifest_cannot_self_authorize_external_sources(tmp_path: Path) -> None:
    outside = tmp_path / 'outside.md'
    make_markdown(outside, paragraphs=1)
    bundle_dir = tmp_path / 'bundle'
    bundle_dir.mkdir()
    manifest = bundle_dir / 'manifest.json'
    write_json(manifest, {
        'allow_external_sources': True,
        'sources': [{'source_id': 'outside', 'locator': '../outside.md'}],
    })

    blocked = run_cli(
        'restore', str(manifest), '--out', str(tmp_path / 'blocked'),
        '--target', 'review', '--ocr', 'none', check=False,
    )
    assert blocked.returncode == 4
    assert 'bundle source escapes manifest directory' in blocked.stderr

    allowed = run_cli(
        'restore', str(manifest), '--out', str(tmp_path / 'allowed'),
        '--target', 'review', '--ocr', 'none', '--allow-external-bundle-sources',
    )
    assert stdout_json(allowed)['gate_status'] == 'REVIEW_READY'


def test_bundle_rejects_missing_locator_unsafe_and_duplicate_source_ids(tmp_path: Path) -> None:
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    make_markdown(bundle / 'a.md', paragraphs=1)

    cases = [
        ({'sources': [{'source_id': 'a'}]}, 'requires locator'),
        ({'sources': [{'source_id': '../escape', 'locator': 'a.md'}]}, 'unsafe bundle source_id'),
        ({
            'sources': [
                {'source_id': 'same', 'locator': 'a.md', 'order': 1},
                {'source_id': 'same', 'locator': 'a.md', 'order': 2},
            ],
        }, 'duplicate bundle source_id'),
    ]
    for index, (payload, expected) in enumerate(cases, start=1):
        manifest = bundle / f'case-{index}.json'
        write_json(manifest, payload)
        result = run_cli(
            'restore', str(manifest), '--out', str(tmp_path / f'package-{index}'),
            '--target', 'review', '--ocr', 'none', check=False,
        )
        assert result.returncode == 4
        assert expected in result.stderr
    assert not (tmp_path / 'escape').exists()


def test_bundle_hash_attestation_and_global_ids_fail_closed(tmp_path: Path) -> None:
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    make_markdown(bundle / 'a.md', paragraphs=1)
    make_markdown(bundle / 'b.md', paragraphs=1)
    bad = bundle / 'bad.json'
    write_json(bad, {
        'sources': [{'source_id': 'a', 'locator': 'a.md', 'expected_sha256': '0' * 64}],
    })
    rejected = run_cli(
        'restore', str(bad), '--out', str(tmp_path / 'bad-package'),
        '--target', 'review', '--ocr', 'none', check=False,
    )
    assert rejected.returncode == 4
    assert 'bundle source hash mismatch' in rejected.stderr

    good = bundle / 'good.json'
    write_json(good, {
        'sources': [
            {'source_id': 'primary', 'source_role': 'primary', 'locator': 'a.md', 'order': 1},
            {'source_id': 'supplement', 'source_role': 'supplement', 'locator': 'b.md', 'order': 2},
        ],
    })
    package = tmp_path / 'good-package'
    restored = stdout_json(run_cli(
        'restore', str(good), '--out', str(package), '--target', 'review', '--ocr', 'none',
    ))
    assert restored['gate_status'] == 'REVIEW_READY'
    for rel, key in (
        ('surfaces.jsonl', 'page_id'),
        ('evidence_blocks.jsonl', 'evidence_id'),
        ('canonical_blocks.jsonl', 'block_id'),
    ):
        values = [row[key] for row in read_jsonl(package / 'ledger' / rel)]
        assert len(values) == len(set(values))
        assert all(value.startswith(('primary__', 'supplement__')) for value in values)


def test_sidecar_requires_locator_and_cannot_spoof_engine_or_image_hash(tmp_path: Path) -> None:
    source = tmp_path / 'page.png'
    Image.new('RGB', (120, 80), color=(120, 130, 140)).save(source)
    missing_locator = tmp_path / 'missing-locator.json'
    write_json(missing_locator, {'blocks': [{'text': 'unanchored', 'bbox': [0, 0, 100, 60]}]})
    missing_package = tmp_path / 'missing-package'
    result = stdout_json(run_cli(
        'restore', str(source), '--out', str(missing_package), '--target', 'review',
        '--ocr', 'sidecar', '--sidecar', str(missing_locator),
    ))
    assert result['gate_status'] == 'FAIL_REVIEW'
    extraction = read_json(missing_package / 'audit' / 'extraction_audit.json')
    assert any(row['kind'] == 'ocr_failure' and 'requires page_id' in row['message'] for row in extraction['hard_blockers'])
    assert not read_jsonl(missing_package / 'ledger' / 'canonical_blocks.jsonl')

    spoofed = tmp_path / 'spoofed.json'
    write_json(spoofed, {
        'engine': 'Unlimited-OCR',
        'engine_version': 'claimed-999',
        'blocks': [{
            'page_id': 'page_0001',
            'text': 'claimed OCR evidence',
            'bbox': [0, 0, 100, 60],
            'source_image_sha256': 'f' * 64,
        }],
    })
    spoofed_package = tmp_path / 'spoofed-package'
    spoofed_result = stdout_json(run_cli(
        'restore', str(source), '--out', str(spoofed_package), '--target', 'review',
        '--ocr', 'sidecar', '--sidecar', str(spoofed),
    ))
    evidence = read_jsonl(spoofed_package / 'ledger' / 'evidence_blocks.jsonl')
    extraction = read_json(spoofed_package / 'audit' / 'extraction_audit.json')
    findings = {row['kind'] for row in extraction['hard_blockers']}
    assert spoofed_result['gate_status'] == 'FAIL_REVIEW'
    assert {row['engine'] for row in evidence} == {'sidecar'}
    assert evidence[0]['metadata']['sidecar_producer']['claimed_engine'] == 'Unlimited-OCR'
    assert {'sidecar_source_image_unverified', 'sidecar_provenance_requires_review'} <= findings


def test_run_switch_rebinds_manifest_and_active_projection(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=2)
    first = restore_markdown(source, package, '--transcription', 'source')
    second = restore_markdown(source, package, '--transcription', 'normalized')
    assert first['run_id'] != second['run_id']
    assert read_json(package / 'package_manifest.json')['active_run_id'] == second['run_id']

    switched = restore_markdown(source, package, '--transcription', 'source')
    manifest = read_json(package / 'package_manifest.json')
    active_run = package / 'runs' / first['run_id']
    assert switched['reused'] is True
    assert manifest['active_run_id'] == first['run_id']
    assert set(manifest['runs']) == {first['run_id'], second['run_id']}
    assert manifest['active_run_manifest_sha256'] == sha256_file(active_run / 'run_manifest.json')
    for rel in (
        'ledger/surfaces.jsonl',
        'ledger/evidence_blocks.jsonl',
        'ledger/canonical_blocks.jsonl',
        'audit/extraction_audit.json',
    ):
        assert sha256_file(package / rel) == sha256_file(active_run / rel)
    inventory = read_json(package / 'source' / 'source_inventory.json')
    assert inventory['active_run_id'] == first['run_id']


def test_review_authority_is_isolated_by_active_run_and_recovers_on_safe_switchback(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=2)
    first = restore_markdown(source, package, '--transcription', 'source')
    reviewed = stdout_json(apply_decisions(package, tmp_path / 'review.json', semantic_decisions(package)))
    assert reviewed['gate_status'] == 'PASS_STRICT'

    second = restore_markdown(source, package, '--transcription', 'normalized')
    assert second['run_id'] != first['run_id']
    assert second['trust_status'] == 'needs_review'
    stdout_json(run_cli('status', str(package)))
    citation_gate = read_json(package / 'audit' / 'gates' / 'citation.json')
    assert citation_gate['public_status'] == 'FAIL_REVIEW'
    assert any(row['code'] == 'manual_page_review_missing' for row in citation_gate['hard_blockers'])
    assert not (package / 'ledger' / 'paragraph_coverage.jsonl').exists()

    switched_back = restore_markdown(source, package, '--transcription', 'source')
    assert switched_back['run_id'] == first['run_id']
    status = stdout_json(run_cli('status', str(package)))
    assert status['trust_status'] == 'citation_grade'
    assert status['gate_status'] == 'PASS_STRICT'


def test_review_authority_never_leaks_across_accepted_source_revisions(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=1)
    first = restore_markdown(source, package)
    reviewed = stdout_json(apply_decisions(package, tmp_path / 'review.json', semantic_decisions(package)))
    assert reviewed['gate_status'] == 'PASS_STRICT'
    package_id = read_json(package / 'package_manifest.json')['package_id']

    make_markdown(source, paragraphs=3)
    second = restore_markdown(source, package, '--accept-source-update')
    manifest = read_json(package / 'package_manifest.json')
    assert second['run_id'] != first['run_id']
    assert manifest['package_id'] == package_id
    assert len(manifest['source_revisions']) == 2
    status = stdout_json(run_cli('status', str(package)))
    assert status['gate_status'] == 'FAIL_REVIEW'
    assert 'manual_page_review_missing' in blocker_codes(package)


def test_new_run_is_unique_even_when_two_requests_share_the_same_clock_tick(tmp_path: Path, monkeypatch) -> None:
    sys.path.insert(0, str(REPO / 'src'))
    from xuanzang import restoration
    from xuanzang.contracts import RestorePolicy, RestoreRequest

    class FrozenDateTime:
        @classmethod
        def now(cls, tz=None):
            return RealDateTime(2026, 1, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(restoration, 'datetime', FrozenDateTime)
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=1)
    request = RestoreRequest(
        source=source,
        out=package,
        policy=RestorePolicy(target='review', ocr='none'),
        new_run=True,
    )
    first = restoration.restore_source(request)
    second = restoration.restore_source(request)
    assert first.run_id != second.run_id
    assert (package / 'runs' / first.run_id / 'run_manifest.json').exists()
    assert (package / 'runs' / second.run_id / 'run_manifest.json').exists()


def test_active_run_id_traversal_and_run_manifest_path_injection_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=1)
    restore_markdown(source, package)
    manifest_path = package / 'package_manifest.json'
    manifest = read_json(manifest_path)
    manifest['active_run_id'] = '../../outside'
    write_json(manifest_path, manifest)

    status = stdout_json(run_cli('status', str(package)))
    gate = read_json(package / 'audit' / 'gates' / 'citation.json')
    assert status['gate_status'] == 'FAIL_REVIEW'
    integrity = next(row for row in gate['hard_blockers'] if row['code'] == 'stale_or_tampered_artifact')
    assert 'active_run_id_invalid' in integrity['observed']

    # Recreate a clean package, then simulate a forged run manifest whose head
    # binding and Merkle-like digest root were both rewritten by an attacker.
    package2 = tmp_path / 'package2'
    restored = restore_markdown(source, package2)
    head_path = package2 / 'package_manifest.json'
    head = read_json(head_path)
    run_manifest_path = package2 / 'runs' / restored['run_id'] / 'run_manifest.json'
    run_manifest = read_json(run_manifest_path)
    run_manifest['artifact_digests']['../../outside'] = '0' * 64
    run_manifest['artifact_root_sha256'] = sha256_text('\n'.join(
        f'{rel}:{digest}' for rel, digest in sorted(run_manifest['artifact_digests'].items())
    ))
    write_json(run_manifest_path, run_manifest)
    head['active_run_manifest_sha256'] = sha256_file(run_manifest_path)
    write_json(head_path, head)

    status2 = stdout_json(run_cli('status', str(package2)))
    gate2 = read_json(package2 / 'audit' / 'gates' / 'citation.json')
    assert status2['gate_status'] == 'FAIL_REVIEW'
    observed = next(row for row in gate2['hard_blockers'] if row['code'] == 'stale_or_tampered_artifact')['observed']
    assert 'run_artifact_path:../../outside' in observed


def test_malformed_reasoning_leap_rolls_back_entire_review_batch(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=1)
    restore_markdown(source, package)
    decisions = semantic_decisions(package)
    paragraph = next(row for row in decisions if row['kind'] == 'paragraph')
    paragraph['reasoning_leap_candidates'] = [{
        'premises': ['Source premise'],
        'inference': 'A candidate conceptual leap',
        # uncertainty is intentionally absent
    }]
    ledger = package / 'ledger' / 'review_decisions.jsonl'
    before_ledger = ledger.read_bytes()
    before_manifest = read_json(package / 'package_manifest.json')
    decision_path = tmp_path / 'malformed-leap.json'
    write_json(decision_path, {'decisions': decisions})

    result = run_cli('review', str(package), '--decisions', str(decision_path), check=False)
    assert result.returncode == 4
    assert 'reasoning leap requires premises, inference, and uncertainty' in result.stderr
    assert ledger.read_bytes() == before_ledger
    after_manifest = read_json(package / 'package_manifest.json')
    assert after_manifest['review_revision'] == before_manifest['review_revision']
    assert after_manifest['review_ledger_sha256'] == before_manifest['review_ledger_sha256']


def test_reasoning_leap_cannot_reference_a_nonexported_paragraph(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=2)
    restore_markdown(source, package)
    decisions = semantic_decisions(package)
    paragraphs = [row for row in decisions if row['kind'] == 'paragraph']
    host, hidden = paragraphs[0], paragraphs[1]
    hidden['disposition'] = 'reference_only'
    hidden['paragraph_role'] = 'reference_only'
    hidden['used_in_card'] = False
    hidden['reason'] = 'Retained for navigation but intentionally omitted from citation chunks.'
    host['reasoning_leap_candidates'] = [{
        'premises': ['A premise that points at a paragraph omitted from citation chunks.'],
        'premise_paragraph_ids': [hidden['target_id']],
        'inference': 'The candidate inference would otherwise publish a dangling paragraph ID.',
        'conclusion_paragraph_ids': [host['target_id']],
        'assumptions': [],
        'novelty_context': 'Potentially novel only within the supplied source.',
        'counterevidence': [],
        'source_local_boundary': 'Do not generalize beyond this supplied source.',
        'uncertainty': 'Requires scientific review.',
        'alternatives': [],
        'testable_predictions': [],
        'reviewer_status': 'candidate',
    }]
    ledger = package / 'ledger' / 'review_decisions.jsonl'
    before_ledger = ledger.read_bytes()
    decision_path = tmp_path / 'dangling-leap.json'
    write_json(decision_path, {'decisions': decisions})

    result = run_cli('review', str(package), '--decisions', str(decision_path), check=False)

    assert result.returncode == 4
    assert 'must be disposition=used' in result.stderr
    assert ledger.read_bytes() == before_ledger


def test_review_hash_chain_tamper_is_detected_even_if_ledger_binding_is_rewritten(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=2)
    restore_markdown(source, package)
    reviewed = stdout_json(apply_decisions(package, tmp_path / 'review.json', semantic_decisions(package)))
    assert reviewed['gate_status'] == 'PASS_STRICT'

    ledger_path = package / 'ledger' / 'review_decisions.jsonl'
    rows = read_jsonl(ledger_path)
    rows[0]['reason'] = 'tampered after review'
    write_jsonl(ledger_path, rows)
    manifest_path = package / 'package_manifest.json'
    manifest = read_json(manifest_path)
    manifest['review_ledger_sha256'] = sha256_file(ledger_path)
    write_json(manifest_path, manifest)

    status = stdout_json(run_cli('status', str(package)))
    assert status['gate_status'] == 'FAIL_REVIEW'
    assert 'review_decision_chain_invalid' in blocker_codes(package)


def test_paragraph_coverage_projection_tamper_does_not_control_citation_export(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=2)
    restore_markdown(source, package)
    reviewed = stdout_json(apply_decisions(package, tmp_path / 'review.json', semantic_decisions(package)))
    assert reviewed['gate_status'] == 'PASS_STRICT'
    expected_texts = [
        row['text'] for row in read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl')
    ]
    write_jsonl(package / 'ledger' / 'paragraph_coverage.jsonl', [{
        'paragraph_id': 'attacker-controlled',
        'text': 'This projection must never become publication authority.',
        'coverage_status': 'used',
    }])

    export = tmp_path / 'citation-export'
    published = stdout_json(run_cli('publish', str(package), '--target', 'citation', '--out', str(export)))
    chunks = read_jsonl(export / 'chunks.jsonl')
    assert published['gate_status'] == 'PASS_STRICT'
    assert [row['text'] for row in chunks] == expected_texts
    assert 'attacker-controlled' not in (export / 'document.md').read_text(encoding='utf-8')


def test_scope_mismatch_blocks_status_review_publish_and_manifest_scope_tamper(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=1)
    stdout_json(run_cli(
        'restore', str(source), '--out', str(package), '--target', 'review', '--ocr', 'none',
        '--privacy', 'tenant', '--tenant-id', 'tenant-a', '--access-tag', 'project:alpha',
    ))
    empty_decisions = tmp_path / 'empty.json'
    write_json(empty_decisions, {'decisions': []})
    ledger_before = (package / 'ledger' / 'review_decisions.jsonl').read_bytes()

    status = run_cli('status', str(package), '--expected-tenant-id', 'tenant-b', check=False)
    review = run_cli(
        'review', str(package), '--decisions', str(empty_decisions),
        '--expected-tenant-id', 'tenant-b', check=False,
    )
    publish = run_cli(
        'publish', str(package), '--target', 'hint', '--out', str(tmp_path / 'wrong-export'),
        '--expected-tenant-id', 'tenant-b', check=False,
    )
    assert status.returncode == review.returncode == publish.returncode == 4
    assert (package / 'ledger' / 'review_decisions.jsonl').read_bytes() == ledger_before
    assert not (tmp_path / 'wrong-export' / 'manifest.json').exists()

    manifest_path = package / 'package_manifest.json'
    manifest = read_json(manifest_path)
    manifest['scope']['tenant_id'] = 'tenant-b'
    write_json(manifest_path, manifest)
    tampered_status = stdout_json(run_cli('status', str(package)))
    assert tampered_status['gate_status'] == 'FAIL_REVIEW'
    assert 'scope_binding_mismatch' in blocker_codes(package)


def test_local_revocation_blocks_every_future_package_operation_and_emits_tombstone(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=1)
    stdout_json(run_cli(
        'restore', str(source), '--out', str(package), '--target', 'review', '--ocr', 'none',
        '--privacy', 'tenant', '--tenant-id', 'tenant-a',
    ))
    external_tombstone = tmp_path / 'revocation.json'
    tombstone = stdout_json(run_cli(
        'revoke', str(package), '--reason', 'rights withdrawn', '--out', str(external_tombstone),
        '--expected-tenant-id', 'tenant-a',
    ))
    assert tombstone['state'] == 'revoked'
    assert tombstone['scope']['tenant_id'] == 'tenant-a'
    assert tombstone['acknowledgements_required'] is True
    assert external_tombstone.exists()

    status = stdout_json(run_cli('status', str(package), '--expected-tenant-id', 'tenant-a'))
    empty = tmp_path / 'empty.json'
    write_json(empty, {'decisions': []})
    review = run_cli('review', str(package), '--decisions', str(empty), check=False)
    publish = run_cli(
        'publish', str(package), '--target', 'hint', '--out', str(tmp_path / 'export'), check=False,
    )
    restore = run_cli(
        'restore', str(source), '--out', str(package), '--target', 'review', '--ocr', 'none', check=False,
    )
    assert status['gate_status'] == 'FAIL_REVIEW'
    assert 'package_revoked' in blocker_codes(package)
    assert review.returncode == 4
    assert publish.returncode == 2
    assert restore.returncode == 4
    assert not (tmp_path / 'export' / 'manifest.json').exists()


def test_epub_duplicate_zip_bomb_and_opf_escape_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / 'duplicate.epub'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(duplicate, 'w') as archive:
            archive.writestr('mimetype', 'application/epub+zip')
            archive.writestr('META-INF/container.xml', '<container/>')
            archive.writestr('META-INF/container.xml', '<container/>')
    duplicate_result = run_cli(
        'restore', str(duplicate), '--out', str(tmp_path / 'duplicate-package'),
        '--target', 'review', '--ocr', 'none', check=False,
    )
    assert duplicate_result.returncode == 4
    assert 'duplicate or case-colliding archive members' in duplicate_result.stderr

    bomb = tmp_path / 'bomb.epub'
    with zipfile.ZipFile(bomb, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('mimetype', 'application/epub+zip')
        archive.writestr('bomb.bin', b'0' * (2 * 1024 * 1024))
    bomb_result = run_cli(
        'restore', str(bomb), '--out', str(tmp_path / 'bomb-package'),
        '--target', 'review', '--ocr', 'none', check=False,
    )
    assert bomb_result.returncode == 4
    assert 'exceeds safe compression ratio' in bomb_result.stderr

    escaped_opf = tmp_path / 'escaped-opf.epub'
    container = (
        '<?xml version="1.0"?>'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
        '<rootfiles><rootfile full-path="../outside.opf" media-type="application/oebps-package+xml"/>'
        '</rootfiles></container>'
    )
    with zipfile.ZipFile(escaped_opf, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip')
        archive.writestr('META-INF/container.xml', container)
    escape_result = run_cli(
        'restore', str(escaped_opf), '--out', str(tmp_path / 'escape-package'),
        '--target', 'review', '--ocr', 'none', check=False,
    )
    assert escape_result.returncode == 4
    assert 'EPUB rootfile path escapes the archive root' in escape_result.stderr


def test_restore_refuses_nonempty_output_and_migration_overlap(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    make_markdown(source, paragraphs=1)
    package = tmp_path / 'package'
    package.mkdir()
    sentinel = package / 'user-data.txt'
    sentinel.write_text('must survive', encoding='utf-8')
    restore = run_cli(
        'restore', str(source), '--out', str(package), '--target', 'review', '--ocr', 'none', check=False,
    )
    assert restore.returncode == 4
    assert 'non-empty directory' in restore.stderr
    assert sentinel.read_text(encoding='utf-8') == 'must survive'
    assert not (package / 'package_manifest.json').exists()

    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    migration = run_cli('migrate-v1', str(legacy), '--out', str(legacy / 'nested-output'), check=False)
    assert migration.returncode == 4
    assert 'migration input and output must not contain one another' in migration.stderr


def test_v1_migration_rejects_non_sha256_source_identity(tmp_path: Path) -> None:
    source = tmp_path / 'legacy.txt'
    source.write_text('Legacy bytes whose identity can be recomputed.\n', encoding='utf-8')
    old = tmp_path / 'legacy-package'
    inventory = {
        'source_path': str(source),
        'source_sha256': '../../attacker-controlled-identity',
        'format': 'text',
    }
    write_json(old / 'package_manifest.json', {'package_version': 1, 'source': inventory})
    write_json(old / 'source' / 'source_inventory.json', inventory)
    write_jsonl(old / 'ledger' / 'source_blocks.jsonl', [{
        'block_id': 'legacy-block-1',
        'source_type': 'text_native',
        'spine_index': 1,
        'text': 'Legacy bytes whose identity can be recomputed.',
        'block_kind': 'text_candidate',
    }])
    write_jsonl(old / 'ledger' / 'image_blocks.jsonl', [])

    migrated = tmp_path / 'migrated'
    result = run_cli('migrate-v1', str(old), '--out', str(migrated), check=False)
    assert result.returncode == 4
    assert 'source identity' in result.stderr.lower()
    assert 'sha256' in result.stderr.lower()
    assert not (migrated / 'package_manifest.json').exists()

    verified = tmp_path / 'verified-migration'
    accepted = stdout_json(run_cli(
        'migrate-v1', str(old), '--out', str(verified), '--source', str(source),
    ))
    report = read_json(verified / 'audit' / 'migration_report.json')
    assert accepted['status'] == 'migrated'
    assert read_json(verified / 'package_manifest.json')['source']['sha256'] == sha256_file(source)
    assert report['source_identity_status'] == 'verified_from_explicit_source'


def test_normalized_transcription_keeps_source_variant_and_binds_normalized_canonical(tmp_path: Path) -> None:
    source = tmp_path / 'source.txt'
    decomposed = 'Cafe\u0301 is preserved as source evidence.'
    normalized = 'Caf\u00e9 is preserved as source evidence.'
    source.write_text(decomposed + '\n', encoding='utf-8')
    package = tmp_path / 'package'
    result = stdout_json(run_cli(
        'restore', str(source), '--out', str(package), '--target', 'review', '--ocr', 'none',
        '--transcription', 'normalized',
    ))
    assert result['gate_status'] == 'REVIEW_READY'
    evidence = read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')
    source_variant = next(row for row in evidence if row['engine'] == 'text_native')
    normalized_variant = next(row for row in evidence if row['engine'] == 'unicode_normalization')
    canonical = read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')
    manifest = read_json(package / 'package_manifest.json')
    assert source_variant['text'] == decomposed
    assert normalized_variant['text'] == normalized
    assert normalized_variant['metadata']['derived_from_evidence_id'] == source_variant['evidence_id']
    assert canonical[0]['text'] == normalized
    assert canonical[0]['source_evidence_id'] == source_variant['evidence_id']
    assert manifest['profile']['transcription'] == 'normalized'


def test_source_size_and_image_pixel_budgets_stop_before_commit(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    make_markdown(source, paragraphs=2)
    oversized = run_cli(
        'restore', str(source), '--out', str(tmp_path / 'oversized'), '--target', 'review', '--ocr', 'none',
        '--max-source-bytes', '8', check=False,
    )
    assert oversized.returncode == 4
    assert 'max_source_bytes' in oversized.stderr
    assert not (tmp_path / 'oversized' / 'package_manifest.json').exists()

    image = tmp_path / 'large.png'
    Image.new('RGB', (40, 40), color=(100, 110, 120)).save(image)
    pixels = run_cli(
        'restore', str(image), '--out', str(tmp_path / 'pixels'), '--target', 'review', '--ocr', 'mock',
        '--max-total-pixels', '100', check=False,
    )
    assert pixels.returncode == 4
    assert 'max_total_pixels' in pixels.stderr
    assert not (tmp_path / 'pixels' / 'package_manifest.json').exists()


def test_batch_restore_is_incremental_distinct_and_containment_safe(tmp_path: Path) -> None:
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    make_markdown(corpus / 'same-name.md', paragraphs=1)
    nested = corpus / 'nested'
    nested.mkdir()
    make_markdown(nested / 'same-name.md', paragraphs=2)

    overlap = run_cli(
        'batch', str(corpus), '--out-root', str(corpus / 'output'),
        '--target', 'hint', '--ocr', 'none', check=False,
    )
    assert overlap.returncode == 4
    assert 'outside source_dir' in overlap.stderr

    out = tmp_path / 'batch-output'
    first = stdout_json(run_cli(
        'batch', str(corpus), '--out-root', str(out), '--target', 'hint', '--ocr', 'none',
        '--workers', '2',
    ))
    rows = read_jsonl(out / 'batch_results.jsonl')
    assert first['selected'] == first['completed'] == 2
    assert first['failed'] == 0
    assert len({row['package_rel'] for row in rows}) == 2
    assert all(row['gate_status'] == 'HINT_READY' for row in rows)
    assert all((out / row['package_rel'] / 'package_manifest.json').exists() for row in rows)

    second = stdout_json(run_cli(
        'batch', str(corpus), '--out-root', str(out), '--target', 'hint', '--ocr', 'none',
        '--workers', '2',
    ))
    all_rows = read_jsonl(out / 'batch_results.jsonl')
    assert second['completed'] == 2
    assert len(all_rows) == 4
    assert all(row['reused'] is True for row in all_rows[-2:])


def test_batch_fail_fast_accounts_for_completed_failed_and_cancelled_work(tmp_path: Path) -> None:
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    # The invalid bundle fails quickly while at least one Markdown restore may
    # already be running. Every future must still appear in the audit ledger.
    write_json(corpus / '00-invalid.json', {'unexpected': 'not a source bundle'})
    make_markdown(corpus / '10-valid.md', paragraphs=1)
    make_markdown(corpus / '20-valid.md', paragraphs=2)
    out = tmp_path / 'batch-output'

    summary = stdout_json(run_cli(
        'batch', str(corpus), '--out-root', str(out), '--target', 'hint', '--ocr', 'none',
        '--workers', '2', '--fail-fast',
    ))
    rows = read_jsonl(out / 'batch_results.jsonl')
    assert summary['selected'] == 3
    assert summary['selected'] == summary['completed'] + summary['failed'] + summary['cancelled']
    assert len(rows) == summary['selected']
    assert {row['status'] for row in rows} <= {'complete', 'failed', 'cancelled'}
    assert any(row['status'] == 'failed' for row in rows)

    recorded_packages = {row['package_rel'] for row in rows}
    materialized_packages = {
        str(path.parent.relative_to(out))
        for path in (out / 'packages').glob('*/package_manifest.json')
    }
    assert materialized_packages <= recorded_packages


def test_docx_dtd_and_entity_payload_is_rejected(tmp_path: Path) -> None:
    docx = tmp_path / 'entity.docx'
    document_xml = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE w:document [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body></w:document>'
    )
    with zipfile.ZipFile(docx, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', document_xml)
    result = run_cli(
        'restore', str(docx), '--out', str(tmp_path / 'docx-package'),
        '--target', 'review', '--ocr', 'none', check=False,
    )
    assert result.returncode == 4
    assert 'DTD/entity declarations are not allowed' in result.stderr


def test_binary_and_run_artifact_tamper_block_hint_and_citation(tmp_path: Path) -> None:
    source = tmp_path / 'page.png'
    Image.new('RGB', (160, 100), color=(100, 110, 120)).save(source)
    package = tmp_path / 'package'
    restored = stdout_json(run_cli(
        'restore', str(source), '--out', str(package), '--target', 'review', '--ocr', 'mock',
    ))
    assert restored['gate_status'] == 'REVIEW_READY'
    surface = read_jsonl(package / 'ledger' / 'surfaces.jsonl')[0]
    binary = package / surface['page_image_path']
    binary.write_bytes(b'attacker replaced binary evidence')

    status = stdout_json(run_cli('status', str(package)))
    assert status['gate_status'] == 'FAIL_REVIEW'
    codes = blocker_codes(package)
    assert 'binary_evidence_integrity_failure' in codes
    assert 'stale_or_tampered_artifact' in codes
    hint = run_cli(
        'publish', str(package), '--target', 'hint', '--out', str(tmp_path / 'hint'), check=False,
    )
    citation = run_cli(
        'publish', str(package), '--target', 'citation', '--out', str(tmp_path / 'citation'), check=False,
    )
    assert hint.returncode == citation.returncode == 2
    assert not (tmp_path / 'hint' / 'manifest.json').exists()
    assert not (tmp_path / 'citation' / 'manifest.json').exists()


def test_reviewed_reorder_preserves_raw_blocks_and_creates_bound_projection(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=3)
    restore_markdown(source, package)
    raw_path = package / 'ledger' / 'canonical_blocks.jsonl'
    raw_before = raw_path.read_bytes()
    blocks = read_jsonl(raw_path)
    assert len(blocks) >= 3
    decision = {
        'kind': 'canonical_block',
        'target_id': blocks[0]['block_id'],
        'action': 'reorder_blocks',
        'ordered_block_ids': [blocks[0]['block_id'], blocks[2]['block_id'], blocks[1]['block_id']],
        'disposition': 'selected',
        'semantic_reading': True,
        'reviewer_type': 'human',
        'reviewer_id': 'adversarial-fixture-reviewer',
        'created_at': FIXED_REVIEW_TIME,
        'reason': 'A visual column-order review established this contiguous same-surface order.',
    }
    result = stdout_json(apply_decisions(package, tmp_path / 'reorder.json', [decision]))
    reviewed = read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl')
    manifest = read_json(package / 'package_manifest.json')

    assert result['gate_status'] == 'FAIL_REVIEW'
    assert [row['block_id'] for row in reviewed[:3]] == decision['ordered_block_ids']
    assert all(row['selection_status'] == 'reviewed_reorder' for row in reviewed[:3])
    assert raw_path.read_bytes() == raw_before
    assert manifest['canonical_revision'] == sha256_file(package / 'ledger' / 'canonical_reviewed.jsonl')[:20]
    assert manifest['paragraph_projection_sha256'] == sha256_file(
        package / 'ledger' / 'paragraph_candidates_reviewed.jsonl'
    )
    original_projection = [row['block_id'] for row in reviewed]
    restore_markdown(source, package, '--transcription', 'normalized')
    restore_markdown(source, package, '--transcription', 'source')
    rehydrated = read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl')
    rehydrated_manifest = read_json(package / 'package_manifest.json')
    assert [row['block_id'] for row in rehydrated] == original_projection
    assert rehydrated_manifest['canonical_revision'] == sha256_file(
        package / 'ledger' / 'canonical_reviewed.jsonl'
    )[:20]


def test_reviewed_cross_surface_resegmentation_is_exact_and_reversible(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=3)
    restore_markdown(source, package)
    raw_path = package / 'ledger' / 'canonical_blocks.jsonl'
    raw_before = raw_path.read_bytes()
    blocks = read_jsonl(raw_path)
    first, third = blocks[0], blocks[2]
    joined_text = f"{first['text']} {third['text']}"
    decision = {
        'kind': 'canonical_block',
        'target_id': first['block_id'],
        'action': 'resegment_blocks_across_surfaces',
        'source_block_ids': [third['block_id']],
        'segments': [{
            'text': joined_text,
            'block_kind': 'text_candidate',
            'source_spans': [
                {'block_id': first['block_id'], 'start_offset': 0, 'end_offset': len(first['text'])},
                {'block_id': third['block_id'], 'start_offset': 0, 'end_offset': len(third['text'])},
            ],
        }],
        'disposition': 'selected',
        'semantic_reading': True,
        'reviewer_type': 'agent_semantic',
        'reviewer_id': 'adversarial-fixture-reviewer',
        'created_at': FIXED_REVIEW_TIME,
        'reason': 'Visual review confirmed one sentence split by an intervening full-page float.',
    }

    apply_decisions(package, tmp_path / 'resegment.json', [decision])
    reviewed = read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl')

    assert reviewed[0]['text'] == joined_text
    assert reviewed[0]['selection_status'] == 'reviewed_resegmentation'
    assert [span['block_id'] for span in reviewed[0]['source_spans']] == [
        first['block_id'], third['block_id'],
    ]
    assert reviewed[1]['block_id'] == blocks[1]['block_id']
    assert raw_path.read_bytes() == raw_before


def test_reviewed_reorder_can_skip_explicitly_excluded_noise(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=3)
    restore_markdown(source, package)
    blocks = read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')
    assert len(blocks) >= 3
    decisions = [
        {
            'kind': 'canonical_block',
            'target_id': blocks[0]['block_id'],
            'action': 'reorder_blocks',
            'ordered_block_ids': [blocks[2]['block_id'], blocks[0]['block_id']],
            'disposition': 'selected',
            'semantic_reading': True,
            'reviewer_type': 'agent_semantic',
            'reviewer_id': 'adversarial-fixture-reviewer',
            'created_at': FIXED_REVIEW_TIME,
            'reason': 'Visual review established that the middle OCR block is noise between two valid blocks.',
        },
        {
            'kind': 'canonical_block',
            'target_id': blocks[1]['block_id'],
            'action': 'exclude_block',
            'disposition': 'excluded',
            'semantic_reading': True,
            'reviewer_type': 'agent_semantic',
            'reviewer_id': 'adversarial-fixture-reviewer',
            'created_at': FIXED_REVIEW_TIME,
            'reason': 'Full-resolution visual review confirms this OCR block has no source glyph counterpart.',
        },
    ]

    apply_decisions(package, tmp_path / 'reorder-with-noise.json', decisions)
    reviewed = read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl')
    active = [row['block_id'] for row in reviewed if row.get('canonical_disposition') != 'excluded']

    assert active[:2] == [blocks[2]['block_id'], blocks[0]['block_id']]
    excluded = next(row for row in reviewed if row['block_id'] == blocks[1]['block_id'])
    assert excluded['canonical_disposition'] == 'excluded'


def test_reviewed_reorder_preserves_member_text_corrections(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=3)
    restore_markdown(source, package)
    blocks = read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')
    corrected = f"{blocks[1]['text']} corrected"
    decisions = [
        {
            'kind': 'canonical_block',
            'target_id': blocks[0]['block_id'],
            'action': 'reorder_blocks',
            'ordered_block_ids': [blocks[1]['block_id'], blocks[0]['block_id'], blocks[2]['block_id']],
            'disposition': 'selected',
            'semantic_reading': True,
            'reviewer_type': 'agent_semantic',
            'reviewer_id': 'adversarial-fixture-reviewer',
            'created_at': FIXED_REVIEW_TIME,
            'reason': 'Visual review established a corrected first paragraph followed by the remaining source order.',
        },
        {
            'kind': 'canonical_block',
            'target_id': blocks[1]['block_id'],
            'action': 'correct_text',
            'corrected_text': corrected,
            'disposition': 'selected',
            'semantic_reading': True,
            'reviewer_type': 'agent_semantic',
            'reviewer_id': 'adversarial-fixture-reviewer',
            'created_at': FIXED_REVIEW_TIME,
            'reason': 'Visual review resolves a source glyph omitted by OCR.',
        },
    ]

    apply_decisions(package, tmp_path / 'reorder-with-correction.json', decisions)
    reviewed = read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl')

    assert reviewed[0]['block_id'] == blocks[1]['block_id']
    assert reviewed[0]['text'] == corrected
    assert reviewed[0]['selection_status'] == 'reviewed_correction'
    assert reviewed[0]['reorder_decision_id']
    assert reviewed[1]['selection_status'] == 'reviewed_reorder'


def test_reviewed_reorder_preserves_superseded_target_text_correction(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=3)
    restore_markdown(source, package)
    blocks = read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')
    corrected = f"{blocks[0]['text']} corrected"
    correction = {
        'kind': 'canonical_block',
        'target_id': blocks[0]['block_id'],
        'action': 'correct_text',
        'corrected_text': corrected,
        'disposition': 'selected',
        'semantic_reading': True,
        'reviewer_type': 'agent_semantic',
        'reviewer_id': 'adversarial-fixture-reviewer',
        'created_at': FIXED_REVIEW_TIME,
        'reason': 'Full-resolution visual review resolves a source glyph omitted by OCR.',
    }
    apply_decisions(package, tmp_path / 'target-correction.json', [correction])
    correction_decision = read_jsonl(package / 'ledger' / 'review_decisions.jsonl')[-1]
    reorder = {
        'kind': 'canonical_block',
        'target_id': blocks[0]['block_id'],
        'action': 'reorder_blocks',
        'ordered_block_ids': [blocks[1]['block_id'], blocks[0]['block_id'], blocks[2]['block_id']],
        'preserved_target_correction': {
            'decision_id': correction_decision['decision_id'],
            'corrected_text': corrected,
        },
        'supersedes': [correction_decision['decision_id']],
        'disposition': 'selected',
        'semantic_reading': True,
        'reviewer_type': 'agent_semantic',
        'reviewer_id': 'adversarial-fixture-reviewer',
        'created_at': FIXED_REVIEW_TIME,
        'reason': 'Visual review establishes the page order while preserving the target glyph correction.',
    }

    apply_decisions(package, tmp_path / 'target-reorder.json', [reorder])
    reviewed = read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl')
    target = next(row for row in reviewed if row['block_id'] == blocks[0]['block_id'])

    assert target['text'] == corrected
    assert target['selection_status'] == 'reviewed_correction'
    assert target['review_decision_id'] == correction_decision['decision_id']
    assert target['reorder_decision_id']


def test_reviewed_reorder_rejects_silent_loss_of_target_text_correction(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=3)
    restore_markdown(source, package)
    blocks = read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')
    correction = {
        'kind': 'canonical_block',
        'target_id': blocks[0]['block_id'],
        'action': 'correct_text',
        'corrected_text': f"{blocks[0]['text']} corrected",
        'disposition': 'selected',
        'semantic_reading': True,
        'reviewer_type': 'agent_semantic',
        'reviewer_id': 'adversarial-fixture-reviewer',
        'created_at': FIXED_REVIEW_TIME,
        'reason': 'Full-resolution visual review resolves a source glyph omitted by OCR.',
    }
    apply_decisions(package, tmp_path / 'target-correction.json', [correction])
    correction_id = read_jsonl(package / 'ledger' / 'review_decisions.jsonl')[-1]['decision_id']
    reorder = {
        'kind': 'canonical_block',
        'target_id': blocks[0]['block_id'],
        'action': 'reorder_blocks',
        'ordered_block_ids': [blocks[1]['block_id'], blocks[0]['block_id'], blocks[2]['block_id']],
        'supersedes': [correction_id],
        'disposition': 'selected',
        'semantic_reading': True,
        'reviewer_type': 'agent_semantic',
        'reviewer_id': 'adversarial-fixture-reviewer',
        'created_at': FIXED_REVIEW_TIME,
        'reason': 'This invalid fixture would silently discard the target correction.',
    }

    decisions_path = tmp_path / 'target-reorder-without-preservation.json'
    write_json(decisions_path, {'decisions': [reorder]})
    result = run_cli(
        'review', str(package), '--decisions', str(decisions_path), check=False,
    )

    assert result.returncode == 4
    assert 'must preserve the target correction explicitly' in (result.stdout + result.stderr)


def test_structure_review_is_partitioned_bound_and_exported_with_all_semantic_assets(tmp_path: Path) -> None:
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    make_markdown(bundle / 'a.md', paragraphs=1)
    make_markdown(bundle / 'b.md', paragraphs=1)
    write_json(bundle / 'manifest.json', {
        'sources': [
            {'source_id': 'a', 'locator': 'a.md', 'order': 1},
            {'source_id': 'b', 'locator': 'b.md', 'order': 2},
        ],
    })
    package = tmp_path / 'package'
    stdout_json(run_cli(
        'restore', str(bundle / 'manifest.json'), '--out', str(package),
        '--target', 'review', '--ocr', 'none',
    ))

    invalid = semantic_decisions(package)
    next(row for row in invalid if row['kind'] == 'structure')['toc_items'] = []
    invalid_path = tmp_path / 'invalid-structure.json'
    write_json(invalid_path, {'decisions': invalid})
    invalid_result = run_cli('review', str(package), '--decisions', str(invalid_path), check=False)
    assert invalid_result.returncode == 4
    assert 'non-empty canonical TOC' in invalid_result.stderr
    assert read_jsonl(package / 'ledger' / 'review_decisions.jsonl') == []

    decisions = semantic_decisions(package)
    paragraph = next(row for row in decisions if row['kind'] == 'paragraph')
    paragraph_id = paragraph['target_id']
    paragraph['claim_candidates'] = [{'text': 'Anchored claim'}]
    paragraph['method_candidates'] = [{'text': 'Anchored method'}]
    paragraph['metric_candidates'] = [{'text': 'Anchored metric'}]
    paragraph['boundary_candidates'] = [{'text': 'Anchored boundary'}]
    paragraph['reasoning_leap_candidates'] = [{
        'premises': ['A source-local premise'],
        'premise_paragraph_ids': [paragraph_id],
        'inference': 'A candidate bridge from premise to a new framing.',
        'conclusion_paragraph_ids': [],
        'assumptions': ['The local terminology is used consistently.'],
        'novelty_context': 'Potentially novel within this supplied source only.',
        'counterevidence': [],
        'source_local_boundary': 'Do not treat this candidate as cross-source novelty.',
        'uncertainty': 'Requires scientific review and external challenge evidence.',
        'alternatives': ['A narrower interpretation'],
        'testable_predictions': ['A downstream reviewer can formulate a falsifiable test.'],
        'reviewer_status': 'candidate',
    }]
    reviewed = stdout_json(apply_decisions(package, tmp_path / 'valid-structure.json', decisions))
    assert reviewed['gate_status'] == 'PASS_STRICT'
    manifest = read_json(package / 'package_manifest.json')
    assert manifest['toc_projection_sha256'] == sha256_file(package / 'toc' / 'canonical_toc.json')
    assert manifest['boundary_projection_sha256'] == sha256_file(package / 'toc' / 'chapter_boundary_map.json')
    assert all(row['structure_path'] for row in read_jsonl(package / 'ledger' / 'paragraph_candidates_reviewed.jsonl'))

    exported = tmp_path / 'citation'
    stdout_json(run_cli('publish', str(package), '--target', 'citation', '--out', str(exported)))
    chunks = read_jsonl(exported / 'chunks.jsonl')
    enriched = next(row for row in chunks if row['paragraph_ids'] == [paragraph_id])
    for field in (
        'claim_candidates', 'method_candidates', 'metric_candidates',
        'boundary_candidates', 'reasoning_leap_candidates', 'structure_path',
    ):
        assert enriched[field]
    leap_projection = read_jsonl(package / 'ledger' / 'reasoning_leap_candidates.jsonl')
    assert leap_projection[0]['premise_paragraph_ids'] == [paragraph_id]
    assert leap_projection[0]['source_local_boundary']

    reused = stdout_json(run_cli(
        'restore', str(bundle / 'manifest.json'), '--out', str(package),
        '--target', 'review', '--ocr', 'none',
    ))
    assert reused['reused'] is True
    assert stdout_json(run_cli('status', str(package)))['gate_status'] == 'PASS_STRICT'
    alternate = stdout_json(run_cli(
        'restore', str(bundle / 'manifest.json'), '--out', str(package),
        '--target', 'review', '--ocr', 'none', '--transcription', 'normalized',
    ))
    assert alternate['run_id'] != reused['run_id']
    switched_back = stdout_json(run_cli(
        'restore', str(bundle / 'manifest.json'), '--out', str(package),
        '--target', 'review', '--ocr', 'none', '--transcription', 'source',
    ))
    assert switched_back['run_id'] == reused['run_id']
    assert stdout_json(run_cli('status', str(package)))['gate_status'] == 'PASS_STRICT'

    compat = run_cli('toc', str(package), check=False)
    assert compat.returncode == 4
    assert 'cannot mutate a reviewed v2 package' in compat.stderr
    toc_path = package / 'toc' / 'canonical_toc.json'
    toc = read_json(toc_path)
    toc['items'][0]['title'] = 'tampered'
    write_json(toc_path, toc)
    status = stdout_json(run_cli('status', str(package)))
    assert status['gate_status'] == 'FAIL_REVIEW'
    assert 'toc_projection_mismatch' in blocker_codes(package)


def test_local_strict_acceptance_binds_revision_and_markdown_contract(tmp_path: Path) -> None:
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    make_markdown(bundle / 'chapter-a.md', paragraphs=1)
    make_markdown(bundle / 'chapter-b.md', paragraphs=1)
    write_json(bundle / 'manifest.json', {
        'sources': [
            {'source_id': 'chapter-a', 'locator': 'chapter-a.md', 'order': 1},
            {'source_id': 'chapter-b', 'locator': 'chapter-b.md', 'order': 2},
        ],
    })
    package = tmp_path / 'package'
    stdout_json(run_cli(
        'restore', str(bundle / 'manifest.json'), '--out', str(package),
        '--target', 'review', '--ocr', 'none',
    ))
    decisions = semantic_decisions(package)
    structure = next(row for row in decisions if row['kind'] == 'structure')
    structure['document_title'] = 'Fixture Book'
    reviewed = stdout_json(apply_decisions(package, tmp_path / 'decisions.json', decisions))
    assert reviewed['gate_status'] == 'PASS_STRICT'

    exported = tmp_path / 'export'
    stdout_json(run_cli('publish', str(package), '--target', 'citation', '--out', str(exported)))
    markdown = (exported / 'document.md').read_text(encoding='utf-8')
    headings = [line for line in markdown.splitlines() if line.startswith('#')]
    assert headings[0] == '# Fixture Book'
    assert headings.count('# Fixture Book') == 1
    assert '## Document' in headings
    assert not any(line.startswith('####') for line in headings)

    accepted = stdout_json(run_cli(
        'verify-local-strict', str(package), '--export', str(exported),
    ))
    assert accepted['status'] == 'PASS_STRICT'
    assert accepted['failure_count'] == 0
    assert read_json(exported / 'local_strict_acceptance.json')['status'] == 'PASS_STRICT'

    (exported / 'document.md').write_text(markdown + '\n#### injected heading\n', encoding='utf-8')
    rejected = run_cli(
        'verify-local-strict', str(package), '--export', str(exported), check=False,
    )
    assert rejected.returncode == 2
    report = stdout_json(rejected)
    assert report['status'] == 'FAIL_REVIEW'
    assert {row['code'] for row in report['failures']} >= {
        'artifact_hash_mismatch', 'markdown_heading_too_deep',
    }


def test_resolution_assertions_cannot_clear_bad_image_hash(tmp_path: Path) -> None:
    image = tmp_path / 'page.png'
    Image.new('RGB', (160, 100), color=(120, 130, 140)).save(image)
    sidecar = tmp_path / 'sidecar.json'
    write_json(sidecar, {
        'engine': 'Unlimited-OCR', 'engine_version': '1',
        'blocks': [{
            'page_id': 'page_0001', 'text': 'sidecar evidence', 'bbox': [0, 0, 120, 80],
            'source_image_sha256': 'f' * 64,
        }],
    })
    package = tmp_path / 'sidecar-package'
    stdout_json(run_cli(
        'restore', str(image), '--out', str(package), '--target', 'review',
        '--ocr', 'sidecar', '--sidecar', str(sidecar),
    ))
    decisions = semantic_decisions(package)
    page = next(row for row in decisions if row['kind'] == 'page')
    evidence_id = read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')[0]['evidence_id']
    page.update({
        'resolves': ['sidecar_source_image_unverified'],
        'resolution_evidence': [{
            'code': 'sidecar_source_image_unverified', 'method': 'source_image_hash_verified',
            'verified': True, 'evidence_ids': [evidence_id],
        }],
    })
    reviewed = stdout_json(apply_decisions(package, tmp_path / 'hash-assertion.json', decisions))
    assert reviewed['gate_status'] == 'FAIL_REVIEW'
    unresolved = next(
        row for row in read_json(package / 'audit' / 'gates' / 'citation.json')['hard_blockers']
        if row['code'] == 'unresolved_extraction_finding'
    )['observed']
    assert any(row['kind'] == 'sidecar_source_image_unverified' for row in unresolved)


def test_plugin_adapters_cannot_opt_out_of_anchor_or_provenance_review(tmp_path: Path, monkeypatch) -> None:
    sys.path.insert(0, str(REPO / 'src'))
    from xuanzang import adapters
    from xuanzang.contracts import RestorePolicy
    from xuanzang.extractors import extract_source

    class FakeAdapter:
        name = 'unsafe-plugin'

        def available(self):
            return True

        def version(self):
            return '1'

        def recognize(self, image, *, lang=None, page_id=None):
            return [adapters.OCRBlock('plugin text', [0, 0, 80, 60], 0.99)]

    class FakeEntry:
        name = 'unsafe'

        @staticmethod
        def load():
            return FakeAdapter

    monkeypatch.setattr(adapters.importlib.metadata, 'entry_points', lambda **kwargs: [FakeEntry()])
    adapter = adapters.choose_ocr_adapter('plugin:unsafe')
    assert adapter is not None
    assert adapter.requires_anchor_attestation is True
    assert adapter.requires_provenance_review is True
    assert adapter.xuanzang_plugin_name == 'unsafe'
    try:
        RestorePolicy(ocr='plugin:unsafe', sidecar=str(tmp_path / 'unrelated.json')).validate()
        raise AssertionError('plugin OCR accepted an unrelated sidecar provenance input')
    except ValueError as exc:
        assert 'sidecar path is valid only with ocr=sidecar' in str(exc)
    image_path = tmp_path / 'page.png'
    Image.new('RGB', (100, 80), color=(120, 130, 140)).save(image_path)
    result = extract_source(
        image_path, tmp_path / 'work',
        RestorePolicy(target='review', ocr='plugin:unsafe'), adapter,
    )
    findings = {row['kind'] for row in result.blockers}
    assert 'external_ocr_source_image_unverified' in findings
    assert 'external_ocr_provenance_requires_review' in findings


def test_select_variant_requires_an_explicit_variant_group_and_preserves_raw_span(tmp_path: Path) -> None:
    unrelated_source = tmp_path / 'unrelated.md'
    unrelated_package = tmp_path / 'unrelated-package'
    make_markdown(unrelated_source, paragraphs=2)
    restore_markdown(unrelated_source, unrelated_package)
    unrelated_blocks = read_jsonl(unrelated_package / 'ledger' / 'canonical_blocks.jsonl')
    unrelated_decision = {
        'kind': 'canonical_block', 'target_id': unrelated_blocks[0]['block_id'],
        'action': 'select_variant', 'selected_evidence_id': unrelated_blocks[1]['evidence_id'],
        'disposition': 'selected', 'semantic_reading': True, 'reviewer_type': 'human',
        'reviewer_id': 'adversarial-fixture-reviewer', 'reason': 'Attempted unrelated same-page substitution.',
    }
    unrelated_path = tmp_path / 'unrelated-decision.json'
    write_json(unrelated_path, {'decisions': [unrelated_decision]})
    rejected = run_cli(
        'review', str(unrelated_package), '--decisions', str(unrelated_path), check=False,
    )
    assert rejected.returncode == 4
    assert 'shared variant_group_id' in rejected.stderr

    source = tmp_path / 'normalized.md'
    source.write_text('# Cafe\u0301\n\nA decomposed source variant.\n', encoding='utf-8')
    package = tmp_path / 'normalized-package'
    restore_markdown(source, package, '--transcription', 'both')
    raw_block = read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')[0]
    selected_id = raw_block['source_evidence_id']
    accepted = stdout_json(apply_decisions(package, tmp_path / 'variant.json', [{
        'kind': 'canonical_block', 'target_id': raw_block['block_id'],
        'action': 'select_variant', 'selected_evidence_id': selected_id,
        'disposition': 'selected', 'semantic_reading': True, 'reviewer_type': 'human',
        'reviewer_id': 'adversarial-fixture-reviewer',
        'reason': 'Selected the source-form member of the explicit transcription variant group.',
    }]))
    reviewed = read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl')[0]
    assert accepted['gate_status'] == 'FAIL_REVIEW'
    assert reviewed['evidence_id'] == selected_id
    assert reviewed['source_spans'][0]['evidence_id'] == raw_block['evidence_id']
    assert reviewed['variant_group_id'] == raw_block['variant_group_id']
