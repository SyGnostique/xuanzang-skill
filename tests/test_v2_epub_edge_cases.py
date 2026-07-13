from __future__ import annotations

import json
import os
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
ENTITY_MARKER = 'XUANZANG_ENTITY_EXPANSION_MUST_NOT_APPEAR'


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


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def container_xml(opf_path: str = 'OPS/package.opf') -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
        f'<rootfiles><rootfile full-path="{opf_path}" '
        'media-type="application/oebps-package+xml"/></rootfiles>'
        '</container>'
    )


def package_opf(*, manifest: str, spine: str, title: str = 'EPUB edge-case fixture') -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="book-id">urn:xuanzang:test</dc:identifier>'
        f'<dc:title>{title}</dc:title>'
        '<dc:language>en</dc:language>'
        '</metadata>'
        f'<manifest>{manifest}</manifest>'
        f'<spine>{spine}</spine>'
        '</package>'
    )


def xhtml(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        f'<head><title>Fixture</title></head><body>{body}</body></html>'
    )


def write_epub(path: Path, entries: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        for name, payload in entries.items():
            archive.writestr(name, payload)


def restore_epub(epub: Path, package: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_cli(
        'restore', str(epub), '--out', str(package),
        '--target', 'review', '--ocr', 'none', check=check,
    )


def toc_candidates(package: Path) -> list[dict]:
    return read_json(package / 'toc' / 'toc_candidates.json')['candidates']


def test_epub3_navigation_candidates_are_not_overwritten_by_legacy_seed(tmp_path: Path) -> None:
    epub = tmp_path / 'nav-and-heading.epub'
    manifest = (
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(
            manifest=manifest,
            spine='<itemref idref="chapter"/>',
        ),
        'OPS/nav.xhtml': (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><body>'
            '<nav epub:type="toc"><ol><li>'
            '<a href="chapter.xhtml#opening">Authoritative NAV label</a>'
            '</li></ol></nav></body></html>'
        ),
        'OPS/chapter.xhtml': xhtml('<h1 id="opening">Body-derived heading</h1><p>Evidence text.</p>'),
    })

    restore_epub(epub, tmp_path / 'package')
    candidates = toc_candidates(tmp_path / 'package')

    nav = [row for row in candidates if row.get('source') == 'epub_nav']
    assert [row['text'] for row in nav] == ['Authoritative NAV label']
    assert nav[0]['page_id'] == 'spine_0001'
    assert any(row.get('text') == 'Body-derived heading' for row in candidates)


def test_nested_nav_and_ncx_hrefs_resolve_from_each_navigation_document(tmp_path: Path) -> None:
    epub = tmp_path / 'nested-navigation.epub'
    manifest = (
        '<item id="nav" href="navigation/deep/nav.xhtml" '
        'media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="ncx" href="toc/deep/legacy.ncx" media-type="application/x-dtbncx+xml"/>'
        '<item id="chapter-1" href="text/chapter-1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="chapter-2" href="text/chapter-2.xhtml" media-type="application/xhtml+xml"/>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(
            manifest=manifest,
            spine='<itemref idref="chapter-1"/><itemref idref="chapter-2"/>',
        ),
        'OPS/navigation/deep/nav.xhtml': (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><body>'
            '<nav epub:type="toc"><ol><li>'
            '<a href="../../text/chapter-1.xhtml#section">Nested NAV chapter</a>'
            '</li></ol></nav></body></html>'
        ),
        'OPS/toc/deep/legacy.ncx': (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><navMap>'
            '<navPoint id="chapter-2" playOrder="1"><navLabel><text>Nested NCX chapter</text></navLabel>'
            '<content src="../../text/chapter-2.xhtml#section"/></navPoint>'
            '</navMap></ncx>'
        ),
        'OPS/text/chapter-1.xhtml': xhtml('<h1 id="section">Chapter one</h1>'),
        'OPS/text/chapter-2.xhtml': xhtml('<h1 id="section">Chapter two</h1>'),
    })

    restore_epub(epub, tmp_path / 'package')
    candidates = toc_candidates(tmp_path / 'package')
    nav = next(row for row in candidates if row.get('source') == 'epub_nav')
    ncx = next(row for row in candidates if row.get('source') == 'epub_ncx')

    assert nav['page_id'] == 'spine_0001'
    assert ncx['page_id'] == 'spine_0002'
    assert '..' not in nav['href'] and nav['href'].endswith('text/chapter-1.xhtml')
    assert '..' not in ncx['href'] and ncx['href'].endswith('text/chapter-2.xhtml')


