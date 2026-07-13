from __future__ import annotations

import html
import json
import posixpath
import re
import shutil
import subprocess
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from .adapters import OCRAdapter
from .contracts import RestorePolicy, detect_source_format
from .epub import extract_epub
from .utils import (
    assert_safe_xml_bytes,
    contained_path,
    ensure_dir,
    read_json,
    read_jsonl,
    sha256_file,
    sha256_path,
    sha256_text,
    validate_zip_archive,
    write_json,
)

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp'}


@dataclass
class ExtractionResult:
    source_format: str
    metadata: dict[str, Any]
    pages: list[dict[str, Any]] = field(default_factory=list)
    evidence_blocks: list[dict[str, Any]] = field(default_factory=list)
    canonical_blocks: list[dict[str, Any]] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    toc_candidates: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)


def _stable_id(prefix: str, *parts: object) -> str:
    digest = sha256_text('|'.join(str(x) for x in parts))[:16]
    return f'{prefix}_{digest}'


def _kind(text: str, tag: str | None = None) -> str:
    normalized = ' '.join(text.split())
    low = normalized.lower()
    if tag and tag.lower() in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
        return 'heading_candidate'
    if re.match(r'^(chapter|part|book|section)\b', low) or re.match(r'^第[一二三四五六七八九十百0-9]+[章节部篇卷]', normalized):
        return 'heading_candidate'
    if re.match(r'^(fig(?:ure)?|table|图|表)\s*[0-9一二三四五六七八九十.-]+', normalized, re.I):
        return 'caption_candidate'
    if tag and tag.lower() in {'table', 'tr', 'td', 'th'}:
        return 'table_candidate'
    return 'text_candidate'


def _text_profile(text: str) -> tuple[list[str], str]:
    scripts = set()
    rtl = 0
    strong = 0
    for ch in text:
        code = ord(ch)
        if 0x3400 <= code <= 0x9FFF:
            scripts.add('Han')
        elif 0x3040 <= code <= 0x30FF:
            scripts.add('Kana')
        elif 0xAC00 <= code <= 0xD7AF:
            scripts.add('Hangul')
        elif 0x0600 <= code <= 0x06FF:
            scripts.add('Arabic')
        elif 0x0590 <= code <= 0x05FF:
            scripts.add('Hebrew')
        elif 0x0900 <= code <= 0x097F:
            scripts.add('Devanagari')
        elif 'LATIN' in unicodedata.name(ch, ''):
            scripts.add('Latin')
        bidi = unicodedata.bidirectional(ch)
        if bidi in {'R', 'AL'}:
            rtl += 1
            strong += 1
        elif bidi == 'L':
            strong += 1
    direction = 'rtl' if strong and rtl / strong > 0.5 else 'ltr'
    return sorted(scripts), direction


