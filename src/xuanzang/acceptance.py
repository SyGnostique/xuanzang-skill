from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .gates import evaluate_gates
from .utils import read_json, read_jsonl, sha256_file, sha256_text, utc_now, write_json


REQUIRED_EXPORT_ARTIFACTS = {
    'document': 'document.md',
    'chunks': 'chunks.jsonl',
    'assets': 'assets.jsonl',
    'objects': 'objects.jsonl',
    'gate_report': 'gate_report.json',
    'publication_validation': 'publication_validation.json',
    'embedding_manifest': 'embedding_manifest.json',
}


def _artifact_path(export_dir: Path, manifest: dict[str, Any], field: str) -> Path:
    value = str(manifest.get(field) or REQUIRED_EXPORT_ARTIFACTS[field])
    path = (export_dir / value).resolve()
    if export_dir.resolve() not in path.parents:
        raise ValueError(f'export manifest {field} escapes the export directory')
    return path


def _markdown_headings(text: str) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    in_frontmatter = False
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_number == 1 and line.strip() == '---':
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line.strip() == '---':
                in_frontmatter = False
            continue
        if re.match(r'^\s*```', line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r'^(#{1,6})\s+(.+?)\s*#*\s*$', line)
        if match:
            headings.append({
                'level': len(match.group(1)),
                'title': match.group(2).strip(),
                'line': line_number,
            })
    return headings