def test_textless_legal_spine_items_still_have_surfaces_and_explicit_state(tmp_path: Path) -> None:
    epub = tmp_path / 'textless-spine.epub'
    manifest = (
        '<item id="image-only" href="text/image-only.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="blank" href="text/blank.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="hidden" href="text/hidden.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="visible" href="text/visible.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="figure" href="images/figure.png" media-type="image/png"/>'
    )
    one_pixel_png = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8'
        b'\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(
            manifest=manifest,
            spine=(
                '<itemref idref="image-only"/><itemref idref="blank"/>'
                '<itemref idref="hidden"/><itemref idref="visible"/>'
            ),
        ),
        'OPS/text/image-only.xhtml': xhtml('<img src="../images/figure.png" alt=""/>'),
        'OPS/text/blank.xhtml': xhtml('<p>  \n  </p>'),
        'OPS/text/hidden.xhtml': xhtml('<script>hidden text</script><style>.x { display: none; }</style>'),
        'OPS/text/visible.xhtml': xhtml('<p>Visible control paragraph.</p>'),
        'OPS/images/figure.png': one_pixel_png,
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    surfaces = read_jsonl(package / 'ledger' / 'surfaces.jsonl')
    assets = read_jsonl(package / 'ledger' / 'assets.jsonl')
    blockers = read_json(package / 'audit' / 'extraction_audit.json')['hard_blockers']

    assert [row['spine_index'] for row in surfaces] == [1, 2, 3, 4]
    surface_ids = {row['page_id'] for row in surfaces}
    assert assets and assets[0]['page_id'] in surface_ids
    assert assets[0]['page_id'] == 'spine_0001'

    by_page = {row['page_id']: row for row in surfaces}
    for page_id in ('spine_0001', 'spine_0002', 'spine_0003'):
        surface = by_page[page_id]
        explicitly_classified = (
            surface.get('status') not in {None, 'extracted'}
            or bool(surface.get('quality_flags'))
            or any(row.get('page_id') == page_id for row in blockers)
        )
        assert explicitly_classified, f'{page_id} silently looked like a normal text surface'


def malicious_utf16_xml(
    root_name: str,
    body: str,
    *,
    namespace: str | None = None,
    attributes: str = '',
) -> bytes:
    namespace_attribute = f' xmlns="{namespace}"' if namespace else ''
    payload = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        f'<!DOCTYPE {root_name} [<!ENTITY probe "{ENTITY_MARKER}">]>'
        f'<{root_name}{namespace_attribute}{attributes}>{body}</{root_name}>'
    )
    return payload.encode('utf-16')


def derived_package_text(package: Path) -> str:
    paths = [
        package / 'package_manifest.json',
        package / 'ledger' / 'evidence_blocks.jsonl',
        package / 'ledger' / 'canonical_blocks.jsonl',
        package / 'toc' / 'toc_candidates.json',
    ]
    if (package / 'package_manifest.json').exists():
        manifest = read_json(package / 'package_manifest.json')
        paths.append(package / 'runs' / manifest['active_run_id'] / 'source_inventory.json')
    return '\n'.join(path.read_text(encoding='utf-8') for path in paths if path.is_file())


