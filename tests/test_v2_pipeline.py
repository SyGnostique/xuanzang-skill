from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageDraw
from xuanzang.adapters import (
    OCRBlock,
    PaddleOCRAdapter,
    TesseractOCRAdapter,
    choose_ocr_adapter,
)
from xuanzang.extractors import _english_plate_ocr_usable, _native_usable
from xuanzang.publish import _expected_canonical_headings, _published_canonical_items


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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_born_digital_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(72, 72, 520, 240),
        'Evidence Restoration\nThis born-digital document contains enough authoritative text for native extraction and review.',
        fontsize=12,
    )
    doc.save(path)
    doc.close()


def make_mixed_linked_unlinked_asset_pdf(path: Path) -> None:
    image_paths = []
    for index, color in enumerate(('navy', 'olive', 'maroon'), start=1):
        image_path = path.with_name(f'figure-{index}.png')
        Image.new('RGB', (160, 80), color).save(image_path)
        image_paths.append(image_path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(72, 35, 540, 70),
        'Mixed linked and unlinked figures retain immutable source order.',
        fontsize=11,
    )
    page.insert_image(fitz.Rect(100, 100, 360, 180), filename=str(image_paths[0]))
    page.insert_image(fitz.Rect(80, 240, 240, 310), filename=str(image_paths[1]))
    page.insert_image(fitz.Rect(80, 560, 240, 630), filename=str(image_paths[2]))
    # Insertion order intentionally follows a two-column reading model:
    # upper caption, lower-left caption, then the middle figure's side caption.
    page.insert_textbox(fitz.Rect(100, 190, 500, 215), 'Figure 1 Upper linked figure.', fontsize=10)
    page.insert_textbox(fitz.Rect(80, 640, 300, 665), 'Figure 3 Lower linked figure.', fontsize=10)
    page.insert_textbox(fitz.Rect(330, 270, 540, 310), 'Figure 2 Side-positioned caption.', fontsize=10)
    doc.save(path)
    doc.close()


def make_vector_figure_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(72, 72, 520, 130),
        'This source explains a vector plot and retains enough surrounding native prose for review.',
        fontsize=11,
    )
    page.draw_rect(fitz.Rect(250, 170, 470, 325), color=(0, 0, 0), width=1)
    page.draw_line(fitz.Point(270, 300), fitz.Point(450, 190), color=(0, 0, 0), width=2)
    page.draw_line(fitz.Point(270, 300), fitz.Point(450, 300), color=(0, 0, 0), width=1)
    page.draw_line(fitz.Point(270, 300), fitz.Point(270, 190), color=(0, 0, 0), width=1)
    page.insert_text(fitz.Point(455, 315), 'x', fontsize=10)
    page.insert_text(fitz.Point(255, 190), 'y', fontsize=10)
    page.insert_textbox(
        fitz.Rect(190, 345, 500, 385),
        'Figure 1 Vector plot used as source evidence.',
        fontsize=10,
    )
    page.insert_textbox(
        fitz.Rect(72, 420, 520, 475),
        'The prose continues after the caption and must remain outside the graphical occurrence.',
        fontsize=11,
    )
    # A distant decorative rule is a negative counterexample and must not be
    # absorbed into the caption-bound vector occurrence.
    page.draw_rect(fitz.Rect(80, 760, 200, 770), color=(0, 0, 0), width=1)
    doc.save(path)
    doc.close()


def test_short_native_figure_caption_can_use_plate_threshold() -> None:
    blocks = [{'text': 'Fig. 98 Paul Henreid'}]

    assert not _native_usable(blocks)
    assert _native_usable(blocks, min_meaningful=8)
    assert not _native_usable([{'text': '117'}], min_meaningful=8)
    assert not _native_usable([{'text': '\ufffd' * 12}], min_meaningful=8)


