from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import ReviewerContext
from .gates import RESOLUTION_METHODS, evaluate_gates
from .utils import (
    append_jsonl,
    assert_expected_scope,
    package_lock,
    read_json,
    read_jsonl,
    sha256_file,
    sha256_text,
    utc_now,
    write_json,
    write_jsonl,
)

ALLOWED_KINDS = {'page', 'surface', 'paragraph', 'asset', 'object', 'structure', 'source_boundary', 'canonical_block'}
ALLOWED_DISPOSITIONS = {
    'reviewed', 'blank_confirmed', 'quarantined',
    'used', 'excluded', 'reference_only',
    'selected', 'rejected',
}


def _load_decisions(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding='utf-8')
    if path.suffix.lower() == '.json':
        payload = json.loads(text)
        return payload if isinstance(payload, list) else payload.get('decisions', [])
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _targets(package: Path) -> dict[str, set[str]]:
    pages = read_jsonl(package / 'ledger' / 'surfaces.jsonl') or read_jsonl(package / 'ledger' / 'pages.jsonl')
    paragraphs = read_jsonl(package / 'ledger' / 'paragraph_candidates_reviewed.jsonl') or read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl')
    canonical = read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl') or read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')
    return {
        'page': {str(row.get('page_id') or row.get('surface_id')) for row in pages},
        'surface': {str(row.get('surface_id') or row.get('page_id')) for row in pages},
        'paragraph': {str(row.get('paragraph_id')) for row in paragraphs},
        'asset': {str(row.get('occurrence_id')) for row in read_jsonl(package / 'ledger' / 'assets.jsonl')},
        'object': {str(row.get('object_id')) for row in read_jsonl(package / 'ledger' / 'objects.jsonl')},
        'canonical_block': {str(row.get('block_id')) for row in canonical},
    }