def _evidence(
    *, source_sha: str, page_id: str, ordinal: int, engine: str, engine_version: str | None,
    text: str, bbox: list[float], confidence: float | None, block_kind: str,
    coordinate_space: str, metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_id = _stable_id('ev', source_sha, page_id, engine, ordinal, text, bbox)
    scripts, direction = _text_profile(text)
    return {
        'evidence_id': evidence_id,
        'page_id': page_id,
        'ordinal': ordinal,
        'engine': engine,
        'engine_version': engine_version,
        'text': text,
        'text_sha256': sha256_text(text),
        'bbox': [round(float(x), 3) for x in bbox],
        'coordinate_space': coordinate_space,
        'confidence': confidence,
        'block_kind': block_kind,
        'variant_group_id': (metadata or {}).get('variant_group_id'),
        'scripts': scripts,
        'direction': (metadata or {}).get('text_direction', direction),
        'normalization_status': 'source_preserved',
        'metadata': metadata or {},
    }


def _canonical(evidence: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        'block_id': _stable_id('blk', evidence['page_id'], evidence['evidence_id']),
        'page_id': evidence['page_id'],
        'evidence_id': evidence['evidence_id'],
        'text': evidence['text'],
        'bbox': evidence['bbox'],
        'coordinate_space': evidence['coordinate_space'],
        'block_kind': evidence['block_kind'],
        'variant_group_id': evidence.get('variant_group_id'),
        'selection_status': 'machine_selected',
        'selection_reason': reason,
    }


def _apply_transcription_policy(result: ExtractionResult, policy: RestorePolicy) -> ExtractionResult:
    result.metadata['transcription_policy'] = policy.transcription
    for evidence in result.evidence_blocks:
        evidence.setdefault('metadata', {})['transcription_layer'] = 'source'
    if policy.transcription in {'source', 'diplomatic'}:
        return result

    evidence_by_id = {row['evidence_id']: row for row in result.evidence_blocks}
    derived = []
    for block in result.canonical_blocks:
        source_evidence = evidence_by_id.get(block.get('evidence_id'))
        if not source_evidence or source_evidence.get('engine') == 'unicode_normalization':
            continue
        source_text = source_evidence.get('text', '')
        normalized = unicodedata.normalize('NFC', source_text.replace('\r\n', '\n').replace('\r', '\n'))
        variant_group_id = source_evidence.get('variant_group_id') or _stable_id(
            'variant', source_evidence['evidence_id'], 'transcription',
        )
        source_evidence['variant_group_id'] = variant_group_id
        source_evidence.setdefault('metadata', {})['variant_group_id'] = variant_group_id
        normalized_evidence = _evidence(
            source_sha=str(result.metadata.get('source_sha256', '')),
            page_id=str(source_evidence.get('page_id')),
            ordinal=int(source_evidence.get('ordinal', 0)),
            engine='unicode_normalization',
            engine_version=unicodedata.unidata_version,
            text=normalized,
            bbox=list(source_evidence.get('bbox', [])),
            confidence=source_evidence.get('confidence'),
            block_kind=str(source_evidence.get('block_kind', 'text_candidate')),
            coordinate_space=str(source_evidence.get('coordinate_space', 'source')),
            metadata={
                'transcription_layer': 'normalized',
                'derived_from_evidence_id': source_evidence['evidence_id'],
                'normalization_form': 'Unicode NFC plus line-ending normalization',
                'source_text_sha256': source_evidence.get('text_sha256'),
                'variant_group_id': variant_group_id,
            },
        )
        normalized_evidence['normalization_status'] = 'normalized_variant_source_preserved'
        derived.append(normalized_evidence)
        block.update({
            'source_evidence_id': source_evidence['evidence_id'],
            'evidence_id': normalized_evidence['evidence_id'],
            'variant_group_id': variant_group_id,
            'text': normalized,
            'selection_status': 'machine_selected_normalized_variant',
            'selection_reason': f'{policy.transcription}_transcription_policy',
        })
    result.evidence_blocks.extend(derived)
    result.metadata['transcription_layers'] = ['source', 'normalized']
    return result


def _image_blank_candidate(path: Path) -> bool:
    try:
        from PIL import Image, ImageStat
        with Image.open(path) as im:
            stat = ImageStat.Stat(im.convert('L').resize((128, 128)))
            return bool(stat.stddev and stat.stddev[0] < 1.8 and stat.mean[0] > 245)
    except Exception:
        return False


def _native_usable(blocks: list[dict[str, Any]]) -> bool:
    text = ''.join(b['text'] for b in blocks)
    meaningful = sum(ch.isalnum() or '\u3400' <= ch <= '\u9fff' for ch in text)
    replacement = text.count('\ufffd')
    return meaningful >= 20 and replacement / max(1, len(text)) < 0.01


def extract_pdf_v2(source: Path, work: Path, policy: RestorePolicy, ocr: OCRAdapter | None) -> ExtractionResult:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError('PDF support requires PyMuPDF (`pip install PyMuPDF`)') from exc
    source_sha = sha256_file(source)
    result = ExtractionResult('pdf', {'source_sha256': source_sha})
    pages_dir = ensure_dir(work / 'assets' / 'pages')
    checkpoint_dir = ensure_dir(work / 'checkpoints' / 'pages')
    doc = fitz.open(str(source))
    if doc.page_count > policy.max_pages:
        page_count = doc.page_count
        doc.close()
        raise ValueError(f'PDF exceeds max_pages: {page_count} > {policy.max_pages}')
    result.metadata.update({'pages': doc.page_count, 'metadata': dict(doc.metadata or {})})
    try:
        for index, item in enumerate(doc.get_toc(simple=False) or [], start=1):
            level, title, destination_page = item[:3]
            result.toc_candidates.append({
                'candidate_id': f'pdf_outline_{index:05d}',
                'text': str(title), 'level': int(level),
                'page_id': f'page_{int(destination_page):04d}' if int(destination_page) > 0 else None,
                'source_page': int(destination_page) if int(destination_page) > 0 else None,
                'source': 'pdf_outline', 'status': 'needs_review',
                'confidence_signals': {'embedded_outline': True},
            })
    except Exception:
        result.metadata['pdf_outline_status'] = 'unavailable_or_malformed'
    rendered_pixels = 0
    for page_number, page in enumerate(doc, start=1):
        page_id = f'page_{page_number:04d}'
        checkpoint = checkpoint_dir / f'{page_id}.json'
        if checkpoint.exists():
            saved = read_json(checkpoint)
            if saved.get('page', {}).get('rendered_for_review'):
                scale = policy.render_dpi / 72
                rendered_pixels += int(
                    max(1, float(saved['page'].get('width', 0)) * scale)
                    * max(1, float(saved['page'].get('height', 0)) * scale)
                )
                if rendered_pixels > policy.max_total_pixels:
                    doc.close()
                    raise ValueError('resumed PDF render exceeds max_total_pixels')
            result.pages.append(saved['page'])
            result.evidence_blocks.extend(saved.get('evidence_blocks', []))
            result.canonical_blocks.extend(saved.get('canonical_blocks', []))
            result.assets.extend(saved.get('assets', []))
            result.blockers.extend(saved.get('blockers', []))
            continue
        evidence_start = len(result.evidence_blocks)
        canonical_start = len(result.canonical_blocks)
        asset_start = len(result.assets)
        blocker_start = len(result.blockers)
        native = []
        for ordinal, raw in enumerate(page.get_text('blocks') or [], start=1):
            if len(raw) < 5 or not str(raw[4]).strip():
                continue
            text = str(raw[4]).strip()
            ev = _evidence(
                source_sha=source_sha, page_id=page_id, ordinal=ordinal, engine='pdf_native', engine_version=fitz.VersionBind,
                text=text, bbox=[float(x) for x in raw[:4]], confidence=None, block_kind=_kind(text),
                coordinate_space='pdf_points', metadata={'block_number': raw[5] if len(raw) > 5 else ordinal},
            )
            native.append(ev)
        result.evidence_blocks.extend(native)
        native_ok = _native_usable(native)
        page_images = []
        covered_area = 0.0
        for image_info in page.get_images(full=True):
            xref = int(image_info[0])
            rects = page.get_image_rects(xref) or [page.rect]
            page_images.append((image_info, xref, rects))
            for rect in rects:
                covered_area += max(0.0, float(rect.width) * float(rect.height))
        page_area = max(1.0, float(page.rect.width) * float(page.rect.height))
        image_coverage_ratio = min(1.0, covered_area / page_area)
        mixed_visual = bool(native and image_coverage_ratio >= 0.12)
        left_column = [
            row for row in native
            if row.get('bbox') and (row['bbox'][0] + row['bbox'][2]) / 2 < float(page.rect.width) * 0.45
        ]
        right_column = [
            row for row in native
            if row.get('bbox') and (row['bbox'][0] + row['bbox'][2]) / 2 > float(page.rect.width) * 0.55
        ]
        multi_column = len(left_column) >= 2 and len(right_column) >= 2
        needs_ocr = policy.force_ocr or not native_ok
        needs_render = policy.target in {'review', 'citation'} or needs_ocr
        scale = policy.render_dpi / 72
        pix = None
        image_path = None
        if needs_render:
            rendered_pixels += int(max(1, page.rect.width * scale) * max(1, page.rect.height * scale))
            if rendered_pixels > policy.max_total_pixels:
                doc.close()
                raise ValueError(
                    f'PDF render exceeds max_total_pixels: {rendered_pixels} > {policy.max_total_pixels}'
                )
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image_path = pages_dir / f'{page_id}.png'
            pix.save(str(image_path))
        printed_page = None
        if hasattr(page, 'get_label'):
            try:
                printed_page = page.get_label() or None
            except Exception:
                printed_page = None
        page_row = {
            'page_id': page_id,
            'ordinal': page_number,
            'source_page': page_number,
            'printed_page': printed_page,
            'width': float(page.rect.width),
            'height': float(page.rect.height),
            'rotation': int(page.rotation),
            'coordinate_transforms': {
                'pdf_points_to_render_pixels': {
                    'scale_x': policy.render_dpi / 72,
                    'scale_y': policy.render_dpi / 72,
                    'rotation_degrees': int(page.rotation),
                }
            },
            'page_image_path': str(image_path.relative_to(work)) if image_path else None,
            'page_image_sha256': sha256_file(image_path) if image_path else None,
            'rendered_for_review': bool(image_path),
            'route': None,
            'status': 'pending',
            'quality_flags': [],
        }

        page_row['image_coverage_ratio'] = round(image_coverage_ratio, 4)
        ocr_blocks: list[dict[str, Any]] = []
        if needs_ocr and ocr is not None and image_path is not None and pix is not None:
            try:
                raw_blocks = ocr.recognize(image_path, lang=policy.lang, page_id=page_id)
                for ordinal, block in enumerate(raw_blocks, start=1):
                    bbox = block.bbox
                    bbox_valid = bool(
                        isinstance(bbox, list) and len(bbox) == 4
                        and 0 <= float(bbox[0]) <= float(bbox[2]) <= float(pix.width)
                        and 0 <= float(bbox[1]) <= float(bbox[3]) <= float(pix.height)
                        and (float(bbox[2]) > float(bbox[0]) or float(bbox[3]) > float(bbox[1]))
                    )
                    if not bbox_valid:
                        result.blockers.append({'kind': 'ocr_bbox_invalid', 'page_id': page_id, 'ordinal': ordinal, 'engine': ocr.name})
                    if getattr(ocr, 'requires_anchor_attestation', False):
                        supplied = (block.metadata or {}).get('source_image_sha256') or (block.metadata or {}).get('page_image_sha256')
                        actual = sha256_file(image_path)
                        if supplied != actual:
                            result.blockers.append({
                                'kind': (
                                    'sidecar_source_image_unverified' if ocr.name == 'sidecar'
                                    else 'external_ocr_source_image_unverified'
                                ), 'page_id': page_id,
                                'ordinal': ordinal, 'engine': ocr.name,
                            })
                    ocr_blocks.append(_evidence(
                        source_sha=source_sha, page_id=page_id, ordinal=ordinal, engine=ocr.name,
                        engine_version=ocr.version(), text=block.text, bbox=block.bbox,
                        confidence=block.confidence, block_kind=block.block_kind or _kind(block.text),
                        coordinate_space='render_pixels', metadata=block.metadata,
                    ))
                result.evidence_blocks.extend(ocr_blocks)
                if ocr_blocks and (ocr.name == 'sidecar' or getattr(ocr, 'requires_provenance_review', False)):
                    result.blockers.append({
                        'kind': (
                            'sidecar_provenance_requires_review' if ocr.name == 'sidecar'
                            else 'external_ocr_provenance_requires_review'
                        ), 'page_id': page_id,
                        'adapter_name': ocr.name, 'adapter_version': ocr.version(),
                        'producer_engine_claims': sorted({
                            str((block.get('metadata') or {}).get('sidecar_producer', {}).get('claimed_engine'))
                            for block in ocr_blocks
                        }),
                    })
            except Exception as exc:
                page_row['quality_flags'].append('ocr_failure')
                result.blockers.append({'kind': 'ocr_failure', 'page_id': page_id, 'message': str(exc), 'retryable': True})

        selected = native if native_ok else (ocr_blocks or native)
        reason = 'usable_native_text' if native_ok else (
            'ocr_required_for_weak_or_missing_text_layer' if ocr_blocks else ('weak_native_preserved_for_review' if native else 'none')
        )
        result.canonical_blocks.extend(_canonical(ev, reason) for ev in selected)
        if mixed_visual:
            page_row['quality_flags'].append('mixed_visual_region_requires_reconciliation')
            result.blockers.append({'kind': 'mixed_visual_region_requires_reconciliation', 'page_id': page_id})
        if multi_column:
            page_row['quality_flags'].append('multi_column_reading_order_requires_review')
            result.blockers.append({'kind': 'multi_column_reading_order_requires_review', 'page_id': page_id})

        image_occurrence = 0
        for image_info, xref, rects in page_images:
            try:
                extracted = doc.extract_image(xref)
                asset_bytes = extracted.get('image')
                extension = extracted.get('ext', 'bin')
            except Exception:
                asset_bytes, extension = None, 'bin'
            asset_path = None
            asset_sha = None
            if asset_bytes:
                asset_sha = __import__('hashlib').sha256(asset_bytes).hexdigest()
                target = ensure_dir(work / 'assets' / 'embedded') / f'{asset_sha}.{extension}'
                if not target.exists():
                    target.write_bytes(asset_bytes)
                asset_path = str(target.relative_to(work))
            for rect in rects:
                image_occurrence += 1
                occurrence_id = _stable_id('occ', source_sha, page_id, xref, image_occurrence)
                result.assets.append({
                    'asset_id': f'asset_{asset_sha[:16]}' if asset_sha else _stable_id('asset', source_sha, xref),
                    'occurrence_id': occurrence_id,
                    'page_id': page_id,
                    'asset_sha256': asset_sha,
                    'asset_path': asset_path,
                    'bbox': [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
                    'coordinate_space': 'pdf_points',
                    'kind': 'embedded_image',
                    'xref': xref,
                    'review_status': 'unreviewed',
                })
                if not asset_path or not asset_sha:
                    result.blockers.append({
                        'kind': 'missing_image_asset', 'occurrence_id': occurrence_id,
                        'page_id': page_id, 'xref': xref,
                    })

        if selected:
            page_row['status'] = 'extracted' if native_ok or ocr_blocks else 'needs_review'
            page_row['route'] = 'native_text' if native_ok and not ocr_blocks else ('hybrid' if native and ocr_blocks else ('ocr' if ocr_blocks else 'weak_native'))
            if native and not native_ok and not ocr_blocks:
                page_row['quality_flags'].append('weak_native_text_layer_unresolved')
                result.blockers.append({'kind': 'weak_native_text_layer_unresolved', 'page_id': page_id})
            confidences = [b['confidence'] for b in ocr_blocks if b['confidence'] is not None]
            if confidences and sum(confidences) / len(confidences) < 0.90:
                page_row['quality_flags'].append('low_ocr_confidence_unresolved')
                result.blockers.append({'kind': 'low_ocr_confidence_unresolved', 'page_id': page_id})
        elif _image_blank_candidate(image_path):
            page_row['status'] = 'blank_candidate'
            page_row['route'] = 'blank_review'
            page_row['quality_flags'].append('blank_requires_confirmation')
        else:
            page_row['status'] = 'unresolved'
            page_row['route'] = 'ocr_required'
            blocker = 'ocr_required_but_unavailable' if ocr is None else 'source_page_without_text'
            page_row['quality_flags'].append(blocker)
            result.blockers.append({'kind': blocker, 'page_id': page_id})
        result.pages.append(page_row)
        write_json(checkpoint, {
            'page': page_row,
            'evidence_blocks': result.evidence_blocks[evidence_start:],
            'canonical_blocks': result.canonical_blocks[canonical_start:],
            'assets': result.assets[asset_start:],
            'blockers': result.blockers[blocker_start:],
        })
    doc.close()
    return result


def _epub_resolve_href(
    tree_root: Path, referrer_archive_path: str, href: str, *, base_href: str | None = None,
) -> dict[str, Any]:
    """Resolve an OCF URL without granting filesystem or network authority."""
    raw_href = urlsplit(str(href).strip())
    raw_base = urlsplit(str(base_href).strip()) if base_href else None
    if raw_href.scheme or raw_href.netloc or (raw_base and (raw_base.scheme or raw_base.netloc)):
        return {
            'status': 'external', 'archive_path': None, 'fragment': raw_href.fragment,
            'query': raw_href.query, 'resolved_url': str(href),
        }
    root_url = f'https://xuanzang-epub.invalid/{str(referrer_archive_path).lstrip("/")}'
    base_url = urljoin(root_url, base_href) if base_href else root_url
    resolved = urljoin(base_url, str(href).strip())
    parsed = urlsplit(resolved)
    if parsed.scheme != 'https' or parsed.netloc != 'xuanzang-epub.invalid':
        return {
            'status': 'external', 'archive_path': None, 'fragment': parsed.fragment,
            'query': parsed.query, 'resolved_url': resolved,
        }
    archive_path = posixpath.normpath(unquote(parsed.path).lstrip('/'))
    if archive_path in {'', '.', '..'} or archive_path.startswith('../') or archive_path.startswith('/'):
        return {
            'status': 'invalid', 'archive_path': None, 'fragment': parsed.fragment,
            'query': parsed.query, 'resolved_url': resolved,
        }
    try:
        contained_path(tree_root, archive_path)
    except ValueError:
        return {
            'status': 'invalid', 'archive_path': None, 'fragment': parsed.fragment,
            'query': parsed.query, 'resolved_url': resolved,
        }
    return {
        'status': 'local', 'archive_path': archive_path, 'fragment': parsed.fragment,
        'query': parsed.query, 'resolved_url': resolved,
    }


def _epub_nav_type(nav: Any) -> str:
    for key, value in getattr(nav, 'attrs', {}).items():
        if str(key).split(':')[-1] == 'type':
            tokens = str(value).split()
            if 'toc' in tokens:
                return 'toc'
            if 'page-list' in tokens:
                return 'page-list'
            if 'landmarks' in tokens:
                return 'landmarks'
            if tokens:
                return tokens[0]
    return 'other'


def extract_epub_v2(source: Path, work: Path, policy: RestorePolicy) -> ExtractionResult:
    source_sha = sha256_file(source)
    result = ExtractionResult('epub', {'source_sha256': source_sha})
    with tempfile.TemporaryDirectory(prefix='xuanzang-epub-') as tmp:
        legacy = Path(tmp) / 'legacy'
        extract_epub(source, legacy)
        inventory = read_json(legacy / 'source' / 'source_inventory.json')
        result.metadata.update(inventory)
        tree_target = work / 'assets' / 'epub_tree'
        ensure_dir(tree_target.parent)
        shutil.copytree(legacy / 'source' / 'epub_tree', tree_target, dirs_exist_ok=True)
        blocks = read_jsonl(legacy / 'ledger' / 'source_blocks.jsonl')
        image_rows = read_jsonl(legacy / 'ledger' / 'image_blocks.jsonl')
        opf = inventory.get('opf', {})
        opf_rel = str(opf.get('opf_rel', ''))
        spine = list(opf.get('spine', []))
        global_fixed_layout = opf.get('metadata_properties', {}).get('rendition:layout') == 'pre-paginated'
        result.metadata['fixed_layout'] = global_fixed_layout
        result.metadata['spine_occurrence_count'] = len(spine)
        blocks_by_spine: dict[int, list[dict[str, Any]]] = {}
        images_by_spine: dict[int, list[dict[str, Any]]] = {}
        for block in blocks:
            blocks_by_spine.setdefault(int(block.get('spine_index', 0)), []).append(block)
        for image in image_rows:
            images_by_spine.setdefault(int(image.get('spine_index', 0)), []).append(image)

        page_map: dict[int, str] = {}
        spine_href_to_pages: dict[str, list[str]] = {}
        for spine_index, item in enumerate(spine, start=1):
            page_id = f'spine_{spine_index:04d}'
            page_map[spine_index] = page_id
            href = str(item.get('href', ''))
            media_type = str(item.get('media-type', ''))
            itemref = item.get('itemref', {}) if isinstance(item.get('itemref'), dict) else {}
            itemref_properties = str(itemref.get('properties', '')).split()
            manifest_properties = str(item.get('properties', '')).split()
            effective_fixed_layout = global_fixed_layout or 'rendition:layout-pre-paginated' in {
                *itemref_properties, *manifest_properties,
            }
            resolved = _epub_resolve_href(tree_target, opf_rel, href) if href else {
                'status': 'invalid', 'archive_path': None, 'fragment': '', 'query': '',
            }
            archive_href = resolved.get('archive_path')
            resource = contained_path(tree_target, archive_href) if archive_href else None
            resource_exists = bool(resource and resource.is_file())
            is_markup = 'html' in media_type or href.lower().endswith(('.xhtml', '.html', '.htm'))
            is_visual_resource = media_type.startswith('image/') or href.lower().endswith(tuple(IMAGE_SUFFIXES) + ('.svg',))
            has_text = bool(blocks_by_spine.get(spine_index))
            has_images = bool(images_by_spine.get(spine_index)) or is_visual_resource
            quality_flags: list[str] = []
            if resolved.get('status') != 'local' or not resource_exists:
                status = 'unresolved'
                route = 'epub_spine_unresolved'
                quality_flags.append('spine_resource_missing_or_invalid')
                result.blockers.append({
                    'kind': 'epub_spine_resource_missing_or_invalid', 'page_id': page_id,
                    'spine_index': spine_index, 'idref': item.get('idref'), 'href': href,
                })
            elif is_markup and has_text:
                status = 'extracted'
                route = 'epub_dom'
            elif (is_markup and has_images) or is_visual_resource:
                status = 'extracted'
                route = 'epub_dom_visual' if is_markup else 'epub_manifest_visual'
                quality_flags.append('visual_only_requires_rendered_evidence')
                result.blockers.append({
                    'kind': 'visual_only_spine_requires_rendered_evidence', 'page_id': page_id,
                    'spine_index': spine_index, 'href': archive_href,
                })
            elif is_markup:
                status = 'blank_candidate'
                route = 'blank_review'
                quality_flags.append('blank_requires_confirmation')
            else:
                status = 'unresolved'
                route = 'epub_spine_unsupported'
                quality_flags.append('unsupported_spine_media_type')
                result.blockers.append({
                    'kind': 'epub_spine_media_type_unsupported', 'page_id': page_id,
                    'spine_index': spine_index, 'media_type': media_type, 'href': archive_href,
                    'fallback': item.get('fallback'),
                })
            result.pages.append({
                'page_id': page_id, 'ordinal': spine_index, 'source_page': None,
                'spine_index': spine_index, 'idref': item.get('idref'),
                'href': archive_href, 'original_href': href, 'media_type': media_type,
                'linear': itemref.get('linear', 'yes'), 'itemref_properties': itemref_properties,
                'manifest_properties': manifest_properties, 'fallback': item.get('fallback'),
                'page_image_path': None, 'status': status, 'route': route,
                'quality_flags': quality_flags, 'effective_fixed_layout': effective_fixed_layout,
            })
            if archive_href:
                spine_href_to_pages.setdefault(archive_href, []).append(page_id)
            if effective_fixed_layout:
                result.blockers.append({
                    'kind': 'fixed_layout_requires_rendered_evidence', 'page_id': page_id,
                })

            if is_visual_resource and resource_exists:
                digest = sha256_file(resource)
                result.assets.append({
                    'asset_id': _stable_id('asset', source_sha, archive_href),
                    'occurrence_id': _stable_id('occ', source_sha, spine_index, archive_href),
                    'page_id': page_id, 'asset_path': f'assets/epub_tree/{archive_href}',
                    'asset_sha256': digest, 'kind': 'epub_spine_visual',
                    'href': archive_href, 'review_status': 'unreviewed', 'exists': True,
                })

        for ordinal, block in enumerate(blocks, start=1):
            spine_index = int(block.get('spine_index', 0))
            page_id = page_map.get(spine_index)
            if page_id is None:
                result.blockers.append({'kind': 'epub_block_surface_fk_invalid', 'spine_index': spine_index})
                continue
            ev = _evidence(
                source_sha=source_sha, page_id=page_id, ordinal=ordinal, engine='epub_dom', engine_version=None,
                text=block['text'], bbox=[], confidence=None, block_kind=block.get('block_kind', _kind(block['text'], block.get('tag'))),
                coordinate_space='dom_path', metadata={k: block.get(k) for k in ('href', 'dom_path', 'tag', 'class', 'raw_xhtml')},
            )
            result.evidence_blocks.append(ev)
            result.canonical_blocks.append(_canonical(ev, 'authoritative_epub_dom_text'))
        for image in image_rows:
            asset_rel = image.get('asset_path')
            try:
                asset_file = contained_path(tree_target, str(asset_rel)) if asset_rel else None
            except ValueError:
                asset_file = None
            asset_exists = bool(asset_file and asset_file.is_file())
            spine_index = int(image.get('spine_index', 0))
            result.assets.append({
                'asset_id': _stable_id('asset', source_sha, image.get('asset_path') or image.get('src')),
                'occurrence_id': _stable_id('occ', source_sha, image.get('spine_index'), image.get('dom_path'), image.get('src')),
                'page_id': page_map.get(spine_index),
                'asset_path': f"assets/epub_tree/{asset_rel}" if image.get('exists') and asset_exists else None,
                'asset_sha256': sha256_file(asset_file) if asset_exists else None,
                'dom_path': image.get('dom_path'),
                'href': image.get('href'),
                'kind': 'epub_image',
                'review_status': 'unreviewed',
                'exists': bool(image.get('exists') and asset_exists),
            })
            if result.assets[-1]['page_id'] is None:
                result.blockers.append({
                    'kind': 'epub_asset_surface_fk_invalid',
                    'occurrence_id': result.assets[-1]['occurrence_id'], 'spine_index': spine_index,
                })
            if not image.get('exists') or not asset_exists:
                result.blockers.append({'kind': 'missing_image_asset', 'occurrence_id': result.assets[-1]['occurrence_id']})

        seed = legacy / 'toc' / 'toc_candidates_seed.json'
        if seed.exists():
            for candidate in read_json(seed).get('candidates', []):
                row = dict(candidate)
                spine_index = int(row.get('spine_index', 0) or 0)
                row['page_id'] = page_map.get(spine_index)
                if row.get('href'):
                    resolved = _epub_resolve_href(tree_target, opf_rel, str(row['href']))
                    if resolved.get('archive_path'):
                        row['href'] = resolved['archive_path']
                result.toc_candidates.append(row)

        result.metadata['navigation_documents'] = []
        for item_id, item in opf.get('manifest', {}).items():
            href = str(item.get('href', ''))
            media_type = str(item.get('media-type', ''))
            properties = str(item.get('properties', '')).split()
            is_nav = 'nav' in properties
            is_ncx = media_type == 'application/x-dtbncx+xml' or href.lower().endswith('.ncx')
            if not href or not (is_nav or is_ncx):
                continue
            navigation_ref = _epub_resolve_href(tree_target, opf_rel, href)
            navigation_rel = navigation_ref.get('archive_path')
            if navigation_ref.get('status') != 'local' or not navigation_rel:
                result.blockers.append({'kind': 'epub_navigation_path_invalid', 'manifest_id': item_id})
                continue
            navigation_path = contained_path(tree_target, navigation_rel)
            if not navigation_path.is_file():
                result.blockers.append({'kind': 'epub_navigation_missing', 'manifest_id': item_id})
                continue
            data = navigation_path.read_bytes()
            try:
                assert_safe_xml_bytes(data, label=f'EPUB navigation {navigation_rel}')
            except ValueError as exc:
                result.blockers.append({
                    'kind': 'epub_navigation_unsafe_xml', 'manifest_id': item_id,
                    'message': str(exc),
                })
                continue
            result.metadata['navigation_documents'].append({
                'manifest_id': item_id, 'archive_path': navigation_rel,
                'navigation_kind': 'epub3_nav' if is_nav else 'epub2_ncx',
                'sha256': sha256_file(navigation_path),
            })

            def add_navigation_candidate(
                *, candidate_id: str, text: str, original_href: str,
                source_kind: str, navigation_type: str, depth: int, parent_id: str | None,
                order: int, base_href: str | None = None,
            ) -> None:
                target = _epub_resolve_href(
                    tree_target, navigation_rel, original_href, base_href=base_href,
                )
                canonical_href = target.get('archive_path')
                page_ids = spine_href_to_pages.get(str(canonical_href), []) if canonical_href else []
                page_id = page_ids[0] if len(page_ids) == 1 else None
                eligible = navigation_type == 'toc'
                if target.get('status') == 'external':
                    status = 'external_reference'
                elif target.get('status') != 'local':
                    status = 'invalid_target'
                elif not page_ids:
                    status = 'non_spine_target_needs_review'
                elif len(page_ids) > 1:
                    status = 'ambiguous_repeated_spine_target'
                else:
                    status = 'needs_review'
                result.toc_candidates.append({
                    'candidate_id': candidate_id, 'text': text, 'source': source_kind,
                    'navigation_type': navigation_type, 'candidate_role': (
                        'primary_navigation' if eligible else 'auxiliary_navigation'
                    ),
                    'eligible_for_toc': eligible, 'original_href': original_href,
                    'href': canonical_href or original_href.split('#', 1)[0],
                    'fragment': target.get('fragment'), 'query': target.get('query'),
                    'page_id': page_id, 'page_ids': page_ids, 'depth': depth,
                    'parent_id': parent_id, 'order': order, 'status': status,
                })
                if eligible and status in {'invalid_target', 'non_spine_target_needs_review', 'ambiguous_repeated_spine_target'}:
                    result.blockers.append({
                        'kind': 'epub_navigation_target_unresolved', 'candidate_id': candidate_id,
                        'status': status, 'href': original_href, 'page_ids': page_ids,
                    })

            if is_nav:
                try:
                    soup = BeautifulSoup(data, 'lxml-xml')
                except Exception as exc:
                    result.blockers.append({'kind': 'epub_navigation_malformed', 'manifest_id': item_id, 'message': str(exc)})
                    continue
                base = soup.find('base', href=True)
                base_href = str(base.get('href')) if base else None
                if base_href:
                    base_resolution = _epub_resolve_href(tree_target, navigation_rel, base_href)
                    if base_resolution.get('status') != 'local':
                        result.blockers.append({'kind': 'epub_navigation_base_invalid', 'manifest_id': item_id, 'href': base_href})
                nav_index = 0
                for nav in soup.find_all('nav'):
                    navigation_type = _epub_nav_type(nav)
                    last_by_depth: dict[int, str] = {}
                    for link in nav.find_all('a', href=True):
                        text = link.get_text(' ', strip=True)
                        if not text:
                            continue
                        nav_index += 1
                        depth = max(1, len(link.find_parents('li')))
                        candidate_id = f'epub_nav_{item_id}_{nav_index:05d}'
                        parent_id = last_by_depth.get(depth - 1)
                        last_by_depth[depth] = candidate_id
                        last_by_depth = {key: value for key, value in last_by_depth.items() if key <= depth}
                        add_navigation_candidate(
                            candidate_id=candidate_id, text=text,
                            original_href=str(link.get('href', '')), source_kind='epub_nav',
                            navigation_type=navigation_type, depth=depth, parent_id=parent_id,
                            order=nav_index, base_href=base_href,
                        )
            else:
                try:
                    root = ET.fromstring(data)
                except ET.ParseError as exc:
                    result.blockers.append({'kind': 'epub_navigation_malformed', 'manifest_id': item_id, 'message': str(exc)})
                    continue
                counter = 0

                def walk_ncx(points: list[ET.Element], depth: int, parent_id: str | None) -> None:
                    nonlocal counter
                    for point in points:
                        counter += 1
                        candidate_id = f'epub_ncx_{item_id}_{counter:05d}'
                        label = point.find('./{*}navLabel/{*}text')
                        content = point.find('./{*}content')
                        text = ''.join(label.itertext()).strip() if label is not None else ''
                        target_href = str(content.attrib.get('src', '')) if content is not None else ''
                        if text and target_href:
                            add_navigation_candidate(
                                candidate_id=candidate_id, text=text, original_href=target_href,
                                source_kind='epub_ncx', navigation_type='toc', depth=depth,
                                parent_id=parent_id, order=counter,
                            )
                        walk_ncx(point.findall('./{*}navPoint'), depth + 1, candidate_id)

                nav_map = root.find('.//{*}navMap')
                if nav_map is not None:
                    walk_ncx(nav_map.findall('./{*}navPoint'), 1, None)
    return result


def _extract_docx(source: Path, work: Path) -> ExtractionResult:
    source_sha = sha256_file(source)
    result = ExtractionResult('docx', {'source_sha256': source_sha, 'core_properties': {}})
    ns = {
        'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
        'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
        'pr': 'http://schemas.openxmlformats.org/package/2006/relationships',
    }
    w = f"{{{ns['w']}}}"
    r_embed = f"{{{ns['r']}}}embed"

    def safe_xml(data: bytes, *, label: str) -> ET.Element:
        assert_safe_xml_bytes(data, label=label)
        return ET.fromstring(data)

    def story_members(names: list[str]) -> list[str]:
        candidates = ['word/document.xml', 'word/footnotes.xml', 'word/endnotes.xml', 'word/comments.xml']
        candidates += sorted(n for n in names if re.match(r'word/(header|footer)[0-9]+\.xml$', n))
        return [name for name in candidates if name in names]

    def iter_blocks(root: ET.Element):
        body = root.find('w:body', ns)
        start = list(body) if body is not None else list(root)
        stack = list(reversed(start))
        while stack:
            node = stack.pop()
            local = node.tag.rsplit('}', 1)[-1]
            if local in {'p', 'tbl'}:
                yield node
                continue
            stack.extend(reversed(list(node)))

    def rels_for(zf: zipfile.ZipFile, story: str) -> dict[str, dict[str, Any]]:
        story_path = Path(story)
        rel_path = str(story_path.parent / '_rels' / f'{story_path.name}.rels')
        if rel_path not in zf.namelist():
            return {}
        root = safe_xml(zf.read(rel_path), label='DOCX relationships')
        return {
            el.attrib.get('Id', ''): {
                'target': el.attrib.get('Target', ''),
                'external': el.attrib.get('TargetMode', '').lower() == 'external',
            }
            for el in root.findall('pr:Relationship', ns)
        }

    with zipfile.ZipFile(source) as zf:
        validate_zip_archive(zf, label='DOCX')
        names = zf.namelist()
        if '[Content_Types].xml' not in names or 'word/document.xml' not in names:
            raise ValueError('invalid DOCX package')
        media_assets: dict[str, tuple[str, str]] = {}
        for name in names:
            if name.startswith('word/media/') and not name.endswith('/'):
                data = zf.read(name)
                digest = __import__('hashlib').sha256(data).hexdigest()
                target = ensure_dir(work / 'assets' / 'docx_media') / f'{digest[:16]}_{Path(name).name}'
                target.write_bytes(data)
                media_assets[name] = (digest, str(target.relative_to(work)))

        global_ordinal = 0
        for story_index, story in enumerate(story_members(names), start=1):
            story_kind = Path(story).stem
            page_id = f'docx_story_{story_index:03d}_{story_kind}'
            result.pages.append({
                'page_id': page_id, 'ordinal': story_index, 'source_page': None,
                'story_part': story, 'status': 'extracted', 'route': 'docx_ooxml', 'quality_flags': [],
            })
            root = safe_xml(zf.read(story), label=f'DOCX story {story}')
            relationships = rels_for(zf, story)
            for local_ordinal, node in enumerate(iter_blocks(root), start=1):
                global_ordinal += 1
                local = node.tag.rsplit('}', 1)[-1]
                deleted_text = ''.join(el.text or '' for el in node.findall('.//w:delText', ns)).strip()
                current_text = ''.join(el.text or '' for el in node.findall('.//w:t', ns)).strip()
                has_tracking = node.find('.//w:ins', ns) is not None or node.find('.//w:del', ns) is not None
                has_textbox = node.find('.//w:txbxContent', ns) is not None
                has_math = node.find('.//m:oMath', ns) is not None or node.find('.//m:oMathPara', ns) is not None
                metadata: dict[str, Any] = {
                    'story_part': story, 'xml_block_index': local_ordinal,
                    'tracked_changes': has_tracking, 'textbox': has_textbox, 'math': has_math,
                }
                if has_tracking or deleted_text:
                    metadata['variant_group_id'] = _stable_id(
                        'variant', source_sha, story, local_ordinal, 'tracked_change',
                    )
                if local == 'tbl':
                    rows = []
                    for tr in node.findall('./w:tr', ns):
                        cells = [''.join(t.text or '' for t in tc.findall('.//w:t', ns)).strip() for tc in tr.findall('./w:tc', ns)]
                        rows.append(cells)
                    current_text = '\n'.join(' | '.join(cells) for cells in rows).strip()
                    metadata['rows'] = rows
                    block_kind = 'table_candidate'
                else:
                    style_el = node.find('./w:pPr/w:pStyle', ns)
                    style = style_el.attrib.get(f'{w}val') if style_el is not None else None
                    metadata['style'] = style
                    block_kind = 'equation_candidate' if has_math and not current_text else _kind(current_text, 'h1' if style and 'heading' in style.lower() else 'p')
                if current_text:
                    ev = _evidence(
                        source_sha=source_sha, page_id=page_id, ordinal=global_ordinal, engine='docx_ooxml', engine_version=None,
                        text=current_text, bbox=[], confidence=None, block_kind=block_kind, coordinate_space='docx_xml', metadata=metadata,
                    )
                    result.evidence_blocks.append(ev)
                    result.canonical_blocks.append(_canonical(ev, 'authoritative_docx_current_view'))
                if deleted_text:
                    result.evidence_blocks.append(_evidence(
                        source_sha=source_sha, page_id=page_id, ordinal=global_ordinal, engine='docx_deleted_variant', engine_version=None,
                        text=deleted_text, bbox=[], confidence=None, block_kind=block_kind, coordinate_space='docx_xml',
                        metadata={**metadata, 'selection_status': 'alternate_deleted_text'},
                    ))
                if has_tracking:
                    result.blockers.append({'kind': 'tracked_changes_require_review', 'page_id': page_id, 'block_ordinal': local_ordinal})
                if has_textbox:
                    result.blockers.append({'kind': 'textbox_reading_order_requires_review', 'page_id': page_id, 'block_ordinal': local_ordinal})
                if has_math:
                    result.blockers.append({'kind': 'equation_representation_requires_review', 'page_id': page_id, 'block_ordinal': local_ordinal})

                for image_index, blip in enumerate(node.findall('.//a:blip', ns), start=1):
                    rel_id = blip.attrib.get(r_embed)
                    relationship = relationships.get(rel_id or '', {})
                    target_rel = str(relationship.get('target', ''))
                    external = bool(relationship.get('external'))
                    member = posixpath.normpath(posixpath.join(posixpath.dirname(story), target_rel.replace('\\', '/')))
                    safe_member = bool(
                        target_rel and not external and not target_rel.startswith('/')
                        and member.startswith('word/') and '..' not in Path(member).parts
                    )
                    asset = media_assets.get(member) if safe_member else None
                    digest, asset_path = asset if asset else (None, None)
                    result.assets.append({
                        'asset_id': f'asset_{digest[:16]}' if digest else _stable_id('asset', source_sha, story, rel_id),
                        'occurrence_id': _stable_id('occ', source_sha, story, local_ordinal, rel_id, image_index),
                        'page_id': page_id, 'asset_path': asset_path, 'asset_sha256': digest,
                        'kind': 'docx_image', 'relationship_id': rel_id, 'relationship_target': target_rel,
                        'external_reference': external, 'relationship_safe': safe_member,
                        'xml_block_index': local_ordinal, 'review_status': 'unreviewed', 'exists': bool(asset),
                    })
                    if not asset:
                        result.blockers.append({
                            'kind': 'external_image_reference_requires_review' if external else (
                                'unsafe_relationship_target' if not safe_member else 'missing_image_asset'
                            ),
                            'occurrence_id': result.assets[-1]['occurrence_id'], 'page_id': page_id,
                        })
    if not result.evidence_blocks:
        result.blockers.append({'kind': 'source_coverage_gap'})
    return result


def _extract_textual(source: Path, source_format: str) -> ExtractionResult:
    source_sha = sha256_file(source)
    raw = source.read_text(encoding='utf-8', errors='replace')
    if source_format == 'html':
        soup = BeautifulSoup(raw, 'lxml')
        blocks = [(node.name, node.get_text(' ', strip=True)) for node in soup.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li', 'figcaption', 'table'])]
    else:
        blocks = []
        for chunk in re.split(r'\n\s*\n', raw):
            text = chunk.strip()
            if text:
                tag = 'h1' if text.startswith('# ') else ('h2' if text.startswith('## ') else 'p')
                blocks.append((tag, text.lstrip('# ').strip()))
    result = ExtractionResult(source_format, {'source_sha256': source_sha})
    page_id = 'document_0001'
    result.pages.append({'page_id': page_id, 'ordinal': 1, 'source_page': None, 'status': 'extracted', 'route': source_format, 'quality_flags': []})
    for ordinal, (tag, text) in enumerate(blocks, start=1):
        if not text:
            continue
        ev = _evidence(
            source_sha=source_sha, page_id=page_id, ordinal=ordinal, engine=f'{source_format}_native', engine_version=None,
            text=html.unescape(text), bbox=[], confidence=None, block_kind=_kind(text, tag), coordinate_space=source_format,
            metadata={'tag': tag},
        )
        result.evidence_blocks.append(ev)
        result.canonical_blocks.append(_canonical(ev, f'authoritative_{source_format}_text'))
    if not result.evidence_blocks:
        result.blockers.append({'kind': 'source_coverage_gap', 'page_id': page_id})
    return result


def _extract_images(source: Path, work: Path, policy: RestorePolicy, ocr: OCRAdapter | None) -> ExtractionResult:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError('image support requires Pillow') from exc
    paths = [source] if source.is_file() else sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not paths:
        raise ValueError('image directory contains no supported images')
    source_sha = sha256_text('|'.join(sha256_file(p) for p in paths))
    result = ExtractionResult('image_directory' if source.is_dir() else 'image', {'source_sha256': source_sha, 'input_count': len(paths)})
    target_dir = ensure_dir(work / 'assets' / 'pages')
    originals_dir = ensure_dir(work / 'assets' / 'original_images')
    frames = []
    total_pixels = 0
    original_refs = {}
    for path in paths:
        digest = sha256_file(path)
        original = originals_dir / f'{digest[:16]}{path.suffix.lower()}'
        if not original.exists():
            shutil.copy2(path, original)
        original_refs[path] = (digest, str(original.relative_to(work)))
        try:
            with Image.open(path) as im:
                frame_count = int(getattr(im, 'n_frames', 1))
                if len(frames) + frame_count > policy.max_pages:
                    raise ValueError(f'image input exceeds max_pages: {len(frames) + frame_count} > {policy.max_pages}')
                for frame_index in range(frame_count):
                    im.seek(frame_index)
                    frame_pixels = im.width * im.height
                    if frame_pixels > int(Image.MAX_IMAGE_PIXELS or 178956970):
                        raise ValueError(f'image exceeds safe pixel limit: {path} frame {frame_index}')
                    total_pixels += frame_pixels
                    if total_pixels > policy.max_total_pixels:
                        raise ValueError(
                            f'image input exceeds max_total_pixels: {total_pixels} > {policy.max_total_pixels}'
                        )
        except Image.DecompressionBombError as exc:
            raise ValueError(f'image decompression bomb rejected: {path}') from exc
        frames.extend((path, frame_index) for frame_index in range(frame_count))
    result.metadata['surface_count'] = len(frames)
    if len(frames) > policy.max_pages:
        raise ValueError(f'image input exceeds max_pages: {len(frames)} > {policy.max_pages}')
    for page_number, (path, frame_index) in enumerate(frames, start=1):
        page_id = f'page_{page_number:04d}'
        target = target_dir / f'{page_id}.png'
        with Image.open(path) as im:
            im.seek(frame_index)
            frame = ImageOps.exif_transpose(im.copy())
            if frame.mode in {'RGBA', 'LA'}:
                canvas = Image.new('RGB', frame.size, 'white')
                alpha = frame.getchannel('A')
                canvas.paste(frame.convert('RGB'), mask=alpha)
                frame = canvas
            elif frame.mode not in {'RGB', 'L'}:
                frame = frame.convert('RGB')
            width, height = frame.size
            frame.save(target, format='PNG')
        original_sha, original_path = original_refs[path]
        page = {
            'page_id': page_id, 'ordinal': page_number, 'source_page': page_number,
            'width': width, 'height': height, 'page_image_path': str(target.relative_to(work)),
            'page_image_sha256': sha256_file(target), 'route': 'ocr_required', 'status': 'pending', 'quality_flags': [],
            'original_image_path': original_path, 'original_image_sha256': original_sha,
            'original_filename': path.name, 'frame_index': frame_index,
            'coordinate_transforms': {'original_to_normalized': {'exif_transpose_applied': True}},
        }
        blocks = []
        if ocr is not None:
            try:
                for ordinal, block in enumerate(ocr.recognize(target, lang=policy.lang, page_id=page_id), start=1):
                    bbox = block.bbox
                    bbox_valid = bool(
                        isinstance(bbox, list) and len(bbox) == 4
                        and 0 <= float(bbox[0]) <= float(bbox[2]) <= float(width)
                        and 0 <= float(bbox[1]) <= float(bbox[3]) <= float(height)
                        and (float(bbox[2]) > float(bbox[0]) or float(bbox[3]) > float(bbox[1]))
                    )
                    if not bbox_valid:
                        result.blockers.append({'kind': 'ocr_bbox_invalid', 'page_id': page_id, 'ordinal': ordinal, 'engine': ocr.name})
                    if getattr(ocr, 'requires_anchor_attestation', False):
                        supplied = (block.metadata or {}).get('source_image_sha256') or (block.metadata or {}).get('page_image_sha256')
                        if supplied != sha256_file(target):
                            result.blockers.append({
                                'kind': (
                                    'sidecar_source_image_unverified' if ocr.name == 'sidecar'
                                    else 'external_ocr_source_image_unverified'
                                ), 'page_id': page_id,
                                'ordinal': ordinal, 'engine': ocr.name,
                            })
                    blocks.append(_evidence(
                        source_sha=source_sha, page_id=page_id, ordinal=ordinal, engine=ocr.name, engine_version=ocr.version(),
                        text=block.text, bbox=block.bbox, confidence=block.confidence,
                        block_kind=block.block_kind or _kind(block.text), coordinate_space='render_pixels', metadata=block.metadata,
                    ))
            except Exception as exc:
                result.blockers.append({'kind': 'ocr_failure', 'page_id': page_id, 'message': str(exc), 'retryable': True})
        result.evidence_blocks.extend(blocks)
        if blocks and ocr is not None and (ocr.name == 'sidecar' or getattr(ocr, 'requires_provenance_review', False)):
            result.blockers.append({
                'kind': (
                    'sidecar_provenance_requires_review' if ocr.name == 'sidecar'
                    else 'external_ocr_provenance_requires_review'
                ), 'page_id': page_id,
                'adapter_name': ocr.name, 'adapter_version': ocr.version(),
                'producer_engine_claims': sorted({
                    str((block.get('metadata') or {}).get('sidecar_producer', {}).get('claimed_engine'))
                    for block in blocks
                }),
            })
        result.canonical_blocks.extend(_canonical(ev, 'image_ocr') for ev in blocks)
        if blocks:
            page.update(status='extracted', route='ocr')
        elif _image_blank_candidate(target):
            page.update(status='blank_candidate', route='blank_review')
            page['quality_flags'].append('blank_requires_confirmation')
        else:
            page.update(status='unresolved', route='ocr_required')
            blocker = 'ocr_required_but_unavailable' if ocr is None else 'source_page_without_text'
            page['quality_flags'].append(blocker)
            result.blockers.append({'kind': blocker, 'page_id': page_id})
        result.pages.append(page)
    return result


def _load_bundle_manifest(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == '.json':
        payload = json.loads(path.read_text(encoding='utf-8'))
    else:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError('YAML bundle manifests require PyYAML') from exc
        payload = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict) or not isinstance(payload.get('sources'), list) or not payload['sources']:
        raise ValueError('bundle manifest requires a non-empty sources list')
    for index, entry in enumerate(payload['sources'], start=1):
        if not isinstance(entry, dict) or not str(entry.get('locator', '')).strip():
            raise ValueError(f'bundle source #{index} requires locator')
        try:
            int(entry.get('order', 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f'bundle source #{index} has an invalid order') from exc
    return payload


def bundle_graph_digest(
    source: Path, *, allow_external_sources: bool = False, depth: int = 0,
) -> str:
    """Content identity for a manifest and every declared source member."""
    if depth > 2:
        raise ValueError('nested source bundles exceed the maximum depth of 2')
    payload = _load_bundle_manifest(source)
    base = source.parent.resolve()
    hashes = []
    entries = sorted(payload['sources'], key=lambda row: (int(row.get('order', 0)), str(row.get('locator', ''))))
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or not entry.get('locator'):
            raise ValueError(f'bundle source #{index} requires locator')
        child = Path(str(entry['locator'])).expanduser()
        child = (child if child.is_absolute() else base / child).resolve()
        if not allow_external_sources and child != base and base not in child.parents:
            raise ValueError(f'bundle source escapes manifest directory: {entry["locator"]}')
        if not child.exists():
            raise FileNotFoundError(child)
        if child.is_file() and child.suffix.lower() in {'.json', '.yaml', '.yml'}:
            digest = bundle_graph_digest(
                child, allow_external_sources=allow_external_sources, depth=depth + 1,
            )
        else:
            digest = sha256_path(child)
        if entry.get('expected_sha256') and entry['expected_sha256'] != digest:
            raise ValueError(f'bundle source hash mismatch: {entry["locator"]}')
        hashes.append(digest)
    return sha256_text(sha256_file(source) + '|' + '|'.join(hashes))


def _extract_bundle(
    source: Path, work: Path, policy: RestorePolicy, ocr: OCRAdapter | None, *, depth: int,
) -> ExtractionResult:
    if depth > 2:
        raise ValueError('nested source bundles exceed the maximum depth of 2')
    payload = _load_bundle_manifest(source)
    base = source.parent.resolve()
    # The manifest cannot grant itself filesystem authority. External sources
    # require an explicit caller policy/CLI opt-in.
    allow_external = bool(policy.allow_external_sources)
    child_entries = sorted(payload['sources'], key=lambda row: (int(row.get('order', 0)), str(row.get('locator', ''))))
    child_hashes = []
    resolved = []
    member_ids: set[str] = set()
    for index, entry in enumerate(child_entries, start=1):
        if not isinstance(entry, dict) or not entry.get('locator'):
            raise ValueError(f'bundle source #{index} requires locator')
        child = Path(str(entry['locator'])).expanduser()
        child = child if child.is_absolute() else (base / child)
        child = child.resolve()
        if not allow_external and base not in child.parents and child != base:
            raise ValueError(f'bundle source escapes manifest directory: {entry["locator"]}')
        if not child.exists():
            raise FileNotFoundError(child)
        member_id = str(entry.get('source_id') or f'source_{index:03d}')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', member_id) or '..' in member_id:
            raise ValueError(f'unsafe bundle source_id: {member_id}')
        if member_id in member_ids:
            raise ValueError(f'duplicate bundle source_id: {member_id}')
        member_ids.add(member_id)
        if child.is_file() and child.suffix.lower() in {'.json', '.yaml', '.yml'}:
            digest = bundle_graph_digest(
                child, allow_external_sources=allow_external, depth=depth + 1,
            )
        else:
            digest = sha256_path(child)
        if entry.get('expected_sha256') and entry['expected_sha256'] != digest:
            raise ValueError(f'bundle source hash mismatch: {entry["locator"]}')
        child_hashes.append(digest)
        resolved.append((index, entry, child, digest, member_id))
    bundle_sha = sha256_text(sha256_file(source) + '|' + '|'.join(child_hashes))
    result = ExtractionResult('source_bundle', {
        'source_sha256': bundle_sha, 'bundle_id': payload.get('bundle_id'),
        'work_identity': payload.get('work_identity', {}), 'rights': payload.get('rights', {}),
        'member_count': len(resolved), 'members': [],
    })
    global_ordinal = 0
    edition_values = {str(entry.get('edition')) for _, entry, _, _, _ in resolved if entry.get('edition') is not None}
    if len(edition_values) > 1:
        result.blockers.append({'kind': 'cross_edition_merge_forbidden', 'editions': sorted(edition_values)})
    for index, entry, child, digest, member_id in resolved:
        role = str(entry.get('source_role') or 'primary')
        subwork = ensure_dir(work / 'bundle' / member_id)
        child_result = extract_source(child, subwork, policy, ocr, _depth=depth + 1)
        if len(result.pages) + len(child_result.pages) > policy.max_pages:
            raise ValueError(
                f'source bundle exceeds max_pages: {len(result.pages) + len(child_result.pages)} > {policy.max_pages}'
            )
        page_map = {}
        for page in child_result.pages:
            global_ordinal += 1
            old_page = page['page_id']
            new_page = f'{member_id}__{old_page}'
            page_map[old_page] = new_page
            row = dict(page)
            prior_chain = list(row.get('source_member_chain', []))
            if row.get('source_member_id') and not prior_chain:
                prior_chain = [row['source_member_id']]
            row.update({
                'page_id': new_page, 'surface_id': new_page, 'ordinal': global_ordinal,
                'source_member_id': member_id, 'source_role': role, 'member_sha256': digest,
                'source_member_format': child_result.source_format,
                'source_member_chain': [member_id, *prior_chain],
                'surface_kind': {
                    'pdf': 'pdf_page', 'image': 'image_page', 'image_directory': 'image_page',
                    'epub': 'epub_spine_item', 'docx': 'docx_story', 'html': 'html_document',
                    'text': 'legacy_text', 'markdown': 'legacy_text',
                }.get(child_result.source_format, 'document_surface'),
            })
            image_path = row.get('page_image_path')
            if image_path and not Path(str(image_path)).is_absolute():
                row['page_image_path'] = f'bundle/{member_id}/{image_path}'
            original_path = row.get('original_image_path')
            if original_path and not Path(str(original_path)).is_absolute():
                row['original_image_path'] = f'bundle/{member_id}/{original_path}'
            result.pages.append(row)
        evidence_map = {
            str(row['evidence_id']): f'{member_id}__{row["evidence_id"]}'
            for row in child_result.evidence_blocks
        }
        block_map = {
            str(row['block_id']): f'{member_id}__{row["block_id"]}'
            for row in child_result.canonical_blocks
        }
        occurrence_map = {
            str(row.get('occurrence_id')): f'{member_id}__{row.get("occurrence_id")}'
            for row in child_result.assets
        }
        for evidence in child_result.evidence_blocks:
            row = dict(evidence)
            row['page_id'] = page_map[evidence['page_id']]
            row['evidence_id'] = evidence_map[str(evidence['evidence_id'])]
            prior_metadata = row.get('metadata', {})
            prior_chain = list(prior_metadata.get('source_member_chain', []))
            if prior_metadata.get('source_member_id') and not prior_chain:
                prior_chain = [prior_metadata['source_member_id']]
            row['metadata'] = {
                **prior_metadata, 'source_member_id': member_id, 'source_role': role,
                'member_sha256': digest, 'source_member_chain': [member_id, *prior_chain],
            }
            result.evidence_blocks.append(row)
        for block in child_result.canonical_blocks:
            row = dict(block)
            row['page_id'] = page_map[block['page_id']]
            row['block_id'] = block_map[str(block['block_id'])]
            row['evidence_id'] = evidence_map[str(block['evidence_id'])]
            result.canonical_blocks.append(row)
        for asset in child_result.assets:
            row = dict(asset)
            prior_chain = list(row.get('source_member_chain', []))
            if row.get('source_member_id') and not prior_chain:
                prior_chain = [row['source_member_id']]
            if row.get('page_id'):
                row['page_id'] = page_map[row['page_id']]
            asset_path = row.get('asset_path')
            if asset_path and not Path(str(asset_path)).is_absolute():
                row['asset_path'] = f'bundle/{member_id}/{asset_path}'
            row['occurrence_id'] = occurrence_map[str(asset.get('occurrence_id'))]
            row.update({
                'source_member_id': member_id, 'source_role': role, 'member_sha256': digest,
                'source_member_chain': [member_id, *prior_chain],
            })
            result.assets.append(row)
        for candidate in child_result.toc_candidates:
            row = dict(candidate)
            if row.get('page_id') in page_map:
                row['page_id'] = page_map[row['page_id']]
            if row.get('candidate_id'):
                row['candidate_id'] = f'{member_id}__{row["candidate_id"]}'
            if row.get('block_id') in block_map:
                row['block_id'] = block_map[str(row['block_id'])]
            row.update({'source_member_id': member_id, 'source_role': role})
            result.toc_candidates.append(row)
        for blocker in child_result.blockers:
            row = dict(blocker)
            if row.get('page_id') in page_map:
                row['page_id'] = page_map[row['page_id']]
            if row.get('occurrence_id') in occurrence_map:
                row['occurrence_id'] = occurrence_map[str(row['occurrence_id'])]
            row['source_member_id'] = member_id
            result.blockers.append(row)
        result.metadata['members'].append({
            'source_member_id': member_id, 'source_role': role, 'locator': str(entry['locator']),
            'sha256': digest, 'format': child_result.source_format, 'metadata': child_result.metadata,
        })
    return result


def _extract_source_impl(
    source: Path, work: Path, policy: RestorePolicy, ocr: OCRAdapter | None, *, _depth: int = 0,
) -> ExtractionResult:
    source_format = detect_source_format(source)
    if source_format == 'pdf':
        return extract_pdf_v2(source, work, policy, ocr)
    if source_format == 'epub':
        return extract_epub_v2(source, work, policy)
    if source_format == 'docx':
        return _extract_docx(source, work)
    if source_format in {'text', 'markdown', 'html'}:
        return _extract_textual(source, source_format)
    if source_format in {'image', 'image_directory'}:
        return _extract_images(source, work, policy, ocr)
    if source_format == 'bundle_manifest':
        return _extract_bundle(source, work, policy, ocr, depth=_depth)
    if source_format == 'mobi':
        if not policy.allow_local_conversion or not shutil.which('ebook-convert'):
            raise RuntimeError('MOBI/AZW3 requires local Calibre ebook-convert or prior conversion to EPUB')
        converted = work / 'converted.epub'
        cp = subprocess.run(['ebook-convert', str(source), str(converted)], text=True, capture_output=True, timeout=600, check=False)
        if cp.returncode != 0 or not converted.exists():
            raise RuntimeError(f'ebook-convert failed: {cp.stderr[-500:]}')
        result = extract_epub_v2(converted, work, policy)
        result.source_format = 'mobi_converted_to_epub'
        result.metadata['original_source_sha256'] = sha256_file(source)
        version = subprocess.run(
            ['ebook-convert', '--version'], text=True, capture_output=True, timeout=30, check=False,
        )
        result.metadata['conversion'] = {
            'tool': 'ebook-convert',
            'version': (version.stdout or version.stderr).strip().splitlines()[0] if (version.stdout or version.stderr) else None,
            'converted_epub_sha256': sha256_file(converted),
            'status': 'derived_rendition_requires_review',
        }
        result.blockers.extend({
            'kind': 'local_conversion_requires_review', 'page_id': page.get('page_id'),
        } for page in result.pages)
        return result
    raise ValueError(f'unsupported source format: {source_format}')


def extract_source(
    source: Path, work: Path, policy: RestorePolicy, ocr: OCRAdapter | None, *, _depth: int = 0,
) -> ExtractionResult:
    result = _extract_source_impl(source, work, policy, ocr, _depth=_depth)
    return _apply_transcription_policy(result, policy)
