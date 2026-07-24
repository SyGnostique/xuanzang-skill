from __future__ import annotations

import json
import re
import shutil
from bisect import bisect_right
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


def _source_block_ids(paragraph: dict[str, Any]) -> list[str]:
    return [
        str(span.get('block_id')) for span in paragraph.get('source_spans', [])
        if isinstance(span, dict) and span.get('block_id')
    ]


def _table_markdown(
    obj: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    cells = []
    for representation in obj.get('representations', []):
        if representation.get('kind') == 'table_cells' and isinstance(representation.get('value'), list):
            cells.extend(representation['value'])
    grouped: dict[tuple[int, int], list[str]] = {}
    exact_dom_text: dict[tuple[int, int], list[str]] = {}
    tags: dict[tuple[int, int], str] = {}
    for cell in cells:
        if cell.get('row') is None or cell.get('column') is None:
            continue
        key = (int(cell['row']), int(cell['column']))
        grouped.setdefault(key, [])
        text = str(cell.get('text') or '').strip()
        if text:
            grouped[key].append(text)
        evidence = (evidence_by_id or {}).get(str(cell.get('evidence_id')), {})
        container_text = str(
            cell.get('dom_container_text')
            or (evidence.get('metadata') or {}).get('dom_container_text')
            or ''
        )
        if container_text:
            # A cell can contain several block containers (for example, two
            # list items or paragraphs). Inline fragments from one container
            # repeat the same exact DOM text, so collapse adjacent repeats but
            # preserve distinct containers in source order.
            containers = exact_dom_text.setdefault(key, [])
            if not containers or containers[-1] != container_text:
                containers.append(container_text)
        tags[key] = str(cell.get('tag') or '')
    if not grouped:
        return str(obj.get('caption') or 'Table')
    max_row = max(row for row, _ in grouped)
    max_col = max(column for _, column in grouped)
    rows = []
    for row_index in range(max_row + 1):
        row = []
        for column_index in range(max_col + 1):
            key = (row_index, column_index)
            value = ' '.join(exact_dom_text[key]) if key in exact_dom_text else ' '.join(grouped.get(key, []))
            row.append(value.replace('|', '\\|').replace('\n', '<br>'))
        rows.append(row)
    first_is_header = any(tags.get((0, column)) == 'th' for column in range(max_col + 1))
    if first_is_header:
        header, body = rows[0], rows[1:]
    else:
        header = [f'Column {index + 1}' for index in range(max_col + 1)]
        body = rows
    lines = []
    if obj.get('caption'):
        lines.extend([f"**{obj['caption']}**", ''])
    lines.append('| ' + ' | '.join(header) + ' |')
    lines.append('| ' + ' | '.join(['---'] * len(header)) + ' |')
    lines.extend('| ' + ' | '.join(row) + ' |' for row in body)
    return '\n'.join(lines)


def _code_text(obj: dict[str, Any]) -> str:
    return next(
        (
            str(representation.get('value') or '')
            for representation in obj.get('representations', [])
            if representation.get('kind') == 'code_text'
        ),
        '',
    )


def _markdown_source_text(text: str) -> str:
    """Keep source text from being reinterpreted as document structure.

    Canonical headings are emitted separately from ``structure_path``. Literal
    source lines such as ``# of Shots`` or ``#### = four-digit padding`` are
    prose and must render as their original text rather than creating H1/H4
    nodes in the published derivative.
    """
    escaped = []
    for line in text.splitlines():
        line = re.sub(r'^( {0,3})(#{1,6})(?=\s|$)', r'\1\\\2', line)
        if re.fullmatch(r' {0,3}(?:={3,}|-{3,}|\*{3,}|_{3,})\s*', line):
            prefix = len(line) - len(line.lstrip(' '))
            line = line[:prefix] + '\\' + line[prefix:]
        escaped.append(line)
    return '\n'.join(escaped)


def _should_render_list_item(text: str, list_semantics: dict[str, Any] | None) -> bool:
    """Refuse to reinterpret bibliography years as ordered-list markers."""
    if not list_semantics:
        return False
    return not (
        list_semantics.get('kind') == 'ordered'
        and bool(re.match(r'^\d{4}[.)]\s+', text))
    )


def _normalized_external_href(href: str) -> str:
    """Repair unbalanced sentence punctuation without erasing source evidence."""
    normalized = href.strip()
    while normalized.endswith(')') and normalized.count(')') > normalized.count('('):
        normalized = normalized[:-1]
    return normalized


def _display_structure_heading(value: str) -> str:
    """Hide deterministic duplicate disambiguators from visible headings."""
    return re.sub(r'\s+\[[A-Za-z0-9_.-]+\]$', '', value).strip()


def _heading_key(value: str) -> str:
    return re.sub(r'[^\w]+', '', value).casefold()


def _published_canonical_items(
    canonical_items: list[dict[str, Any]], selected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only structure nodes that lead to citation-selected content."""
    selected_paths = [
        tuple(str(value) for value in paragraph.get('structure_path', []) if str(value))
        for paragraph in selected
        if paragraph.get('structure_path')
    ]
    if not canonical_items or not selected_paths:
        return []
    return [
        item for item in canonical_items
        if any(
            tuple(str(value) for value in item.get('structure_path', []))
            == selected_path[:len(item.get('structure_path', []))]
            for selected_path in selected_paths
        )
    ]


def _expected_canonical_headings(
    canonical_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expand canonical path transitions into the visible heading sequence."""
    expected: list[dict[str, Any]] = []
    current_path: list[str] = []
    emitted_paths: set[tuple[str, ...]] = set()
    for item in canonical_items:
        structure_path = [
            str(value) for value in item.get('structure_path', []) if str(value)
        ]
        common = 0
        while (
            common < len(current_path)
            and common < len(structure_path)
            and current_path[common] == structure_path[common]
        ):
            common += 1
        for level_index, heading in enumerate(
            structure_path[common:], start=common
        ):
            heading_path = tuple(structure_path[:level_index + 1])
            if heading_path in emitted_paths:
                continue
            expected.append({
                'title': _display_structure_heading(heading),
                # H1 is reserved for the book title. Materialized chapter/
                # section structure stays within H2/H3; deeper logical
                # hierarchy remains losslessly available in structure_path.
                'level': min(3, level_index + 2),
                'structure_path': structure_path[:level_index + 1],
            })
            emitted_paths.add(heading_path)
        current_path = structure_path
    return expected


def _source_list_semantics(
    paragraph: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Recover ordered/unordered list semantics from retained EPUB DOM ancestry."""
    for span in paragraph.get('source_spans', []):
        metadata = evidence_by_id.get(str(span.get('evidence_id')), {}).get('metadata', {})
        tags = [metadata.get('tag'), *metadata.get('ancestor_tags', [])]
        if 'li' not in tags:
            continue
        containers = [tag for tag in tags if tag in {'ol', 'ul'}]
        if not containers:
            continue
        nearest = containers[0]
        return {
            'kind': 'ordered' if nearest == 'ol' else 'unordered',
            'depth': len(containers),
            'marker': '1.' if nearest == 'ol' else '-',
        }
    return None


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
    review_gate = evaluate_gates(package, target='review')

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
        hint_paragraphs = (
            read_jsonl(package / 'ledger' / 'paragraph_candidates_reviewed.jsonl')
            or read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl')
        )
        for block in hint_paragraphs:
            selected.append({
                **block,
                'paragraph_id': block['paragraph_id'], 'page_id': block['page_id'],
                'page_anchor': block.get('page_anchor') or block['page_id'],
                'text_sha256': block.get('text_sha256') or sha256_text(block['text']),
                'coverage_status': 'hint_only',
            })

    md_path, chunks_path, manifest_path, embedding_path = _output_paths(out)
    canonical_projection = (
        read_json(package / 'toc' / 'canonical_toc.json')
        if (package / 'toc' / 'canonical_toc.json').is_file() else {}
    )
    canonical_items_for_render = canonical_projection.get('items', [])
    source_stem = Path(manifest.get('source', {}).get('path', 'document')).stem
    title = str(canonical_projection.get('document_title') or source_stem or 'Document').strip()
    lines = [
        '---',
        f'export_trust_status: {json.dumps(gate["trust_status"], ensure_ascii=False)}',
        f'package_review_status: {json.dumps(review_gate["public_status"], ensure_ascii=False)}',
        f'trust_status: {json.dumps(gate["trust_status"], ensure_ascii=False)}',
        f'package_id: {json.dumps(manifest.get("package_id"), ensure_ascii=False)}',
        f'run_id: {json.dumps(manifest.get("active_run_id"), ensure_ascii=False)}',
        '---', '',
        f'# {title}', '',
    ]
    chunks = []
    current_path: list[str] = []
    emitted_structure_headings: list[dict[str, Any]] = []
    emitted_structure_paths: set[tuple[str, ...]] = set()
    scope = manifest.get('scope', {})
    profile = manifest.get('profile', {})
    reviewed_objects = (
        read_jsonl(package / 'ledger' / 'objects_reviewed.jsonl')
        or read_jsonl(package / 'ledger' / 'objects.jsonl')
    )
    reviewed_assets = (
        read_jsonl(package / 'ledger' / 'assets_reviewed.jsonl')
        or read_jsonl(package / 'ledger' / 'assets.jsonl')
    )
    # Citation output contains only evidence explicitly marked ``used``.
    # ``reference_only`` remains fully preserved in the package ledgers, but
    # must not leak promotional, publication, contributor, or locator-only
    # objects and assets into citation chunks.
    if target == 'citation':
        used_object_asset_occurrences = {
            str(occurrence_id)
            for row in reviewed_objects
            if row.get('review_status') == 'used'
            for occurrence_id in row.get('asset_occurrence_ids', [])
            if occurrence_id
        }
        reviewed_objects = [
            row for row in reviewed_objects if row.get('review_status') == 'used'
        ]
        reviewed_assets = [
            row for row in reviewed_assets
            if (
                row.get('review_status') == 'used'
                or str(row.get('occurrence_id')) in used_object_asset_occurrences
            )
        ]
    evidence_by_id = {
        str(row.get('evidence_id')): row
        for row in read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')
    }
    surface_rows = read_jsonl(package / 'ledger' / 'surfaces.jsonl')
    surface_order = {
        str(row.get('surface_id') or row.get('page_id')): int(row.get('ordinal', 0))
        for row in surface_rows
    }
    spine_index_by_surface = {
        str(row.get('surface_id') or row.get('page_id')): int(row.get('spine_index', 0) or 0)
        for row in surface_rows
    }
    asset_dir = ensure_dir(md_path.parent / 'assets')
    asset_map_path = md_path.parent / 'assets.jsonl'
    object_map_path = md_path.parent / 'objects.jsonl'
    exported_assets = []
    exported_asset_by_occurrence: dict[str, dict[str, Any]] = {}
    # PDF figures are often assembled from a raster base plus vector labels.
    # Treat intersecting rectangles as one visual occurrence group before
    # ordering side-by-side figures. A global top/left sort can otherwise put
    # the right figure's overlay before the left figure's overlay.
    pdf_visual_rank: dict[str, tuple[int, int]] = {}
    pdf_assets_by_page: dict[str, list[dict[str, Any]]] = {}
    for asset in reviewed_assets:
        bbox = asset.get('bbox') or []
        if asset.get('dom_path') or len(bbox) != 4:
            continue
        pdf_assets_by_page.setdefault(str(asset.get('page_id')), []).append(asset)
    for page_assets in pdf_assets_by_page.values():
        parent = list(range(len(page_assets)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for left in range(len(page_assets)):
            left_bbox = [float(value) for value in page_assets[left]['bbox']]
            for right in range(left + 1, len(page_assets)):
                right_bbox = [float(value) for value in page_assets[right]['bbox']]
                horizontal_overlap = min(left_bbox[2], right_bbox[2]) > max(
                    left_bbox[0], right_bbox[0]
                )
                vertical_overlap = min(left_bbox[3], right_bbox[3]) > max(
                    left_bbox[1], right_bbox[1]
                )
                if horizontal_overlap and vertical_overlap:
                    union(left, right)
        components: dict[int, list[dict[str, Any]]] = {}
        for index, asset in enumerate(page_assets):
            components.setdefault(find(index), []).append(asset)
        ordered_components = sorted(
            components.values(),
            key=lambda rows: (
                int(min(float(row['bbox'][1]) for row in rows) // 6),
                min(float(row['bbox'][0]) for row in rows),
                min(float(row['bbox'][1]) for row in rows),
            ),
        )
        for component_rank, component in enumerate(ordered_components):
            for item_rank, asset in enumerate(sorted(
                component,
                key=lambda row: (
                    float(row['bbox'][1]), float(row['bbox'][0]),
                    float(row['bbox'][3]), float(row['bbox'][2]),
                    str(row.get('occurrence_id') or ''),
                ),
            )):
                pdf_visual_rank[str(asset.get('occurrence_id'))] = (
                    component_rank, item_rank
                )

    def asset_source_order_key(asset: dict[str, Any]) -> tuple[Any, ...]:
        bbox = asset.get('bbox') or []
        visual_position = (
            float(bbox[1]), float(bbox[0]), float(bbox[3]), float(bbox[2])
        ) if len(bbox) == 4 else (float('inf'),) * 4
        return (
            surface_order.get(str(asset.get('page_id')), 10**9),
            tuple(asset.get('dom_path') or ()),
            pdf_visual_rank.get(
                str(asset.get('occurrence_id')), (10**9, 10**9)
            ),
            visual_position,
            str(asset.get('occurrence_id') or ''),
        )

    # The extraction ledger is immutable, while the publication registry follows
    # source reading order. EPUB occurrences use DOM paths; born-digital PDF
    # occurrences use their page-space top/left bounding boxes.
    for asset in sorted(reviewed_assets, key=asset_source_order_key):
        if asset.get('review_status') not in {'used', 'reference_only'}:
            continue
        occurrence_id = str(asset.get('occurrence_id'))
        source_path = package / str(asset.get('asset_path') or '')
        if not source_path.is_file() or sha256_file(source_path) != asset.get('asset_sha256'):
            continue
        suffix = source_path.suffix.lower() or '.bin'
        export_rel = Path('assets') / f'{occurrence_id}{suffix}'
        export_path = md_path.parent / export_rel
        shutil.copy2(source_path, export_path)
        row = {
            **asset,
            'package_asset_path': asset.get('asset_path'),
            'export_path': export_rel.as_posix(),
            'asset_uri': f"xuanzang://package/{manifest.get('package_id')}/asset/{occurrence_id}",
            'export_sha256': sha256_file(export_path),
        }
        exported_assets.append(row)
        exported_asset_by_occurrence[occurrence_id] = row
    write_jsonl(asset_map_path, exported_assets)
    # Preserve the extractor's immutable occurrence order for assets that do not
    # carry a DOM path (notably born-digital PDF image/XObject occurrences).
    # Sorting such occurrences by their generated ids scrambles source order
    # inside a figure/object chunk even though coverage remains complete.
    asset_occurrence_source_rank = {
        str(asset.get('occurrence_id')): index
        for index, asset in enumerate(exported_assets)
    }

    objects_by_block: dict[str, list[dict[str, Any]]] = {}
    object_by_id = {str(obj.get('object_id')): obj for obj in reviewed_objects}
    required_visible_dom_anchor_ids = {
        str(representation.get('value'))[1:]
        for obj in reviewed_objects
        if obj.get('object_kind') == 'callout'
        for representation in obj.get('representations', [])
        if representation.get('kind') == 'callout_link'
        and str(representation.get('value') or '').startswith('#')
    }
    for obj in reviewed_objects:
        if obj.get('review_status') not in {'used', 'reference_only'}:
            continue
        for block_id in obj.get('source_block_ids', []):
            objects_by_block.setdefault(str(block_id), []).append(obj)
    exported_objects = []
    for obj in reviewed_objects:
        row = dict(obj)
        row['object_uri'] = f"xuanzang://package/{manifest.get('package_id')}/object/{obj.get('object_id')}"
        row['asset_export_paths'] = [
            exported_asset_by_occurrence[str(value)]['export_path']
            for value in obj.get('asset_occurrence_ids', [])
            if str(value) in exported_asset_by_occurrence
        ]
        exported_objects.append(row)
    write_jsonl(object_map_path, exported_objects)

    objects_by_occurrence: dict[str, list[dict[str, Any]]] = {}
    linked_asset_occurrences: set[str] = set()
    active_source_block_ids = {
        block_id for paragraph in selected for block_id in _source_block_ids(paragraph)
    }
    for obj in reviewed_objects:
        occurrences = [str(value) for value in obj.get('asset_occurrence_ids', []) if value]
        for occurrence_id in occurrences:
            objects_by_occurrence.setdefault(occurrence_id, []).append(obj)
            if set(str(value) for value in obj.get('source_block_ids', [])) & active_source_block_ids:
                linked_asset_occurrences.add(occurrence_id)

    # A born-digital PDF can mix caption-linked figures with other retained
    # image occurrences whose captions are side-positioned or absent.  Those
    # unlinked occurrences have no DOM path, so their immutable extraction
    # rank alone is not comparable with paragraph ``order``.  Record the
    # paragraph anchors of linked occurrences on each page; synthetic image
    # rows can then be placed immediately after the closest preceding linked
    # occurrence (or immediately before the closest following one).  This
    # preserves asset source order without inventing a figure-caption relation.
    linked_asset_anchors_by_page: dict[str, list[tuple[int, int]]] = {}
    linked_asset_ranks_by_paragraph: dict[str, list[int]] = {}
    for paragraph in selected:
        related_objects: dict[str, dict[str, Any]] = {}
        for block_id in _source_block_ids(paragraph):
            for obj in objects_by_block.get(block_id, []):
                related_objects[str(obj.get('object_id'))] = obj
        for object_id in paragraph.get('related_object_ids', []):
            obj = object_by_id.get(str(object_id))
            if obj:
                related_objects[str(obj.get('object_id'))] = obj
        page_id = str(paragraph.get('page_id') or paragraph.get('page_anchor') or '')
        paragraph_order = int(paragraph.get('order', 0))
        for obj in related_objects.values():
            for value in obj.get('asset_occurrence_ids', []):
                occurrence_id = str(value)
                if occurrence_id not in exported_asset_by_occurrence:
                    continue
                linked_asset_anchors_by_page.setdefault(page_id, []).append((
                    asset_occurrence_source_rank.get(occurrence_id, 10**9),
                    paragraph_order,
                ))
                linked_asset_ranks_by_paragraph.setdefault(
                    str(paragraph.get('paragraph_id')), []
                ).append(asset_occurrence_source_rank.get(occurrence_id, 10**9))
    for anchors in linked_asset_anchors_by_page.values():
        anchors.sort()
    boundary_path = package / 'toc' / 'chapter_boundary_map.json'
    boundary_map = read_json(boundary_path) if boundary_path.exists() else {'chapters': []}
    canonical_title_keys = {
        _heading_key(_display_structure_heading(str(boundary.get('title') or '')))
        for boundary in boundary_map.get('chapters', [])
        if boundary.get('title')
    }
    canonical_title_depths: dict[str, int] = {}
    for boundary in boundary_map.get('chapters', []):
        key = _heading_key(_display_structure_heading(str(boundary.get('title') or '')))
        if not key:
            continue
        depth = max(0, len(boundary.get('structure_path') or []) - 1)
        canonical_title_depths[key] = min(depth, canonical_title_depths.get(key, depth))
    path_by_surface = {}
    for boundary in boundary_map.get('chapters', []):
        for surface_id in boundary.get('surface_ids', []):
            path_by_surface.setdefault(str(surface_id), boundary.get('structure_path', [boundary.get('title')]))

    def paragraph_dom_path(paragraph: dict[str, Any]) -> tuple[int, ...]:
        paths = [
            tuple(int(value) for value in metadata.get('dom_path', []))
            for span in paragraph.get('source_spans', []) if isinstance(span, dict)
            for metadata in [evidence_by_id.get(str(span.get('evidence_id')), {}).get('metadata') or {}]
            if metadata.get('dom_path')
        ]
        return min(paths) if paths else ()

    paragraph_positions_by_surface: dict[str, list[tuple[tuple[int, ...], list[str]]]] = {}
    for paragraph in selected:
        dom_path = paragraph_dom_path(paragraph)
        if not dom_path:
            continue
        page_id = str(paragraph.get('page_id') or paragraph.get('page_anchor') or '')
        structure_path = [str(value) for value in paragraph.get('structure_path', []) if str(value)]
        paragraph_positions_by_surface.setdefault(page_id, []).append((dom_path, structure_path))
    for positions in paragraph_positions_by_surface.values():
        positions.sort(key=lambda row: row[0])

    def structure_path_at_dom(page_id: str, dom_path: tuple[int, ...]) -> list[str]:
        positions = paragraph_positions_by_surface.get(page_id, [])
        if positions and dom_path:
            index = bisect_right([row[0] for row in positions], dom_path) - 1
            if index >= 0 and positions[index][1]:
                return positions[index][1]
        return [str(value) for value in path_by_surface.get(page_id, [page_id]) if str(value)]

    synthetic_images = []
    for occurrence_id, asset in exported_asset_by_occurrence.items():
        if occurrence_id in linked_asset_occurrences:
            continue
        related = objects_by_occurrence.get(occurrence_id, [])
        representations = [
            representation for obj in related for representation in obj.get('representations', [])
            if representation.get('occurrence_id') == occurrence_id
        ]
        description = next((str(row.get('alt_text')) for row in representations if row.get('alt_text')), '')
        description = description or str(asset.get('caption_text') or Path(asset['export_path']).stem)
        page_id = str(asset.get('page_id'))
        asset_dom_path = tuple(int(value) for value in asset.get('dom_path', []) if value is not None)
        synthetic_image = {
            'paragraph_id': f'image_{occurrence_id}',
            'order': asset_occurrence_source_rank.get(occurrence_id, 10**9),
            'page_id': page_id,
            'page_anchor': page_id,
            'text': description,
            'text_sha256': sha256_text(description),
            'source_spans': [],
            'block_kind': 'image',
            'structure_path': structure_path_at_dom(page_id, asset_dom_path),
            '_source_dom_path': asset_dom_path,
            'related_object_ids': [obj.get('object_id') for obj in related],
            'asset_occurrence_ids_override': [occurrence_id],
            'coverage_status': 'hint_only',
            '_source_asset_rank': asset_occurrence_source_rank.get(occurrence_id, 10**9),
        }
        if not asset_dom_path:
            source_rank = asset_occurrence_source_rank.get(occurrence_id, 10**9)
            anchors = linked_asset_anchors_by_page.get(page_id, [])
            preceding = [row for row in anchors if row[0] < source_rank]
            following = [row for row in anchors if row[0] > source_rank]
            if preceding:
                _, anchor_order = max(preceding, key=lambda row: row[0])
                synthetic_image['_source_order_anchor'] = anchor_order
                synthetic_image['_source_order_phase'] = 1
            elif following:
                _, anchor_order = min(following, key=lambda row: row[0])
                synthetic_image['_source_order_anchor'] = anchor_order
                synthetic_image['_source_order_phase'] = -1
        synthetic_images.append(synthetic_image)
    selected.extend(synthetic_images)
    synthetic_links = []
    for obj in reviewed_objects:
        if (
            obj.get('object_kind') != 'link'
            or obj.get('source_block_ids')
            or obj.get('review_status') not in {'used', 'reference_only'}
        ):
            continue
        representation = next(
            (row for row in obj.get('representations', []) if row.get('kind') == 'pdf_link_annotation'),
            None,
        )
        target_value = representation.get('value', {}) if representation else {}
        target_text = str(
            target_value.get('uri') or target_value.get('destination_page_id')
            or target_value.get('named_target') or 'unresolved PDF link target'
        )
        page_id = str(obj.get('page_id'))
        synthetic_links.append({
            'paragraph_id': f"link_{obj.get('object_id')}",
            'order': -2,
            'page_id': page_id,
            'page_anchor': page_id,
            'text': f'PDF link annotation: {target_text}',
            'text_sha256': sha256_text(f'PDF link annotation: {target_text}'),
            'source_spans': [],
            'block_kind': 'link_annotation',
            'structure_path': path_by_surface.get(page_id, [page_id]),
            'related_object_ids': [obj.get('object_id')],
            'coverage_status': 'object_evidence',
        })
    selected.extend(synthetic_links)
    def publication_order_key(row: dict[str, Any]) -> tuple[Any, ...]:
        dom_path = tuple(row.get('_source_dom_path') or ()) or paragraph_dom_path(row)
        source_order = int(row.get('_source_order_anchor', row.get('order', 0)))
        source_order_phase = int(row.get('_source_order_phase', 0))
        source_asset_rank = int(row.get('_source_asset_rank', 10**9))
        return (
            surface_order.get(str(row.get('page_id')), 10**9),
            0 if dom_path else 1,
            dom_path if dom_path else (source_order, source_order_phase, source_asset_rank),
            1 if row.get('block_kind') == 'image' else 0,
            str(row.get('paragraph_id')),
        )

    selected.sort(key=publication_order_key)

    # Native PDF text extraction can report two captions on the same page in
    # an order that disagrees with the immutable visual asset occurrence
    # ledger.  Keep every asset-bearing row in its existing prose slot, but
    # order those rows within the page by the source asset rank.  This preserves
    # both nearby prose placement and the exact figure sequence.
    asset_row_indexes_by_page: dict[str, list[int]] = {}
    for index, row in enumerate(selected):
        paragraph_id = str(row.get('paragraph_id') or '')
        if (
            row.get('_source_asset_rank') is None
            and not linked_asset_ranks_by_paragraph.get(paragraph_id)
        ):
            continue
        page_id = str(row.get('page_id') or row.get('page_anchor') or '')
        asset_row_indexes_by_page.setdefault(page_id, []).append(index)
    for indexes in asset_row_indexes_by_page.values():
        ordered_rows = sorted(
            (selected[index] for index in indexes),
            key=lambda row: min(
                [
                    int(row.get('_source_asset_rank', 10**9)),
                    *linked_asset_ranks_by_paragraph.get(
                        str(row.get('paragraph_id') or ''), []
                    ),
                ]
            ),
        )
        for index, row in zip(indexes, ordered_rows):
            selected[index] = row

    table_by_block = {
        str(block_id): obj
        for obj in reviewed_objects if obj.get('object_kind') == 'table'
        for block_id in obj.get('source_block_ids', [])
    }
    paragraphs_by_block: dict[str, list[dict[str, Any]]] = {}
    for paragraph in selected:
        for block_id in _source_block_ids(paragraph):
            paragraphs_by_block.setdefault(block_id, []).append(paragraph)
    collapsed = []
    emitted_tables: set[str] = set()
    for paragraph in selected:
        table_objects = {
            str(table_by_block[block_id].get('object_id')): table_by_block[block_id]
            for block_id in _source_block_ids(paragraph) if block_id in table_by_block
        }
        if not table_objects:
            collapsed.append(paragraph)
            continue
        for object_id, table in table_objects.items():
            if object_id in emitted_tables:
                continue
            emitted_tables.add(object_id)
            table_paragraphs = []
            seen_paragraphs = set()
            for block_id in table.get('source_block_ids', []):
                for member in paragraphs_by_block.get(str(block_id), []):
                    if member.get('paragraph_id') not in seen_paragraphs:
                        table_paragraphs.append(member)
                        seen_paragraphs.add(member.get('paragraph_id'))
            table_paragraphs.sort(key=lambda row: int(row.get('order', 0)))
            source_spans = [
                span for member in table_paragraphs for span in member.get('source_spans', [])
            ]
            table_text = _table_markdown(table, evidence_by_id)
            seed = table_paragraphs[0] if table_paragraphs else paragraph
            collapsed.append({
                **seed,
                'paragraph_id': f'table_{object_id}',
                'source_paragraph_ids': [
                    str(member.get('paragraph_id')) for member in table_paragraphs
                    if member.get('paragraph_id')
                ],
                'text': table_text,
                'text_sha256': sha256_text(table_text),
                'source_spans': source_spans,
                'block_kind': 'table',
                'related_object_ids': [object_id],
            })
    selected = collapsed

    # A source ``pre`` may contain thousands of inline syntax-highlight spans
    # and embedded numbered callout images.  Paragraph joins are still retained
    # for reverse coverage, but publication projects the reviewed code object as
    # one source-faithful unit so whitespace and token adjacency cannot be lost.
    code_objects = [
        obj for obj in reviewed_objects
        if obj.get('object_kind') == 'code'
        and obj.get('review_status') in {'used', 'reference_only'}
    ]
    callout_objects = [
        obj for obj in reviewed_objects
        if obj.get('object_kind') == 'callout'
        and obj.get('review_status') in {'used', 'reference_only'}
    ]
    code_member_blocks: dict[str, list[str]] = {}
    code_related_objects: dict[str, list[str]] = {}
    code_by_block: dict[str, dict[str, Any]] = {}
    for code in code_objects:
        object_id = str(code.get('object_id'))
        page_id = str(code.get('page_id'))
        code_path = tuple(code.get('dom_path') or ())
        related_callouts = [
            callout for callout in callout_objects
            if str(callout.get('page_id')) == page_id
            and tuple(callout.get('dom_path') or ())[:len(code_path)] == code_path
        ]
        member_blocks = [str(value) for value in code.get('source_block_ids', []) if value]
        member_blocks.extend(
            str(value)
            for callout in related_callouts
            for value in callout.get('source_block_ids', [])
            if value
        )
        member_blocks = list(dict.fromkeys(member_blocks))
        code_member_blocks[object_id] = member_blocks
        code_related_objects[object_id] = [
            object_id, *[str(callout.get('object_id')) for callout in related_callouts]
        ]
        for block_id in member_blocks:
            code_by_block[block_id] = code

    paragraphs_by_block = {}
    for paragraph in selected:
        for block_id in _source_block_ids(paragraph):
            paragraphs_by_block.setdefault(block_id, []).append(paragraph)
    collapsed = []
    emitted_code: set[str] = set()
    for paragraph in selected:
        paragraph_codes = {
            str(code_by_block[block_id].get('object_id')): code_by_block[block_id]
            for block_id in _source_block_ids(paragraph) if block_id in code_by_block
        }
        if not paragraph_codes:
            collapsed.append(paragraph)
            continue
        for object_id, code in paragraph_codes.items():
            if object_id in emitted_code:
                continue
            emitted_code.add(object_id)
            code_paragraphs = []
            seen_paragraphs = set()
            for block_id in code_member_blocks.get(object_id, []):
                for member in paragraphs_by_block.get(block_id, []):
                    member_id = str(member.get('paragraph_id'))
                    if member_id not in seen_paragraphs:
                        code_paragraphs.append(member)
                        seen_paragraphs.add(member_id)
            code_paragraphs.sort(key=lambda row: int(row.get('order', 0)))
            code_text = _code_text(code)
            seed = code_paragraphs[0] if code_paragraphs else paragraph
            collapsed.append({
                **seed,
                'paragraph_id': f'code_{object_id}',
                'source_paragraph_ids': [
                    str(member.get('paragraph_id')) for member in code_paragraphs
                    if member.get('paragraph_id')
                ],
                'text': code_text,
                'text_sha256': sha256_text(code_text),
                'source_spans': [
                    span for member in code_paragraphs for span in member.get('source_spans', [])
                ],
                'block_kind': 'code',
                'related_object_ids': code_related_objects.get(object_id, [object_id]),
            })
    selected = collapsed
    canonical_items_for_render = _published_canonical_items(
        canonical_items_for_render, selected,
    )

    emitted_asset_occurrences: set[str] = set()
    emitted_dom_anchor_ids: set[str] = set()
    for order, paragraph in enumerate(selected, start=1):
        page = paragraph.get('page_id') or paragraph.get('page_anchor')
        structure_path = [str(value) for value in paragraph.get('structure_path', []) if str(value)]
        if not structure_path:
            structure_path = [str(page)]
        common = 0
        while common < len(current_path) and common < len(structure_path) and current_path[common] == structure_path[common]:
            common += 1
        for level_index, heading in enumerate(structure_path[common:], start=common):
            heading_path = tuple(structure_path[:level_index + 1])
            if heading_path in emitted_structure_paths:
                continue
            emitted_structure_headings.append({
                'title': _display_structure_heading(heading),
                'level': min(3, level_index + 2),
                'structure_path': structure_path[:level_index + 1],
            })
            emitted_structure_paths.add(heading_path)
            lines.extend([
                f'{"#" * min(3, level_index + 2)} {_display_structure_heading(heading)}',
                '',
            ])
        current_path = structure_path
        paragraph_text = paragraph.get('text', '')
        list_semantics = paragraph.get('list_semantics') or _source_list_semantics(paragraph, evidence_by_id)
        display_structure_path = [_display_structure_heading(value) for value in structure_path]
        title_key = _heading_key(display_structure_path[-1])
        paragraph_key = _heading_key(paragraph_text)
        heading_echo = (
            title_key == paragraph_key
            and paragraph.get('block_kind') in {
                'heading_candidate', 'structure_candidate', 'text_candidate', 'image',
            }
        )
        navigation_entry = bool(
            title_key in {'contents', 'tableofcontents'}
            and paragraph_key in canonical_title_keys
            and paragraph_key != title_key
        )
        suppress_visible_text = heading_echo or paragraph.get('block_kind') == 'image'
        source_dom_anchor_ids = []
        for span in paragraph.get('source_spans', []):
            if not isinstance(span, dict):
                continue
            metadata = evidence_by_id.get(str(span.get('evidence_id')), {}).get('metadata') or {}
            for value in metadata.get('ancestor_ids', []):
                anchor_id = str(value or '').strip()
                if anchor_id and anchor_id not in source_dom_anchor_ids:
                    source_dom_anchor_ids.append(anchor_id)
        for anchor_id in source_dom_anchor_ids:
            if anchor_id not in required_visible_dom_anchor_ids:
                continue
            if anchor_id in emitted_dom_anchor_ids:
                continue
            emitted_dom_anchor_ids.add(anchor_id)
            safe_anchor_id = re.sub(r'[^A-Za-z0-9_.:-]+', '-', anchor_id)
            lines.extend([f'<a id="{safe_anchor_id}"></a>', ''])
        if not suppress_visible_text:
            rendered_text = _markdown_source_text(paragraph_text)
            code_languages = {
                str((evidence_by_id.get(str(span.get('evidence_id')), {}).get('metadata') or {}).get('code_language'))
                for span in paragraph.get('source_spans', []) if isinstance(span, dict)
                if (evidence_by_id.get(str(span.get('evidence_id')), {}).get('metadata') or {}).get('code_language')
            }
            container_types = {
                str(value).casefold()
                for span in paragraph.get('source_spans', []) if isinstance(span, dict)
                for value in [
                    *((evidence_by_id.get(str(span.get('evidence_id')), {}).get('metadata') or {}).get('data_types', [])),
                    *((evidence_by_id.get(str(span.get('evidence_id')), {}).get('metadata') or {}).get('epub_types', [])),
                ]
                if value
            }
            if (
                paragraph.get('block_kind') == 'heading_candidate'
                and container_types & {
                    'tip', 'note', 'warning', 'caution', 'important', 'sidebar',
                    'example', 'figure', 'table', 'equation', 'footnote', 'footnotes',
                }
            ):
                rendered_text = f'**{rendered_text}**'
            if paragraph.get('block_kind') in {'code', 'code_candidate'}:
                language = sorted(code_languages)[0] if code_languages else ''
                rendered_text = f'```{language}\n{paragraph_text}\n```'
            elif navigation_entry:
                depth = min(4, canonical_title_depths.get(paragraph_key, 0))
                rendered_text = f'{"  " * depth}- {rendered_text}'
            elif _should_render_list_item(rendered_text, list_semantics):
                indent = '    ' * max(0, int(list_semantics['depth']) - 1)
                continuation = indent + '   '
                if list_semantics['kind'] == 'unordered':
                    rendered_text = re.sub(r'^[•◦▪‣]\s+', '', rendered_text, count=1)
                else:
                    rendered_text = re.sub(
                        r'^(?:\d{1,3}|[A-Za-z])[.)]\s+', '', rendered_text, count=1,
                    )
                rendered_text = (
                    f"{indent}{list_semantics['marker']} "
                    + rendered_text.replace('\n', '\n' + continuation)
                )
            lines.extend([rendered_text, ''])
        source_block_ids = [
            str(span.get('block_id')) for span in paragraph.get('source_spans', [])
            if isinstance(span, dict) and span.get('block_id')
        ]
        related_objects = []
        seen_object_ids = set()
        for block_id in source_block_ids:
            for obj in objects_by_block.get(block_id, []):
                object_id = str(obj.get('object_id'))
                if object_id not in seen_object_ids:
                    related_objects.append(obj)
                    seen_object_ids.add(object_id)
        for object_id in paragraph.get('related_object_ids', []):
            object_id = str(object_id)
            obj = object_by_id.get(object_id)
            if obj and object_id not in seen_object_ids:
                related_objects.append(obj)
                seen_object_ids.add(object_id)
        links = []
        seen_links = set()
        for span in paragraph.get('source_spans', []):
            if not isinstance(span, dict):
                continue
            evidence = evidence_by_id.get(str(span.get('evidence_id')), {})
            metadata = evidence.get('metadata') or {}
            href = str(metadata.get('link_href') or '')
            if not href:
                continue
            source_href = href
            if re.match(r'^(?:https?|mailto):', href, re.I):
                href = _normalized_external_href(href)
            key = (href, str(metadata.get('link_text') or evidence.get('text') or ''))
            if key in seen_links:
                continue
            seen_links.add(key)
            links.append({
                'href': href,
                'source_href': source_href,
                'text': key[1],
                'source_document': metadata.get('href'),
                'dom_path': metadata.get('dom_path'),
                'kind': 'external' if re.match(r'^(?:https?|mailto):', href, re.I) else 'internal_epub',
            })
        for obj in related_objects:
            if obj.get('object_kind') != 'callout':
                continue
            representation = next(
                (row for row in obj.get('representations', []) if row.get('kind') == 'callout_link'),
                None,
            )
            href = str((representation or {}).get('value') or '')
            if not href:
                continue
            key = (href, str(obj.get('source_id') or obj.get('object_id')))
            if key in seen_links:
                continue
            seen_links.add(key)
            links.append({
                'href': href,
                'text': str(obj.get('source_id') or 'code callout'),
                'source_document': page,
                'dom_path': (representation or {}).get('dom_path'),
                'object_id': obj.get('object_id'),
                'kind': 'internal_epub_callout',
            })
        for obj in related_objects:
            if obj.get('object_kind') != 'link':
                continue
            representation = next(
                (row for row in obj.get('representations', []) if row.get('kind') == 'pdf_link_annotation'),
                None,
            )
            target_value = representation.get('value', {}) if representation else {}
            href = str(target_value.get('uri') or '')
            destination_page_id = target_value.get('destination_page_id')
            named_target = target_value.get('named_target')
            if not href:
                href = (
                    f"xuanzang://package/{manifest.get('package_id')}/surface/{destination_page_id}"
                    if destination_page_id
                    else f"xuanzang://package/{manifest.get('package_id')}/named/{named_target}"
                )
            key = (href, str(named_target or destination_page_id or href), str(obj.get('object_id')))
            if key in seen_links:
                continue
            seen_links.add(key)
            links.append({
                'href': href,
                'text': key[1],
                'source_document': obj.get('source_locator'),
                'dom_path': None,
                'object_id': obj.get('object_id'),
                'kind': 'external' if re.match(r'^(?:https?|mailto):', href, re.I) else 'internal_pdf',
            })
        callout_links = [link for link in links if link['kind'] == 'internal_epub_callout']
        if callout_links:
            rendered_callouts = ', '.join(
                f"[{link['text']}]({link['href']})" for link in callout_links
            )
            lines.extend([f'Callout target: {rendered_callouts}', ''])
        candidate_asset_occurrence_ids = sorted({
            str(value) for obj in related_objects for value in obj.get('asset_occurrence_ids', []) if value
        } | {str(value) for value in paragraph.get('asset_occurrence_ids_override', []) if value}, key=lambda value: (
            0 if exported_asset_by_occurrence.get(value, {}).get('dom_path') else 1,
            tuple(exported_asset_by_occurrence.get(value, {}).get('dom_path') or ()),
            asset_occurrence_source_rank.get(value, 10**9),
            value,
        ))
        asset_occurrence_ids = [
            value for value in candidate_asset_occurrence_ids
            if value not in emitted_asset_occurrences
        ]
        emitted_asset_occurrences.update(asset_occurrence_ids)
        asset_export_paths = [
            exported_asset_by_occurrence[value]['export_path']
            for value in asset_occurrence_ids if value in exported_asset_by_occurrence
        ]
        if asset_export_paths:
            if paragraph.get('block_kind') == 'table':
                alt = next(
                    (
                        str(obj.get('caption')).strip()
                        for obj in related_objects
                        if obj.get('object_kind') == 'table' and str(obj.get('caption') or '').strip()
                    ),
                    'Source table',
                )
            else:
                alt = re.sub(r'[\[\]\n]+', ' ', paragraph_text).strip() or 'Source figure'
            for asset_path in asset_export_paths:
                lines.extend([f'![{alt}]({asset_path})', ''])
        raw_source_spans = [
            span for span in paragraph.get('source_spans', []) if isinstance(span, dict)
        ]
        enriched_source_spans = []
        for span in raw_source_spans:
            evidence = evidence_by_id.get(str(span.get('evidence_id')), {})
            metadata = evidence.get('metadata') or {}
            enriched_source_spans.append({
                **span,
                'source_text': evidence.get('text'),
                'source_text_sha256': evidence.get('text_sha256'),
                'dom_path': metadata.get('dom_path'),
                'href': metadata.get('href'),
                'raw_xhtml': metadata.get('raw_xhtml'),
                'tag': metadata.get('tag'),
                'ancestor_tags': metadata.get('ancestor_tags', []),
                'dom_container_text': metadata.get('dom_container_text'),
            })
        source_format = str(manifest.get('source', {}).get('format') or '').lower()
        canonical_normalized = re.sub(r'\s+', ' ', str(paragraph.get('text') or '')).strip()
        source_normalized = ' '.join(
            re.sub(r'\s+', ' ', str(span.get('source_text') or '')).strip()
            for span in enriched_source_spans
        ).strip()
        visual_text_correction = bool(
            enriched_source_spans and canonical_normalized != source_normalized
        )
        if not enriched_source_spans:
            source_reconstruction = None
        elif paragraph.get('block_kind') == 'table':
            source_reconstruction = {
                'operation': 'reviewed_table_object_projection',
                'separator_policy': 'one retained DOM-container text value per row-column cell',
                'normalization_steps': [
                    'group ordered evidence fragments by source table row and column',
                    'use retained dom_container_text to preserve inline adjacency and symbols',
                    'escape Markdown pipe characters without changing canonical cell text',
                ],
            }
        elif paragraph.get('block_kind') == 'code':
            source_reconstruction = {
                'operation': 'reviewed_code_object_projection',
                'separator_policy': 'object_representation_bound_to_ordered_source_spans',
                'normalization_steps': [],
            }
        elif source_format == 'pdf' and visual_text_correction:
            source_reconstruction = {
                'operation': 'reviewed_pdf_visual_text_correction',
                'separator_policy': 'ordered_pdf_source_blocks_with_rendered_page_verification',
                'normalization_steps': [
                    'preserve_ordered_pdf_block_ids_evidence_ids_bboxes_and_offsets',
                    'verify_corrected_text_against_the_bound_full_page_rendition',
                    'normalize_unicode_whitespace_without_inventing_source_claims',
                ],
            }
        elif source_format == 'pdf' and len(enriched_source_spans) > 1:
            source_reconstruction = {
                'operation': 'reviewed_pdf_source_block_join',
                'separator_policy': 'join_ordered_pdf_blocks_in_verified_reading_order',
                'normalization_steps': [
                    'preserve_ordered_pdf_block_ids_evidence_ids_bboxes_and_offsets',
                    'replace_each_unicode_whitespace_run_with_one_U+0020',
                    'strip_leading_and_trailing_whitespace',
                ],
            }
        elif len(enriched_source_spans) > 1:
            source_reconstruction = {
                'operation': 'reviewed_epub_dom_block_join',
                'separator_policy': 'resolve_shared_dom_block_and_read_source_text_nodes_in_dom_order',
                'normalization_steps': [
                    'concatenate_original_dom_text_nodes_in_order',
                    'materialize_each_source_br_element_as_a_whitespace_boundary',
                    'replace_each_unicode_whitespace_run_with_one_U+0020',
                    'strip_leading_and_trailing_whitespace',
                ],
            }
        else:
            source_reconstruction = {
                'operation': 'literal_source_span',
                'separator_policy': 'none',
                'normalization_steps': [],
            }
        if source_reconstruction is not None:
            source_reconstruction.update({
                'canonical_text_sha256': paragraph.get('text_sha256') or sha256_text(paragraph.get('text', '')),
                'ordered_evidence_ids': [str(span.get('evidence_id')) for span in enriched_source_spans],
                'source_span_count': len(enriched_source_spans),
            })
        chunks.append({
            'chunk_id': f"chunk_{sha256_text(paragraph.get('paragraph_id', '') + paragraph.get('text_sha256', ''))[:16]}",
            'order': order,
            'text': paragraph.get('text', ''),
            'text_sha256': paragraph.get('text_sha256') or sha256_text(paragraph.get('text', '')),
            'paragraph_ids': paragraph.get('source_paragraph_ids') or [paragraph.get('paragraph_id')],
            'source_spans': enriched_source_spans,
            'source_reconstruction': source_reconstruction,
            'page_anchor': paragraph.get('page_anchor') or page,
            'structure_path': structure_path,
            'block_kind': paragraph.get('block_kind'),
            'visible_projection': (
                'suppressed_structural_echo' if suppress_visible_text else 'rendered'
            ),
            'list_semantics': list_semantics,
            'object_ids': [obj.get('object_id') for obj in related_objects],
            'asset_occurrence_ids': asset_occurrence_ids,
            'asset_paths': asset_export_paths,
            'links': links,
            'source_dom_anchor_ids': source_dom_anchor_ids,
            'visual_anchors': [{
                'occurrence_id': occurrence_id,
                'asset_sha256': exported_asset_by_occurrence[occurrence_id].get('asset_sha256'),
                'asset_path': exported_asset_by_occurrence[occurrence_id].get('export_path'),
                'page_id': exported_asset_by_occurrence[occurrence_id].get('page_id'),
            } for occurrence_id in asset_occurrence_ids if occurrence_id in exported_asset_by_occurrence],
            'anchor_classification': (
                'source_text_span' if paragraph.get('source_spans')
                else (
                    'asset_occurrence_only' if asset_occurrence_ids
                    else ('pdf_link_annotation_only' if paragraph.get('block_kind') == 'link_annotation' else 'synthetic_structure')
                )
            ),
            'reversibility_status': (
                'source_spans_bound' if paragraph.get('source_spans')
                else (
                    'asset_sha256_page_occurrence_bound' if asset_occurrence_ids
                    else ('pdf_page_xref_bbox_bound' if paragraph.get('block_kind') == 'link_annotation' else 'synthetic_no_source_claim')
                )
            ),
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
            'package_review_status': review_gate['public_status'],
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

    referenced_occurrences = {
        str(value) for chunk in chunks for value in chunk.get('asset_occurrence_ids', []) if value
    }
    expected_occurrences = set(exported_asset_by_occurrence)
    occurrence_reference_counts = {
        occurrence_id: sum(
            1 for chunk in chunks if occurrence_id in chunk.get('asset_occurrence_ids', [])
        )
        for occurrence_id in sorted(expected_occurrences)
    }
    duplicate_occurrences = sorted(
        occurrence_id for occurrence_id, count in occurrence_reference_counts.items() if count > 1
    )
    expected_table_ids = {
        str(obj.get('object_id')) for obj in reviewed_objects if obj.get('object_kind') == 'table'
    }
    rendered_table_ids = {
        str(value) for chunk in chunks
        for value in chunk.get('object_ids', [])
        if str(value) in expected_table_ids
    }
    table_objects_by_id = {
        str(obj.get('object_id')): obj
        for obj in reviewed_objects if obj.get('object_kind') == 'table'
    }
    table_cell_dom_fidelity_violations = []
    for object_id, table in table_objects_by_id.items():
        expected_text = _table_markdown(table, evidence_by_id)
        matching_chunks = [
            chunk for chunk in chunks if object_id in chunk.get('object_ids', [])
            and chunk.get('block_kind') == 'table'
        ]
        if len(matching_chunks) != 1 or str(matching_chunks[0].get('text') or '') != expected_text:
            table_cell_dom_fidelity_violations.append({
                'object_id': object_id,
                'matching_chunk_ids': [str(chunk.get('chunk_id')) for chunk in matching_chunks],
                'expected_text_sha256': sha256_text(expected_text),
                'observed_text_sha256': (
                    sha256_text(str(matching_chunks[0].get('text') or ''))
                    if len(matching_chunks) == 1 else None
                ),
            })
    expected_external_link_object_ids = {
        str(obj.get('object_id')) for obj in reviewed_objects
        if obj.get('object_kind') == 'link'
        and obj.get('review_status') in {'used', 'reference_only'}
        and any(
            row.get('kind') == 'pdf_link_annotation'
            and re.match(r'^(?:https?|mailto):', str((row.get('value') or {}).get('uri') or ''), re.I)
            for row in obj.get('representations', [])
        )
    }
    rendered_external_link_object_ids = {
        str(link.get('object_id')) for chunk in chunks for link in chunk.get('links', [])
        if link.get('kind') == 'external' and link.get('object_id')
    }
    expected_callout_object_ids = {
        str(obj.get('object_id')) for obj in reviewed_objects
        if obj.get('object_kind') == 'callout'
        and obj.get('review_status') in {'used', 'reference_only'}
    }
    rendered_callout_object_ids = {
        str(link.get('object_id')) for chunk in chunks for link in chunk.get('links', [])
        if link.get('kind') == 'internal_epub_callout' and link.get('object_id')
    }
    expected_code_object_ids = {
        str(obj.get('object_id')) for obj in reviewed_objects
        if obj.get('object_kind') == 'code'
        and obj.get('review_status') in {'used', 'reference_only'}
    }
    rendered_code_object_ids = {
        str(value) for chunk in chunks if chunk.get('block_kind') in {'code', 'code_candidate'}
        for value in chunk.get('object_ids', [])
        if str(value) in expected_code_object_ids
    }
    callout_target_fragments = {
        str(link.get('href'))[1:]
        for chunk in chunks for link in chunk.get('links', [])
        if link.get('kind') == 'internal_epub_callout'
        and str(link.get('href') or '').startswith('#')
    }
    expected_occurrence_order = [str(row.get('occurrence_id')) for row in exported_assets]
    published_occurrence_order = [
        str(value) for chunk in chunks for value in chunk.get('asset_occurrence_ids', []) if value
    ]
    asset_dom_order_regressions = []
    last_dom_path_by_page: dict[str, tuple[int, ...]] = {}
    for chunk in chunks:
        dom_paths = [
            tuple(int(value) for value in span.get('dom_path', []))
            for span in chunk.get('source_spans', []) if span.get('dom_path')
        ]
        dom_paths.extend(
            tuple(int(value) for value in exported_asset_by_occurrence.get(str(occurrence_id), {}).get('dom_path', []))
            for occurrence_id in chunk.get('asset_occurrence_ids', [])
            if exported_asset_by_occurrence.get(str(occurrence_id), {}).get('dom_path')
        )
        if not dom_paths:
            continue
        page_id = str(chunk.get('page_anchor') or '')
        dom_path = min(dom_paths)
        previous = last_dom_path_by_page.get(page_id)
        if previous is not None and dom_path < previous:
            asset_dom_order_regressions.append({
                'page_id': page_id,
                'previous_dom_path': list(previous),
                'observed_dom_path': list(dom_path),
                'chunk_id': chunk.get('chunk_id'),
            })
        last_dom_path_by_page[page_id] = dom_path
    canonical_items = canonical_items_for_render
    # Markdown is emitted by walking paragraph paths. When the next
    # canonical item leaves one branch and enters another, ancestor headings
    # are emitted again to establish that branch. Build the expected sequence
    # with the same path-transition contract.
    expected_structure_headings = _expected_canonical_headings(canonical_items)
    canonical_heading_invariant_required = bool(
        target == 'citation'
        and canonical_items
        and all(
            int(item.get('level', 0) or 0) >= 1
            and bool(item.get('structure_path'))
            for item in canonical_items
        )
    )
    canonical_heading_mismatches = []
    for index in range(max(len(expected_structure_headings), len(emitted_structure_headings))):
        expected = expected_structure_headings[index] if index < len(expected_structure_headings) else None
        observed = emitted_structure_headings[index] if index < len(emitted_structure_headings) else None
        if expected != observed:
            canonical_heading_mismatches.append({
                'index': index,
                'expected': expected,
                'observed': observed,
            })
    source_inventory_path = package / 'source' / 'source_inventory.json'
    source_inventory = read_json(source_inventory_path) if source_inventory_path.is_file() else {}
    visibility_audit = (
        source_inventory.get('visibility_audit')
        or (source_inventory.get('metadata') or {}).get('visibility_audit')
        or {}
    )
    hidden_dom_paths = {
        (int(surface.get('spine_index', 0) or 0), tuple(int(value) for value in dom_path))
        for surface in visibility_audit.get('surfaces', [])
        for dom_path in surface.get('hidden_text_dom_paths', [])
    }
    css_hidden_chunk_leak_ids = []
    for chunk in chunks:
        page_id = str(chunk.get('page_anchor') or '')
        spine_index = spine_index_by_surface.get(page_id, 0)
        if any(
            (spine_index, tuple(int(value) for value in span.get('dom_path', []))) in hidden_dom_paths
            for span in chunk.get('source_spans', [])
            if span.get('dom_path')
        ):
            css_hidden_chunk_leak_ids.append(str(chunk.get('chunk_id')))
    numbered_heading_hierarchy_violations = []
    canonical_item_by_id = {
        str(item.get('toc_id')): item for item in canonical_items if item.get('toc_id')
    }
    for item in canonical_items:
        title = str(item.get('title') or '').strip()
        match = re.match(r'^\*?(\d+(?:\.\d+)+)\b', title)
        if not match:
            continue
        components = match.group(1).split('.')
        structure_path = [str(value) for value in item.get('structure_path', [])]
        parent_number = '.'.join(components[:-1])
        parent_item = canonical_item_by_id.get(str(item.get('parent_toc_id') or ''))
        parent_title = str((parent_item or {}).get('title') or '').lstrip('*')
        normalized_parent = re.sub(r'^Chapter\s+', '', parent_title, flags=re.I)
        parent_matches = bool(
            parent_item
            and re.match(
                rf'^{re.escape(parent_number)}(?=\b|\s*:|$)',
                normalized_parent,
                re.I,
            )
        )
        expected_level = int((parent_item or {}).get('level', 0)) + 1
        if int(item.get('level', 0)) != expected_level or not parent_matches:
            numbered_heading_hierarchy_violations.append({
                'toc_id': item.get('toc_id'),
                'title': title,
                'observed_level': item.get('level'),
                'expected_level': expected_level,
                'observed_parent': parent_title or None,
                'expected_parent_number': parent_number,
            })
    missing_source_reconstruction_chunk_ids = [
        str(chunk.get('chunk_id')) for chunk in chunks
        if chunk.get('source_spans') and not chunk.get('source_reconstruction')
    ]
    publication_validation = {
        'status': 'PASS',
        'asset_occurrences_expected': len(expected_occurrences),
        'asset_occurrences_referenced': len(referenced_occurrences),
        'missing_asset_occurrence_ids': sorted(expected_occurrences - referenced_occurrences),
        'asset_occurrence_reference_counts': occurrence_reference_counts,
        'duplicate_asset_occurrence_ids': duplicate_occurrences,
        'asset_occurrence_source_order_matches': published_occurrence_order == expected_occurrence_order,
        'asset_dom_order_regressions': asset_dom_order_regressions,
        'canonical_structure_headings_expected': len(expected_structure_headings),
        'canonical_structure_headings_emitted': len(emitted_structure_headings),
        'canonical_heading_invariant_required': canonical_heading_invariant_required,
        'canonical_heading_sequence_matches': not canonical_heading_mismatches,
        'canonical_heading_mismatches': canonical_heading_mismatches,
        'css_hidden_source_text_nodes': int(visibility_audit.get('hidden_text_nodes', 0) or 0),
        'css_hidden_dom_paths_audited': len(hidden_dom_paths),
        'css_hidden_content_excluded': not css_hidden_chunk_leak_ids,
        'css_hidden_chunk_leak_ids': css_hidden_chunk_leak_ids,
        'numbered_heading_hierarchy_violations': numbered_heading_hierarchy_violations,
        'missing_source_reconstruction_chunk_ids': missing_source_reconstruction_chunk_ids,
        'table_objects_expected': len(expected_table_ids),
        'table_objects_rendered': len(rendered_table_ids),
        'table_cell_dom_fidelity_violations': table_cell_dom_fidelity_violations,
        'missing_table_object_ids': sorted(expected_table_ids - rendered_table_ids),
        'external_links_rendered': sum(
            1 for chunk in chunks for link in chunk.get('links', []) if link.get('kind') == 'external'
        ),
        'external_link_annotations_expected': len(expected_external_link_object_ids),
        'external_link_annotations_referenced': len(rendered_external_link_object_ids),
        'missing_external_link_object_ids': sorted(
            expected_external_link_object_ids - rendered_external_link_object_ids
        ),
        'callout_links_expected': len(expected_callout_object_ids),
        'callout_links_referenced': len(rendered_callout_object_ids),
        'missing_callout_object_ids': sorted(
            expected_callout_object_ids - rendered_callout_object_ids
        ),
        'callout_target_fragments_expected': len(callout_target_fragments),
        'callout_target_fragments_materialized': len(
            callout_target_fragments & emitted_dom_anchor_ids
        ),
        'missing_callout_target_fragments': sorted(
            callout_target_fragments - emitted_dom_anchor_ids
        ),
        'code_objects_expected': len(expected_code_object_ids),
        'code_objects_rendered': len(rendered_code_object_ids),
        'missing_code_object_ids': sorted(
            expected_code_object_ids - rendered_code_object_ids
        ),
        'source_list_items_rendered': sum(bool(chunk.get('list_semantics')) for chunk in chunks),
    }
    if (
        publication_validation['missing_asset_occurrence_ids']
        or publication_validation['duplicate_asset_occurrence_ids']
        or publication_validation['missing_table_object_ids']
        or publication_validation['table_cell_dom_fidelity_violations']
        or publication_validation['missing_external_link_object_ids']
        or publication_validation['missing_callout_object_ids']
        or publication_validation['missing_callout_target_fragments']
        or publication_validation['missing_code_object_ids']
        or not publication_validation['asset_occurrence_source_order_matches']
        or publication_validation['asset_dom_order_regressions']
        or (
            publication_validation['canonical_heading_invariant_required']
            and publication_validation['canonical_heading_mismatches']
        )
        or publication_validation['css_hidden_chunk_leak_ids']
        or publication_validation['numbered_heading_hierarchy_violations']
        or publication_validation['missing_source_reconstruction_chunk_ids']
    ):
        publication_validation['status'] = 'FAIL_REVIEW'
    publication_validation_path = md_path.parent / 'publication_validation.json'
    write_json(publication_validation_path, publication_validation)
    if publication_validation['status'] != 'PASS':
        raise RuntimeError('published projection failed asset/table coverage validation')

    invalidation_key = sha256_text('|'.join([
        str(manifest.get('package_id')), str(manifest.get('active_run_id')),
        str(manifest.get('canonical_revision')), str(manifest.get('review_revision', '0')),
        target, sha256_file(chunks_path), sha256_file(asset_map_path), sha256_file(object_map_path),
        sha256_file(publication_validation_path),
    ]))
    embedding_manifest = {
        'schema_version': 2,
        'status': 'unembedded',
        'input': chunks_path.name,
        'input_sha256': sha256_file(chunks_path),
        'chunk_count': len(chunks),
        'invalidation_key': invalidation_key,
        'trust_status': gate['trust_status'],
        'package_review_status': review_gate['public_status'],
        'package_id': manifest.get('package_id'),
        'run_id': manifest.get('active_run_id'),
        'canonical_revision': manifest.get('canonical_revision'),
        'review_revision': manifest.get('review_revision', '0'),
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
        'package_review_status': review_gate['public_status'],
        'package_id': manifest.get('package_id'),
        'run_id': manifest.get('active_run_id'),
        'active_run_id': manifest.get('active_run_id'),
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
        'assets': asset_map_path.name,
        'assets_sha256': sha256_file(asset_map_path),
        'asset_count': len(exported_assets),
        'objects': object_map_path.name,
        'objects_sha256': sha256_file(object_map_path),
        'object_count': len(exported_objects),
        'publication_validation': publication_validation_path.name,
        'publication_validation_sha256': sha256_file(publication_validation_path),
        'embedding_manifest': embedding_path.name,
        'embedding_manifest_sha256': sha256_file(embedding_path),
        'chunk_count': len(chunks),
        'limitations': limitations,
        'created_at': utc_now(),
    }
    export['spec_sha256'] = sha256_text(json.dumps({
        'schema_version': export['schema_version'], 'export_kind': export['export_kind'],
        'target': target,
        'required_artifacts': ['document', 'chunks', 'assets', 'objects', 'publication_validation', 'embedding_manifest', 'gate_report'],
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