@pytest.mark.parametrize('malicious_part', ['container', 'opf', 'nav', 'ncx'])
def test_utf16_epub_xml_dtd_and_entities_are_rejected_or_hard_blocked(
    tmp_path: Path,
    malicious_part: str,
) -> None:
    epub = tmp_path / f'utf16-{malicious_part}.epub'
    manifest = '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    entries: dict[str, str | bytes] = {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        'OPS/chapter.xhtml': xhtml('<h1>Safe visible chapter</h1>'),
    }

    if malicious_part == 'container':
        entries['META-INF/container.xml'] = malicious_utf16_xml(
            'container',
            '<rootfiles><rootfile full-path="OPS/package.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles>',
            namespace='urn:oasis:names:tc:opendocument:xmlns:container',
            attributes=' version="&probe;"',
        )
    elif malicious_part == 'opf':
        entries['OPS/package.opf'] = (
            '<?xml version="1.0" encoding="UTF-16"?>'
            f'<!DOCTYPE package [<!ENTITY probe "{ENTITY_MARKER}">]>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>&probe;</dc:title></metadata>'
            f'<manifest>{manifest}</manifest><spine><itemref idref="chapter"/></spine>'
            '</package>'
        ).encode('utf-16')
    elif malicious_part == 'nav':
        manifest = (
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
        )
        entries['OPS/package.opf'] = package_opf(manifest=manifest, spine='<itemref idref="chapter"/>')
        entries['OPS/nav.xhtml'] = (
            '<?xml version="1.0" encoding="UTF-16"?>'
            f'<!DOCTYPE html [<!ENTITY probe "{ENTITY_MARKER}">]>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li>'
            '<a href="chapter.xhtml">&probe;</a>'
            '</li></ol></nav></body></html>'
        ).encode('utf-16')
    else:
        manifest = (
            '<item id="ncx" href="legacy.ncx" media-type="application/x-dtbncx+xml"/>'
            '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
        )
        entries['OPS/package.opf'] = package_opf(manifest=manifest, spine='<itemref idref="chapter"/>')
        entries['OPS/legacy.ncx'] = (
            '<?xml version="1.0" encoding="UTF-16"?>'
            f'<!DOCTYPE ncx [<!ENTITY probe "{ENTITY_MARKER}">]>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><navMap>'
            '<navPoint id="chapter" playOrder="1"><navLabel><text>&probe;</text></navLabel>'
            '<content src="chapter.xhtml"/></navPoint></navMap></ncx>'
        ).encode('utf-16')

    write_epub(epub, entries)
    package = tmp_path / 'package'
    result = restore_epub(epub, package, check=False)

    if result.returncode == 0:
        blocker_kinds = {
            str(row.get('kind', '')).lower()
            for row in read_json(package / 'audit' / 'extraction_audit.json')['hard_blockers']
        }
        assert any(
            token in kind
            for kind in blocker_kinds
            for token in ('unsafe_xml', 'dtd', 'entity')
        ), f'UTF-16 {malicious_part} XML was accepted without a hard blocker'
    else:
        assert result.returncode == 4

    assert ENTITY_MARKER not in derived_package_text(package)


def test_zip_member_names_with_nfc_nfd_canonical_collision_are_rejected(tmp_path: Path) -> None:
    epub = tmp_path / 'unicode-collision.epub'
    nfc_name = 'OPS/text/Caf\u00e9.xhtml'
    nfd_name = 'OPS/text/Cafe\u0301.xhtml'
    assert nfc_name != nfd_name
    assert unicodedata.normalize('NFC', nfc_name) == unicodedata.normalize('NFC', nfd_name)
    manifest = '<item id="chapter" href="text/Caf\u00e9.xhtml" media-type="application/xhtml+xml"/>'
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        nfc_name: xhtml('<p>NFC member.</p>'),
        nfd_name: xhtml('<p>NFD collision member.</p>'),
    })

    result = restore_epub(epub, tmp_path / 'package', check=False)

    assert result.returncode == 4
    assert 'duplicate' in result.stderr.lower() or 'collid' in result.stderr.lower()