def test_english_plate_ocr_filter_keeps_caption_and_rejects_photo_texture() -> None:
    assert _english_plate_ocr_usable({'text': 'Fig. 43', 'confidence': 0.90})
    assert _english_plate_ocr_usable({'text': 'Spanish Beauty, Mary Inclan', 'confidence': 0.88})
    assert not _english_plate_ocr_usable({'text': 'AS', 'confidence': 0.95})
    assert not _english_plate_ocr_usable({'text': "'T", 'confidence': 0.80})
    assert not _english_plate_ocr_usable({'text': 'long texture guess', 'confidence': 0.42})
    assert _english_plate_ocr_usable({
        'text': 'www.ucpress.edn', 'confidence': 0.28,
        'metadata': {'supplemental_variant': 'inverted_autocontrast_threshold'},
    })
    assert _english_plate_ocr_usable({
        'text': 'ISBN-13 978-D-520-08944%-5', 'confidence': 0.24,
        'metadata': {'supplemental_variant': 'inverted_autocontrast_threshold'},
    })
    assert not _english_plate_ocr_usable({'text': 'ISBN-ish texture', 'confidence': 0.24})


def test_tesseract_tsv_words_are_grouped_into_lines() -> None:
    header = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext'
    tsv = '\n'.join([
        header,
        '5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t90\tFig.',
        '5\t1\t1\t1\t1\t2\t45\t20\t20\t10\t80\t43',
        '5\t1\t1\t1\t2\t1\t10\t40\t35\t10\t70\tCaption',
    ])

    blocks = TesseractOCRAdapter._parse_tsv_lines(tsv, psm=3)

    assert [block.text for block in blocks] == ['Fig. 43', 'Caption']
    assert blocks[0].bbox == [10.0, 20.0, 65.0, 30.0]
    assert blocks[0].confidence == pytest.approx((90 * 4 + 80 * 2) / (100 * 6))
    assert blocks[0].metadata == {
        'tesseract_psm': 3,
        'tesseract_line_key': [1, 1, 1, 1],
        'word_count': 2,
    }


def test_tesseract_retries_sparse_mode_only_after_empty_auto_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = []
    header = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    sparse = header + '5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t95\tFig.\n5\t1\t1\t1\t1\t2\t45\t20\t20\t10\t95\t43\n'

    def fake_run_tsv(image: Path, *, tess_lang: str, psm: int) -> str:
        calls.append((image, tess_lang, psm))
        return header if psm == 3 else sparse

    monkeypatch.setattr(TesseractOCRAdapter, '_run_tsv', staticmethod(fake_run_tsv))
    image = tmp_path / 'plate.png'
    image.write_bytes(b'fixture')

    blocks = TesseractOCRAdapter().recognize(image, lang='en')

    assert [call[2] for call in calls] == [3, 11]
    assert [block.text for block in blocks] == ['Fig. 43']
    assert blocks[0].metadata['tesseract_psm'] == 11


def test_auto_ocr_can_prefer_tesseract_for_memory_bounded_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('XUANZANG_AUTO_OCR_PREFERRED', 'tesseract')
    monkeypatch.setattr(TesseractOCRAdapter, 'available', lambda self: True)

    assert choose_ocr_adapter('auto').name == 'tesseract'


def test_tesseract_selects_clearly_better_rotated_ocr_and_maps_bbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    image = tmp_path / 'upside-down.png'
    Image.new('RGB', (200, 100), 'white').save(image)
    primary = [OCRBlock('nwoD edispU', [10, 10, 70, 20], 0.30)]
    candidate = [
        OCRBlock(
            'This corrected orientation contains enough authoritative source text for review.',
            [20, 30, 180, 50], 0.95,
        )
    ]
    monkeypatch.setattr(
        TesseractOCRAdapter, '_recognize_default',
        classmethod(lambda cls, path, *, tess_lang: candidate),
    )

    selected, corrected = TesseractOCRAdapter().retry_rotated_180_if_better(
        image, primary, lang='en', page_id='page_0001',
    )

    assert corrected is True
    assert selected[0].text.startswith('This corrected orientation')
    assert selected[0].bbox == [20.0, 50.0, 180.0, 70.0]
    assert selected[0].metadata['ocr_orientation_correction_degrees'] == 180
    assert selected[0].metadata['corrected_orientation_bbox'] == [20, 30, 180, 50]


