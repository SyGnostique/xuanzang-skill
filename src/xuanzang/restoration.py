from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import choose_ocr_adapter
from .contracts import PACKAGE_VERSION, PIPELINE_VERSION, RestoreRequest, RestoreResult, detect_source_format
from .extractors import ExtractionResult, extract_source
from .gates import evaluate_gates
from .utils import (
    append_jsonl,
    assert_expected_scope,
    ensure_dir,
    package_lock,
    read_json,
    sha256_file,
    sha256_path,
    sha256_text,
    utc_now,
    write_json,
    write_jsonl,
)


def _source_digest(source: Path, *, allow_external_sources: bool = False, depth: int = 0) -> str:
    if depth > 2:
        raise ValueError('nested source bundles exceed the maximum depth of 2')
    if source.is_file():
        if source.suffix.lower() in {'.json', '.yaml', '.yml'}:
            from .extractors import bundle_graph_digest
            return bundle_graph_digest(
                source, allow_external_sources=allow_external_sources, depth=depth,
            )
        return sha256_file(source)
    return sha256_path(source)


def _source_size(source: Path, *, allow_external_sources: bool = False, depth: int = 0) -> int:
    if depth > 2:
        raise ValueError('nested source bundles exceed the maximum depth of 2')
    if source.is_file():
        total = source.stat().st_size
        if source.suffix.lower() in {'.json', '.yaml', '.yml'}:
            from .extractors import _load_bundle_manifest
            payload = _load_bundle_manifest(source)
            base = source.parent.resolve()
            for entry in payload['sources']:
                child = Path(str(entry['locator'])).expanduser()
                child = (child if child.is_absolute() else base / child).resolve()
                if not allow_external_sources and child != base and base not in child.parents:
                    raise ValueError(f'bundle source escapes manifest directory: {entry["locator"]}')
                total += _source_size(
                    child, allow_external_sources=allow_external_sources, depth=depth + 1,
                )
        return total
    total = 0
    for member in source.rglob('*'):
        if member.is_symlink():
            raise ValueError(f'symlink sources are not supported: {member}')
        if member.is_file():
            total += member.stat().st_size
    return total


def _run_id(source_sha: str, policy_fingerprint: str, *, new_run: bool = False) -> str:
    base = f'r_{source_sha[:12]}_{policy_fingerprint[:12]}'
    if not new_run:
        return base
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    return f'{base}_{stamp}_{uuid.uuid4().hex[:8]}'


def _effective_policy_fingerprint(policy) -> str:
    fingerprint = policy.fingerprint
    if policy.sidecar:
        sidecar = Path(policy.sidecar).resolve()
        if sidecar.exists() and sidecar.is_file():
            fingerprint = sha256_text(f'{fingerprint}|sidecar:{sha256_file(sidecar)}')
    return fingerprint


def _source_locator(source: Path, privacy: str) -> str:
    return str(source.resolve()) if privacy == 'local_only' else source.name


def _sanitize_metadata(value: Any, privacy: str) -> Any:
    if privacy == 'local_only':
        return value
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if any(token in key_lower for token in ('path', 'locator', 'uri', 'sidecar')) and isinstance(item, str):
                out[key] = Path(item).name
            else:
                out[key] = _sanitize_metadata(item, privacy)
        return out
    if isinstance(value, list):
        return [_sanitize_metadata(item, privacy) for item in value]
    return value


def _resolve_document_kind(requested: str, source_format: str, surface_count: int) -> str:
    if requested != 'auto':
        return requested
    if source_format in {'epub', 'mobi_converted_to_epub'}:
        return 'book'
    if source_format == 'source_bundle':
        return 'book'
    if source_format in {'docx', 'markdown', 'text', 'html'}:
        return 'manuscript'
    if source_format in {'image', 'image_directory'}:
        return 'image_sequence'
    if source_format == 'pdf':
        return 'book' if surface_count >= 30 else 'paper'
    return 'archive'


def _paragraph_candidates(result: ExtractionResult) -> list[dict[str, Any]]:
    source_id = str(result.metadata.get('source_sha256', ''))
    evidence = {row['evidence_id']: row for row in result.evidence_blocks}
    page_order = {row['page_id']: int(row['ordinal']) for row in result.pages}
    blocks = sorted(
        result.canonical_blocks,
        key=lambda row: (page_order.get(row['page_id'], 0), evidence.get(row['evidence_id'], {}).get('ordinal', 0)),
    )
    paragraphs = []
    for block in blocks:
        ev = evidence.get(block['evidence_id'], {})
        spans = [{
            'block_id': block['block_id'], 'evidence_id': block['evidence_id'], 'page_id': block['page_id'],
            'bbox': block.get('bbox', []), 'start_offset': 0, 'end_offset': len(block.get('text', '')),
        }]
        pid = f"para_{sha256_text(json.dumps(spans, sort_keys=True))[:16]}"
        paragraphs.append({
            'source_id': source_id,
            'sourcepage_path': f'xuanzang://source/{source_id}/surface/{block["page_id"]}',
            'paragraph_id': pid,
            'order': len(paragraphs) + 1,
            'page_id': block['page_id'],
            'page_anchor': block['page_id'],
            'text': block['text'],
            'text_sha256': sha256_text(block['text']),
            'block_kind': block.get('block_kind'),
            'source_role': (ev.get('metadata') or {}).get('source_role', 'primary'),
            'source_spans': spans,
            'coverage_status': 'unreviewed',
            'paragraph_role': None,
            'semantic_summary': None,
            'claim_candidates': [],
            'method_candidates': [],
            'metric_candidates': [],
            'boundary_candidates': [],
            'reasoning_leap_candidates': [],
            'used_in_card': None,
            'use_reason': None,
            'exclusion_reason': None,
            'requires_primary_anchor': True,
            'producer': {'kind': 'mechanical_candidate', 'pipeline_version': PIPELINE_VERSION, 'engine': ev.get('engine')},
        })
    return paragraphs