def test_valid_utf16_container_opf_spine_and_nav_preserve_text_and_navigation(tmp_path: Path) -> None:
    epub = tmp_path / 'valid-utf16.epub'
    manifest = (
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    )
    entries = {
        'META-INF/container.xml': container_xml().replace('UTF-8', 'UTF-16').encode('utf-16'),
        'OPS/package.opf': package_opf(
            manifest=manifest, spine='<itemref idref="chapter"/>', title='合法 UTF-16 书目',
        ).replace('UTF-8', 'UTF-16').encode('utf-16'),
        'OPS/chapter.xhtml': xhtml('<h1 id="section">合法 UTF-16 章节</h1>').replace('UTF-8', 'UTF-16').encode('utf-16'),
        'OPS/nav.xhtml': (
            '<?xml version="1.0" encoding="UTF-16"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li>'
            '<a href="chapter.xhtml#section">合法 UTF-16 导航</a>'
            '</li></ol></nav></body></html>'
        ).encode('utf-16'),
    }
    write_epub(epub, entries)
    package = tmp_path / 'package'

    result = restore_epub(epub, package)

    assert result.returncode == 0
    assert any('合法 UTF-16 章节' in row['text'] for row in read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl'))
    nav = next(row for row in toc_candidates(package) if row.get('source') == 'epub_nav')
    assert nav['text'] == '合法 UTF-16 导航'
    assert nav['page_id'] == 'spine_0001'


@pytest.mark.parametrize(
    ('first', 'second'),
    [
        ('OPS/text/Straße.xhtml', 'OPS/text/STRASSE.xhtml'),
        ('OPS/Café/chapter.xhtml', 'OPS/Café/chapter.xhtml'),
    ],
)
def test_zip_member_full_casefold_and_directory_normalization_collisions_are_rejected(
    tmp_path: Path, first: str, second: str,
) -> None:
    epub = tmp_path / 'canonical-collision.epub'
    with zipfile.ZipFile(epub, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        archive.writestr('META-INF/container.xml', container_xml())
        archive.writestr('OPS/package.opf', package_opf(
            manifest=f'<item id="chapter" href="{first.removeprefix("OPS/")}" media-type="application/xhtml+xml"/>',
            spine='<itemref idref="chapter"/>',
        ))
        archive.writestr(first, xhtml('<p>first</p>'))
        archive.writestr(second, xhtml('<p>second</p>'))
    result = restore_epub(epub, tmp_path / 'package', check=False)
    assert result.returncode == 4
    assert 'collid' in result.stderr.lower()


def test_epub_gate_reconciles_spine_occurrences_with_surfaces(tmp_path: Path) -> None:
    epub = tmp_path / 'two-spines.epub'
    manifest = (
        '<item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="b" href="b.xhtml" media-type="application/xhtml+xml"/>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="a"/><itemref idref="b"/>'),
        'OPS/a.xhtml': xhtml('<p>First surface.</p>'),
        'OPS/b.xhtml': xhtml('<p>Second surface.</p>'),
    })
    package = tmp_path / 'package'
    restore_epub(epub, package)
    surfaces_path = package / 'ledger' / 'surfaces.jsonl'
    surfaces = read_jsonl(surfaces_path)
    surfaces_path.write_text(json.dumps(surfaces[1], sort_keys=True) + '\n', encoding='utf-8')

    status = json.loads(run_cli('status', str(package)).stdout)
    blockers = read_json(package / 'audit' / 'gates' / 'citation.json')['hard_blockers']

    assert status['gate_status'] == 'FAIL_REVIEW'
    assert any(row['code'] == 'epub_spine_surface_coverage_gap' for row in blockers)


def test_fixed_layout_resolution_requires_a_real_hashed_rendition(tmp_path: Path) -> None:
    epub = tmp_path / 'fixed-layout.epub'
    opf = package_opf(
        manifest='<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
        spine='<itemref idref="chapter"/>',
    ).replace(
        '</metadata>', '<meta property="rendition:layout">pre-paginated</meta></metadata>',
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': opf,
        'OPS/chapter.xhtml': xhtml('<p>Fixed-layout source text.</p>'),
    })
    package = tmp_path / 'package'
    restore_epub(epub, package)
    decisions = tmp_path / 'decisions.json'
    decisions.write_text(json.dumps({'decisions': [{
        'kind': 'page', 'target_id': 'spine_0001', 'disposition': 'reviewed',
        'semantic_reading': True, 'reviewer_type': 'human', 'reviewer_id': 'fixture-reviewer',
        'reason': 'Reviewed the source surface.',
        'resolves': ['fixed_layout_requires_rendered_evidence'],
        'resolution_evidence': [{
            'code': 'fixed_layout_requires_rendered_evidence',
            'method': 'rendered_rendition_attached', 'verified': True,
            'artifact_path': 'runs/fake/page.png', 'sha256': 'f' * 64,
        }],
    }]}), encoding='utf-8')

    reviewed = json.loads(run_cli('review', str(package), '--decisions', str(decisions)).stdout)
    blockers = read_json(package / 'audit' / 'gates' / 'citation.json')['hard_blockers']
    unresolved = next(row for row in blockers if row['code'] == 'unresolved_extraction_finding')['observed']

    assert reviewed['gate_status'] == 'FAIL_REVIEW'
    assert any(row['kind'] == 'fixed_layout_requires_rendered_evidence' for row in unresolved)