def test_tesseract_rejects_rotated_candidate_without_clear_quality_gain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    image = tmp_path / 'upright.png'
    Image.new('RGB', (200, 100), 'white').save(image)
    primary = [OCRBlock('Short valid caption', [10, 10, 90, 20], 0.78)]
    candidate = [OCRBlock('Weak rotated noise', [20, 30, 100, 50], 0.80)]
    monkeypatch.setattr(
        TesseractOCRAdapter, '_recognize_default',
        classmethod(lambda cls, path, *, tess_lang: candidate),
    )

    selected, corrected = TesseractOCRAdapter().retry_rotated_180_if_better(
        image, primary, lang='en', page_id='page_0001',
    )

    assert corrected is False
    assert selected is primary


def test_paddle_rotated_retry_maps_bboxes_and_reuses_same_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    image = tmp_path / 'upside-down.png'
    Image.new('RGB', (200, 100), 'white').save(image)
    primary = [OCRBlock('nwoD edispU source text', [10, 10, 90, 20], 0.35)]
    candidate = [OCRBlock(
        'Corrected Paddle orientation contains complete authoritative source text.',
        [20, 30, 180, 50], 0.98,
    )]
    adapter = PaddleOCRAdapter()
    monkeypatch.setattr(adapter, 'recognize', lambda *args, **kwargs: candidate)

    selected, corrected = adapter.retry_rotated_180_if_better(
        image, primary, lang='en', page_id='page_0001',
    )

    assert corrected is True
    assert selected[0].bbox == [20.0, 50.0, 180.0, 70.0]
    assert selected[0].metadata['ocr_orientation_correction_degrees'] == 180


def test_tesseract_supplemental_merge_preserves_new_regions_without_duplicates() -> None:
    primary = [
        OCRBlock('Existing line', [10, 100, 200, 120], 0.95),
        OCRBlock('Footer', [10, 500, 100, 520], 0.90),
    ]
    supplemental = [
        OCRBlock('Existing line', [10, 100, 200, 120], 0.99),
        OCRBlock('Panel quotation', [10, 200, 300, 230], 0.92),
        OCRBlock('Overlapping noise', [10, 500, 100, 520], 0.88),
    ]

    merged = TesseractOCRAdapter.merge_supplemental_blocks(primary, supplemental)

    assert [block.text for block in merged] == ['Existing line', 'Panel quotation', 'Footer']


def make_blank_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()


def make_scanned_pdf(path: Path, image_path: Path) -> None:
    image = Image.new('RGB', (800, 500), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 760, 460), outline='black', width=5)
    for y in range(90, 410, 45):
        draw.text((80, y), 'scanned evidence line 0123456789', fill='black')
    image.save(image_path)
    doc = fitz.open()
    page = doc.new_page(width=800, height=500)
    page.insert_image(page.rect, filename=str(image_path))
    doc.save(path)
    doc.close()


def make_markdown(path: Path, *, paragraphs: int = 2) -> None:
    parts = ['# Evidence chapter']
    for index in range(1, paragraphs + 1):
        parts.append(
            f'Paragraph {index} records a distinct source-supported statement for exhaustive ManualStrict coverage.'
        )
    path.write_text('\n\n'.join(parts) + '\n', encoding='utf-8')


def restore(source: Path, package: Path, *, target: str = 'review', ocr: str = 'none') -> dict:
    result = run_cli(
        'restore', str(source), '--out', str(package), '--target', target, '--ocr', ocr,
    )
    return stdout_json(result)