def _empty_leaf_headings(text: str, headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = text.splitlines()
    failures = []
    for index, heading in enumerate(headings):
        if heading['level'] == 1:
            continue
        next_index = next(
            (
                other_index for other_index in range(index + 1, len(headings))
                if headings[other_index]['level'] <= heading['level']
            ),
            len(headings),
        )
        descendants = headings[index + 1:next_index]
        if descendants:
            continue
        end_line = headings[index + 1]['line'] - 1 if index + 1 < len(headings) else len(lines)
        body = '\n'.join(lines[heading['line']:end_line]).strip()
        if not body:
            failures.append(heading)
    return failures


def verify_local_strict(package: Path, export_dir: Path, *, write_report: bool = True) -> dict[str, Any]:
    """Independently verify the final local citation export.

    This verifier never promotes a package. It recomputes the package gate and
    then proves that the exported Markdown/JSONL projection is the same active,
    hash-bound, citation-grade revision with a single book H1, H2/H3 structure,
    complete object/asset ledgers, and reverse-locatable chunks.
    """
    package = package.resolve()
    export_path = export_dir.resolve()
    file_export = export_path.suffix.lower() == '.md'
    export_dir = export_path.parent if file_export else export_path
    acceptance_path = (
        export_path.with_suffix('.acceptance.json')
        if file_export else export_dir / 'local_strict_acceptance.json'
    )
    failures: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    def fail(code: str, detail: Any) -> None:
        failures.append({'code': code, 'detail': detail})

    package_manifest_path = package / 'package_manifest.json'
    export_manifest_path = (
        export_path.with_suffix('.manifest.json')
        if file_export else export_dir / 'manifest.json'
    )
    if not package_manifest_path.is_file():
        fail('missing_package_manifest', str(package_manifest_path))
    if not export_manifest_path.is_file():
        fail('missing_export_manifest', str(export_manifest_path))
    if failures:
        result = {
            'schema_version': 1,
            'status': 'FAIL_REVIEW',
            'package': str(package),
            'export': str(export_path),
            'failures': failures,
            'checks': checks,
            'verified_at': utc_now(),
        }
        if write_report:
            export_dir.mkdir(parents=True, exist_ok=True)
            write_json(acceptance_path, result)
        return result

    package_manifest = read_json(package_manifest_path)
    export_manifest = read_json(export_manifest_path)
    gate = evaluate_gates(package, target='citation')
    checks['package_gate'] = {
        'status': gate.get('status'),
        'public_status': gate.get('public_status'),
        'trust_status': gate.get('trust_status'),
        'hard_blocker_count': len(gate.get('hard_blockers', [])),
    }
    if (
        gate.get('status') != 'pass'
        or gate.get('public_status') != 'PASS_STRICT'
        or gate.get('trust_status') != 'citation_grade'
        or gate.get('hard_blockers')
    ):
        fail('package_not_citation_grade', checks['package_gate'])

    expected_identity = {
        'package_id': package_manifest.get('package_id'),
        'active_run_id': package_manifest.get('active_run_id'),
        'source_sha256': (package_manifest.get('source') or {}).get('sha256'),
    }
    observed_identity = {
        'package_id': export_manifest.get('package_id'),
        'active_run_id': export_manifest.get('active_run_id') or export_manifest.get('run_id'),
        'source_sha256': export_manifest.get('source_sha256'),
    }
    checks['identity'] = {'expected': expected_identity, 'observed': observed_identity}
    if expected_identity != observed_identity:
        fail('export_identity_mismatch', checks['identity'])
    expected_revision = {
        'run_id': package_manifest.get('active_run_id'),
        'canonical_revision': package_manifest.get('canonical_revision'),
        'review_revision': str(package_manifest.get('review_revision', '0')),
    }
    observed_revision = {
        **(export_manifest.get('package_revision') or {}),
        'review_revision': str((export_manifest.get('package_revision') or {}).get('review_revision', '0')),
    }
    checks['revision'] = {'expected': expected_revision, 'observed': observed_revision}
    if expected_revision != observed_revision:
        fail('export_revision_mismatch', checks['revision'])
    if (
        export_manifest.get('target') != 'citation'
        or export_manifest.get('gate_status') != 'PASS_STRICT'
        or export_manifest.get('trust_status') != 'citation_grade'
    ):
        fail('export_not_strict_citation', {
            'target': export_manifest.get('target'),
            'gate_status': export_manifest.get('gate_status'),
            'trust_status': export_manifest.get('trust_status'),
        })

    artifact_paths: dict[str, Path] = {}
    for field in REQUIRED_EXPORT_ARTIFACTS:
        try:
            path = _artifact_path(export_dir, export_manifest, field)
        except ValueError as exc:
            fail('unsafe_artifact_path', {'field': field, 'error': str(exc)})
            continue
        artifact_paths[field] = path
        if not path.is_file():
            fail('missing_export_artifact', {'field': field, 'path': str(path)})
            continue
        expected_hash = export_manifest.get(f'{field}_sha256')
        observed_hash = sha256_file(path)
        if expected_hash != observed_hash:
            fail('artifact_hash_mismatch', {
                'field': field, 'expected': expected_hash, 'observed': observed_hash,
            })
    checks['artifact_count'] = len(artifact_paths)

    if 'gate_report' in artifact_paths and artifact_paths['gate_report'].is_file():
        gate_report = read_json(artifact_paths['gate_report'])
        if (
            gate_report.get('status') != 'pass'
            or gate_report.get('public_status') != 'PASS_STRICT'
            or gate_report.get('trust_status') != 'citation_grade'
            or gate_report.get('hard_blockers')
        ):
            fail('exported_gate_report_failed', gate_report)

    publication: dict[str, Any] = {}
    if 'publication_validation' in artifact_paths and artifact_paths['publication_validation'].is_file():
        publication = read_json(artifact_paths['publication_validation'])
        if publication.get('status') != 'PASS':
            fail('publication_validation_failed', publication)
        negative_fields = {
            key: value for key, value in publication.items()
            if (
                key.startswith('missing_')
                or key.endswith('_violations')
                or key.endswith('_regressions')
            ) and value
        }
        false_invariants = {
            key: value for key, value in publication.items()
            if (
                key.endswith(('_matches', '_excluded'))
                and value is False
                and not (
                    key == 'canonical_heading_sequence_matches'
                    and not publication.get('canonical_heading_invariant_required')
                )
            )
        }
        if negative_fields or false_invariants:
            fail('publication_invariant_failed', {
                'findings': negative_fields,
                'false_invariants': false_invariants,
            })

    canonical_toc_path = package / 'toc' / 'canonical_toc.json'
    canonical_projection = read_json(canonical_toc_path) if canonical_toc_path.is_file() else {}
    reviewed_document_title = str(canonical_projection.get('document_title') or '').strip()
    checks['reviewed_document_title'] = reviewed_document_title or None
    if not reviewed_document_title:
        fail('document_title_not_reviewed', str(canonical_toc_path))

    if 'document' in artifact_paths and artifact_paths['document'].is_file():
        markdown = artifact_paths['document'].read_text(encoding='utf-8')
        headings = _markdown_headings(markdown)
        h1 = [row for row in headings if row['level'] == 1]
        overdeep = [row for row in headings if row['level'] > 3]
        empty = _empty_leaf_headings(markdown, headings)
        checks['markdown'] = {
            'heading_count': len(headings),
            'h1_count': len(h1),
            'h1_title': h1[0]['title'] if len(h1) == 1 else None,
            'overdeep_heading_count': len(overdeep),
            'empty_leaf_heading_count': len(empty),
        }
        if len(h1) != 1 or not h1[0]['title'].strip():
            fail('markdown_book_title_contract', h1)
        elif reviewed_document_title and h1[0]['title'] != reviewed_document_title:
            fail('markdown_book_title_mismatch', {
                'expected': reviewed_document_title,
                'observed': h1[0]['title'],
            })
        if overdeep:
            fail('markdown_heading_too_deep', overdeep[:20])
        if empty:
            fail('markdown_empty_leaf_sections', empty[:20])

    chunks = (
        read_jsonl(artifact_paths['chunks'])
        if 'chunks' in artifact_paths and artifact_paths['chunks'].is_file() else []
    )
    assets = (
        read_jsonl(artifact_paths['assets'])
        if 'assets' in artifact_paths and artifact_paths['assets'].is_file() else []
    )
    objects = (
        read_jsonl(artifact_paths['objects'])
        if 'objects' in artifact_paths and artifact_paths['objects'].is_file() else []
    )
    checks['projection_counts'] = {
        'chunks': len(chunks), 'assets': len(assets), 'objects': len(objects),
    }
    for field, rows in [('chunk', chunks), ('asset', assets), ('object', objects)]:
        expected = int(export_manifest.get(f'{field}_count', 0) or 0)
        if expected != len(rows):
            fail(f'{field}_count_mismatch', {'expected': expected, 'observed': len(rows)})
    if not chunks:
        fail('empty_chunk_projection', None)

    chunk_ids: set[str] = set()
    bad_chunks = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_id = str(chunk.get('chunk_id') or '')
        text = str(chunk.get('text') or '')
        visual_anchors = chunk.get('visual_anchors') or []
        source_spans = chunk.get('source_spans') or []
        if (
            not chunk_id
            or chunk_id in chunk_ids
            or chunk.get('trust_status') != 'citation_grade'
            or chunk.get('package_id') != expected_identity['package_id']
            or chunk.get('run_id') != expected_identity['active_run_id']
            or chunk.get('source_sha256') != expected_identity['source_sha256']
            or not chunk.get('page_anchor')
            or not chunk.get('structure_path')
            or not chunk.get('paragraph_ids')
            or not text
            or chunk.get('text_sha256') != sha256_text(text)
            or (not source_spans and not visual_anchors)
            or (source_spans and not chunk.get('source_reconstruction'))
        ):
            bad_chunks.append({'line': index, 'chunk_id': chunk_id})
        chunk_ids.add(chunk_id)
    if bad_chunks:
        fail('non_reversible_or_invalid_chunks', bad_chunks[:50])

    occurrence_ids: set[str] = set()
    bad_assets = []
    for index, asset in enumerate(assets, start=1):
        occurrence_id = str(asset.get('occurrence_id') or '')
        export_path = str(asset.get('export_path') or '')
        asset_path = (export_dir / export_path).resolve() if export_path else export_dir
        if (
            not occurrence_id
            or occurrence_id in occurrence_ids
            or export_dir not in asset_path.parents
            or not asset_path.is_file()
            or sha256_file(asset_path) != asset.get('export_sha256')
            or not asset.get('page_id')
        ):
            bad_assets.append({'line': index, 'occurrence_id': occurrence_id})
        occurrence_ids.add(occurrence_id)
    if bad_assets:
        fail('invalid_or_unbound_assets', bad_assets[:50])

    referenced_occurrences = [
        str(value)
        for chunk in chunks
        for value in chunk.get('asset_occurrence_ids', [])
        if value
    ]
    if (
        set(referenced_occurrences) != occurrence_ids
        or len(referenced_occurrences) != len(set(referenced_occurrences))
    ):
        fail('asset_reference_not_exactly_once', {
            'unreferenced': sorted(occurrence_ids - set(referenced_occurrences)),
            'unknown': sorted(set(referenced_occurrences) - occurrence_ids),
            'duplicate_count': len(referenced_occurrences) - len(set(referenced_occurrences)),
        })

    object_ids = [str(row.get('object_id') or '') for row in objects]
    if any(not value for value in object_ids) or len(object_ids) != len(set(object_ids)):
        fail('invalid_or_duplicate_objects', {'count': len(object_ids), 'unique': len(set(object_ids))})

    result = {
        'schema_version': 1,
        'status': 'PASS_STRICT' if not failures else 'FAIL_REVIEW',
        'package': str(package),
        'export': str(export_path),
        'package_id': expected_identity['package_id'],
        'active_run_id': expected_identity['active_run_id'],
        'source_sha256': expected_identity['source_sha256'],
        'checks': checks,
        'failure_count': len(failures),
        'failures': failures,
        'verified_at': utc_now(),
    }
    if write_report:
        write_json(acceptance_path, result)
    return result