def _toc_candidates(result: ExtractionResult, paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(result.toc_candidates)
    seen = {(str(row.get('text', '')).strip().lower(), row.get('page_id') or row.get('spine_index')) for row in rows}
    counts = Counter(p['text'].strip().lower() for p in paragraphs if p.get('block_kind') == 'heading_candidate')
    for p in paragraphs:
        if p.get('block_kind') != 'heading_candidate':
            continue
        text = p['text'].strip()
        key = (text.lower(), p['page_id'])
        if key in seen:
            continue
        repeated = counts[text.lower()] >= 3
        rows.append({
            'candidate_id': f"toc_{sha256_text(p['paragraph_id'])[:12]}",
            'text': text,
            'page_id': p['page_id'],
            'paragraph_id': p['paragraph_id'],
            'source': 'canonical_heading_candidate',
            'candidate_role': 'running_header_candidate' if repeated else 'body_heading_candidate',
            'status': 'needs_review',
            'confidence_signals': {'repeated_occurrences': counts[text.lower()]},
        })
        seen.add(key)
    return rows


def _complex_objects(result: ExtractionResult, source: Path | None = None) -> list[dict[str, Any]]:
    evidence = {row['evidence_id']: row for row in result.evidence_blocks}

    def source_metadata(ev: dict[str, Any]) -> dict[str, Any]:
        metadata = ev.get('metadata', {}) or {}
        derived = metadata.get('derived_from_evidence_id')
        if derived and str(derived) in evidence:
            return source_metadata(evidence[str(derived)])
        return metadata
    def bbox4(row: dict[str, Any]) -> list[float]:
        value = row.get('bbox')
        if isinstance(value, list) and len(value) == 4:
            return [float(item) for item in value]
        return [0.0, 0.0, 0.0, 0.0]

    objects: list[dict[str, Any]] = []
    table_groups: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    caption_groups: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    code_groups: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for block in result.canonical_blocks:
        kind = block.get('block_kind')
        ev = evidence.get(block.get('evidence_id'), {})
        metadata = ev.get('metadata', {}) or {}
        if metadata.get('pre_dom_path') is not None:
            identity = str(metadata.get('pre_dom_path'))
            code_groups.setdefault((str(block.get('page_id')), identity), []).append((block, ev))
        if kind not in {'table_candidate', 'equation_candidate', 'caption_candidate'}:
            continue
        if kind == 'table_candidate':
            identity = str(metadata.get('table_id') or metadata.get('table_dom_path') or block['block_id'])
            table_groups.setdefault((str(block.get('page_id')), identity), []).append((block, ev))
            continue
        if kind == 'caption_candidate':
            identity = str(metadata.get('figcaption_id') or metadata.get('figcaption_dom_path') or block['block_id'])
            caption_groups.setdefault((str(block.get('page_id')), identity), []).append((block, ev))
            continue
        representations = [
            {'kind': 'text', 'value': block.get('text', ''), 'metadata': metadata},
        ]
        if kind == 'equation_candidate' and metadata.get('mathml_xml'):
            representations.append({
                'kind': 'mathml',
                'value': metadata.get('mathml_xml'),
                'sha256': metadata.get('mathml_sha256'),
                'alttext': metadata.get('mathml_alttext'),
                'display': metadata.get('mathml_display'),
                'dom_path': metadata.get('mathml_dom_path'),
                'source_document': metadata.get('raw_xhtml'),
            })
        objects.append({
            'object_id': f"obj_{sha256_text(block['block_id'] + str(kind))[:16]}",
            'object_kind': kind.replace('_candidate', ''), 'page_id': block.get('page_id'),
            'source_block_ids': [block.get('block_id')], 'evidence_ids': [block.get('evidence_id')],
            'bbox': block.get('bbox', []), 'coordinate_space': block.get('coordinate_space'),
            'dom_path': metadata.get('mathml_dom_path'),
            'source_id': metadata.get('mathml_sha256'),
            'representations': representations,
            'relation_status': 'needs_review' if kind == 'caption_candidate' else 'not_applicable',
            'review_status': 'unreviewed',
        })

    for (page_id, identity), members in table_groups.items():
        first_meta = members[0][1].get('metadata', {}) or {}
        ordered = sorted(members, key=lambda item: int(item[1].get('ordinal', 0)))
        cells = [{
            'row': (ev.get('metadata') or {}).get('table_row_index'),
            'column': (ev.get('metadata') or {}).get('table_cell_index'),
            'tag': (ev.get('metadata') or {}).get('table_cell_tag'),
            'rowspan': (ev.get('metadata') or {}).get('rowspan'),
            'colspan': (ev.get('metadata') or {}).get('colspan'),
            'text': block.get('text', ''),
            'dom_container_text': (ev.get('metadata') or {}).get('dom_container_text'),
            'block_id': block.get('block_id'),
            'evidence_id': block.get('evidence_id'),
        } for block, ev in ordered]
        objects.append({
            'object_id': f"obj_{sha256_text('table|' + page_id + '|' + identity)[:16]}",
            'object_kind': 'table', 'page_id': page_id,
            'source_block_ids': [block['block_id'] for block, _ in ordered],
            'evidence_ids': [block['evidence_id'] for block, _ in ordered],
            'asset_occurrence_ids': [], 'bbox': [], 'coordinate_space': 'dom_path',
            'dom_path': first_meta.get('table_dom_path'), 'source_id': first_meta.get('table_id'),
            'caption': first_meta.get('table_caption'),
            'representations': [{'kind': 'table_cells', 'value': cells}],
            'relation_status': 'linked' if first_meta.get('table_caption') else 'not_present',
            'review_status': 'unreviewed',
        })

    caption_object_ids: dict[tuple[str, str], str] = {}
    caption_members_by_figure: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {}

    # PDF extractors do not have DOM figure identities.  Bind embedded images to
    # the nearest following caption on the same page using the retained PDF
    # coordinates.  The synthetic identity is deterministic and remains fully
    # auditable through the original asset/caption bboxes and evidence IDs.
    pdf_caption_identity: dict[tuple[str, str], str] = {}
    caption_geometry: dict[str, list[tuple[float, str]]] = {}
    for (page_id, identity), members in caption_groups.items():
        boxes = [block.get('bbox', []) for block, _ in members]
        tops = [float(box[1]) for box in boxes if isinstance(box, list) and len(box) == 4]
        if tops:
            synthetic = f'pdf_caption_{sha256_text(page_id + "|" + identity)[:16]}'
            pdf_caption_identity[(page_id, identity)] = synthetic
            caption_geometry.setdefault(page_id, []).append((min(tops), synthetic))
    for asset in result.assets:
        if asset.get('figure_id') or asset.get('figure_dom_path'):
            continue
        box = asset.get('bbox', [])
        if not isinstance(box, list) or len(box) != 4:
            continue
        page_id = str(asset.get('page_id'))
        asset_bottom = float(box[3])
        following = [
            (top - asset_bottom, identity)
            for top, identity in caption_geometry.get(page_id, [])
            if top >= asset_bottom - 12.0
        ]
        if following:
            distance, identity = min(following, key=lambda item: item[0])
            # A generous page-relative limit permits multi-panel figures while
            # preventing unrelated logos/ornaments from absorbing a caption.
            if distance <= 180.0:
                asset['figure_id'] = identity

    for (page_id, identity), members in caption_groups.items():
        ordered = sorted(members, key=lambda item: int(item[1].get('ordinal', 0)))
        first_meta = ordered[0][1].get('metadata', {}) or {}
        object_id = f"obj_{sha256_text('caption|' + page_id + '|' + identity)[:16]}"
        figure_identity = str(
            first_meta.get('figure_id') or first_meta.get('figure_dom_path')
            or pdf_caption_identity.get((page_id, identity)) or ''
        )
        caption_object_ids[(page_id, figure_identity)] = object_id
        caption_members_by_figure[(page_id, figure_identity)] = ordered
        objects.append({
            'object_id': object_id, 'object_kind': 'caption', 'page_id': page_id,
            'source_block_ids': [block['block_id'] for block, _ in ordered],
            'evidence_ids': [block['evidence_id'] for block, _ in ordered],
            'asset_occurrence_ids': [],
            'bbox': [
                min(bbox4(block)[0] for block, _ in ordered),
                min(bbox4(block)[1] for block, _ in ordered),
                max(bbox4(block)[2] for block, _ in ordered),
                max(bbox4(block)[3] for block, _ in ordered),
            ],
            'coordinate_space': ordered[0][0].get('coordinate_space') or 'dom_path',
            'dom_path': first_meta.get('figcaption_dom_path'),
            'representations': [{
                'kind': 'text',
                'value': ' '.join(block.get('text', '') for block, _ in ordered).strip(),
                'metadata': first_meta,
            }],
            'related_figure_identity': figure_identity,
            'relation_status': 'linked' if figure_identity else 'needs_review',
            'review_status': 'unreviewed',
        })

    for (page_id, identity), members in code_groups.items():
        ordered = sorted(members, key=lambda item: int(item[1].get('ordinal', 0)))
        first_meta = ordered[0][1].get('metadata', {}) or {}
        pre_path = tuple(first_meta.get('pre_dom_path') or ())
        callout_occurrences = [
            asset.get('occurrence_id') for asset in result.assets
            if str(asset.get('page_id')) == page_id
            and asset.get('callout_role') == 'code_callout'
            and tuple(asset.get('dom_path') or ())[:len(pre_path)] == pre_path
        ]
        code_text = str(first_meta.get('pre_text') or '')
        code_xml = str(first_meta.get('pre_xml') or '')
        objects.append({
            'object_id': f"obj_{sha256_text('code|' + page_id + '|' + identity)[:16]}",
            'object_kind': 'code',
            'page_id': page_id,
            'source_block_ids': [str(block.get('block_id')) for block, _ in ordered],
            'evidence_ids': [str(block.get('evidence_id')) for block, _ in ordered],
            'asset_occurrence_ids': callout_occurrences,
            'bbox': [],
            'coordinate_space': 'dom_path',
            'dom_path': list(pre_path),
            'source_id': first_meta.get('pre_text_sha256'),
            'caption_object_id': None,
            'representations': [
                {
                    'kind': 'code_text', 'value': code_text,
                    'sha256': first_meta.get('pre_text_sha256'),
                    'language': first_meta.get('code_language'),
                },
                {
                    'kind': 'source_xml', 'value': code_xml,
                    'sha256': first_meta.get('pre_xml_sha256'),
                    'dom_path': list(pre_path),
                    'source_document': first_meta.get('raw_xhtml'),
                },
            ],
            'relation_status': 'linked' if callout_occurrences else 'not_present',
            'review_status': 'unreviewed',
        })

    callout_blocks: dict[tuple[str, tuple[int, ...]], dict[str, Any]] = {}
    for block in result.canonical_blocks:
        ev = evidence.get(block.get('evidence_id'), {})
        metadata = ev.get('metadata', {}) or {}
        if metadata.get('source_role') == 'code_callout':
            callout_blocks[(
                str(block.get('page_id')),
                tuple(metadata.get('callout_dom_path') or metadata.get('dom_path') or ()),
            )] = block
    for asset in result.assets:
        if asset.get('callout_role') != 'code_callout':
            continue
        page_id = str(asset.get('page_id'))
        block = callout_blocks.get((page_id, tuple(asset.get('dom_path') or ())))
        source_block_ids = [str(block.get('block_id'))] if block else []
        evidence_ids = [str(block.get('evidence_id'))] if block else []
        target = str(asset.get('callout_target') or '')
        objects.append({
            'object_id': f"obj_{sha256_text('callout|' + page_id + '|' + str(asset.get('occurrence_id')))[:16]}",
            'object_kind': 'callout',
            'page_id': page_id,
            'source_block_ids': source_block_ids,
            'evidence_ids': evidence_ids,
            'asset_occurrence_ids': [asset.get('occurrence_id')],
            'bbox': bbox4(asset),
            'coordinate_space': asset.get('coordinate_space') or 'dom_path',
            'dom_path': asset.get('dom_path'),
            'source_id': asset.get('callout_anchor_id') or asset.get('occurrence_id'),
            'caption_object_id': None,
            'representations': [
                {
                    'kind': 'asset', 'value': asset.get('asset_path'),
                    'sha256': asset.get('asset_sha256'),
                    'occurrence_id': asset.get('occurrence_id'),
                    'alt_text': asset.get('alt_text'),
                },
                {
                    'kind': 'callout_link', 'value': target,
                    'anchor_id': asset.get('callout_anchor_id'),
                    'dom_path': asset.get('dom_path'),
                },
            ],
            'relation_status': 'linked' if target and block else 'needs_review',
            'review_status': 'unreviewed',
        })

    figure_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for asset in result.assets:
        if asset.get('callout_role') == 'code_callout':
            continue
        identity = str(asset.get('figure_id') or asset.get('figure_dom_path') or asset.get('occurrence_id'))
        figure_groups.setdefault((str(asset.get('page_id')), identity), []).append(asset)
    for (page_id, identity), group_assets in figure_groups.items():
        caption_members = caption_members_by_figure.get((page_id, identity), [])
        caption_blocks = [block for block, _ in caption_members]
        caption_evidence = [block.get('evidence_id') for block in caption_blocks]
        label_blocks = []
        for asset in group_assets:
            for row in asset.get('vector_label_blocks', []):
                if isinstance(row, dict) and row.get('block_id') and row.get('evidence_id'):
                    label_blocks.append(dict(row))
        label_blocks = list({str(row['block_id']): row for row in label_blocks}.values())
        representations = [{
            'kind': 'asset', 'value': asset.get('asset_path'), 'sha256': asset.get('asset_sha256'),
            'occurrence_id': asset.get('occurrence_id'), 'alt_text': asset.get('alt_text'),
        } for asset in group_assets]
        if label_blocks:
            representations.append({
                'kind': 'figure_labels',
                'value': [{
                    'text': row.get('text', ''),
                    'bbox': row.get('bbox', []),
                    'block_id': row.get('block_id'),
                    'evidence_id': row.get('evidence_id'),
                } for row in label_blocks],
                'coordinate_space': 'pdf_points',
                'publication_role': 'figure_internal_not_body_prose',
            })
        captions = [str(asset.get('caption_text')) for asset in group_assets if asset.get('caption_text')]
        if captions:
            representations.append({'kind': 'caption_text', 'value': captions[0]})
        caption_object_id = caption_object_ids.get((page_id, identity))
        occurrence_ids = [asset.get('occurrence_id') for asset in group_assets]
        objects.append({
            'object_id': f"obj_{sha256_text('figure|' + page_id + '|' + identity)[:16]}",
            'object_kind': 'figure', 'page_id': page_id,
            'source_block_ids': list(dict.fromkeys([
                *[block['block_id'] for block in caption_blocks],
                *[str(row['block_id']) for row in label_blocks],
            ])),
            'evidence_ids': list(dict.fromkeys([
                *caption_evidence,
                *[str(row['evidence_id']) for row in label_blocks],
            ])),
            'asset_occurrence_ids': occurrence_ids,
            'bbox': [
                min(bbox4(asset)[0] for asset in group_assets),
                min(bbox4(asset)[1] for asset in group_assets),
                max(bbox4(asset)[2] for asset in group_assets),
                max(bbox4(asset)[3] for asset in group_assets),
            ],
            'coordinate_space': group_assets[0].get('coordinate_space') or 'dom_path',
            'dom_path': group_assets[0].get('figure_dom_path') or group_assets[0].get('dom_path'),
            'source_id': group_assets[0].get('figure_id'),
            'caption_object_id': caption_object_id,
            'representations': representations,
            'relation_status': 'linked' if caption_blocks or any(asset.get('alt_text') for asset in group_assets) else 'not_present',
            'review_status': 'unreviewed',
        })
        if caption_object_id:
            caption_object = next(
                (row for row in objects if row.get('object_id') == caption_object_id), None,
            )
            if caption_object is not None:
                caption_object['asset_occurrence_ids'] = occurrence_ids

    index_start = min(
        (
            int(row['source_page']) for row in result.toc_candidates
            if str(row.get('text') or '').strip().casefold() == 'index' and row.get('source_page')
        ),
        default=None,
    )
    if result.source_format == 'pdf' and index_start is not None:
        index_members = [
            (block, evidence.get(block.get('evidence_id'), {}))
            for block in result.canonical_blocks
            if int(str(block.get('page_id') or 'page_0').split('_')[-1]) >= index_start
        ]
        pages: list[dict[str, Any]] = []
        for page_id in sorted({str(block.get('page_id')) for block, _ in index_members}):
            members = [(block, ev) for block, ev in index_members if str(block.get('page_id')) == page_id]
            columns = []
            for region in ('left', 'right'):
                selected = [
                    (block, ev) for block, ev in members
                    if source_metadata(ev).get('column_region') == region
                ]
                if not selected:
                    continue
                boxes = [block.get('bbox', []) for block, _ in selected]
                columns.append({
                    'column_index': 0 if region == 'left' else 1,
                    'region': region,
                    'bbox': [
                        min(float(box[0]) for box in boxes), min(float(box[1]) for box in boxes),
                        max(float(box[2]) for box in boxes), max(float(box[3]) for box in boxes),
                    ],
                    'source_block_ids': [block['block_id'] for block, _ in selected],
                    'evidence_ids': [block['evidence_id'] for block, _ in selected],
                    'text': '\n'.join(block.get('text', '') for block, _ in selected),
                })
            pages.append({
                'page_id': page_id,
                'source_page': int(page_id.split('_')[-1]),
                'reading_order': 'left_column_then_right_column',
                'columns': columns,
            })
        source_blocks = [block['block_id'] for block, _ in index_members]
        source_evidence = [block['evidence_id'] for block, _ in index_members]
        objects.append({
            'object_id': f"obj_{sha256_text('pdf-index|' + str(index_start) + '|' + '|'.join(source_blocks))[:16]}",
            'object_kind': 'index',
            'page_id': f'page_{index_start:04d}',
            'page_ids': [page['page_id'] for page in pages],
            'source_block_ids': source_blocks,
            'evidence_ids': source_evidence,
            'asset_occurrence_ids': [],
            'bbox': [],
            'coordinate_space': 'pdf_points',
            'representations': [{
                'kind': 'index_columns',
                'value': pages,
                'metadata': {
                    'serialization': 'page_order_then_left_column_then_right_column',
                    'entry_continuations_preserved': True,
                },
            }],
            'relation_status': 'linked',
            'review_status': 'unreviewed',
        })

    # PDF link annotations are first-class reversible objects.  Visible URL
    # glyphs alone do not preserve an annotation's rectangle, destination, or
    # internal navigation target, and a link-rich TOC/index can otherwise look
    # complete while silently losing its interaction layer.
    if result.source_format == 'pdf' and source is not None and source.is_file():
        try:
            import fitz  # type: ignore

            link_kind_names = {
                int(fitz.LINK_NONE): 'none',
                int(fitz.LINK_GOTO): 'internal_goto',
                int(fitz.LINK_URI): 'external_uri',
                int(fitz.LINK_LAUNCH): 'launch',
                int(fitz.LINK_NAMED): 'named',
                int(fitz.LINK_GOTOR): 'remote_goto',
            }
            with fitz.open(source) as document:
                canonical_by_page: dict[str, list[dict[str, Any]]] = {}
                for block in result.canonical_blocks:
                    canonical_by_page.setdefault(str(block.get('page_id')), []).append(block)
                for page_index, page in enumerate(document):
                    page_id = f'page_{page_index + 1:04d}'
                    for link_index, link in enumerate(page.get_links(), 1):
                        rect_value = link.get('from')
                        rect = [float(value) for value in rect_value] if rect_value is not None else []
                        kind_number = int(link.get('kind', fitz.LINK_NONE))
                        destination_index = link.get('page')
                        destination_page_id = None
                        if isinstance(destination_index, int) and destination_index >= 0:
                            destination_page_id = f'page_{destination_index + 1:04d}'
                        uri = link.get('uri')
                        filename = link.get('file')
                        named_target = (
                            link.get('name') or link.get('nameddest')
                            or (str(destination_index) if isinstance(destination_index, str) else None)
                        )
                        xref = int(link.get('xref') or 0)
                        reversible_locator = {
                            'source_page': page_index + 1,
                            'annotation_index': link_index,
                            'xref': xref,
                            'bbox': rect,
                            'coordinate_space': 'pdf_points',
                        }
                        target = {
                            'link_type': link_kind_names.get(kind_number, f'kind_{kind_number}'),
                            'kind_number': kind_number,
                            'uri': uri,
                            'destination_page_id': destination_page_id,
                            'destination_page_index': destination_index,
                            'destination_point': (
                                [float(value) for value in link['to']]
                                if link.get('to') is not None else None
                            ),
                            'named_target': named_target,
                            'external_file': filename,
                            'zoom': link.get('zoom'),
                        }
                        identity = json.dumps(
                            {'locator': reversible_locator, 'target': target},
                            ensure_ascii=False, sort_keys=True, default=str,
                        )
                        overlapping_blocks = []
                        if len(rect) == 4:
                            x0, y0, x1, y1 = rect
                            for block in canonical_by_page.get(page_id, []):
                                block_rect = block.get('bbox', [])
                                if not isinstance(block_rect, list) or len(block_rect) != 4:
                                    continue
                                bx0, by0, bx1, by1 = [float(value) for value in block_rect]
                                if min(x1, bx1) > max(x0, bx0) and min(y1, by1) > max(y0, by0):
                                    overlapping_blocks.append(block)
                        objects.append({
                            'object_id': f"obj_{sha256_text('pdf-link|' + identity)[:16]}",
                            'object_kind': 'link',
                            'page_id': page_id,
                            'source_block_ids': [block['block_id'] for block in overlapping_blocks],
                            'evidence_ids': [block['evidence_id'] for block in overlapping_blocks],
                            'asset_occurrence_ids': [],
                            'bbox': rect,
                            'coordinate_space': 'pdf_points',
                            'source_locator': reversible_locator,
                            'representations': [{
                                'kind': 'pdf_link_annotation',
                                'value': target,
                                'metadata': reversible_locator,
                            }],
                            'relation_status': 'linked',
                            'review_status': 'unreviewed',
                        })
        except Exception as exc:
            # Extraction must remain usable when the optional PDF backend is
            # unavailable; the missing annotation layer is exposed as a typed
            # object rather than silently discarded.
            objects.append({
                'object_id': f"obj_{sha256_text('pdf-link-extraction-failure|' + type(exc).__name__)[:16]}",
                'object_kind': 'link_extraction_failure',
                'page_id': None,
                'source_block_ids': [],
                'evidence_ids': [],
                'asset_occurrence_ids': [],
                'bbox': [],
                'coordinate_space': 'pdf_points',
                'representations': [{
                    'kind': 'error',
                    'value': {'type': type(exc).__name__, 'message': str(exc)},
                }],
                'relation_status': 'needs_review',
                'review_status': 'unreviewed',
            })
    return objects


def _write_run(
    run_work: Path, source: Path, source_sha: str, run_id: str, request: RestoreRequest,
    result: ExtractionResult, *, policy_fingerprint: str | None = None,
) -> None:
    ensure_dir(run_work / 'ledger')
    ensure_dir(run_work / 'audit')
    ensure_dir(run_work / 'toc')
    paragraphs = _paragraph_candidates(result)
    toc_candidates = _toc_candidates(result, paragraphs)
    surface_kind = {
        'pdf': 'pdf_page', 'image': 'image_page', 'image_directory': 'image_page',
        'epub': 'epub_spine_item', 'docx': 'docx_story', 'text': 'legacy_text',
        'markdown': 'legacy_text', 'html': 'html_document', 'mobi_converted_to_epub': 'epub_spine_item',
    }.get(result.source_format, 'document_surface')
    surfaces = []
    for row in result.pages:
        surface = dict(row)
        image_path = surface.get('page_image_path')
        if image_path and not Path(str(image_path)).is_absolute() and not str(image_path).startswith('runs/'):
            surface['page_image_path'] = f'runs/{run_id}/{image_path}'
        original_path = surface.get('original_image_path')
        if original_path and not Path(str(original_path)).is_absolute() and not str(original_path).startswith('runs/'):
            surface['original_image_path'] = f'runs/{run_id}/{original_path}'
        surface.setdefault('surface_id', surface.get('page_id'))
        surface.setdefault('surface_kind', surface_kind)
        surfaces.append(surface)
    result.pages = surfaces
    for evidence in result.evidence_blocks:
        metadata = evidence.get('metadata')
        raw_xhtml = metadata.get('raw_xhtml') if isinstance(metadata, dict) else None
        if raw_xhtml and not Path(str(raw_xhtml)).is_absolute() and not str(raw_xhtml).startswith('runs/'):
            metadata['raw_xhtml'] = f'runs/{run_id}/{raw_xhtml}'
    for asset in result.assets:
        asset_path = asset.get('asset_path')
        if asset_path and not Path(str(asset_path)).is_absolute() and not str(asset_path).startswith('runs/'):
            asset['asset_path'] = f'runs/{run_id}/{asset_path}'
    objects = _complex_objects(result, source)
    write_jsonl(run_work / 'ledger' / 'surfaces.jsonl', surfaces)
    # Compatibility projection for v1 callers and paginated tooling.
    write_jsonl(run_work / 'ledger' / 'pages.jsonl', surfaces)
    write_jsonl(run_work / 'ledger' / 'evidence_blocks.jsonl', result.evidence_blocks)
    write_jsonl(run_work / 'ledger' / 'canonical_blocks.jsonl', result.canonical_blocks)
    write_jsonl(run_work / 'ledger' / 'paragraph_candidates.jsonl', paragraphs)
    write_jsonl(run_work / 'ledger' / 'assets.jsonl', result.assets)
    write_jsonl(run_work / 'ledger' / 'objects.jsonl', objects)
    # v1 read-only projections keep one-major-version CLI compatibility. They are
    # derived artifacts and never become trust evidence by themselves.
    evidence_by_id = {row['evidence_id']: row for row in result.evidence_blocks}
    page_by_id = {row['page_id']: row for row in surfaces}
    legacy_blocks = []
    for block in result.canonical_blocks:
        ev = evidence_by_id.get(block['evidence_id'], {})
        surface = page_by_id.get(block['page_id'], {})
        legacy_blocks.append({
            'block_id': block['block_id'], 'page': surface.get('source_page'),
            'spine_index': surface.get('spine_index'), 'text': block['text'],
            'normalized_text': ' '.join(block['text'].split()), 'bbox': block.get('bbox', []),
            'block_kind': block.get('block_kind'), 'source_type': ev.get('engine'),
            'ocr_engine': ev.get('engine') if ev.get('engine') not in {'pdf_native', 'epub_dom', 'docx_xml'} else None,
            'ocr_confidence': ev.get('confidence'), 'evidence_id': ev.get('evidence_id'),
            'v2_projection': True,
        })
    write_jsonl(run_work / 'ledger' / 'source_blocks.jsonl', legacy_blocks)
    write_jsonl(run_work / 'ledger' / 'image_blocks.jsonl', [
        {**asset, 'image_id': asset.get('asset_id'), 'marker': f"[[IMAGE {asset.get('occurrence_id')}]]"}
        for asset in result.assets
    ])
    write_json(run_work / 'toc' / 'toc_candidates.json', {'status': 'evidence_only', 'candidates': toc_candidates})
    write_json(run_work / 'toc' / 'canonical_toc.json', {'status': 'needs_review', 'items': [], 'source_candidates': len(toc_candidates)})
    extraction_audit = {
        'status': 'PASS_HINT' if result.pages and result.evidence_blocks and not result.blockers else 'FAIL_REVIEW',
        'source_format': result.source_format,
        'page_count': len(result.pages),
        'evidence_block_count': len(result.evidence_blocks),
        'canonical_block_count': len(result.canonical_blocks),
        'asset_occurrence_count': len(result.assets),
        'hard_blockers': result.blockers,
        'page_statuses': dict(Counter(p.get('status') for p in result.pages)),
    }
    write_json(run_work / 'audit' / 'extraction_audit.json', extraction_audit)
    write_json(run_work / 'audit' / 'source_integrity.json', {
        'status': 'PASS' if result.pages and result.evidence_blocks and not result.blockers else 'FAIL_REVIEW',
        'format': result.source_format, 'pages': len(result.pages),
        'text_blocks': len(result.canonical_blocks), 'image_blocks': len(result.assets),
        'hard_blockers': result.blockers, 'v2_projection': True,
    })
    ocr_evidence = [row for row in result.evidence_blocks if row.get('engine') not in {'pdf_native', 'epub_dom', 'docx_xml', 'text_native', 'markdown_native', 'html_native'}]
    write_json(run_work / 'audit' / 'ocr_audit.json', {
        'status': 'PASS' if not any(b.get('kind') in {'ocr_failure', 'ocr_required_but_unavailable'} for b in result.blockers) else 'FAIL_REVIEW',
        'language': request.policy.lang, 'block_count': len(ocr_evidence),
        'engine_counts': dict(Counter(row.get('engine') for row in ocr_evidence)),
        'hard_blockers': [b for b in result.blockers if b.get('kind', '').startswith('ocr_')],
        'v2_projection': True,
    })
    write_json(run_work / 'source_inventory.json', {
        'path': _source_locator(source, request.policy.privacy),
        'sha256': source_sha,
        'format': result.source_format,
        'metadata': _sanitize_metadata(result.metadata, request.policy.privacy),
    })
    required_artifacts = [
        'ledger/surfaces.jsonl', 'ledger/evidence_blocks.jsonl',
        'ledger/canonical_blocks.jsonl', 'ledger/paragraph_candidates.jsonl',
        'ledger/assets.jsonl', 'toc/toc_candidates.json', 'source_inventory.json',
        'ledger/objects.jsonl', 'audit/extraction_audit.json',
    ]
    artifact_digests = {}
    for artifact in sorted(path for path in run_work.rglob('*') if path.is_file()):
        rel = artifact.relative_to(run_work).as_posix()
        if rel in {'run_manifest.json', 'failure.json'}:
            continue
        artifact_digests[rel] = sha256_file(artifact)
    missing_required = [rel for rel in required_artifacts if rel not in artifact_digests]
    if missing_required:
        raise RuntimeError(f'run materialization missing required artifacts: {missing_required}')
    artifact_root_sha256 = sha256_text('\n'.join(
        f'{rel}:{digest}' for rel, digest in sorted(artifact_digests.items())
    ))
    external_input_digests = {}
    if request.policy.sidecar:
        sidecar = Path(request.policy.sidecar).resolve()
        if sidecar.is_file():
            external_input_digests['ocr_sidecar'] = {
                'sha256': sha256_file(sidecar),
                'locator': _source_locator(sidecar, request.policy.privacy),
            }
    write_json(run_work / 'run_manifest.json', {
        'run_id': run_id,
        'schema_version': PACKAGE_VERSION,
        'pipeline_version': PIPELINE_VERSION,
        'source_sha256': source_sha,
        'policy': _sanitize_metadata(asdict(request.policy), request.policy.privacy),
        'policy_fingerprint': policy_fingerprint or request.policy.fingerprint,
        'status': 'materialized',
        'created_at': utc_now(),
        'artifact_digests': artifact_digests,
        'required_artifacts': required_artifacts,
        'artifact_root_sha256': artifact_root_sha256,
        'external_input_digests': external_input_digests,
    })


def _project_active_run(package: Path, run_dir: Path, *, preserve_review_state: bool = True) -> None:
    for name in ('ledger', 'audit', 'toc'):
        source = run_dir / name
        target = package / name
        preserved: dict[str, bytes] = {}
        if name == 'ledger':
            filenames = ['review_decisions.jsonl']
            if preserve_review_state:
                filenames += ['paragraph_coverage.jsonl', 'canonical_reviewed.jsonl', 'paragraph_candidates_reviewed.jsonl']
            for filename in filenames:
                path = target / filename
                if path.exists():
                    preserved[filename] = path.read_bytes()
        elif name == 'toc' and preserve_review_state:
            canonical = target / 'canonical_toc.json'
            boundaries = target / 'chapter_boundary_map.json'
            if canonical.exists():
                try:
                    if read_json(canonical).get('status') == 'reviewed':
                        preserved[canonical.name] = canonical.read_bytes()
                        if boundaries.exists():
                            preserved[boundaries.name] = boundaries.read_bytes()
                except Exception:
                    pass
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        for filename, data in preserved.items():
            (target / filename).write_bytes(data)


def _build_head_manifest(
    package: Path,
    existing: dict[str, Any] | None,
    request: RestoreRequest,
    source: Path,
    source_sha: str,
    run_id: str,
    run_dir: Path,
    *,
    source_format: str,
    metadata: dict[str, Any],
    preserve_review_state: bool,
) -> dict[str, Any]:
    privacy = request.policy.privacy
    source_revisions = _sanitize_metadata(
        list((existing or {}).get('source_revisions', [])), privacy,
    )
    prior_source = _sanitize_metadata((existing or {}).get('source'), privacy)
    if prior_source and prior_source not in source_revisions:
        source_revisions.append(prior_source)
    current_source = {
        'path': _source_locator(source, privacy), 'sha256': source_sha, 'format': source_format,
    }
    if current_source not in source_revisions:
        source_revisions.append(current_source)
    raw_revision = sha256_file(run_dir / 'ledger' / 'canonical_blocks.jsonl')[:20]
    canonical_revision = (
        (existing or {}).get('canonical_revision', raw_revision)
        if preserve_review_state else raw_revision
    )
    manifest = {
        'package_version': PACKAGE_VERSION,
        'pipeline_version': PIPELINE_VERSION,
        'package_id': (existing or {}).get('package_id') or f'pkg_{source_sha[:20]}',
        'source': current_source,
        'source_revisions': source_revisions,
        'scope': {
            'privacy': privacy, 'tenant_id': request.policy.tenant_id,
            'workspace_id': request.policy.workspace_id, 'rights_basis': request.policy.rights_basis,
            'retention_policy': request.policy.retention_policy,
            'access_tags': list(request.policy.access_tags),
        },
        'profile': {
            **_sanitize_metadata(asdict(request.policy), privacy),
            'resolved_document_kind': metadata.get('resolved_document_kind'),
        },
        'active_run_id': run_id,
        'active_run_manifest_sha256': sha256_file(run_dir / 'run_manifest.json'),
        'runs': sorted({
            *((existing or {}).get('runs', [])),
            *(p.name for p in (package / 'runs').iterdir() if p.is_dir() and not p.name.endswith('.failed')),
        }),
        'trust_status': 'needs_review',
        'canonical_revision': canonical_revision,
        'review_revision': (
            (existing or {}).get('review_revision', '0') if preserve_review_state else '0'
        ),
        'lifecycle': (existing or {}).get('lifecycle', {'state': 'active'}),
        'updated_at': utc_now(),
    }
    if preserve_review_state:
        for field in (
            'paragraph_projection_sha256', 'toc_projection_sha256',
            'boundary_projection_sha256', 'structure_review_decision_id',
        ):
            if (existing or {}).get(field):
                manifest[field] = existing[field]
    return manifest


def _restore_source_locked(request: RestoreRequest) -> RestoreResult:
    request.policy.validate()
    source = request.source.resolve()
    package = request.out.resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_dir() and (package == source or source in package.parents):
        raise ValueError('package output must not be inside a source directory')
    source_bytes = _source_size(
        source, allow_external_sources=request.policy.allow_external_sources,
    )
    if source_bytes > request.policy.max_source_bytes:
        raise ValueError(
            f'source graph exceeds max_source_bytes: {source_bytes} > {request.policy.max_source_bytes}'
        )
    source_sha = _source_digest(source, allow_external_sources=request.policy.allow_external_sources)
    policy_fingerprint = _effective_policy_fingerprint(request.policy)
    run_id = _run_id(source_sha, policy_fingerprint, new_run=request.new_run)
    run_dir = package / 'runs' / run_id
    existing_manifest = package / 'package_manifest.json'
    existing: dict[str, Any] | None = None
    if existing_manifest.exists():
        existing = read_json(existing_manifest)
        if existing.get('lifecycle', {}).get('state', 'active') != 'active':
            raise ValueError('package is revoked; restore into a new package identity')
        existing_sha = existing.get('source', {}).get('sha256')
        if existing_sha and existing_sha != source_sha and not request.accept_source_update:
            raise ValueError('source bytes changed; rerun with --accept-source-update to create a new source revision')
    else:
        allowed_partial = {'.xuanzang.lock', '.staging', 'runs', 'history'}
        unexpected = sorted(
            path.name for path in package.iterdir()
            if path.name not in allowed_partial and not path.name.startswith('.xuanzang.lock.stale.')
        )
        if unexpected:
            raise ValueError(f'refusing to initialize a package in a non-empty directory: {unexpected}')
    if run_dir.exists() and (run_dir / 'run_manifest.json').exists() and not request.new_run:
        same_head = bool(existing and existing.get('active_run_id') == run_id)
        inventory = read_json(run_dir / 'source_inventory.json')
        metadata = inventory.get('metadata', {})
        manifest = _build_head_manifest(
            package, existing, request, source, source_sha, run_id, run_dir,
            source_format=inventory.get('format', detect_source_format(source)),
            metadata=metadata,
            preserve_review_state=same_head,
        )
        _project_active_run(package, run_dir, preserve_review_state=same_head)
        if not (package / 'ledger' / 'review_decisions.jsonl').exists():
            (package / 'ledger' / 'review_decisions.jsonl').touch()
        if not same_head:
            from .review import rehydrate_review_head
            manifest = rehydrate_review_head(package, manifest)
        manifest['review_ledger_sha256'] = sha256_file(package / 'ledger' / 'review_decisions.jsonl')
        write_json(package / 'package_manifest.json', manifest)
        ensure_dir(package / 'source')
        write_json(package / 'source' / 'source_inventory.json', {
            'source_path': _source_locator(source, request.policy.privacy), 'source_sha256': source_sha,
            'format': inventory.get('format'),
            'metadata': _sanitize_metadata(metadata, request.policy.privacy), 'active_run_id': run_id,
        })
        append_jsonl(package / 'history' / 'events.jsonl', {
            'event': 'restore_reused' if same_head else 'head_switched', 'run_id': run_id,
            'source_sha256': source_sha, 'at': utc_now(),
        })
        gate = evaluate_gates(package, target=request.policy.target)
        manifest['trust_status'] = gate['trust_status']
        write_json(package / 'package_manifest.json', manifest)
        return RestoreResult(package, run_id, gate['trust_status'], gate['public_status'], gate['status'], reused=True)

    ensure_dir(package / 'runs')
    ensure_dir(package / 'history')
    staging_root = ensure_dir(package / '.staging')
    failed_dir = package / 'runs' / f'{run_id}.failed'
    if request.resume and failed_dir.exists():
        work = failed_dir
        failure_marker = work / 'failure.json'
        if failure_marker.exists():
            failure_marker.unlink()
    else:
        work = Path(tempfile.mkdtemp(prefix=f'{run_id}.', dir=str(staging_root)))
    try:
        ocr = choose_ocr_adapter(request.policy.ocr, request.policy.sidecar)
        result = extract_source(source, work, request.policy, ocr)
        source_sha_after = _source_digest(
            source, allow_external_sources=request.policy.allow_external_sources,
        )
        if source_sha_after != source_sha:
            raise RuntimeError('source_changed_during_restore; retry from a stable source snapshot')
        if request.policy.sidecar:
            sidecar = Path(request.policy.sidecar).resolve()
            if not sidecar.is_file() or _effective_policy_fingerprint(request.policy) != policy_fingerprint:
                raise RuntimeError('sidecar_changed_during_restore; retry from a stable sidecar snapshot')
        if result.metadata.get('source_sha256') != source_sha:
            result.metadata['extractor_source_sha256'] = result.metadata.get('source_sha256')
            result.metadata['source_sha256'] = source_sha
        result.metadata['resolved_document_kind'] = _resolve_document_kind(request.policy.document_kind, result.source_format, len(result.pages))
        if request.policy.preserve_source and source.is_file():
            preserved = ensure_dir(work / 'source') / source.name
            shutil.copy2(source, preserved)
        _write_run(work, source, source_sha, run_id, request, result, policy_fingerprint=policy_fingerprint)
        os.replace(work, run_dir)
    except Exception:
        failure = {
            'run_id': run_id,
            'source_sha256': source_sha,
            'status': 'failed_retryable',
            'failed_at': utc_now(),
        }
        write_json(work / 'failure.json', failure)
        if work != failed_dir:
            if failed_dir.exists():
                shutil.rmtree(failed_dir)
            os.replace(work, failed_dir)
        append_jsonl(package / 'history' / 'events.jsonl', {'event': 'restore_failed', **failure})
        raise

    manifest = _build_head_manifest(
        package, existing, request, source, source_sha, run_id, run_dir,
        source_format=result.source_format, metadata=result.metadata, preserve_review_state=False,
    )
    _project_active_run(package, run_dir, preserve_review_state=False)
    if not (package / 'ledger' / 'review_decisions.jsonl').exists():
        (package / 'ledger' / 'review_decisions.jsonl').touch()
    manifest['review_ledger_sha256'] = sha256_file(package / 'ledger' / 'review_decisions.jsonl')
    write_json(package / 'package_manifest.json', manifest)
    ensure_dir(package / 'source')
    write_json(package / 'source' / 'source_inventory.json', {
        'source_path': _source_locator(source, request.policy.privacy), 'source_sha256': source_sha,
        'format': result.source_format, 'metadata': _sanitize_metadata(result.metadata, request.policy.privacy),
        'active_run_id': run_id,
    })
    append_jsonl(package / 'history' / 'events.jsonl', {
        'event': 'restore_committed', 'run_id': run_id, 'source_sha256': source_sha,
        'policy_fingerprint': policy_fingerprint, 'at': utc_now(),
    })
    gate = evaluate_gates(package, target=request.policy.target)
    manifest['trust_status'] = gate['trust_status']
    write_json(package / 'package_manifest.json', manifest)
    return RestoreResult(package, run_id, gate['trust_status'], gate['public_status'], gate['status'])


def restore_source(request: RestoreRequest) -> RestoreResult:
    source = request.source.resolve()
    package = request.out.resolve()
    if source.is_dir() and (package == source or source in package.parents):
        raise ValueError('package output must not be inside a source directory')
    with package_lock(package):
        return _restore_source_locked(request)


def _package_status_locked(
    package: Path, *, expected_tenant_id: str | None = None,
    expected_workspace_id: str | None = None, target: str = 'citation',
) -> dict[str, Any]:
    manifest = read_json(package / 'package_manifest.json')
    assert_expected_scope(
        manifest, expected_tenant_id=expected_tenant_id,
        expected_workspace_id=expected_workspace_id,
    )
    gate = evaluate_gates(package, target=target)
    return {
        'package_id': manifest.get('package_id'),
        'package_version': manifest.get('package_version'),
        'active_run_id': manifest.get('active_run_id'),
        'source_sha256': manifest.get('source', {}).get('sha256'),
        'review_revision': manifest.get('review_revision', '0'),
        'lifecycle': manifest.get('lifecycle', {'state': 'active'}),
        'scope': manifest.get('scope', {}),
        'evaluated_target': target,
        'trust_status': gate.get('trust_status'),
        'gate_status': gate.get('public_status'),
        'evaluation_status': gate.get('status'),
        'hard_blocker_count': len(gate.get('hard_blockers', [])),
        'counts': gate.get('counts', {}),
    }


def package_status(
    package: Path, *, expected_tenant_id: str | None = None,
    expected_workspace_id: str | None = None, target: str = 'citation',
) -> dict[str, Any]:
    package = package.resolve()
    with package_lock(package):
        return _package_status_locked(
            package, expected_tenant_id=expected_tenant_id,
            expected_workspace_id=expected_workspace_id, target=target,
        )
