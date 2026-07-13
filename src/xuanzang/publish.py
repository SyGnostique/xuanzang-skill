from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .gates import evaluate_gates
from .utils import (
    atomic_write_text,
    assert_expected_scope,
    ensure_dir,
    package_lock,
    read_json,
    read_jsonl,
    sha256_file,
    sha256_text,
    utc_now,
    write_json,
    write_jsonl,
)


def _output_paths(out: Path) -> tuple[Path, Path, Path, Path]:
    if out.suffix.lower() == '.md':
        ensure_dir(out.parent)
        return (
            out,
            out.with_suffix('.chunks.jsonl'),
            out.with_suffix('.manifest.json'),
            out.with_suffix('.embedding.json'),
        )
    ensure_dir(out)
    return out / 'document.md', out / 'chunks.jsonl', out / 'manifest.json', out / 'embedding_manifest.json'


def _latest_decisions(package: Path, manifest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    latest = {}
    source_sha = manifest.get('source', {}).get('sha256')
    run_id = manifest.get('active_run_id')
    canonical_revision = str(manifest.get('canonical_revision', 'raw'))
    for row in read_jsonl(package / 'ledger' / 'review_decisions.jsonl'):
        if row.get('source_sha256') != source_sha or row.get('active_run_id') != run_id:
            continue
        if row.get('kind') == 'paragraph' and row.get('canonical_revision') != canonical_revision:
            continue
        latest[(str(row.get('kind')), str(row.get('target_id')))] = row
    return latest


def _publish_locked(
    package: Path, *, target: str, out: Path,
    expected_tenant_id: str | None = None, expected_workspace_id: str | None = None,
) -> dict[str, Any]:
    if target not in {'hint', 'citation'}:
        raise ValueError('publish target must be hint or citation')
    package = package.resolve()
    out = out.resolve()
    if out == package or package in out.parents:
        raise ValueError('publish output must be outside the evidence package')
    manifest = read_json(package / 'package_manifest.json')
    assert_expected_scope(
        manifest, expected_tenant_id=expected_tenant_id,
        expected_workspace_id=expected_workspace_id,
    )
    gate = evaluate_gates(package, target=target)
    if gate.get('status') != 'pass':
        raise RuntimeError(f'{target} publish blocked by {len(gate.get("hard_blockers", []))} hard blockers')
    if target == 'citation' and gate.get('trust_status') != 'citation_grade':
        raise RuntimeError(f'citation publish blocked by {len(gate.get("hard_blockers", []))} hard blockers')

    manifest = read_json(package / 'package_manifest.json')
    decisions = _latest_decisions(package, manifest)
    if target == 'citation':
        candidates = (
            read_jsonl(package / 'ledger' / 'paragraph_candidates_reviewed.jsonl')
            or read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl')
        )
        selected = []
        for paragraph in candidates:
            decision = decisions.get(('paragraph', str(paragraph.get('paragraph_id'))))
            if not decision or decision.get('disposition') != 'used':
                continue
            selected.append({
                **paragraph,
                'coverage_status': 'used',
                'paragraph_role': decision.get('paragraph_role'),
                'semantic_summary': decision.get('semantic_summary'),
                'claim_candidates': decision.get('claim_candidates', []),
                'method_candidates': decision.get('method_candidates', []),
                'metric_candidates': decision.get('metric_candidates', []),
                'boundary_candidates': decision.get('boundary_candidates', []),
                'reasoning_leap_candidates': decision.get('reasoning_leap_candidates', []),
                'review_decision_id': decision.get('decision_id'),
                'reviewer_id': decision.get('reviewer_id'),
            })
    else:
        selected = []
        for block in (
            read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl')
            or read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')
        ):
            selected.append({
                'paragraph_id': block['block_id'], 'page_id': block['page_id'], 'page_anchor': block['page_id'],
                'text': block['text'], 'text_sha256': sha256_text(block['text']),
                'source_spans': [{
                    'block_id': block['block_id'], 'evidence_id': block['evidence_id'], 'page_id': block['page_id'],
                    'start_offset': 0, 'end_offset': len(block.get('text', '')),
                }],
                'coverage_status': 'hint_only',
            })

    md_path, chunks_path, manifest_path, embedding_path = _output_paths(out)
    title = Path(manifest.get('source', {}).get('path', 'document')).name
    lines = [
        f'# {title}', '', f'> trust_status: {gate["trust_status"]}',
        f'> package_id: {manifest.get("package_id")}', f'> run_id: {manifest.get("active_run_id")}', '',
    ]
    chunks = []
    current_page = None
    scope = manifest.get('scope', {})
    profile = manifest.get('profile', {})
    for order, paragraph in enumerate(selected, start=1):
        page = paragraph.get('page_id') or paragraph.get('page_anchor')
        if page != current_page:
            lines.extend([f'## {page}', ''])
            current_page = page
        lines.extend([paragraph.get('text', ''), ''])
        chunks.append({
            'chunk_id': f"chunk_{sha256_text(paragraph.get('paragraph_id', '') + paragraph.get('text_sha256', ''))[:16]}",
            'order': order,
            'text': paragraph.get('text', ''),
            'text_sha256': paragraph.get('text_sha256') or sha256_text(paragraph.get('text', '')),
            'paragraph_ids': [paragraph.get('paragraph_id')],
            'source_spans': paragraph.get('source_spans', []),
            'page_anchor': paragraph.get('page_anchor') or page,
            'structure_path': paragraph.get('structure_path', []),
            'language': profile.get('lang'),
            'paragraph_role': paragraph.get('paragraph_role'),
            'semantic_summary': paragraph.get('semantic_summary'),
            'claim_candidates': paragraph.get('claim_candidates', []),
            'method_candidates': paragraph.get('method_candidates', []),
            'metric_candidates': paragraph.get('metric_candidates', []),
            'boundary_candidates': paragraph.get('boundary_candidates', []),
            'reasoning_leap_candidates': paragraph.get('reasoning_leap_candidates', []),
            'review_decision_id': paragraph.get('review_decision_id'),
            'trust_status': gate['trust_status'],
            'package_id': manifest.get('package_id'),
            'run_id': manifest.get('active_run_id'),
            'source_sha256': manifest.get('source', {}).get('sha256'),
            'canonical_revision': manifest.get('canonical_revision'),
            'review_revision': manifest.get('review_revision', '0'),
            'access_tags': scope.get('access_tags', []),
            'privacy': scope.get('privacy'),
            'rights_basis': scope.get('rights_basis'),
            'retention_policy': scope.get('retention_policy'),
            'tenant_id': scope.get('tenant_id'),
            'workspace_id': scope.get('workspace_id'),
        })
    atomic_write_text(md_path, '\n'.join(lines).rstrip() + '\n')
    write_jsonl(chunks_path, chunks)

    invalidation_key = sha256_text('|'.join([
        str(manifest.get('package_id')), str(manifest.get('active_run_id')),
        str(manifest.get('canonical_revision')), str(manifest.get('review_revision', '0')),
        target, sha256_file(chunks_path),
    ]))
    embedding_manifest = {
        'schema_version': 2,
        'status': 'unembedded',
        'input': chunks_path.name,
        'input_sha256': sha256_file(chunks_path),
        'chunk_count': len(chunks),
        'invalidation_key': invalidation_key,
        'trust_status': gate['trust_status'],
        'namespace_requirements': {
            'tenant_id': scope.get('tenant_id'), 'workspace_id': scope.get('workspace_id'),
            'access_tags': scope.get('access_tags', []), 'privacy': scope.get('privacy'),
            'rights_basis': scope.get('rights_basis'), 'retention_policy': scope.get('retention_policy'),
            'target': target,
        },
        'model': None,
        'dimensions': None,
        'note': 'Embeddings are downstream derived artifacts and must be rebuilt when invalidation_key changes.',
    }
    write_json(embedding_path, embedding_manifest)

    gate_path = package / 'audit' / 'gates' / f'{target}.json'
    exported_gate_path = (
        md_path.with_suffix('.gate.json') if out.suffix.lower() == '.md'
        else md_path.parent / 'gate_report.json'
    )
    write_json(exported_gate_path, read_json(gate_path))
    source_boundary = decisions.get(('source_boundary', str(manifest.get('source', {}).get('sha256'))), {})
    review_decisions = sorted({
        str(row.get('decision_id')) for row in decisions.values() if row.get('decision_id')
    })
    limitations = [
        'No embedding vectors are included; use embedding_manifest.json for downstream invalidation and namespace policy.',
        'Authorization tags are carried as metadata; enforcement belongs to the hosting knowledge-base runtime.',
    ]
    if target == 'hint':
        limitations.insert(0, 'Hint output is machine-restored evidence and is not citation-grade.')
    export_id = f"exp_{sha256_text(invalidation_key + target)[:20]}"
    export = {
        'schema_version': 2,
        'export_id': export_id,
        'export_kind': 'knowledge_base_markdown_and_chunks',
        'target': target,
        'trust_status': gate['trust_status'],
        'gate_status': gate['public_status'],
        'package_id': manifest.get('package_id'),
        'package_revision': {
            'run_id': manifest.get('active_run_id'),
            'canonical_revision': manifest.get('canonical_revision'),
            'review_revision': manifest.get('review_revision', '0'),
        },
        'source_sha256': manifest.get('source', {}).get('sha256'),
        'source_revision_count': len(manifest.get('source_revisions', [])),
        'scope': scope,
        'source_use_boundary': source_boundary.get('text'),
        'review_decision_ids': review_decisions,
        'gate_report': exported_gate_path.name,
        'gate_report_sha256': sha256_file(exported_gate_path),
        'review_ledger_sha256': sha256_file(package / 'ledger' / 'review_decisions.jsonl'),
        'document': md_path.name,
        'document_sha256': sha256_file(md_path),
        'chunks': chunks_path.name,
        'chunks_sha256': sha256_file(chunks_path),
        'embedding_manifest': embedding_path.name,
        'embedding_manifest_sha256': sha256_file(embedding_path),
        'chunk_count': len(chunks),
        'limitations': limitations,
        'created_at': utc_now(),
    }
    export['spec_sha256'] = sha256_text(json.dumps({
        'schema_version': export['schema_version'], 'export_kind': export['export_kind'],
        'target': target, 'required_artifacts': ['document', 'chunks', 'embedding_manifest', 'gate_report'],
    }, sort_keys=True))
    write_json(manifest_path, export)
    return export


def publish_package(
    package: Path, *, target: str, out: Path,
    expected_tenant_id: str | None = None, expected_workspace_id: str | None = None,
) -> dict[str, Any]:
    package = package.resolve()
    with package_lock(package):
        return _publish_locked(
            package, target=target, out=out,
            expected_tenant_id=expected_tenant_id, expected_workspace_id=expected_workspace_id,
        )