def _normalize(
    decision: dict[str, Any], package: Path, reviewer_context: ReviewerContext | None = None,
) -> dict[str, Any]:
    row = dict(decision)
    manifest = read_json(package / 'package_manifest.json')
    if manifest.get('lifecycle', {}).get('state', 'active') != 'active':
        raise ValueError('cannot review a revoked package')
    source_sha = manifest.get('source', {}).get('sha256')
    active_run_id = manifest.get('active_run_id')
    if row.get('source_sha256') not in {None, source_sha}:
        raise ValueError('review decision source_sha256 does not match package head')
    if row.get('active_run_id') not in {None, active_run_id}:
        raise ValueError('review decision active_run_id does not match package head')
    row['source_sha256'] = source_sha
    row['active_run_id'] = active_run_id
    canonical_revision = str(manifest.get('canonical_revision', 'raw'))
    if row.get('canonical_revision') not in {None, canonical_revision}:
        raise ValueError('review decision canonical_revision does not match package head')
    row['canonical_revision'] = canonical_revision
    kind = str(row.get('kind', ''))
    if kind not in ALLOWED_KINDS:
        raise ValueError(f'unsupported review decision kind: {kind}')
    target_id = str(row.get('target_id', '')).strip()
    if not target_id:
        raise ValueError('review decision requires target_id')
    disposition = row.get('disposition')
    if disposition and disposition not in ALLOWED_DISPOSITIONS:
        raise ValueError(f'unsupported disposition: {disposition}')
    if row.get('semantic_reading'):
        if reviewer_context is not None:
            reviewer_context.validate(manifest.get('scope', {}))
            row['reviewer_type'] = reviewer_context.reviewer_type
            row['reviewer_id'] = reviewer_context.reviewer_id
            row['review_session_id'] = reviewer_context.review_session_id
            row['reviewer_attestation'] = 'orchestrator_verified'
            row['reviewer_tenant_id'] = reviewer_context.tenant_id
            row['reviewer_workspace_id'] = reviewer_context.workspace_id
        else:
            row.setdefault('reviewer_attestation', 'local_self_asserted')
        if row.get('reviewer_type') not in {'human', 'agent_semantic'}:
            raise ValueError('semantic decisions require reviewer_type=human or agent_semantic')
        if not row.get('reviewer_id'):
            raise ValueError('semantic decisions require reviewer_id')
    if row.get('resolves'):
        if not isinstance(row['resolves'], list) or any(not isinstance(code, str) for code in row['resolves']):
            raise ValueError('resolves must be a list of blocker codes')
        resolutions = row.get('resolution_evidence')
        if not isinstance(resolutions, list):
            raise ValueError('resolves requires a resolution_evidence list')
        resolved_codes = set()
        for resolution in resolutions:
            if not isinstance(resolution, dict):
                raise ValueError('resolution_evidence entries must be objects')
            if not resolution.get('code') or not resolution.get('method') or resolution.get('verified') is not True:
                raise ValueError('resolution evidence requires code, method, and verified=true')
            code = str(resolution['code'])
            if code not in RESOLUTION_METHODS:
                raise ValueError(f'unsupported resolution blocker code: {code}')
            if resolution.get('method') not in RESOLUTION_METHODS[code]:
                raise ValueError(f'unsupported resolution method for {code}: {resolution.get("method")}')
            resolved_codes.add(str(resolution['code']))
        if not set(row['resolves']).issubset(resolved_codes):
            raise ValueError('every resolves code requires typed resolution evidence')
    if kind == 'paragraph':
        for field in ('claim_candidates', 'method_candidates', 'metric_candidates', 'boundary_candidates', 'reasoning_leap_candidates'):
            row.setdefault(field, [])
            if not isinstance(row[field], list):
                raise ValueError(f'paragraph decision {field} must be a list')
        if 'used_in_card' not in row or not isinstance(row.get('used_in_card'), bool):
            raise ValueError('paragraph decision requires boolean used_in_card')
        if 'requires_primary_anchor' not in row or not isinstance(row.get('requires_primary_anchor'), bool):
            raise ValueError('paragraph decision requires boolean requires_primary_anchor')
        if not row.get('source_id') or not row.get('sourcepage_path'):
            raise ValueError('paragraph decision requires source_id and sourcepage_path')
    if kind == 'structure':
        if target_id != 'canonical' or row.get('disposition') != 'reviewed' or not row.get('semantic_reading'):
            raise ValueError('structure decision must semantically review target_id=canonical')
        surfaces = read_jsonl(package / 'ledger' / 'surfaces.jsonl') or read_jsonl(package / 'ledger' / 'pages.jsonl')
        ordered_surfaces = [
            str(item.get('surface_id') or item.get('page_id'))
            for item in sorted(surfaces, key=lambda item: int(item.get('ordinal', 0)))
        ]
        if [str(value) for value in row.get('covered_surface_ids', [])] != ordered_surfaces:
            raise ValueError('structure covered_surface_ids must exactly match source surface order')
        active_paragraphs = (
            read_jsonl(package / 'ledger' / 'paragraph_candidates_reviewed.jsonl')
            or read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl')
        )
        active_paragraphs = sorted(active_paragraphs, key=lambda item: int(item.get('order', 0)))
        ordered_paragraph_ids = [str(item.get('paragraph_id')) for item in active_paragraphs]
        paragraph_by_id = {str(item.get('paragraph_id')): item for item in active_paragraphs}
        surfaces_with_paragraphs = {
            str(item.get('page_id')) for item in active_paragraphs if item.get('page_id')
        }
        textless_surfaces = [
            surface_id for surface_id in ordered_surfaces if surface_id not in surfaces_with_paragraphs
        ]
        candidates = read_json(package / 'toc' / 'toc_candidates.json').get('candidates', [])
        candidate_ids = {str(item.get('candidate_id')) for item in candidates if item.get('candidate_id')}
        dispositions = row.get('candidate_dispositions', [])
        if not isinstance(dispositions, list):
            raise ValueError('structure candidate_dispositions must be a list')
        disposition_by_id = {
            str(item.get('candidate_id')): item for item in dispositions
            if isinstance(item, dict) and item.get('candidate_id')
        }
        if (
            set(disposition_by_id) != candidate_ids
            or any(
                item.get('disposition') not in {'used', 'excluded', 'reference_only'} or not item.get('reason')
                for item in disposition_by_id.values()
            )
        ):
            raise ValueError('structure must disposition every TOC candidate with a reason')
        boundaries = row.get('boundaries')
        if not isinstance(boundaries, list) or not boundaries:
            raise ValueError('structure requires a non-empty boundaries list')
        boundary_ids: set[str] = set()
        flattened_paragraphs: list[str] = []
        assigned_textless_surfaces: list[str] = []
        boundary_surface_union: set[str] = set()
        for boundary in boundaries:
            if not isinstance(boundary, dict):
                raise ValueError('structure boundary entries must be objects')
            boundary_id = str(boundary.get('boundary_id') or '')
            chapter_surfaces = [str(value) for value in boundary.get('surface_ids', [])]
            chapter_paragraphs = [str(value) for value in boundary.get('paragraph_ids', [])]
            chapter_textless = [str(value) for value in boundary.get('textless_surface_ids', [])]
            paragraph_surfaces: set[str] = set()
            for paragraph_id in chapter_paragraphs:
                surface_id = str(paragraph_by_id.get(paragraph_id, {}).get('page_id') or '')
                if surface_id:
                    paragraph_surfaces.add(surface_id)
            expected_chapter_surfaces = [
                surface_id for surface_id in ordered_surfaces
                if surface_id in paragraph_surfaces or surface_id in set(chapter_textless)
            ]
            if (
                not boundary_id or boundary_id in boundary_ids or not boundary.get('title')
                or (not chapter_paragraphs and not chapter_textless)
                or any(surface_id not in textless_surfaces for surface_id in chapter_textless)
                or len(chapter_textless) != len(set(chapter_textless))
                or chapter_surfaces != expected_chapter_surfaces
                or not isinstance(boundary.get('structure_path'), list)
                or not boundary.get('structure_path')
            ):
                raise ValueError('structure boundaries require unique IDs, titles, paths, contiguous paragraphs, and derived surface IDs')
            boundary_ids.add(boundary_id)
            flattened_paragraphs.extend(chapter_paragraphs)
            assigned_textless_surfaces.extend(chapter_textless)
            boundary_surface_union.update(chapter_surfaces)
        if flattened_paragraphs != ordered_paragraph_ids or len(flattened_paragraphs) != len(set(flattened_paragraphs)):
            raise ValueError('structure boundaries must partition every paragraph once in source order')
        if (
            set(assigned_textless_surfaces) != set(textless_surfaces)
            or len(assigned_textless_surfaces) != len(set(assigned_textless_surfaces))
            or boundary_surface_union != set(ordered_surfaces)
        ):
            raise ValueError('structure boundaries must assign every textless surface exactly once and cover every surface')
        toc_items = row.get('toc_items')
        if not isinstance(toc_items, list) or not toc_items:
            raise ValueError('structure requires a non-empty canonical TOC')
        toc_ids: set[str] = set()
        mapped_boundary_ids: set[str] = set()
        mapped_candidate_ids: set[str] = set()
        for item in toc_items:
            toc_id = str(item.get('toc_id') or '') if isinstance(item, dict) else ''
            source_ids = [str(value) for value in item.get('source_candidate_ids', [])] if isinstance(item, dict) else []
            if (
                not toc_id or toc_id in toc_ids or not item.get('title')
                or str(item.get('boundary_id') or '') not in boundary_ids
                or any(value not in candidate_ids for value in source_ids)
            ):
                raise ValueError('canonical TOC items require unique IDs, titles, reviewed boundaries, and valid candidates')
            toc_ids.add(toc_id)
            mapped_boundary_ids.add(str(item.get('boundary_id')))
            mapped_candidate_ids.update(source_ids)
        used_candidate_ids = {
            candidate_id for candidate_id, item in disposition_by_id.items()
            if item.get('disposition') == 'used'
        }
        if mapped_boundary_ids != boundary_ids or mapped_candidate_ids != used_candidate_ids:
            raise ValueError('canonical TOC must map every boundary and every used TOC candidate exactly into the reviewed structure')
    row.setdefault('created_at', utc_now())
    row.setdefault('supersedes', [])
    if not isinstance(row['supersedes'], list) or any(not isinstance(value, str) for value in row['supersedes']):
        raise ValueError('supersedes must be a list of decision_id strings')
    row.setdefault('policy_version', 'xuanzang-2.0')
    canonical = json.dumps(
        {k: v for k, v in row.items() if k not in {'decision_id', 'created_at'}},
        ensure_ascii=False, sort_keys=True,
    )
    expected_decision_id = f'dec_{sha256_text(canonical)[:20]}'
    if row.get('decision_id') not in {None, expected_decision_id}:
        raise ValueError('decision_id must match the server-computed content identity')
    row['decision_id'] = expected_decision_id
    row['target_id'] = target_id
    return row