def semantic_decisions(package: Path) -> list[dict]:
    manifest = read_json(package / 'package_manifest.json')
    source_sha = manifest['source']['sha256']
    common = {
        'semantic_reading': True,
        'reviewer_type': 'human',
        'reviewer_id': 'fixture-reviewer',
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
            'reason': 'The complete source surface was visually and semantically reviewed.',
        })
    paragraphs = read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl')
    for paragraph in paragraphs:
        decisions.append({
            **common,
            'kind': 'paragraph',
            'target_id': paragraph['paragraph_id'],
            'disposition': 'used',
            'source_id': paragraph['source_id'],
            'sourcepage_path': f"fixture://{paragraph['page_id']}",
            'paragraph_role': 'definition',
            'semantic_summary': 'A source-grounded paragraph retained for the promoted evidence object.',
            'claim_candidates': [],
            'method_candidates': [],
            'metric_candidates': [],
            'boundary_candidates': [],
            'used_in_card': True,
            'requires_primary_anchor': True,
            'reason': 'The paragraph directly supports the citation-grade source representation.',
        })
    assets = read_jsonl(package / 'ledger' / 'assets.jsonl')
    for asset in assets:
        decisions.append({
            **common,
            'kind': 'asset',
            'target_id': asset['occurrence_id'],
            'disposition': 'reference_only',
            'reason': 'The visual occurrence was inspected and retained as reference-only evidence.',
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
            'reason': 'All source surfaces and structural boundaries were reviewed.',
        })
    decisions.append({
        **common,
        'kind': 'source_boundary',
        'target_id': source_sha,
        'disposition': 'reviewed',
        'text': 'Use only claims anchored to this supplied source; do not import external evidence.',
        'reason': 'The source-use boundary was explicitly reviewed.',
    })
    return decisions


def apply_decisions(package: Path, path: Path, decisions: list[dict], *, expected_revision: str | None = None) -> subprocess.CompletedProcess[str]:
    write_json(path, {'decisions': decisions})
    args = ['review', str(package), '--decisions', str(path)]
    if expected_revision is not None:
        args.extend(['--expected-revision', expected_revision])
    return run_cli(*args)