def test_missing_asset_cannot_be_promoted_by_a_hash_claim_without_bytes(tmp_path: Path) -> None:
    epub = tmp_path / 'missing-asset.epub'
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(
            manifest='<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>',
            spine='<itemref idref="chapter"/>',
        ),
        'OPS/chapter.xhtml': xhtml('<p>Text remains available.</p><img src="missing.png"/>'),
    })
    package = tmp_path / 'package'
    restore_epub(epub, package)
    asset = read_jsonl(package / 'ledger' / 'assets.jsonl')[0]
    assert asset['asset_path'] is None and asset['asset_sha256'] is None
    decisions = tmp_path / 'asset-decisions.json'
    decisions.write_text(json.dumps({'decisions': [{
        'kind': 'asset', 'target_id': asset['occurrence_id'], 'disposition': 'reference_only',
        'semantic_reading': True, 'reviewer_type': 'human', 'reviewer_id': 'fixture-reviewer',
        'reason': 'Attempted to retain the missing occurrence.',
        'resolves': ['missing_image_asset'],
        'resolution_evidence': [{
            'code': 'missing_image_asset', 'method': 'asset_ingested_and_hashed',
            'verified': True, 'artifact_path': 'runs/fake/missing.png', 'sha256': 'f' * 64,
        }],
    }]}), encoding='utf-8')

    reviewed = json.loads(run_cli('review', str(package), '--decisions', str(decisions)).stdout)
    blockers = read_json(package / 'audit' / 'gates' / 'citation.json')['hard_blockers']
    unresolved = next(row for row in blockers if row['code'] == 'unresolved_extraction_finding')['observed']

    assert reviewed['gate_status'] == 'FAIL_REVIEW'
    assert any(row['kind'] == 'missing_image_asset' for row in unresolved)


def test_structure_can_account_for_a_reviewed_textless_surface(tmp_path: Path) -> None:
    epub = tmp_path / 'textless-structure.epub'
    manifest = (
        '<item id="blank" href="blank.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="text" href="text.xhtml" media-type="application/xhtml+xml"/>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="blank"/><itemref idref="text"/>'),
        'OPS/blank.xhtml': xhtml('<p>   </p>'),
        'OPS/text.xhtml': xhtml('<p>Visible paragraph.</p>'),
    })
    package = tmp_path / 'package'
    restore_epub(epub, package)
    surfaces = read_jsonl(package / 'ledger' / 'surfaces.jsonl')
    paragraph_ids = [row['paragraph_id'] for row in read_jsonl(package / 'ledger' / 'paragraph_candidates.jsonl')]
    candidate_ids = [row['candidate_id'] for row in toc_candidates(package)]
    decisions = tmp_path / 'structure.json'
    decisions.write_text(json.dumps({'decisions': [{
        'kind': 'structure', 'target_id': 'canonical', 'disposition': 'reviewed',
        'covered_surface_ids': [row['surface_id'] for row in surfaces],
        'candidate_dispositions': [
            {'candidate_id': candidate_id, 'disposition': 'used', 'reason': 'Mapped into the canonical item.'}
            for candidate_id in candidate_ids
        ],
        'toc_items': [{
            'toc_id': 'toc_all', 'title': 'Document', 'boundary_id': 'boundary_all',
            'source_candidate_ids': candidate_ids,
        }],
        'boundaries': [{
            'boundary_id': 'boundary_all', 'title': 'Document', 'structure_path': ['Document'],
            'paragraph_ids': paragraph_ids,
            'surface_ids': [row['surface_id'] for row in surfaces],
            'textless_surface_ids': ['spine_0001'],
        }],
        'semantic_reading': True, 'reviewer_type': 'human', 'reviewer_id': 'fixture-reviewer',
        'reason': 'The blank surface and visible paragraph were assigned to the reviewed structure.',
    }]}), encoding='utf-8')

    reviewed = json.loads(run_cli('review', str(package), '--decisions', str(decisions)).stdout)
    boundary = read_json(package / 'toc' / 'chapter_boundary_map.json')['chapters'][0]

    assert reviewed['gate_status'] == 'FAIL_REVIEW'
    assert boundary['textless_surface_ids'] == ['spine_0001']
    assert boundary['surface_ids'] == ['spine_0001', 'spine_0002']