def _build_reviewed_canonical(package: Path, latest: dict[tuple[str, str], dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base = read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl') or read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')
    raw_by_id = {row['block_id']: row for row in read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')}
    evidence = {row['evidence_id']: row for row in read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')}
    by_id = {row['block_id']: row for row in base}
    consumed: set[str] = set()
    out = []
    for block in base:
        block_id = block['block_id']
        if block_id in consumed:
            continue
        decision = latest.get(('canonical_block', block_id))
        if not decision:
            row = dict(block)
            row.setdefault('source_spans', [{
                'block_id': block_id, 'evidence_id': block.get('evidence_id'), 'page_id': block.get('page_id'),
                'bbox': block.get('bbox', []), 'start_offset': 0, 'end_offset': len(block.get('text', '')),
            }])
            out.append(row)
            continue
        action = decision.get('action')
        if action not in {'correct_text', 'select_variant', 'join_blocks', 'split_block', 'reorder_blocks'}:
            raise ValueError(f'unsupported canonical_block action: {action}')
        if action == 'correct_text':
            corrected = str(decision.get('corrected_text', ''))
            if not corrected:
                raise ValueError('correct_text requires corrected_text')
            row = dict(block)
            row.update({
                'text': corrected, 'text_sha256': sha256_text(corrected),
                'selection_status': 'reviewed_correction', 'review_decision_id': decision['decision_id'],
                'source_spans': block.get('source_spans') or [{
                    'block_id': block_id, 'evidence_id': block.get('evidence_id'), 'page_id': block.get('page_id'),
                    'bbox': block.get('bbox', []), 'start_offset': 0, 'end_offset': len(block.get('text', '')),
                }],
            })
            out.append(row)
        elif action == 'select_variant':
            selected_id = decision.get('selected_evidence_id')
            selected = evidence.get(selected_id)
            if not selected or selected.get('page_id') != block.get('page_id'):
                raise ValueError('selected_evidence_id must exist on the same surface')
            target_evidence = evidence.get(block.get('evidence_id'), {})
            target_group = block.get('variant_group_id') or target_evidence.get('variant_group_id')
            selected_group = selected.get('variant_group_id')
            if not target_group or selected_group != target_group:
                raise ValueError('select_variant requires an explicit shared variant_group_id')
            row = dict(block)
            row.update({
                'evidence_id': selected_id, 'text': selected['text'], 'text_sha256': selected['text_sha256'],
                'bbox': selected.get('bbox', []), 'coordinate_space': selected.get('coordinate_space'),
                'block_kind': selected.get('block_kind'), 'selection_status': 'reviewed_variant_selection',
                'variant_group_id': selected_group,
                'selected_variant_evidence_id': selected_id,
                'review_decision_id': decision['decision_id'],
                'source_spans': block.get('source_spans') or [{
                    'block_id': block_id, 'evidence_id': block.get('evidence_id'),
                    'page_id': block.get('page_id'), 'bbox': block.get('bbox', []),
                    'start_offset': 0, 'end_offset': len(block.get('text', '')),
                }],
            })
            out.append(row)
        elif action == 'join_blocks':
            join_ids = list(dict.fromkeys([block_id, *decision.get('join_block_ids', [])]))
            try:
                indexes = sorted([list(by_id).index(value) for value in join_ids])
            except ValueError as exc:
                raise ValueError('join_blocks references an unknown canonical block') from exc
            if indexes != list(range(min(indexes), max(indexes) + 1)):
                raise ValueError('join_blocks requires contiguous canonical blocks')
            join_ids = [list(by_id)[index] for index in indexes]
            members = [by_id[value] for value in join_ids]
            if len({row.get('page_id') for row in members}) != 1:
                raise ValueError('join_blocks cannot cross surfaces; use structure relations for cross-page continuity')
            text = str(decision.get('corrected_text') or ' '.join(row.get('text', '') for row in members))
            spans = []
            for row in members:
                spans.extend(row.get('source_spans') or [{
                    'block_id': row['block_id'], 'evidence_id': row.get('evidence_id'), 'page_id': row.get('page_id'),
                    'bbox': row.get('bbox', []), 'start_offset': 0, 'end_offset': len(raw_by_id.get(row['block_id'], row).get('text', '')),
                }])
            out.append({
                **block, 'block_id': f"blk_join_{sha256_text('|'.join(join_ids))[:16]}",
                'text': text, 'text_sha256': sha256_text(text), 'source_block_ids': join_ids,
                'source_spans': spans, 'selection_status': 'reviewed_join', 'review_decision_id': decision['decision_id'],
            })
            consumed.update(join_ids[1:])
        elif action == 'split_block':
            texts = decision.get('split_texts')
            ranges = decision.get('split_ranges')
            if not isinstance(texts, list) or not texts or not isinstance(ranges, list) or len(texts) != len(ranges):
                raise ValueError('split_block requires equally sized split_texts and split_ranges')
            existing_spans = block.get('source_spans') or [{
                'block_id': block_id, 'evidence_id': block.get('evidence_id'), 'page_id': block.get('page_id'),
                'bbox': block.get('bbox', []), 'start_offset': 0, 'end_offset': len(block.get('text', '')),
            }]
            if len(existing_spans) != 1 or existing_spans[0].get('block_id') not in raw_by_id:
                raise ValueError('split_block currently requires one unsplit raw source span')
            raw_block_id = existing_spans[0]['block_id']
            raw_text = raw_by_id[raw_block_id].get('text', '')
            cursor = 0
            for index, (text, span) in enumerate(zip(texts, ranges), start=1):
                if not isinstance(span, list) or len(span) != 2:
                    raise ValueError('split range must be [start, end]')
                start, end = int(span[0]), int(span[1])
                if start != cursor or end < start or end > len(raw_text):
                    raise ValueError('split ranges must be contiguous and cover the original block')
                cursor = end
                out.append({
                    **block, 'block_id': f"blk_split_{sha256_text(f'{raw_block_id}|{index}|{start}|{end}')[:16]}",
                    'text': str(text), 'text_sha256': sha256_text(str(text)), 'source_block_ids': [raw_block_id],
                    'source_spans': [{
                        'block_id': raw_block_id, 'evidence_id': block.get('evidence_id'), 'page_id': block.get('page_id'),
                        'bbox': block.get('bbox', []), 'start_offset': start, 'end_offset': end,
                    }],
                    'selection_status': 'reviewed_split', 'review_decision_id': decision['decision_id'],
                })
            if cursor != len(raw_text):
                raise ValueError('split ranges must cover the original block exactly')
        elif action == 'reorder_blocks':
            ordered_ids = decision.get('ordered_block_ids')
            if not isinstance(ordered_ids, list) or len(ordered_ids) < 2 or len(set(ordered_ids)) != len(ordered_ids):
                raise ValueError('reorder_blocks requires unique ordered_block_ids')
            if block_id not in ordered_ids:
                raise ValueError('reorder_blocks must include its target block')
            try:
                original_indexes = sorted(list(by_id).index(value) for value in ordered_ids)
            except ValueError as exc:
                raise ValueError('reorder_blocks references an unknown canonical block') from exc
            if original_indexes != list(range(min(original_indexes), max(original_indexes) + 1)):
                raise ValueError('reorder_blocks currently requires a contiguous source block range')
            if list(by_id)[min(original_indexes)] != block_id:
                raise ValueError('reorder_blocks decision must target the first source block in its range')
            members = [by_id[value] for value in ordered_ids]
            if len({row.get('page_id') for row in members}) != 1:
                raise ValueError('reorder_blocks cannot cross surfaces')
            for member in members:
                row = dict(member)
                row.update({
                    'selection_status': 'reviewed_reorder',
                    'review_decision_id': decision['decision_id'],
                    'source_spans': member.get('source_spans') or [{
                        'block_id': member['block_id'], 'evidence_id': member.get('evidence_id'),
                        'page_id': member.get('page_id'), 'bbox': member.get('bbox', []),
                        'start_offset': 0, 'end_offset': len(raw_by_id.get(member['block_id'], member).get('text', '')),
                    }],
                })
                out.append(row)
            consumed.update(set(ordered_ids) - {block_id})
    source_id = read_json(package / 'package_manifest.json').get('source', {}).get('sha256')
    paragraphs = []
    for order, block in enumerate(out, start=1):
        spans = block.get('source_spans') or []
        pid = f"para_{sha256_text(json.dumps(spans, sort_keys=True))[:16]}"
        paragraphs.append({
            'source_id': source_id,
            'sourcepage_path': f'xuanzang://source/{source_id}/surface/{block.get("page_id")}',
            'paragraph_id': pid, 'order': order,
            'page_id': block.get('page_id'), 'page_anchor': block.get('page_id'), 'text': block.get('text', ''),
            'text_sha256': sha256_text(block.get('text', '')), 'block_kind': block.get('block_kind'),
            'source_role': (evidence.get(block.get('evidence_id'), {}).get('metadata') or {}).get('source_role', 'primary'),
            'source_spans': spans, 'coverage_status': 'unreviewed', 'paragraph_role': None,
            'semantic_summary': None, 'claim_candidates': [], 'method_candidates': [], 'metric_candidates': [],
            'boundary_candidates': [], 'used_in_card': None, 'use_reason': None, 'exclusion_reason': None,
            'reasoning_leap_candidates': [],
            'requires_primary_anchor': True, 'producer': {'kind': 'reviewed_canonical_projection'},
        })
    return out, paragraphs


def _apply_review_locked(
    package: Path, decisions_path: Path, *, expected_revision: str | None = None,
    expected_tenant_id: str | None = None, expected_workspace_id: str | None = None,
    reviewer_context: ReviewerContext | None = None,
) -> dict[str, Any]:
    package = package.resolve()
    manifest = read_json(package / 'package_manifest.json')
    if manifest.get('lifecycle', {}).get('state', 'active') != 'active':
        raise ValueError('cannot review a revoked package')
    assert_expected_scope(
        manifest, expected_tenant_id=expected_tenant_id,
        expected_workspace_id=expected_workspace_id,
    )
    current_revision = str(manifest.get('review_revision', '0'))
    if expected_revision is not None and expected_revision != current_revision:
        raise ValueError(f'review revision conflict: expected {expected_revision}, current {current_revision}')
    target_sets = _targets(package)
    ledger_path = package / 'ledger' / 'review_decisions.jsonl'
    existing_rows = read_jsonl(ledger_path)
    by_id = {row.get('decision_id'): row for row in existing_rows}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in existing_rows:
        if row.get('source_sha256') != manifest.get('source', {}).get('sha256') or row.get('active_run_id') != manifest.get('active_run_id'):
            continue
        latest[(str(row.get('kind')), str(row.get('target_id')))] = row
    accepted = []
    staged_by_id = dict(by_id)
    staged_latest = dict(latest)
    for raw in _load_decisions(decisions_path):
        row = _normalize(raw, package, reviewer_context)
        kind, target_id = row['kind'], row['target_id']
        if kind in target_sets and target_id not in target_sets[kind]:
            raise ValueError(f'unknown {kind} target: {target_id}')
        if kind == 'structure' and target_id != 'canonical':
            raise ValueError('structure decision target_id must be canonical')
        if kind == 'source_boundary' and target_id != manifest.get('source', {}).get('sha256'):
            raise ValueError('source_boundary target_id must match the package source sha256')
        if row['decision_id'] in staged_by_id:
            prior_same_id = {
                key: value for key, value in staged_by_id[row['decision_id']].items()
                if key not in {'previous_decision_hash', 'decision_hash', 'created_at'}
            }
            current_same_id = {key: value for key, value in row.items() if key != 'created_at'}
            if prior_same_id != current_same_id:
                raise ValueError(f'decision_id collision: {row["decision_id"]}')
            continue
        prior = staged_latest.get((kind, target_id))
        if prior and prior.get('decision_id') not in row.get('supersedes', []):
            raise ValueError(f'new decision for {kind}:{target_id} must supersede {prior.get("decision_id")}')
        staged_by_id[row['decision_id']] = row
        staged_latest[(kind, target_id)] = row
        accepted.append(row)

    chain_head = (
        str(existing_rows[-1].get('decision_hash')) if existing_rows and existing_rows[-1].get('decision_hash')
        else sha256_text(f'review-genesis|{manifest.get("package_id")}')
    )
    for row in accepted:
        row['previous_decision_hash'] = chain_head
        row['decision_hash'] = sha256_text(json.dumps(
            {key: value for key, value in row.items() if key != 'decision_hash'},
            ensure_ascii=False, sort_keys=True,
        ))
        chain_head = row['decision_hash']

    accepted_canonical = [row for row in accepted if row['kind'] == 'canonical_block']
    accepted_paragraphs = [row for row in accepted if row['kind'] == 'paragraph']
    if accepted_canonical and accepted_paragraphs:
        raise ValueError('canonical edits and paragraph semantic decisions must be separate review revisions')
    if accepted_canonical and any(row['kind'] == 'structure' for row in accepted):
        raise ValueError('canonical edits and structure decisions must be separate review revisions')
    canonical_projection = None
    paragraph_projection = None
    if accepted_canonical:
        canonical_projection, paragraph_projection = _build_reviewed_canonical(
            package, {('canonical_block', row['target_id']): row for row in accepted_canonical},
        )

    latest = staged_latest
    paragraphs = (
        paragraph_projection if paragraph_projection is not None
        else (read_jsonl(package / 'ledger' / 'paragraph_candidates_reviewed.jsonl') or read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl'))
    )
    coverage = []
    for paragraph in paragraphs:
        decision = latest.get(('paragraph', paragraph['paragraph_id']))
        row = dict(paragraph)
        if decision:
            row.update({
                'coverage_status': decision.get('disposition'),
                'source_id': decision.get('source_id'),
                'sourcepage_path': decision.get('sourcepage_path'),
                'paragraph_role': decision.get('paragraph_role'),
                'semantic_summary': decision.get('semantic_summary'),
                'claim_candidates': decision.get('claim_candidates', []),
                'method_candidates': decision.get('method_candidates', []),
                'metric_candidates': decision.get('metric_candidates', []),
                'boundary_candidates': decision.get('boundary_candidates', []),
                'reasoning_leap_candidates': decision.get('reasoning_leap_candidates', []),
                'used_in_card': decision.get('used_in_card'),
                'requires_primary_anchor': decision.get('requires_primary_anchor'),
                'use_reason': decision.get('reason') if decision.get('disposition') == 'used' else None,
                'exclusion_reason': decision.get('reason') if decision.get('disposition') in {'excluded', 'reference_only'} else None,
                'review_decision_id': decision['decision_id'],
                'reviewer_type': decision.get('reviewer_type'),
                'reviewer_id': decision.get('reviewer_id'),
            })
        coverage.append(row)
    leap_rows = []
    paragraph_ids = {str(row.get('paragraph_id')) for row in coverage}
    paragraph_dispositions = {
        str(row.get('paragraph_id')): str(row.get('coverage_status') or '')
        for row in coverage
    }
    for paragraph in coverage:
        for index, leap in enumerate(paragraph.get('reasoning_leap_candidates', []), start=1):
            if not isinstance(leap, dict):
                raise ValueError('reasoning_leap_candidates entries must be objects')
            required = ('premises', 'inference', 'uncertainty')
            if any(not leap.get(field) for field in required):
                raise ValueError('reasoning leap requires premises, inference, and uncertainty')
            premise_ids = [str(value) for value in leap.get('premise_paragraph_ids', [])]
            conclusion_ids = [str(value) for value in leap.get('conclusion_paragraph_ids', [])]
            if (
                not isinstance(leap.get('premises'), list) or not leap.get('premises')
                or not premise_ids or any(value not in paragraph_ids for value in premise_ids)
                or any(value not in paragraph_ids for value in conclusion_ids)
                or not isinstance(leap.get('assumptions'), list)
                or not isinstance(leap.get('counterevidence'), list)
                or not isinstance(leap.get('alternatives', []), list)
                or not isinstance(leap.get('testable_predictions', []), list)
                or not leap.get('novelty_context') or not leap.get('source_local_boundary')
                or leap.get('reviewer_status') not in {'candidate', 'verified', 'rejected'}
            ):
                raise ValueError(
                    'reasoning leap requires anchored premise IDs, typed assumption/counterevidence lists, '
                    'novelty context, source-local boundary, and reviewer status'
                )
            referenced_ids = premise_ids + conclusion_ids
            if (
                paragraph_dispositions.get(str(paragraph.get('paragraph_id'))) != 'used'
                or any(paragraph_dispositions.get(value) != 'used' for value in referenced_ids)
            ):
                raise ValueError(
                    'reasoning leap host, premise, and conclusion paragraphs must be disposition=used '
                    'so the citation export contains every referenced paragraph'
                )
            leap_rows.append({
                'leap_id': leap.get('leap_id') or f"leap_{sha256_text(paragraph['paragraph_id'] + str(index) + json.dumps(leap, sort_keys=True, ensure_ascii=False))[:16]}",
                'paragraph_id': paragraph['paragraph_id'], 'source_id': paragraph.get('source_id'),
                'source_spans': paragraph.get('source_spans', []), 'premises': leap['premises'],
                'inference': leap['inference'], 'uncertainty': leap['uncertainty'],
                'premise_paragraph_ids': premise_ids, 'conclusion_paragraph_ids': conclusion_ids,
                'assumptions': leap['assumptions'], 'novelty_context': leap['novelty_context'],
                'counterevidence': leap['counterevidence'],
                'source_local_boundary': leap['source_local_boundary'],
                'alternatives': leap.get('alternatives', []),
                'testable_predictions': leap.get('testable_predictions', []),
                'reviewer_status': leap['reviewer_status'],
                'status': 'candidate_not_source_fact', 'review_decision_id': paragraph.get('review_decision_id'),
            })
    structure = latest.get(('structure', 'canonical'))
    toc_projection = None
    boundary_projection = None
    if structure:
        toc_projection = {
            'status': 'reviewed' if structure.get('disposition') == 'reviewed' else 'needs_review',
            'items': structure.get('toc_items', []),
            'review_decision_id': structure['decision_id'],
        }
        boundary_projection = {
            'status': 'reviewed' if structure.get('disposition') == 'reviewed' else 'needs_review',
            'chapters': structure.get('boundaries', []),
            'review_decision_id': structure['decision_id'],
        }
        paragraph_to_path: dict[str, list[str]] = {}
        for boundary in structure.get('boundaries', []):
            if not isinstance(boundary, dict):
                continue
            path = boundary.get('structure_path')
            if not isinstance(path, list) or not path:
                path = [str(boundary.get('title') or boundary.get('boundary_id') or '')]
            for paragraph_id in boundary.get('paragraph_ids', []):
                paragraph_to_path[str(paragraph_id)] = [str(value) for value in path if str(value)]
        base_projection = paragraph_projection if paragraph_projection is not None else paragraphs
        paragraph_projection = [
            {**row, 'structure_path': paragraph_to_path.get(str(row.get('paragraph_id')), [])}
            for row in base_projection
        ]
        coverage = [
            {**row, 'structure_path': paragraph_to_path.get(str(row.get('paragraph_id')), [])}
            for row in coverage
        ]

    # Finish every validation and materialize every derived payload in memory
    # before the first durable write. The manifest is the commit marker and is
    # written last; gate bindings fail closed after an interrupted commit.
    new_ledger_rows = [*existing_rows, *accepted]
    ledger_bytes = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in new_ledger_rows)
    new_manifest = dict(manifest)
    if canonical_projection is not None:
        canonical_bytes = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in canonical_projection)
        new_manifest['canonical_revision'] = sha256_text(canonical_bytes)[:20]
    if paragraph_projection is not None:
        paragraph_bytes = ''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in paragraph_projection)
        new_manifest['paragraph_projection_sha256'] = sha256_text(paragraph_bytes)
    if toc_projection is not None and boundary_projection is not None:
        toc_bytes = json.dumps(toc_projection, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        boundary_bytes = json.dumps(boundary_projection, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        new_manifest['toc_projection_sha256'] = sha256_text(toc_bytes)
        new_manifest['boundary_projection_sha256'] = sha256_text(boundary_bytes)
        new_manifest['structure_review_decision_id'] = structure['decision_id'] if structure else None
    revision_seed = '|'.join(row.get('decision_id', '') for row in new_ledger_rows)
    new_manifest['review_revision'] = sha256_text(revision_seed)[:20] if revision_seed else '0'
    new_manifest['review_ledger_sha256'] = sha256_text(ledger_bytes)
    new_manifest['updated_at'] = utc_now()

    if canonical_projection is not None:
        write_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl', canonical_projection)
    if paragraph_projection is not None:
        write_jsonl(package / 'ledger' / 'paragraph_candidates_reviewed.jsonl', paragraph_projection)
    write_jsonl(package / 'ledger' / 'paragraph_coverage.jsonl', coverage)
    write_jsonl(package / 'ledger' / 'reasoning_leap_candidates.jsonl', leap_rows)
    if toc_projection is not None and boundary_projection is not None:
        write_json(package / 'toc' / 'canonical_toc.json', toc_projection)
        write_json(package / 'toc' / 'chapter_boundary_map.json', boundary_projection)
    if accepted:
        write_jsonl(ledger_path, new_ledger_rows)
    write_json(package / 'package_manifest.json', new_manifest)
    for row in accepted:
        append_jsonl(package / 'history' / 'events.jsonl', {
            'event': 'review_decision_applied', 'decision_id': row['decision_id'],
            'kind': row['kind'], 'target_id': row['target_id'], 'at': utc_now(),
        })
    manifest = new_manifest
    gate = evaluate_gates(package, target='citation')
    manifest['trust_status'] = gate['trust_status']
    write_json(package / 'package_manifest.json', manifest)
    return {
        'accepted': len(accepted),
        'review_revision': manifest['review_revision'],
        'trust_status': gate['trust_status'],
        'gate_status': gate['public_status'],
        'evaluation_status': gate['status'],
        'hard_blocker_count': len(gate['hard_blockers']),
    }


def apply_review(
    package: Path, decisions_path: Path, *, expected_revision: str | None = None,
    expected_tenant_id: str | None = None, expected_workspace_id: str | None = None,
    reviewer_context: ReviewerContext | None = None,
) -> dict[str, Any]:
    package = package.resolve()
    with package_lock(package):
        return _apply_review_locked(
            package, decisions_path, expected_revision=expected_revision,
            expected_tenant_id=expected_tenant_id, expected_workspace_id=expected_workspace_id,
            reviewer_context=reviewer_context,
        )


def rehydrate_review_head(package: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Rebuild review-derived projections when a previously reviewed run becomes active.

    Raw run artifacts remain immutable. This function derives every restored
    projection from the append-only decision ledger instead of trusting a saved
    top-level copy from another head.
    """
    package = package.resolve()
    source_sha = manifest.get('source', {}).get('sha256')
    run_id = manifest.get('active_run_id')
    rows = [
        row for row in read_jsonl(package / 'ledger' / 'review_decisions.jsonl')
        if row.get('source_sha256') == source_sha and row.get('active_run_id') == run_id
    ]
    if not rows:
        return manifest

    current_revision = str(manifest.get('canonical_revision', 'raw'))
    processed: set[str] = set()
    while True:
        group = [
            row for row in rows
            if row.get('kind') == 'canonical_block'
            and str(row.get('canonical_revision')) == current_revision
            and str(row.get('decision_id')) not in processed
        ]
        if not group:
            break
        latest_group: dict[tuple[str, str], dict[str, Any]] = {}
        for row in group:
            latest_group[('canonical_block', str(row.get('target_id')))] = row
            processed.add(str(row.get('decision_id')))
        canonical_projection, paragraph_projection = _build_reviewed_canonical(package, latest_group)
        write_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl', canonical_projection)
        write_jsonl(package / 'ledger' / 'paragraph_candidates_reviewed.jsonl', paragraph_projection)
        next_revision = sha256_file(package / 'ledger' / 'canonical_reviewed.jsonl')[:20]
        if next_revision == current_revision:
            break
        current_revision = next_revision

    manifest['canonical_revision'] = current_revision
    paragraphs = (
        read_jsonl(package / 'ledger' / 'paragraph_candidates_reviewed.jsonl')
        or read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl')
    )
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get('kind') in {'paragraph', 'structure'} and str(row.get('canonical_revision')) != current_revision:
            continue
        latest[(str(row.get('kind')), str(row.get('target_id')))] = row

    coverage = []
    for paragraph in paragraphs:
        decision = latest.get(('paragraph', str(paragraph.get('paragraph_id'))))
        row = dict(paragraph)
        if decision:
            row.update({
                'coverage_status': decision.get('disposition'),
                'source_id': decision.get('source_id'),
                'sourcepage_path': decision.get('sourcepage_path'),
                'paragraph_role': decision.get('paragraph_role'),
                'semantic_summary': decision.get('semantic_summary'),
                'claim_candidates': decision.get('claim_candidates', []),
                'method_candidates': decision.get('method_candidates', []),
                'metric_candidates': decision.get('metric_candidates', []),
                'boundary_candidates': decision.get('boundary_candidates', []),
                'reasoning_leap_candidates': decision.get('reasoning_leap_candidates', []),
                'used_in_card': decision.get('used_in_card'),
                'requires_primary_anchor': decision.get('requires_primary_anchor'),
                'use_reason': decision.get('reason') if decision.get('disposition') == 'used' else None,
                'exclusion_reason': decision.get('reason') if decision.get('disposition') in {'excluded', 'reference_only'} else None,
                'review_decision_id': decision.get('decision_id'),
                'reviewer_type': decision.get('reviewer_type'),
                'reviewer_id': decision.get('reviewer_id'),
            })
        coverage.append(row)

    structure = latest.get(('structure', 'canonical'))
    if structure:
        toc_projection = {
            'status': 'reviewed' if structure.get('disposition') == 'reviewed' else 'needs_review',
            'items': structure.get('toc_items', []),
            'review_decision_id': structure.get('decision_id'),
        }
        boundary_projection = {
            'status': 'reviewed' if structure.get('disposition') == 'reviewed' else 'needs_review',
            'chapters': structure.get('boundaries', []),
            'review_decision_id': structure.get('decision_id'),
        }
        paragraph_to_path = {
            str(paragraph_id): [str(value) for value in boundary.get('structure_path', []) if str(value)]
            for boundary in structure.get('boundaries', []) if isinstance(boundary, dict)
            for paragraph_id in boundary.get('paragraph_ids', [])
        }
        paragraphs = [
            {**row, 'structure_path': paragraph_to_path.get(str(row.get('paragraph_id')), [])}
            for row in paragraphs
        ]
        coverage = [
            {**row, 'structure_path': paragraph_to_path.get(str(row.get('paragraph_id')), [])}
            for row in coverage
        ]
        write_json(package / 'toc' / 'canonical_toc.json', toc_projection)
        write_json(package / 'toc' / 'chapter_boundary_map.json', boundary_projection)
        manifest['toc_projection_sha256'] = sha256_file(package / 'toc' / 'canonical_toc.json')
        manifest['boundary_projection_sha256'] = sha256_file(package / 'toc' / 'chapter_boundary_map.json')
        manifest['structure_review_decision_id'] = structure.get('decision_id')

    if (package / 'ledger' / 'canonical_reviewed.jsonl').exists() or structure:
        write_jsonl(package / 'ledger' / 'paragraph_candidates_reviewed.jsonl', paragraphs)
        manifest['paragraph_projection_sha256'] = sha256_file(
            package / 'ledger' / 'paragraph_candidates_reviewed.jsonl'
        )
    write_jsonl(package / 'ledger' / 'paragraph_coverage.jsonl', coverage)
    leap_rows = []
    for paragraph in coverage:
        for index, leap in enumerate(paragraph.get('reasoning_leap_candidates', []), start=1):
            leap_rows.append({
                'leap_id': leap.get('leap_id') or f"leap_{sha256_text(paragraph['paragraph_id'] + str(index) + json.dumps(leap, sort_keys=True, ensure_ascii=False))[:16]}",
                'paragraph_id': paragraph.get('paragraph_id'), 'source_id': paragraph.get('source_id'),
                'source_spans': paragraph.get('source_spans', []),
                'premises': leap.get('premises', []), 'inference': leap.get('inference'),
                'uncertainty': leap.get('uncertainty'),
                'premise_paragraph_ids': leap.get('premise_paragraph_ids', []),
                'conclusion_paragraph_ids': leap.get('conclusion_paragraph_ids', []),
                'assumptions': leap.get('assumptions', []),
                'novelty_context': leap.get('novelty_context'),
                'counterevidence': leap.get('counterevidence', []),
                'source_local_boundary': leap.get('source_local_boundary'),
                'alternatives': leap.get('alternatives', []),
                'testable_predictions': leap.get('testable_predictions', []),
                'reviewer_status': leap.get('reviewer_status'),
                'status': 'candidate_not_source_fact',
                'review_decision_id': paragraph.get('review_decision_id'),
            })
    write_jsonl(package / 'ledger' / 'reasoning_leap_candidates.jsonl', leap_rows)
    return manifest
