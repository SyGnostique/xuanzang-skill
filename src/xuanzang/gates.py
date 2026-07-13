from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

from .utils import read_json, read_jsonl, sha256_file, sha256_text, utc_now, write_json


REQUIRED_RUN_ARTIFACTS = {
    'ledger/surfaces.jsonl', 'ledger/evidence_blocks.jsonl',
    'ledger/canonical_blocks.jsonl', 'ledger/paragraph_candidates.jsonl',
    'ledger/assets.jsonl', 'ledger/objects.jsonl', 'toc/toc_candidates.json',
    'source_inventory.json', 'audit/extraction_audit.json',
}

RESOLUTION_METHODS = {
    'sidecar_source_image_unverified': {'source_image_hash_verified', 'replacement_evidence_selected'},
    'sidecar_provenance_requires_review': {'producer_manifest_verified'},
    'external_ocr_source_image_unverified': {'source_image_hash_verified', 'replacement_evidence_selected'},
    'external_ocr_provenance_requires_review': {'producer_manifest_verified'},
    'ocr_bbox_invalid': {'corrected_bbox_attached', 'block_quarantined'},
    'legacy_ocr_bbox_invalid': {'corrected_bbox_attached', 'block_quarantined'},
    'mixed_visual_region_requires_reconciliation': {'visual_regions_reconciled'},
    'multi_column_reading_order_requires_review': {'reading_order_verified', 'canonical_order_corrected'},
    'low_ocr_confidence_unresolved': {'visual_transcription_verified', 'replacement_evidence_selected'},
    'weak_native_text_layer_unresolved': {'visual_transcription_verified', 'replacement_evidence_selected'},
    'tracked_changes_require_review': {'accepted_view_selected', 'alternate_variants_preserved'},
    'textbox_reading_order_requires_review': {'reading_order_verified'},
    'equation_representation_requires_review': {'visual_representation_verified'},
    'fixed_layout_requires_rendered_evidence': {'rendered_rendition_attached'},
    'visual_only_spine_requires_rendered_evidence': {'rendered_rendition_attached'},
    'epub_navigation_target_unresolved': {'navigation_target_reconciled'},
    'local_conversion_requires_review': {'source_and_rendition_compared'},
    'external_image_reference_requires_review': {'asset_ingested_and_hashed', 'asset_quarantined'},
    'unsafe_relationship_target': {'asset_quarantined'},
    'missing_image_asset': {'asset_ingested_and_hashed', 'asset_quarantined'},
    'book_m1_image_missing': {'asset_ingested_and_hashed', 'page_quarantined'},
}

HINT_TOLERABLE_FINDINGS = {
    'sidecar_source_image_unverified', 'sidecar_provenance_requires_review',
    'external_ocr_source_image_unverified', 'external_ocr_provenance_requires_review',
    'ocr_bbox_invalid', 'legacy_ocr_bbox_invalid',
    'mixed_visual_region_requires_reconciliation', 'low_ocr_confidence_unresolved',
    'multi_column_reading_order_requires_review',
    'weak_native_text_layer_unresolved', 'tracked_changes_require_review',
    'textbox_reading_order_requires_review', 'equation_representation_requires_review',
    'fixed_layout_requires_rendered_evidence', 'local_conversion_requires_review',
    'visual_only_spine_requires_rendered_evidence', 'epub_navigation_target_unresolved',
    'external_image_reference_requires_review', 'unsafe_relationship_target',
    'missing_image_asset', 'book_m1_image_missing', 'ocr_failure',
}