def test_born_digital_pdf_is_review_ready_and_hint_publishable(tmp_path: Path) -> None:
    source = tmp_path / 'born-digital.pdf'
    package = tmp_path / 'package'
    make_born_digital_pdf(source)

    restored = restore(source, package, target='review', ocr='none')

    assert restored['gate_status'] == 'REVIEW_READY'
    assert restored['trust_status'] == 'needs_review'
    assert {row['engine'] for row in read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')} == {'pdf_native'}

    export_dir = tmp_path / 'hint-export'
    published = stdout_json(run_cli('publish', str(package), '--target', 'hint', '--out', str(export_dir)))
    assert published['gate_status'] == 'HINT_READY'
    assert published['trust_status'] == 'hint_only'
    assert published['chunk_count'] >= 1
    assert (export_dir / 'document.md').exists()


def test_published_canonical_items_exclude_reference_only_leaves_but_keep_ancestors() -> None:
    canonical = [
        {'toc_id': 'cover', 'structure_path': ['Cover']},
        {'toc_id': 'copyright', 'structure_path': ['Copyright']},
        {'toc_id': 'chapter', 'structure_path': ['Chapter 1']},
        {'toc_id': 'section', 'structure_path': ['Chapter 1', 'Section A']},
    ]
    selected = [{
        'paragraph_id': 'body',
        'structure_path': ['Chapter 1', 'Section A'],
    }]

    assert [
        item['toc_id'] for item in _published_canonical_items(canonical, selected)
    ] == ['chapter', 'section']


def test_expected_canonical_headings_match_emitter_path_deduplication() -> None:
    canonical = [
        {'structure_path': ['Part I']},
        {'structure_path': ['Interstitial']},
        {'structure_path': ['Part I', 'Chapter 1']},
    ]

    assert [
        row['structure_path'] for row in _expected_canonical_headings(canonical)
    ] == [
        ['Part I'],
        ['Interstitial'],
        ['Part I', 'Chapter 1'],
    ]
    assert [row['level'] for row in _expected_canonical_headings(canonical)] == [2, 2, 3]


def test_citation_publish_omits_reference_only_asset(tmp_path: Path) -> None:
    source = tmp_path / 'reference-only-asset.pdf'
    package = tmp_path / 'package'
    make_born_digital_pdf(source)
    restore(source, package, target='review', ocr='none')
    decisions = semantic_decisions(package)
    decision_path = tmp_path / 'decisions.json'
    applied = apply_decisions(package, decision_path, decisions)
    assert applied.returncode == 0

    export_dir = tmp_path / 'citation-export'
    published = stdout_json(
        run_cli('publish', str(package), '--target', 'citation', '--out', str(export_dir))
    )
    assert published['asset_count'] == 0


def test_publish_preserves_pdf_asset_order_when_linked_and_unlinked_figures_mix(
    tmp_path: Path,
) -> None:
    source = tmp_path / 'mixed-assets.pdf'
    package = tmp_path / 'package'
    make_mixed_linked_unlinked_asset_pdf(source)
    restored = restore(source, package, target='review', ocr='none')
    assert restored['gate_status'] == 'REVIEW_READY'

    assets = read_jsonl(package / 'ledger' / 'assets.jsonl')
    figures = [
        row for row in read_jsonl(package / 'ledger' / 'objects.jsonl')
        if row['object_kind'] == 'figure'
    ]
    assert len(assets) == len(figures) == 3
    figure_by_occurrence = {
        str(row['asset_occurrence_ids'][0]): row for row in figures
    }
    assert [
        bool(figure_by_occurrence[str(asset['occurrence_id'])]['source_block_ids'])
        for asset in assets
    ] == [True, False, True]

    decisions = semantic_decisions(package)
    common = {
        'semantic_reading': True,
        'reviewer_type': 'human',
        'reviewer_id': 'fixture-reviewer',
        'created_at': FIXED_REVIEW_TIME,
    }
    for obj in read_jsonl(package / 'ledger' / 'objects.jsonl'):
        decisions.append({
            **common,
            'kind': 'object',
            'target_id': obj['object_id'],
            'disposition': 'used',
            'representation_status': 'verified',
            'relations_reviewed': True,
            'source_verified': True,
            'visual_verified': True,
            'reason': 'The fixture object and its retained relation state were verified.',
        })
    reviewed = stdout_json(apply_decisions(package, tmp_path / 'review.json', decisions))
    assert reviewed['gate_status'] == 'PASS_STRICT'

    export = tmp_path / 'citation-export'
    stdout_json(run_cli('publish', str(package), '--target', 'citation', '--out', str(export)))
    expected = [str(row['occurrence_id']) for row in read_jsonl(export / 'assets.jsonl')]
    observed = [
        str(occurrence_id)
        for chunk in read_jsonl(export / 'chunks.jsonl')
        for occurrence_id in chunk.get('asset_occurrence_ids', [])
    ]
    validation = read_json(export / 'publication_validation.json')
    assert observed == expected
    assert validation['asset_occurrence_source_order_matches'] is True
    assert validation['status'] == 'PASS'


def test_pdf_vector_figure_becomes_caption_bound_asset_without_decorative_rule(tmp_path: Path) -> None:
    source = tmp_path / 'vector-figure.pdf'
    package = tmp_path / 'package'
    make_vector_figure_pdf(source)

    restore(source, package, target='review', ocr='none')

    assets = read_jsonl(package / 'ledger' / 'assets.jsonl')
    objects = read_jsonl(package / 'ledger' / 'objects.jsonl')
    vector_assets = [row for row in assets if row.get('kind') == 'pdf_vector_figure_render']
    assert len(vector_assets) == 1
    asset = vector_assets[0]
    assert (package / asset['asset_path']).is_file()
    assert sha256_file(package / asset['asset_path']) == asset['asset_sha256']
    assert asset['source_drawing_count'] >= 3
    assert asset['source_vector_bbox'][3] < 400
    assert {row['text'] for row in asset['vector_label_blocks']} >= {'x', 'y'}

    caption = next(row for row in objects if row.get('object_kind') == 'caption')
    figure = next(row for row in objects if row.get('object_kind') == 'figure')
    assert caption['asset_occurrence_ids'] == [asset['occurrence_id']]
    assert figure['asset_occurrence_ids'] == [asset['occurrence_id']]
    assert figure['caption_object_id'] == caption['object_id']
    labels = next(row for row in figure['representations'] if row.get('kind') == 'figure_labels')
    assert {row['text'] for row in labels['value']} >= {'x', 'y'}
    assert asset['bbox'][3] < caption['bbox'][1]


def test_status_names_the_evaluated_gate_and_can_check_hint_tier(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=1)
    restored = restore(source, package, target='hint', ocr='none')
    assert restored['gate_status'] == 'HINT_READY'

    citation_status = stdout_json(run_cli('status', str(package)))
    hint_status = stdout_json(run_cli('status', str(package), '--target', 'hint'))

    assert citation_status['evaluated_target'] == 'citation'
    assert citation_status['gate_status'] == 'FAIL_REVIEW'
    assert hint_status['evaluated_target'] == 'hint'
    assert hint_status['gate_status'] == 'HINT_READY'
    assert hint_status['trust_status'] == 'hint_only'


def test_scanned_and_blank_pdf_without_ocr_fail_closed(tmp_path: Path) -> None:
    scanned = tmp_path / 'scan.pdf'
    make_scanned_pdf(scanned, tmp_path / 'scan.png')
    blank = tmp_path / 'blank.pdf'
    make_blank_pdf(blank)

    scanned_result = restore(scanned, tmp_path / 'scan-package', target='review', ocr='none')
    blank_result = restore(blank, tmp_path / 'blank-package', target='review', ocr='none')

    assert scanned_result['gate_status'] == 'FAIL_REVIEW'
    assert blank_result['gate_status'] == 'FAIL_REVIEW'
    scanned_gate = read_json(tmp_path / 'scan-package' / 'audit' / 'gates' / 'review.json')
    blank_surfaces = read_jsonl(tmp_path / 'blank-package' / 'ledger' / 'surfaces.jsonl')
    assert any(finding['code'] == 'unresolved_source_page' for finding in scanned_gate['hard_blockers'])
    assert blank_surfaces[0]['status'] == 'blank_candidate'
    assert not read_jsonl(tmp_path / 'blank-package' / 'ledger' / 'canonical_blocks.jsonl')


def test_mock_ocr_can_support_review_but_never_citation(tmp_path: Path) -> None:
    image = tmp_path / 'page.png'
    Image.new('RGB', (400, 240), color=(210, 220, 230)).save(image)
    package = tmp_path / 'package'

    restored = restore(image, package, target='review', ocr='mock')
    assert restored['gate_status'] == 'REVIEW_READY'

    status = stdout_json(run_cli('status', str(package)))
    gate = read_json(package / 'audit' / 'gates' / 'citation.json')
    publish = run_cli('publish', str(package), '--target', 'citation', '--out', str(tmp_path / 'citation'), check=False)

    assert status['trust_status'] == 'needs_review'
    assert any(finding['code'] == 'mock_ocr_not_citation_eligible' for finding in gate['hard_blockers'])
    assert publish.returncode == 2
    assert not (tmp_path / 'citation' / 'manifest.json').exists()


def test_complete_manualstrict_review_is_required_for_citation_publish(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=2)
    restore(source, package, target='citation', ocr='none')

    blocked = run_cli('publish', str(package), '--target', 'citation', '--out', str(tmp_path / 'before'), check=False)
    assert blocked.returncode == 2

    review = stdout_json(apply_decisions(package, tmp_path / 'decisions.json', semantic_decisions(package)))
    assert review['gate_status'] == 'PASS_STRICT'
    assert review['trust_status'] == 'citation_grade'

    export_dir = tmp_path / 'citation'
    published = stdout_json(run_cli('publish', str(package), '--target', 'citation', '--out', str(export_dir)))
    assert published['gate_status'] == 'PASS_STRICT'
    assert published['trust_status'] == 'citation_grade'
    assert published['chunk_count'] == len(read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl'))


def test_one_missing_paragraph_blocks_citation(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=3)
    restore(source, package, target='review', ocr='none')
    decisions = semantic_decisions(package)
    paragraph_decisions = [row for row in decisions if row['kind'] == 'paragraph']
    assert len(paragraph_decisions) >= 2
    missing_id = paragraph_decisions[-1]['target_id']
    decisions.remove(paragraph_decisions[-1])

    review = stdout_json(apply_decisions(package, tmp_path / 'incomplete.json', decisions))
    gate = read_json(package / 'audit' / 'gates' / 'citation.json')
    publish = run_cli('publish', str(package), '--target', 'citation', '--out', str(tmp_path / 'citation'), check=False)

    assert review['gate_status'] == 'FAIL_REVIEW'
    coverage_finding = next(row for row in gate['hard_blockers'] if row['code'] == 'paragraph_coverage_gap')
    assert missing_id in coverage_finding['observed']
    assert publish.returncode == 2


def test_review_and_restore_reruns_are_idempotent_and_preserve_decisions(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    decisions_path = tmp_path / 'decisions.json'
    make_markdown(source, paragraphs=2)
    restore(source, package, target='citation', ocr='none')
    decisions = semantic_decisions(package)

    first = stdout_json(apply_decisions(package, decisions_path, decisions))
    ledger_before = (package / 'ledger' / 'review_decisions.jsonl').read_bytes()
    revision_before = first['review_revision']
    second = stdout_json(apply_decisions(package, decisions_path, decisions))

    assert second['accepted'] == 0
    assert second['review_revision'] == revision_before
    assert (package / 'ledger' / 'review_decisions.jsonl').read_bytes() == ledger_before

    rerun = restore(source, package, target='citation', ocr='none')
    assert rerun['reused'] is True
    assert rerun['trust_status'] == 'citation_grade'
    assert (package / 'ledger' / 'review_decisions.jsonl').read_bytes() == ledger_before
    assert read_json(package / 'package_manifest.json')['review_revision'] == revision_before


def test_tampered_immutable_run_ledger_blocks_promotion(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=1)
    restore(source, package, target='review', ocr='none')
    active_run = read_json(package / 'package_manifest.json')['active_run_id']
    raw_ledger = package / 'runs' / active_run / 'ledger' / 'evidence_blocks.jsonl'
    raw_ledger.write_text(raw_ledger.read_text(encoding='utf-8') + '{"tampered": true}\n', encoding='utf-8')

    status = stdout_json(run_cli('status', str(package)))
    gate = read_json(package / 'audit' / 'gates' / 'citation.json')

    assert status['gate_status'] == 'FAIL_REVIEW'
    integrity = next(row for row in gate['hard_blockers'] if row['code'] == 'stale_or_tampered_artifact')
    assert 'run:ledger/evidence_blocks.jsonl' in integrity['observed']


def test_review_batch_is_transactional_and_revision_conflicts_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / 'source.md'
    package = tmp_path / 'package'
    make_markdown(source, paragraphs=1)
    restore(source, package, target='review', ocr='none')
    all_decisions = semantic_decisions(package)
    page = next(row for row in all_decisions if row['kind'] == 'page')
    paragraph = dict(next(row for row in all_decisions if row['kind'] == 'paragraph'))
    paragraph['target_id'] = 'para_unknown'
    invalid_batch = tmp_path / 'invalid-batch.json'
    write_json(invalid_batch, {'decisions': [page, paragraph]})
    ledger_path = package / 'ledger' / 'review_decisions.jsonl'
    ledger_before = ledger_path.read_bytes()
    revision_before = read_json(package / 'package_manifest.json')['review_revision']

    invalid = run_cli('review', str(package), '--decisions', str(invalid_batch), check=False)

    assert invalid.returncode == 4
    assert ledger_path.read_bytes() == ledger_before
    assert read_json(package / 'package_manifest.json')['review_revision'] == revision_before

    accepted = stdout_json(apply_decisions(package, tmp_path / 'page.json', [page], expected_revision=revision_before))
    ledger_after_page = ledger_path.read_bytes()
    boundary = next(row for row in all_decisions if row['kind'] == 'source_boundary')
    conflict_path = tmp_path / 'conflict.json'
    write_json(conflict_path, {'decisions': [boundary]})
    conflict = run_cli(
        'review', str(package), '--decisions', str(conflict_path),
        '--expected-revision', revision_before, check=False,
    )

    assert accepted['review_revision'] != revision_before
    assert conflict.returncode == 4
    assert 'review revision conflict' in conflict.stderr
    assert ledger_path.read_bytes() == ledger_after_page
    assert read_json(package / 'package_manifest.json')['review_revision'] == accepted['review_revision']


def test_epub_zip_slip_is_rejected_without_writing_outside_staging(tmp_path: Path) -> None:
    epub = tmp_path / 'malicious.epub'
    escaped = tmp_path / 'escaped.txt'
    with zipfile.ZipFile(epub, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip')
        archive.writestr('../escaped.txt', 'zip-slip payload')

    result = run_cli(
        'restore', str(epub), '--out', str(tmp_path / 'package'),
        '--target', 'review', '--ocr', 'none', check=False,
    )

    assert result.returncode == 4
    assert 'unsafe EPUB member path' in result.stderr
    assert not escaped.exists()


def test_image_input_with_mock_ocr_builds_review_package(tmp_path: Path) -> None:
    image = tmp_path / 'evidence.png'
    Image.new('RGB', (320, 180), color=(180, 190, 210)).save(image)
    package = tmp_path / 'package'

    restored = restore(image, package, target='review', ocr='mock')
    evidence = read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')
    surfaces = read_jsonl(package / 'ledger' / 'surfaces.jsonl')

    assert restored['gate_status'] == 'REVIEW_READY'
    assert surfaces[0]['status'] == 'extracted'
    assert surfaces[0]['route'] == 'ocr'
    assert evidence and {row['engine'] for row in evidence} == {'mock'}
    assert evidence[0]['bbox'] == [0.0, 0.0, 320.0, 180.0]


def test_v1_migration_downgrades_legacy_pass_and_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / 'legacy-source.txt'
    source.write_text('Legacy source text retained for migration.\n', encoding='utf-8')
    old = tmp_path / 'v1-package'
    source_sha = sha256_file(source)
    inventory = {
        'source_path': str(source),
        'source_sha256': source_sha,
        'format': 'text',
    }
    write_json(old / 'package_manifest.json', {'package_version': 1, 'source': inventory})
    write_json(old / 'source' / 'source_inventory.json', inventory)
    write_jsonl(old / 'ledger' / 'source_blocks.jsonl', [{
        'block_id': 'b000001',
        'source_type': 'text_native',
        'spine_index': 1,
        'text': 'Legacy source text retained for migration.',
        'block_kind': 'text_candidate',
    }])
    write_jsonl(old / 'ledger' / 'image_blocks.jsonl', [])
    write_json(old / 'audit' / 'pass_fail.json', {'status': 'PASS_STRICT'})
    migrated = tmp_path / 'v2-package'

    first = stdout_json(run_cli('migrate-v1', str(old), '--out', str(migrated)))
    second = stdout_json(run_cli('migrate-v1', str(old), '--out', str(migrated)))
    report = read_json(migrated / 'audit' / 'migration_report.json')

    assert first['status'] == 'migrated'
    assert first['trust_status'] == 'needs_review'
    assert first['gate_status'] == 'FAIL_REVIEW'
    assert second['status'] == 'already_migrated'
    assert second['trust_status'] == 'needs_review'
    assert 'legacy PASS_STRICT -> v2 needs_review' in report['status_downgrades']
    assert (migrated / 'legacy' / 'v1_snapshot' / 'audit' / 'pass_fail.json').exists()