def _latest_decisions(package: Path, manifest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    source_sha = manifest.get('source', {}).get('sha256')
    active_run_id = manifest.get('active_run_id')
    for row in read_jsonl(package / 'ledger' / 'review_decisions.jsonl'):
        if row.get('source_sha256') != source_sha or row.get('active_run_id') != active_run_id:
            continue
        if row.get('kind') in {'paragraph', 'structure'} and row.get('canonical_revision') != str(manifest.get('canonical_revision', 'raw')):
            continue
        key = (str(row.get('kind')), str(row.get('target_id')))
        latest[key] = row
    return latest


def evaluate_gates(package: Path, *, target: str = 'citation') -> dict[str, Any]:
    """Recompute trust gates from evidence; never trust a previous pass/fail file."""
    if target not in {'hint', 'review', 'citation'}:
        raise ValueError(f'unsupported gate target: {target}')
    package = package.resolve()
    manifest = read_json(package / 'package_manifest.json')
    pages = read_jsonl(package / 'ledger' / 'surfaces.jsonl') or read_jsonl(package / 'ledger' / 'pages.jsonl')
    evidence = read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')
    raw_canonical = read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')
    canonical = read_jsonl(package / 'ledger' / 'canonical_reviewed.jsonl') or raw_canonical
    paragraphs = read_jsonl(package / 'ledger' / 'paragraph_candidates_reviewed.jsonl') or read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl')
    assets = read_jsonl(package / 'ledger' / 'assets.jsonl')
    objects = read_jsonl(package / 'ledger' / 'objects.jsonl')
    extraction = read_json(package / 'audit' / 'extraction_audit.json')
    decisions = _latest_decisions(package, manifest)
    page_by_id = {str(row.get('page_id')): row for row in pages}
    evidence_by_id = {str(row.get('evidence_id')): row for row in evidence}
    canonical_evidence_ids = {str(row.get('evidence_id')) for row in canonical}
    canonical_by_page: dict[str, list[dict[str, Any]]] = {}
    for row in canonical:
        canonical_by_page.setdefault(str(row.get('page_id')), []).append(row)
    asset_by_id = {str(row.get('occurrence_id')): row for row in assets}
    object_by_id = {str(row.get('object_id')): row for row in objects}
    toc_candidates = read_json(package / 'toc' / 'toc_candidates.json').get('candidates', [])
    toc_candidate_by_id = {str(row.get('candidate_id')): row for row in toc_candidates}

    hard: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, *, observed: Any, expected: Any, blocker: str | None = None) -> None:
        checks.append({'check_id': check_id, 'status': 'pass' if passed else 'fail', 'expected': expected, 'observed': observed})
        if not passed and blocker:
            hard.append({'code': blocker, 'check_id': check_id, 'observed': observed})

    check('schema_version', manifest.get('package_version') == 2, observed=manifest.get('package_version'), expected=2, blocker='schema_validation_failure')
    source_identity = str(manifest.get('source', {}).get('sha256', ''))
    check(
        'source_identity', bool(re.fullmatch(r'[0-9a-f]{64}', source_identity)),
        observed=source_identity, expected='lowercase sha256', blocker='source_identity_unverified',
    )
    lifecycle_state = manifest.get('lifecycle', {}).get('state', 'active')
    check('lifecycle_active', lifecycle_state == 'active', observed=lifecycle_state, expected='active', blocker='package_revoked')
    scope = manifest.get('scope', {})
    check('rights_basis', bool(scope.get('rights_basis')), observed=scope.get('rights_basis'), expected='declared rights basis', blocker='rights_basis_missing')
    tenant_scope_ok = scope.get('privacy') != 'tenant' or bool(scope.get('tenant_id'))
    check('tenant_scope', tenant_scope_ok, observed=scope.get('tenant_id'), expected='tenant_id when privacy=tenant', blocker='tenant_scope_missing')
    workspace_scope_ok = scope.get('privacy') != 'workspace' or bool(scope.get('workspace_id'))
    check('workspace_scope', workspace_scope_ok, observed=scope.get('workspace_id'), expected='workspace_id when privacy=workspace', blocker='workspace_scope_missing')
    check('surface_accounting', bool(pages), observed=len(pages), expected='>=1', blocker='source_coverage_gap')
    surface_ids = {str(row.get('surface_id') or row.get('page_id')) for row in pages}
    block_surface_orphans = [
        str(row.get('evidence_id')) for row in evidence
        if str(row.get('page_id')) not in surface_ids
    ]
    asset_surface_orphans = [
        str(row.get('occurrence_id')) for row in assets
        if str(row.get('page_id')) not in surface_ids
    ]
    check(
        'evidence_surface_foreign_keys', not block_surface_orphans,
        observed=block_surface_orphans[:100], expected=[], blocker='evidence_surface_fk_invalid',
    )
    check(
        'asset_surface_foreign_keys', not asset_surface_orphans,
        observed=asset_surface_orphans[:100], expected=[], blocker='asset_surface_fk_invalid',
    )
    if manifest.get('source', {}).get('format') == 'epub':
        inventory = read_json(package / 'source' / 'source_inventory.json')
        source_metadata = inventory.get('metadata', {})
        expected_spine_count = int(
            source_metadata.get('spine_occurrence_count')
            or len(source_metadata.get('opf', {}).get('spine', []))
        )
        observed_spine_indexes = [int(row.get('spine_index', 0)) for row in pages]
        check(
            'epub_spine_surface_accounting',
            expected_spine_count > 0 and observed_spine_indexes == list(range(1, expected_spine_count + 1)),
            observed=observed_spine_indexes, expected=list(range(1, expected_spine_count + 1)),
            blocker='epub_spine_surface_coverage_gap',
        )
    unresolved_pages = [p['page_id'] for p in pages if p.get('status') in {'unresolved', 'failed'}]
    check('page_extraction', not unresolved_pages, observed=unresolved_pages, expected=[], blocker='unresolved_source_page')
    blank_candidates = [p['page_id'] for p in pages if p.get('status') == 'blank_candidate']
    if blank_candidates:
        warnings.append({'code': 'blank_pages_need_confirmation', 'page_ids': blank_candidates})
    check('canonical_evidence', bool(canonical), observed=len(canonical), expected='>=1', blocker='canonical_text_missing')
    evidence_ids = {e.get('evidence_id') for e in evidence}
    orphan_canonical = []
    invalid_variant_selections = []
    for block in canonical:
        selected_evidence = evidence_by_id.get(str(block.get('evidence_id')))
        if not selected_evidence or selected_evidence.get('page_id') != block.get('page_id'):
            orphan_canonical.append(block.get('block_id'))
            continue
        selection_status = str(block.get('selection_status', ''))
        if selection_status in {'machine_selected', 'machine_selected_normalized_variant', 'reviewed_variant_selection'}:
            if block.get('text') != selected_evidence.get('text'):
                orphan_canonical.append(block.get('block_id'))
        if selection_status == 'reviewed_variant_selection':
            selected_group = selected_evidence.get('variant_group_id')
            raw_source_ids = [
                str(span.get('evidence_id')) for span in block.get('source_spans', [])
                if isinstance(span, dict) and span.get('evidence_id')
            ]
            raw_groups = {
                evidence_by_id.get(evidence_id, {}).get('variant_group_id')
                for evidence_id in raw_source_ids
            }
            if not selected_group or raw_groups != {selected_group}:
                invalid_variant_selections.append(block.get('block_id'))
    check('canonical_reverse_mapping', not orphan_canonical, observed=orphan_canonical, expected=[], blocker='canonical_anchor_gap')
    check(
        'canonical_variant_relation', not invalid_variant_selections,
        observed=invalid_variant_selections, expected=[], blocker='canonical_variant_relation_invalid',
    )
    review_ledger_path = package / 'ledger' / 'review_decisions.jsonl'
    observed_review_root = sha256_file(review_ledger_path) if review_ledger_path.exists() else None
    check(
        'review_ledger_binding',
        bool(observed_review_root) and manifest.get('review_ledger_sha256') == observed_review_root,
        observed=observed_review_root, expected=manifest.get('review_ledger_sha256'),
        blocker='review_ledger_binding_mismatch',
    )
    review_chain_issues = []
    chain_head = sha256_text(f'review-genesis|{manifest.get("package_id")}')
    for index, decision in enumerate(read_jsonl(review_ledger_path), start=1):
        observed_previous = decision.get('previous_decision_hash')
        expected_hash = sha256_text(json.dumps(
            {key: value for key, value in decision.items() if key != 'decision_hash'},
            ensure_ascii=False, sort_keys=True,
        ))
        if observed_previous != chain_head or decision.get('decision_hash') != expected_hash:
            review_chain_issues.append(index)
        chain_head = str(decision.get('decision_hash') or '')
    check(
        'review_decision_chain', not review_chain_issues,
        observed=review_chain_issues[:100], expected=[], blocker='review_decision_chain_invalid',
    )
    reviewed_canonical_path = package / 'ledger' / 'canonical_reviewed.jsonl'
    active_canonical_path = reviewed_canonical_path if reviewed_canonical_path.exists() else package / 'ledger' / 'canonical_blocks.jsonl'
    observed_canonical_revision = sha256_file(active_canonical_path)[:20] if active_canonical_path.exists() else None
    check(
        'canonical_revision_binding',
        observed_canonical_revision == manifest.get('canonical_revision'),
        observed=observed_canonical_revision, expected=manifest.get('canonical_revision'),
        blocker='canonical_revision_mismatch',
    )
    reviewed_paragraphs_path = package / 'ledger' / 'paragraph_candidates_reviewed.jsonl'
    if reviewed_paragraphs_path.exists():
        observed_paragraph_projection = sha256_file(reviewed_paragraphs_path)
        check(
            'paragraph_projection_binding',
            manifest.get('paragraph_projection_sha256') == observed_paragraph_projection,
            observed=observed_paragraph_projection, expected=manifest.get('paragraph_projection_sha256'),
            blocker='paragraph_projection_mismatch',
        )
    structure_decision = decisions.get(('structure', 'canonical'))
    if structure_decision:
        toc_projection_path = package / 'toc' / 'canonical_toc.json'
        boundary_projection_path = package / 'toc' / 'chapter_boundary_map.json'
        observed_toc_projection = sha256_file(toc_projection_path) if toc_projection_path.is_file() else None
        observed_boundary_projection = sha256_file(boundary_projection_path) if boundary_projection_path.is_file() else None
        check(
            'toc_projection_binding',
            bool(observed_toc_projection and manifest.get('toc_projection_sha256'))
            and observed_toc_projection == manifest.get('toc_projection_sha256')
            and read_json(toc_projection_path).get('review_decision_id') == structure_decision.get('decision_id'),
            observed=observed_toc_projection, expected=manifest.get('toc_projection_sha256'),
            blocker='toc_projection_mismatch',
        )
        check(
            'boundary_projection_binding',
            bool(observed_boundary_projection and manifest.get('boundary_projection_sha256'))
            and observed_boundary_projection == manifest.get('boundary_projection_sha256')
            and read_json(boundary_projection_path).get('review_decision_id') == structure_decision.get('decision_id'),
            observed=observed_boundary_projection, expected=manifest.get('boundary_projection_sha256'),
            blocker='boundary_projection_mismatch',
        )
    active_run = manifest.get('active_run_id')
    tampered = []
    active_run_text = str(active_run or '')
    active_run_valid = bool(
        re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', active_run_text)
        and '..' not in active_run_text
    )
    if not active_run_valid:
        tampered.append('active_run_id_invalid')
    run_root = (package / 'runs' / active_run_text).resolve() if active_run_valid else package / '.invalid-run'
    if active_run_valid and run_root != package and package not in run_root.parents:
        tampered.append('active_run_path_escape')
        active_run_valid = False
        run_root = package / '.invalid-run'
    run_manifest_path = run_root / 'run_manifest.json'
    run_manifest: dict[str, Any] = {}
    if not run_manifest_path.exists():
        tampered.append('missing run_manifest.json')
    else:
        run_manifest = read_json(run_manifest_path)
        if sha256_file(run_manifest_path) != manifest.get('active_run_manifest_sha256'):
            tampered.append('run_manifest_binding')
        if run_manifest.get('run_id') != active_run:
            tampered.append('run_manifest_identity:run_id')
        if run_manifest.get('source_sha256') != manifest.get('source', {}).get('sha256'):
            tampered.append('run_manifest_identity:source_sha256')
        if run_manifest.get('schema_version') != 2:
            tampered.append('run_manifest_identity:schema_version')
        if run_manifest.get('pipeline_version') != manifest.get('pipeline_version'):
            tampered.append('run_manifest_identity:pipeline_version')
        declared_required = set(run_manifest.get('required_artifacts', []))
        digests = run_manifest.get('artifact_digests', {})
        if not REQUIRED_RUN_ARTIFACTS.issubset(declared_required):
            tampered.append('run_manifest_required_artifacts')
        if not isinstance(digests, dict) or not declared_required.issubset(set(digests)):
            tampered.append('run_manifest_artifact_index')
            digests = digests if isinstance(digests, dict) else {}
        observed_root = sha256_text('\n'.join(
            f'{rel}:{digest}' for rel, digest in sorted(digests.items())
        ))
        if observed_root != run_manifest.get('artifact_root_sha256'):
            tampered.append('run_manifest_artifact_root')
        for rel, expected_digest in digests.items():
            rel_path = Path(str(rel))
            if rel_path.is_absolute() or '..' in rel_path.parts:
                tampered.append(f'run_artifact_path:{rel}')
                continue
            run_artifact = (run_root / rel_path).resolve()
            if run_artifact != run_root and run_root not in run_artifact.parents:
                tampered.append(f'run_artifact_path:{rel}')
                continue
            if not run_artifact.exists() or sha256_file(run_artifact) != expected_digest:
                tampered.append(f'run:{rel}')
            projection = (package / rel_path).resolve()
            if projection != package and package not in projection.parents:
                tampered.append(f'projection_path:{rel}')
            elif rel in REQUIRED_RUN_ARTIFACTS and projection.exists() and sha256_file(projection) != expected_digest:
                tampered.append(f'projection:{rel}')
    check('immutable_artifact_integrity', not tampered, observed=tampered, expected=[], blocker='stale_or_tampered_artifact')
    run_policy = run_manifest.get('policy', {})
    expected_scope = {
        'privacy': run_policy.get('privacy'),
        'tenant_id': run_policy.get('tenant_id'),
        'workspace_id': run_policy.get('workspace_id'),
        'rights_basis': run_policy.get('rights_basis'),
        'retention_policy': run_policy.get('retention_policy'),
        'access_tags': list(run_policy.get('access_tags', [])),
    }
    observed_scope = {
        'privacy': scope.get('privacy'),
        'tenant_id': scope.get('tenant_id'),
        'workspace_id': scope.get('workspace_id'),
        'rights_basis': scope.get('rights_basis'),
        'retention_policy': scope.get('retention_policy'),
        'access_tags': list(scope.get('access_tags', [])),
    }
    check(
        'scope_bound_to_run', bool(run_manifest) and observed_scope == expected_scope,
        observed=observed_scope, expected=expected_scope, blocker='scope_binding_mismatch',
    )

    binary_issues = []
    external_binary_refs = []

    def verify_binary(owner: str, locator: Any, expected_sha: Any) -> None:
        if not locator:
            return
        rel = Path(str(locator))
        if rel.is_absolute():
            external_binary_refs.append({'owner': owner, 'path': str(locator)})
            return
        if '..' in rel.parts:
            binary_issues.append({'owner': owner, 'issue': 'path_escape', 'path': str(locator)})
            return
        unresolved = package / rel
        resolved = unresolved.resolve()
        if resolved != package and package not in resolved.parents:
            binary_issues.append({'owner': owner, 'issue': 'path_escape', 'path': str(locator)})
            return
        chain = []
        cursor = unresolved
        while cursor != package and package in cursor.parents:
            chain.append(cursor)
            cursor = cursor.parent
        if any(part.is_symlink() for part in chain):
            binary_issues.append({'owner': owner, 'issue': 'symlink', 'path': str(locator)})
            return
        if not resolved.is_file():
            binary_issues.append({'owner': owner, 'issue': 'missing', 'path': str(locator)})
            return
        if expected_sha and sha256_file(resolved) != expected_sha:
            binary_issues.append({'owner': owner, 'issue': 'sha256_mismatch', 'path': str(locator)})

    for page in pages:
        verify_binary(str(page.get('page_id')), page.get('page_image_path'), page.get('page_image_sha256'))
        verify_binary(str(page.get('page_id')), page.get('original_image_path'), page.get('original_image_sha256'))
    for asset in assets:
        verify_binary(str(asset.get('occurrence_id')), asset.get('asset_path'), asset.get('asset_sha256'))
    check(
        'binary_evidence_integrity', not binary_issues,
        observed=binary_issues[:100], expected=[], blocker='binary_evidence_integrity_failure',
    )
    if external_binary_refs:
        warnings.append({'code': 'external_binary_references', 'references': external_binary_refs[:100]})

    extraction_blockers = extraction.get('hard_blockers', [])
    unresolved_extraction = []
    delegated_to_v2_gates = {
        'legacy_v1_requires_v2_semantic_review',
        'legacy_book_m1_requires_manualstrict',
        'legacy_chapter_boundaries_require_v2_structure_review',
    }

    def bound_file(locator: Any, expected_sha: Any) -> bool:
        if not locator or not re.fullmatch(r'[0-9a-f]{64}', str(expected_sha or '')):
            return False
        rel = Path(str(locator))
        if rel.is_absolute() or '..' in rel.parts:
            return False
        unresolved = package / rel
        resolved = unresolved.resolve()
        if resolved != package and package not in resolved.parents:
            return False
        cursor = unresolved
        while cursor != package and package in cursor.parents:
            if cursor.is_symlink():
                return False
            cursor = cursor.parent
        return resolved.is_file() and sha256_file(resolved) == expected_sha

    def finding_evidence(finding: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for row in evidence:
            if finding.get('page_id') and row.get('page_id') != finding.get('page_id'):
                continue
            if finding.get('engine') and row.get('engine') != finding.get('engine'):
                continue
            if finding.get('ordinal') is not None and int(row.get('ordinal', -1)) != int(finding['ordinal']):
                continue
            out.append(row)
        return out

    def bbox_is_valid(row: dict[str, Any]) -> bool:
        bbox = row.get('bbox')
        if not isinstance(bbox, list) or len(bbox) != 4:
            return False
        try:
            x0, y0, x1, y1 = [float(value) for value in bbox]
        except (TypeError, ValueError):
            return False
        return all(value == value and abs(value) != float('inf') for value in (x0, y0, x1, y1)) and x1 >= x0 and y1 >= y0 and (x1 > x0 or y1 > y0)

    def external_anchor_valid(row: dict[str, Any]) -> bool:
        page = page_by_id.get(str(row.get('page_id')), {})
        expected = page.get('page_image_sha256')
        supplied = (row.get('metadata') or {}).get('source_image_sha256') or (row.get('metadata') or {}).get('page_image_sha256')
        return bool(expected and supplied == expected and bound_file(page.get('page_image_path'), expected))

    def resolution_method_is_backed(
        decision: dict[str, Any], resolution: dict[str, Any], finding: dict[str, Any],
    ) -> bool:
        code = str(finding.get('kind'))
        method = str(resolution.get('method'))
        page_id = str(finding.get('page_id') or decision.get('target_id') or '')
        affected = finding_evidence(finding)
        referenced_ids = [str(value) for value in resolution.get('evidence_ids', [])]
        referenced = [evidence_by_id[value] for value in referenced_ids if value in evidence_by_id]
        if len(referenced) != len(referenced_ids):
            return False

        if method == 'source_image_hash_verified':
            return bool(affected and referenced_ids == [str(row.get('evidence_id')) for row in affected] and all(external_anchor_valid(row) for row in affected))
        if method in {'replacement_evidence_selected', 'corrected_bbox_attached'}:
            replacement_id = str(resolution.get('replacement_evidence_id') or (referenced_ids[0] if len(referenced_ids) == 1 else ''))
            replacement = evidence_by_id.get(replacement_id)
            affected_ids = {str(row.get('evidence_id')) for row in affected}
            declared_affected = {str(value) for value in resolution.get('affected_evidence_ids', [])}
            return bool(
                affected_ids and declared_affected == affected_ids
                and not (affected_ids & canonical_evidence_ids)
                and replacement and str(replacement.get('page_id')) == page_id
                and replacement_id in canonical_evidence_ids and bbox_is_valid(replacement)
                and (replacement.get('engine') not in {'sidecar'} or external_anchor_valid(replacement))
                and replacement_id not in affected_ids
            )
        if method == 'block_quarantined':
            return bool(
                decision.get('disposition') == 'quarantined' and affected
                and {str(row.get('evidence_id')) for row in affected}.issubset(set(referenced_ids))
                and not ({str(row.get('evidence_id')) for row in affected} & canonical_evidence_ids)
            )
        if method == 'producer_manifest_verified':
            if decision.get('reviewer_type') != 'human':
                return False
            page_evidence = [row for row in evidence if str(row.get('page_id')) == page_id and row.get('engine') == finding.get('adapter_name')]
            if not page_evidence:
                page_evidence = affected or [row for row in evidence if str(row.get('page_id')) == page_id and row.get('engine') == 'sidecar']
            claimed = {(row.get('metadata') or {}).get('sidecar_producer', {}).get('claimed_engine') for row in page_evidence}
            versions = {(row.get('metadata') or {}).get('sidecar_producer', {}).get('claimed_version') for row in page_evidence}
            external_input = run_manifest.get('external_input_digests', {}).get('ocr_sidecar', {})
            return bool(
                page_evidence and None not in claimed and '' not in claimed and None not in versions and '' not in versions
                and resolution.get('producer_engine') in claimed
                and resolution.get('producer_version') in versions
                and resolution.get('input_sha256') == external_input.get('sha256')
                and re.fullmatch(r'[0-9a-f]{64}', str(resolution.get('input_sha256') or ''))
            )
        if method in {'rendered_rendition_attached', 'visual_representation_verified'}:
            page = page_by_id.get(page_id, {})
            return bool(
                resolution.get('artifact_path') == page.get('page_image_path')
                and resolution.get('sha256') == page.get('page_image_sha256')
                and bound_file(page.get('page_image_path'), page.get('page_image_sha256'))
            )
        if method == 'asset_ingested_and_hashed':
            asset = asset_by_id.get(str(finding.get('occurrence_id') or decision.get('target_id')))
            return bool(
                asset and resolution.get('artifact_path') == asset.get('asset_path')
                and resolution.get('sha256') == asset.get('asset_sha256')
                and bound_file(asset.get('asset_path'), asset.get('asset_sha256'))
            )
        if method == 'asset_quarantined':
            return bool(decision.get('disposition') in {'excluded', 'quarantined'} and decision.get('reason'))
        if method == 'page_quarantined':
            return bool(decision.get('disposition') == 'quarantined' and decision.get('reason'))
        if method in {'reading_order_verified', 'canonical_order_corrected'}:
            ordered = [str(value) for value in resolution.get('ordered_block_ids', [])]
            actual = [str(row.get('block_id')) for row in canonical_by_page.get(page_id, [])]
            if not ordered or ordered != actual:
                return False
            if method == 'canonical_order_corrected':
                return any(row.get('selection_status') == 'reviewed_reorder' for row in canonical_by_page.get(page_id, []))
            return decision.get('reviewer_type') == 'human'
        if method in {'visual_regions_reconciled', 'visual_transcription_verified', 'accepted_view_selected', 'alternate_variants_preserved'}:
            if method == 'visual_regions_reconciled' and (
                not isinstance(resolution.get('region_map'), list) or not resolution.get('region_map')
            ):
                return False
            return bool(
                decision.get('reviewer_type') == 'human' and referenced
                and all(str(row.get('page_id')) == page_id for row in referenced)
                and set(referenced_ids).issubset(canonical_evidence_ids)
            )
        if method == 'source_and_rendition_compared':
            conversion = manifest.get('profile', {}).get('conversion', {}) or read_json(package / 'source' / 'source_inventory.json').get('metadata', {}).get('conversion', {})
            return bool(
                decision.get('reviewer_type') == 'human'
                and resolution.get('source_sha256') == manifest.get('source', {}).get('sha256')
                and resolution.get('rendition_sha256') == conversion.get('converted_epub_sha256')
            )
        if method == 'navigation_target_reconciled':
            candidate_id = str(resolution.get('candidate_id') or finding.get('candidate_id') or '')
            candidate = toc_candidate_by_id.get(candidate_id)
            resolved_page = str(resolution.get('page_id') or '')
            dispositions = {
                str(row.get('candidate_id')): row for row in decision.get('candidate_dispositions', [])
                if isinstance(row, dict)
            }
            return bool(
                candidate and resolved_page in page_by_id and candidate_id in dispositions
                and dispositions[candidate_id].get('disposition') in {'used', 'excluded', 'reference_only'}
                and dispositions[candidate_id].get('reason')
            )
        return False

    def resolution_is_verified(decision: dict[str, Any] | None, finding: dict[str, Any]) -> bool:
        code = str(finding.get('kind'))
        if (
            not decision or not decision.get('semantic_reading') or code not in decision.get('resolves', [])
            or code not in RESOLUTION_METHODS
        ):
            return False
        for resolution in decision.get('resolution_evidence', []):
            if not isinstance(resolution, dict):
                continue
            if (
                resolution.get('code') == code and resolution.get('verified') is True
                and resolution.get('method') in RESOLUTION_METHODS[code]
                and resolution_method_is_backed(decision, resolution, finding)
            ):
                return True
        return False

    for finding in extraction_blockers:
        code = finding.get('kind') if isinstance(finding, dict) else str(finding)
        if code in delegated_to_v2_gates:
            continue
        if target == 'hint' and code in HINT_TOLERABLE_FINDINGS:
            warnings.append({'code': 'hint_unresolved_extraction_finding', 'finding': finding})
            continue
        page_id = finding.get('page_id') if isinstance(finding, dict) else None
        occurrence_id = finding.get('occurrence_id') if isinstance(finding, dict) else None
        object_id = finding.get('object_id') if isinstance(finding, dict) else None
        candidate_id = finding.get('candidate_id') if isinstance(finding, dict) else None
        decision = (
            decisions.get(('page', str(page_id))) if page_id
            else (decisions.get(('asset', str(occurrence_id))) if occurrence_id
                  else (decisions.get(('object', str(object_id))) if object_id
                        else (decisions.get(('structure', 'canonical')) if candidate_id else None)))
        )
        if not resolution_is_verified(decision, finding if isinstance(finding, dict) else {'kind': code}):
            unresolved_extraction.append(finding)
    check('extraction_findings_resolved', not unresolved_extraction, observed=unresolved_extraction, expected=[], blocker='unresolved_extraction_finding')

    if target in {'hint', 'review'}:
        # Hint/review outputs may be semantically incomplete, but they must
        # still fail closed on identity, integrity, extraction, and scope
        # failures collected above.
        status = 'pass' if pages and evidence and not hard else 'fail'
        trust_status = 'hint_only' if target == 'hint' else 'needs_review'
    else:
        external_binary_owners = {str(row.get('owner')) for row in external_binary_refs}
        check(
            'citation_evidence_tier', run_policy.get('target') in {'review', 'citation'},
            observed=run_policy.get('target'), expected='review or citation',
            blocker='hint_tier_requires_restoration_upgrade',
        )
        if manifest.get('source', {}).get('format') == 'pdf':
            missing_pdf_renditions = [p['page_id'] for p in pages if not p.get('page_image_path')]
            check(
                'pdf_visual_evidence_complete', not missing_pdf_renditions,
                observed=missing_pdf_renditions, expected=[], blocker='pdf_page_rendition_missing',
            )
        mock_evidence = [row.get('evidence_id') for row in evidence if row.get('engine') == 'mock']
        check('no_mock_evidence_for_citation', not mock_evidence, observed=mock_evidence[:100], expected=[], blocker='mock_ocr_not_citation_eligible')
        page_reviews_missing = []
        for page in pages:
            decision = decisions.get(('page', page['page_id']))
            allowed = {'reviewed', 'blank_confirmed'}
            if (
                not decision or decision.get('disposition') not in allowed
                or not decision.get('semantic_reading') or not decision.get('reason')
            ):
                page_reviews_missing.append(page['page_id'])
        check('manual_page_review', not page_reviews_missing, observed=page_reviews_missing, expected=[], blocker='manual_page_review_missing')
        external_page_evidence = [p['page_id'] for p in pages if str(p.get('page_id')) in external_binary_owners]
        check(
            'citation_page_evidence_preserved', not external_page_evidence,
            observed=external_page_evidence, expected=[], blocker='citation_page_binary_not_preserved',
        )

        paragraph_missing = []
        paragraph_invalid = []
        paragraph_ids = {str(row.get('paragraph_id')) for row in paragraphs}
        for paragraph in paragraphs:
            pid = paragraph['paragraph_id']
            decision = decisions.get(('paragraph', pid))
            if not decision:
                paragraph_missing.append(pid)
                continue
            disposition = decision.get('disposition')
            if disposition not in {'used', 'excluded', 'reference_only'} or not decision.get('semantic_reading'):
                paragraph_invalid.append(pid)
                continue
            required_text = ('source_id', 'sourcepage_path', 'semantic_summary', 'paragraph_role', 'reason')
            required_lists = ('claim_candidates', 'method_candidates', 'metric_candidates', 'boundary_candidates', 'reasoning_leap_candidates')
            if any(not decision.get(field) for field in required_text):
                paragraph_invalid.append(pid)
            if decision.get('source_id') != paragraph.get('source_id'):
                paragraph_invalid.append(pid)
            sourcepage_path = str(decision.get('sourcepage_path', ''))
            if str(paragraph.get('page_id')) not in sourcepage_path:
                paragraph_invalid.append(pid)
            if decision.get('paragraph_role') not in {'definition', 'mechanism', 'method', 'metric', 'case', 'boundary', 'caveat', 'reference_only', 'excluded'}:
                paragraph_invalid.append(pid)
            if any(not isinstance(decision.get(field), list) for field in required_lists):
                paragraph_invalid.append(pid)
            for leap in decision.get('reasoning_leap_candidates', []):
                if not isinstance(leap, dict):
                    paragraph_invalid.append(pid)
                    continue
                premise_ids = [str(value) for value in leap.get('premise_paragraph_ids', [])]
                conclusion_ids = [str(value) for value in leap.get('conclusion_paragraph_ids', [])]
                referenced_ids = premise_ids + conclusion_ids
                if (
                    not isinstance(leap.get('premises'), list) or not leap.get('premises')
                    or not leap.get('inference') or not leap.get('uncertainty')
                    or not premise_ids or any(value not in paragraph_ids for value in premise_ids)
                    or any(value not in paragraph_ids for value in conclusion_ids)
                    or disposition != 'used'
                    or any(
                        decisions.get(('paragraph', value), {}).get('disposition') != 'used'
                        for value in referenced_ids
                    )
                    or not isinstance(leap.get('assumptions'), list)
                    or not isinstance(leap.get('counterevidence'), list)
                    or not isinstance(leap.get('alternatives', []), list)
                    or not isinstance(leap.get('testable_predictions', []), list)
                    or not leap.get('novelty_context') or not leap.get('source_local_boundary')
                    or leap.get('reviewer_status') not in {'candidate', 'verified', 'rejected'}
                ):
                    paragraph_invalid.append(pid)
            if not isinstance(decision.get('used_in_card'), bool) or not isinstance(decision.get('requires_primary_anchor'), bool):
                paragraph_invalid.append(pid)
            if (
                decision.get('disposition') == 'used'
                and decision.get('requires_primary_anchor') is True
                and paragraph.get('source_role', 'primary') != 'primary'
            ):
                paragraph_invalid.append(pid)
        check('paragraph_semantic_coverage', not paragraph_missing, observed=paragraph_missing[:100], expected=[], blocker='paragraph_coverage_gap')
        check('paragraph_decision_integrity', not paragraph_invalid, observed=paragraph_invalid[:100], expected=[], blocker='paragraph_semantic_review_invalid')

        raw_by_id = {row.get('block_id'): row for row in raw_canonical}
        ranges_by_block: dict[str, list[tuple[int, int]]] = {str(block_id): [] for block_id in raw_by_id}
        orphan_spans = []
        invalid_span_anchors = []
        for paragraph in paragraphs:
            for span in paragraph.get('source_spans', []):
                if not isinstance(span, dict):
                    invalid_span_anchors.append(str(paragraph.get('paragraph_id')))
                    continue
                block_id = str(span.get('block_id'))
                if block_id not in raw_by_id:
                    orphan_spans.append(block_id)
                    continue
                raw_block = raw_by_id[block_id]
                raw_evidence_id = str(raw_block.get('evidence_id'))
                raw_evidence = evidence_by_id.get(raw_evidence_id)
                try:
                    start = int(span.get('start_offset', 0))
                    end = int(span.get('end_offset', 0))
                except (TypeError, ValueError):
                    invalid_span_anchors.append(block_id)
                    continue
                if (
                    str(span.get('evidence_id')) != raw_evidence_id
                    or str(span.get('page_id')) != str(raw_block.get('page_id'))
                    or not raw_evidence or str(raw_evidence.get('page_id')) != str(raw_block.get('page_id'))
                    or list(span.get('bbox', [])) != list(raw_block.get('bbox', []))
                    or start < 0 or end < start or end > len(raw_block.get('text', ''))
                ):
                    invalid_span_anchors.append(block_id)
                ranges_by_block[block_id].append((start, end))
        missing_spans = []
        duplicate_spans = []
        for block_id, block in raw_by_id.items():
            expected_end = len(block.get('text', ''))
            ranges = sorted(ranges_by_block[str(block_id)])
            if not ranges:
                missing_spans.append(block_id)
                continue
            cursor = 0
            valid = True
            for start, end in ranges:
                if start != cursor or end < start or end > expected_end:
                    valid = False
                    break
                cursor = end
            if cursor != expected_end:
                valid = False
            if not valid:
                duplicate_spans.append(block_id)
        orphan_spans = sorted(set(orphan_spans))
        check('paragraph_source_span_reversibility', not orphan_spans, observed=orphan_spans, expected=[], blocker='paragraph_anchor_gap')
        check(
            'paragraph_source_span_anchor_integrity', not invalid_span_anchors,
            observed=sorted(set(invalid_span_anchors)), expected=[], blocker='paragraph_anchor_integrity_invalid',
        )
        check('canonical_block_disposition_coverage', not missing_spans, observed=missing_spans, expected=[], blocker='unassigned_source_span')
        check('canonical_block_single_disposition', not duplicate_spans, observed=duplicate_spans, expected=[], blocker='overlapping_source_span')

        asset_invalid = []
        for asset in assets:
            aid = str(asset.get('occurrence_id'))
            decision = decisions.get(('asset', aid))
            if not decision or decision.get('disposition') not in {'used', 'excluded', 'reference_only'} or not decision.get('semantic_reading'):
                asset_invalid.append(aid)
            elif aid in external_binary_owners and decision.get('disposition') == 'used':
                asset_invalid.append(aid)
            elif decision.get('disposition') in {'used', 'reference_only'} and not bound_file(asset.get('asset_path'), asset.get('asset_sha256')):
                asset_invalid.append(aid)
            elif decision.get('disposition') in {'excluded', 'reference_only'} and not decision.get('reason'):
                asset_invalid.append(aid)
        check('asset_occurrence_accounting', not asset_invalid, observed=asset_invalid[:100], expected=[], blocker='asset_occurrence_review_gap')

        object_invalid = []
        for obj in objects:
            oid = str(obj.get('object_id'))
            decision = decisions.get(('object', oid))
            if not decision or decision.get('disposition') not in {'used', 'excluded', 'reference_only'} or not decision.get('semantic_reading'):
                object_invalid.append(oid)
                continue
            if decision.get('disposition') == 'used':
                if decision.get('representation_status') != 'verified':
                    object_invalid.append(oid)
                if obj.get('object_kind') in {'table', 'equation'} and not (decision.get('visual_verified') or decision.get('source_verified')):
                    object_invalid.append(oid)
                if obj.get('object_kind') in {'caption', 'figure'} and not decision.get('relations_reviewed'):
                    object_invalid.append(oid)
                if obj.get('object_kind') == 'figure':
                    for occurrence_id in obj.get('asset_occurrence_ids', []):
                        asset = asset_by_id.get(str(occurrence_id))
                        asset_decision = decisions.get(('asset', str(occurrence_id)))
                        if (
                            not asset or not asset_decision
                            or asset_decision.get('disposition') not in {'used', 'reference_only'}
                            or not bound_file(asset.get('asset_path'), asset.get('asset_sha256'))
                        ):
                            object_invalid.append(oid)
            elif not decision.get('reason'):
                object_invalid.append(oid)
        check('complex_object_accounting', not object_invalid, observed=object_invalid[:100], expected=[], blocker='complex_object_review_gap')

        structure = decisions.get(('structure', 'canonical'))
        structure_required = (
            len(pages) > 1 or manifest.get('source', {}).get('format') == 'epub'
            or run_policy.get('document_kind') in {'book', 'monograph', 'edited_volume'}
        )
        ordered_surfaces = [
            str(row.get('surface_id') or row.get('page_id'))
            for row in sorted(pages, key=lambda row: int(row.get('ordinal', 0)))
        ]
        expected_surfaces = set(ordered_surfaces)
        covered_surfaces = set(str(x) for x in (structure or {}).get('covered_surface_ids', []))
        structure_base_ok = bool(
            structure and structure.get('disposition') == 'reviewed' and structure.get('semantic_reading')
            and structure.get('reason')
            and (not structure_required or covered_surfaces == expected_surfaces)
        )
        check(
            'structure_semantic_review', (not structure_required) or structure_base_ok,
            observed=structure, expected='reviewed semantic structure covering every surface',
            blocker='structure_review_missing',
        )
        if structure_required and structure_base_ok:
            candidate_ids = {str(row.get('candidate_id')) for row in toc_candidates if row.get('candidate_id')}
            candidate_dispositions = structure.get('candidate_dispositions', [])
            disposition_by_id = {
                str(row.get('candidate_id')): row for row in candidate_dispositions
                if isinstance(row, dict) and row.get('candidate_id')
            }
            candidate_coverage_ok = bool(
                set(disposition_by_id) == candidate_ids
                and all(
                    row.get('disposition') in {'used', 'excluded', 'reference_only'} and row.get('reason')
                    for row in disposition_by_id.values()
                )
            )
            check(
                'structure_candidate_disposition_coverage', candidate_coverage_ok,
                observed=sorted(disposition_by_id), expected=sorted(candidate_ids),
                blocker='structure_candidate_coverage_gap',
            )

            boundaries = structure.get('boundaries', [])
            boundary_ids: list[str] = []
            ordered_paragraph_ids = [
                str(row.get('paragraph_id'))
                for row in sorted(paragraphs, key=lambda row: int(row.get('order', 0)))
            ]
            paragraph_by_id = {str(row.get('paragraph_id')): row for row in paragraphs}
            surfaces_with_paragraphs = {
                str(row.get('page_id')) for row in paragraphs if row.get('page_id')
            }
            textless_surfaces = [
                surface_id for surface_id in ordered_surfaces if surface_id not in surfaces_with_paragraphs
            ]
            flattened_paragraphs: list[str] = []
            assigned_textless_surfaces: list[str] = []
            boundary_surface_union: set[str] = set()
            boundaries_well_formed = isinstance(boundaries, list) and bool(boundaries)
            if boundaries_well_formed:
                for boundary in boundaries:
                    if not isinstance(boundary, dict):
                        boundaries_well_formed = False
                        break
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
                    structure_path = boundary.get('structure_path')
                    if (
                        not boundary_id or boundary_id in boundary_ids or not boundary.get('title')
                        or (not chapter_paragraphs and not chapter_textless)
                        or any(surface_id not in textless_surfaces for surface_id in chapter_textless)
                        or len(chapter_textless) != len(set(chapter_textless))
                        or chapter_surfaces != expected_chapter_surfaces
                        or not isinstance(structure_path, list) or not structure_path
                    ):
                        boundaries_well_formed = False
                        break
                    boundary_ids.append(boundary_id)
                    flattened_paragraphs.extend(chapter_paragraphs)
                    assigned_textless_surfaces.extend(chapter_textless)
                    boundary_surface_union.update(chapter_surfaces)
            boundaries_well_formed = bool(
                boundaries_well_formed and flattened_paragraphs == ordered_paragraph_ids
                and len(flattened_paragraphs) == len(set(flattened_paragraphs))
                and set(assigned_textless_surfaces) == set(textless_surfaces)
                and len(assigned_textless_surfaces) == len(set(assigned_textless_surfaces))
                and boundary_surface_union == set(ordered_surfaces)
            )
            check(
                'chapter_boundary_partition', boundaries_well_formed,
                observed=flattened_paragraphs, expected=ordered_paragraph_ids,
                blocker='chapter_boundary_invalid',
            )

            toc_items = structure.get('toc_items', [])
            toc_well_formed = isinstance(toc_items, list) and bool(toc_items)
            toc_ids: set[str] = set()
            mapped_boundary_ids: set[str] = set()
            mapped_candidate_ids: set[str] = set()
            if toc_well_formed:
                for item in toc_items:
                    item_id = str(item.get('toc_id') or '') if isinstance(item, dict) else ''
                    source_ids = [str(value) for value in item.get('source_candidate_ids', [])] if isinstance(item, dict) else []
                    if (
                        not item_id or item_id in toc_ids or not item.get('title')
                        or str(item.get('boundary_id') or '') not in set(boundary_ids)
                        or any(value not in candidate_ids for value in source_ids)
                    ):
                        toc_well_formed = False
                        break
                    toc_ids.add(item_id)
                    mapped_boundary_ids.add(str(item.get('boundary_id')))
                    mapped_candidate_ids.update(source_ids)
            used_candidate_ids = {
                candidate_id for candidate_id, row in disposition_by_id.items()
                if row.get('disposition') == 'used'
            }
            toc_well_formed = bool(
                toc_well_formed and mapped_boundary_ids == set(boundary_ids)
                and mapped_candidate_ids == used_candidate_ids
            )
            check(
                'canonical_toc_integrity', toc_well_formed,
                observed=toc_items, expected='non-empty unique TOC items mapped to reviewed boundaries',
                blocker='canonical_toc_invalid',
            )

        source_boundary = decisions.get(('source_boundary', manifest.get('source', {}).get('sha256', '')))
        boundary_ok = bool(source_boundary and source_boundary.get('text') and source_boundary.get('semantic_reading'))
        check('source_use_boundary', boundary_ok, observed=bool(source_boundary), expected=True, blocker='source_boundary_missing')

        reviewers = [d for d in decisions.values() if d.get('semantic_reading')]
        invalid_reviewers = []
        for decision in reviewers:
            valid = decision.get('reviewer_type') in {'human', 'agent_semantic'}
            if scope.get('privacy') in {'workspace', 'tenant'}:
                valid = bool(
                    valid
                    and decision.get('reviewer_attestation') == 'orchestrator_verified'
                    and decision.get('review_session_id')
                    and decision.get('reviewer_tenant_id') == scope.get('tenant_id')
                    and decision.get('reviewer_workspace_id') == scope.get('workspace_id')
                )
            if not valid:
                invalid_reviewers.append(decision.get('decision_id'))
        check('semantic_reviewer_provenance', not invalid_reviewers, observed=invalid_reviewers, expected=[], blocker='semantic_reviewer_provenance_invalid')

        status = 'pass' if not hard else 'needs_review'
        trust_status = 'citation_grade' if status == 'pass' else 'needs_review'

    public_status = (
        'PASS_STRICT' if status == 'pass' and target == 'citation'
        else ('HINT_READY' if status == 'pass' and target == 'hint'
              else ('REVIEW_READY' if status == 'pass' and target == 'review' else 'FAIL_REVIEW'))
    )
    report = {
        'schema_version': 2,
        'evaluated_at': utc_now(),
        'target': target,
        'status': status,
        'public_status': public_status,
        'trust_status': trust_status,
        'hard_blockers': hard,
        'warnings': warnings,
        'checks': checks,
        'counts': {
            'pages': len(pages),
            'evidence_blocks': len(evidence),
            'canonical_blocks': len(canonical),
            'paragraph_candidates': len(paragraphs),
            'assets': len(assets),
            'objects': len(objects),
            'review_decisions': len(decisions),
            'page_statuses': dict(Counter(p.get('status') for p in pages)),
        },
    }
    write_json(package / 'audit' / 'gates' / f'{target}.json', report)
    pass_fail = {
        'status': public_status,
        'trust_status': trust_status,
        'blocking_findings': hard,
        'evaluated_at': report['evaluated_at'],
        'derived_from': f'audit/gates/{target}.json',
    }
    write_json(package / 'audit' / f'pass_fail_{target}.json', pass_fail)
    canonical_report = package / 'audit' / 'gate_report.json'
    if target == 'citation' or not canonical_report.exists():
        write_json(canonical_report, report)
        write_json(package / 'audit' / 'pass_fail.json', pass_fail)
    return report
