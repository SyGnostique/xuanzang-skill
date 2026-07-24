from __future__ import annotations

import json
import os
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path

import pytest

from xuanzang.publish import _should_render_list_item, _table_markdown


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


def test_four_digit_bibliography_year_is_not_rendered_as_ordered_list_item() -> None:
    semantics = {'kind': 'ordered', 'depth': 1, 'marker': '1.'}
    assert not _should_render_list_item('1999. Editors Net Web site.', semantics)
    assert _should_render_list_item('19. A genuine numbered item.', semantics)


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
    navigation_surface = next(
        row for row in read_jsonl(tmp_path / 'package' / 'ledger' / 'surfaces.jsonl')
        if row.get('route') == 'epub_navigation_metadata'
    )
    assert navigation_surface['canonical_inclusion'] == 'excluded'
    assert navigation_surface['navigation_semantic_status'] == 'parsed_semantic_navigation'


def test_epub3_navigation_in_spine_still_has_excluded_logical_surface(tmp_path: Path) -> None:
    epub = tmp_path / 'nav-in-spine.epub'
    manifest = (
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(
            manifest=manifest,
            spine='<itemref idref="nav"/><itemref idref="chapter"/>',
        ),
        'OPS/nav.xhtml': (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><body>'
            '<nav epub:type="toc"><ol><li>'
            '<a href="chapter.xhtml#opening">Chapter</a>'
            '</li></ol></nav></body></html>'
        ),
        'OPS/chapter.xhtml': xhtml('<h1 id="opening">Chapter</h1><p>Evidence text.</p>'),
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    surfaces = read_jsonl(package / 'ledger' / 'surfaces.jsonl')
    navigation_surfaces = [row for row in surfaces if row.get('route') == 'epub_navigation_metadata']
    assert len(navigation_surfaces) == 1
    assert any(row.get('href') == 'OPS/nav.xhtml' and row.get('page_id') == 'spine_0001' for row in surfaces)
    logical = navigation_surfaces[0]
    assert logical['page_id'] != 'spine_0001'
    assert logical['canonical_inclusion'] == 'excluded'
    assert logical['surface_role'] == 'auxiliary_navigation'
    assert logical['surface_kind'] == 'epub_navigation_resource'


def test_css_hidden_spine_navigation_is_audited_but_not_canonical_text(tmp_path: Path) -> None:
    epub = tmp_path / 'hidden-nav-in-spine.epub'
    manifest = (
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="css" href="style.css" media-type="text/css"/>'
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(
            manifest=manifest,
            spine='<itemref idref="nav"/><itemref idref="chapter"/>',
        ),
        'OPS/style.css': 'div.toc1 { visibility: hidden; display: none; }',
        'OPS/nav.xhtml': (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
            '<link rel="stylesheet" href="style.css"/></head><body>'
            '<div class="toc1"><nav epub:type="toc"><ol><li>'
            '<a href="chapter.xhtml#opening">Hidden navigation label</a>'
            '</li></ol></nav></div></body></html>'
        ),
        'OPS/chapter.xhtml': xhtml('<h1 id="opening">Visible chapter</h1><p>Visible evidence.</p>'),
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    evidence = read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')
    assert 'Hidden navigation label' not in {row['text'] for row in evidence}
    assert {'Visible chapter', 'Visible evidence.'} <= {row['text'] for row in evidence}
    inventory = read_json(package / 'source' / 'source_inventory.json')
    visibility = inventory['metadata']['visibility_audit']
    assert visibility['hidden_text_nodes'] == 1
    assert visibility['surfaces'][0]['hidden_text_dom_paths']


def test_br_boundaries_are_retained_in_dom_container_text(tmp_path: Path) -> None:
    epub = tmp_path / 'br-boundary.epub'
    manifest = '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        'OPS/chapter.xhtml': xhtml('<p>First line<br/>second line<br/>third line</p>'),
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    evidence = read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')
    assert [row['text'] for row in evidence] == ['First line', 'second line', 'third line']
    assert {
        (row.get('metadata') or {}).get('dom_container_text') for row in evidence
    } == {'First line second line third line'}


def test_css_display_block_boundaries_are_retained_in_dom_container_text(tmp_path: Path) -> None:
    epub = tmp_path / 'css-block-boundary.epub'
    manifest = (
        '<item id="css" href="style.css" media-type="text/css"/>'
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        'OPS/style.css': '.title-line, .credit { display: block; }',
        'OPS/chapter.xhtml': (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            '<link rel="stylesheet" href="style.css"/></head><body>'
            '<h1><span>1</span><span class="title-line">Chapter title</span></h1>'
            '<figcaption>Caption text<span class="credit">Source: Studio</span></figcaption>'
            '</body></html>'
        ),
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    evidence = read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')
    containers = {
        row['text']: (row.get('metadata') or {}).get('dom_container_text')
        for row in evidence
    }
    assert containers['1'] == '1 Chapter title'
    assert containers['Chapter title'] == '1 Chapter title'
    assert containers['Caption text'] == 'Caption text Source: Studio'
    assert containers['Source: Studio'] == 'Caption text Source: Studio'


def test_table_markdown_uses_exact_dom_cell_text_for_inline_fragments() -> None:
    expected_cell = 'Mixed Reality: (e.g. Microsoft® HoloLens® ) MR description.'
    obj = {
        'representations': [{
            'kind': 'table_cells',
            'value': [
                {'row': 0, 'column': 0, 'tag': 'td', 'text': 'MR:', 'evidence_id': 'label'},
                {'row': 0, 'column': 1, 'tag': 'td', 'text': 'Mixed Reality: Microsoft', 'evidence_id': 'a'},
                {'row': 0, 'column': 1, 'tag': 'td', 'text': '®', 'evidence_id': 'b'},
                {'row': 0, 'column': 1, 'tag': 'td', 'text': 'HoloLens', 'evidence_id': 'c'},
                {'row': 0, 'column': 1, 'tag': 'td', 'text': '®', 'evidence_id': 'd'},
            ],
        }],
    }
    evidence = {
        'label': {'metadata': {'dom_container_text': 'MR:'}},
        **{
            evidence_id: {'metadata': {'dom_container_text': expected_cell}}
            for evidence_id in ('a', 'b', 'c', 'd')
        },
    }
    markdown = _table_markdown(obj, evidence)
    assert f'| MR: | {expected_cell} |' in markdown
    assert 'Microsoft ®' not in markdown
    assert 'HoloLens )' not in markdown


def test_table_markdown_preserves_distinct_block_containers_in_one_cell() -> None:
    obj = {
        'representations': [{
            'kind': 'table_cells',
            'value': [
                {'row': 0, 'column': 0, 'tag': 'td', 'text': 'Exterior Day', 'evidence_id': 'a'},
                {'row': 0, 'column': 0, 'tag': 'td', 'text': 'Monco and Colonel', 'evidence_id': 'b'},
                {'row': 0, 'column': 0, 'tag': 'td', 'text': '’', 'evidence_id': 'c'},
                {'row': 0, 'column': 0, 'tag': 'td', 'text': 's gang.', 'evidence_id': 'd'},
            ],
        }],
    }
    event = 'Monco and Colonel Mortimer kill the gang.'
    evidence = {
        'a': {'metadata': {'dom_container_text': 'Exterior Day'}},
        'b': {'metadata': {'dom_container_text': event}},
        'c': {'metadata': {'dom_container_text': event}},
        'd': {'metadata': {'dom_container_text': event}},
    }
    markdown = _table_markdown(obj, evidence)
    assert '| Exterior Day Monco and Colonel Mortimer kill the gang. |' in markdown
    assert markdown.count(event) == 1


def test_utf8_meta_xhtml_and_literal_markdown_heading_text_survive_publish(tmp_path: Path) -> None:
    epub = tmp_path / 'utf8-meta-and-literal-hash.epub'
    manifest = '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    xhtml_bytes = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8"/>'
        '<title>UTF-8 fixture</title></head><body>'
        '<p>Holmes’s work © 2024.</p>'
        '<p># of Shots — explanatory prose.</p>'
        '<p>#### = four-digit padding.</p>'
        '</body></html>'
    ).encode('utf-8')
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        'OPS/chapter.xhtml': xhtml_bytes,
    })

    package = tmp_path / 'package'
    export = tmp_path / 'export'
    restore_epub(epub, package)
    run_cli('publish', str(package), '--target', 'hint', '--out', str(export))

    evidence_text = '\n'.join(row['text'] for row in read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl'))
    assert 'Holmes’s work © 2024.' in evidence_text
    assert 'Holmesâ€™s' not in evidence_text and 'Â©' not in evidence_text
    markdown = (export / 'document.md').read_text(encoding='utf-8')
    assert '\\# of Shots — explanatory prose.' in markdown
    assert '\\#### = four-digit padding.' in markdown
    assert '\n# of Shots' not in markdown and '\n#### = four-digit padding.' not in markdown


def test_epub_mathml_comments_footer_and_h6_figure_caption_are_semantically_preserved(tmp_path: Path) -> None:
    epub = tmp_path / 'semantic-objects.epub'
    manifest = '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml" properties="mathml"/>'
    chapter = xhtml(
        '<h1>Chapter</h1>'
        '<!-- <p>hidden template instruction</p> -->'
        '<p>Before formula.</p>'
        '<math xmlns="http://www.w3.org/1998/Math/MathML" alttext="x squared equals four" display="block">'
        '<msup><mi>x</mi><mn>2</mn></msup><mo>=</mo><mn>4</mn></math>'
        '<pre>value = 4 <a id="callout-source" href="#callout-explanation">'
        '<img src="1.png" width="12" height="12"/></a></pre>'
        '<p id="callout-explanation">Callout explanation.</p>'
        '<figure><div class="figure" id="figure-one"><img src="pixel.png"/>'
        '<h6><span class="label">Figure 1. </span>Caption text</h6></div></figure>'
        '<p style="text-align:right"><a href="https://example.test/translator" '
        'style="color:#ccc;font-size:0.625rem">Translated by Fixture</a></p>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        'OPS/chapter.xhtml': chapter,
        'OPS/pixel.png': b'\x89PNG\r\n\x1a\n',
        'OPS/1.png': b'\x89PNG\r\n\x1a\n',
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    evidence = read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')
    canonical = read_jsonl(package / 'ledger' / 'canonical_blocks.jsonl')
    objects = read_jsonl(package / 'ledger' / 'objects.jsonl')
    assets = read_jsonl(package / 'ledger' / 'assets.jsonl')

    assert not any('hidden template instruction' in row['text'] for row in evidence)
    footer = next(row for row in evidence if row['text'] == 'Translated by Fixture')
    assert footer['metadata']['source_role'] == 'recurring_footer'
    assert not any(row['text'] == 'Translated by Fixture' for row in canonical)
    equations = [row for row in objects if row.get('object_kind') == 'equation']
    assert len(equations) == 1
    assert equations[0]['source_id']
    assert any(row.get('kind') == 'mathml' for row in equations[0]['representations'])
    assert sum(row.get('block_kind') == 'equation_candidate' for row in evidence) == 1
    assert sum(row.get('block_kind') == 'callout_candidate' for row in evidence) == 1
    assert sum(row.get('block_kind') == 'code_candidate' for row in evidence) == 1
    callout = next(row for row in objects if row.get('object_kind') == 'callout')
    assert callout['source_block_ids'] and callout['relation_status'] == 'linked'
    assert any(
        row.get('kind') == 'callout_link' and row.get('value') == '#callout-explanation'
        for row in callout['representations']
    )
    code = next(row for row in objects if row.get('object_kind') == 'code')
    assert any(
        row.get('kind') == 'code_text' and 'value = 4' in row.get('value', '')
        for row in code['representations']
    )
    assert callout['asset_occurrence_ids'][0] in code['asset_occurrence_ids']
    assert next(row for row in assets if row.get('callout_role') != 'code_callout')['caption_text'] == 'Figure 1. Caption text'
    figure = next(row for row in objects if row.get('object_kind') == 'figure')
    assert figure['caption_object_id']
    assert figure['relation_status'] == 'linked'


def test_epub_preformatted_code_preserves_source_indentation_and_token_spacing(tmp_path: Path) -> None:
    epub = tmp_path / 'preformatted-code.epub'
    manifest = '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    source_code = (
        '<pre data-code-language="python" data-type="programlisting">'
        '<code class="k">class</code> <code class="nc">VAE</code><code class="p">:</code>\n'
        '    <code class="k">def</code> <code class="nf">train</code><code class="p">(</code>'
        '<code class="bp">self</code><code class="p">):</code>\n'
        '        <code class="k">return</code> <code class="mi">1</code>\n'
        '</pre>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        'OPS/chapter.xhtml': xhtml('<h1>Code</h1>' + source_code),
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    code = next(
        row for row in read_jsonl(package / 'ledger' / 'objects.jsonl')
        if row.get('object_kind') == 'code'
    )
    representations = {row['kind']: row for row in code['representations']}
    assert representations['code_text']['value'] == (
        'class VAE:\n    def train(self):\n        return 1\n'
    )
    assert representations['source_xml']['value'] == source_code


def test_published_external_link_repairs_unbalanced_trailing_parenthesis_reversibly(tmp_path: Path) -> None:
    epub = tmp_path / 'malformed-link.epub'
    manifest = '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        'OPS/chapter.xhtml': xhtml(
            '<h1>Link</h1><p>Source: <a href="https://example.test/playground)">'
            'https://example.test/playground)</a></p>'
        ),
    })

    package = tmp_path / 'package'
    export = tmp_path / 'export'
    restore_epub(epub, package)
    run_cli('publish', str(package), '--target', 'hint', '--out', str(export))
    chunk = next(row for row in read_jsonl(export / 'chunks.jsonl') if row.get('links'))
    assert chunk['links'][0]['href'] == 'https://example.test/playground'
    assert chunk['links'][0]['source_href'] == 'https://example.test/playground)'
    markdown = (export / 'document.md').read_text(encoding='utf-8')
    assert 'https://example.test/playground)' in markdown
    assert '\nLinks:' not in markdown


def test_legacy_div_figure_and_image_caption_are_linked(tmp_path: Path) -> None:
    epub = tmp_path / 'legacy-div-figure.epub'
    manifest = '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        'OPS/chapter.xhtml': xhtml(
            '<h1>Legacy figure</h1><div class="fig" id="fig1_2f">'
            '<img src="figure.jpg" alt="Figure 1.2 Source alt"/>'
            '<p class="image_caption" id="fig1_2">Figure 1.2 Linked caption</p></div>'
        ),
        'OPS/figure.jpg': b'fixture-image',
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    objects = read_jsonl(package / 'ledger' / 'objects.jsonl')
    assets = read_jsonl(package / 'ledger' / 'assets.jsonl')
    caption = next(row for row in objects if row.get('object_kind') == 'caption')
    figure = next(row for row in objects if row.get('object_kind') == 'figure')
    assert caption['relation_status'] == 'linked'
    assert figure['caption_object_id'] == caption['object_id']
    assert assets[0]['figure_id'] == 'fig1_2f'
    assert assets[0]['caption_text'] == 'Figure 1.2 Linked caption'


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


def test_standard_external_ncx_doctype_is_removed_without_resolving_it(tmp_path: Path) -> None:
    epub = tmp_path / 'standard-ncx-doctype.epub'
    manifest = (
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        'OPS/toc.ncx': (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" '
            '"http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><navMap>'
            '<navPoint id="chapter" playOrder="1"><navLabel><text>Safe chapter</text></navLabel>'
            '<content src="chapter.xhtml"/></navPoint></navMap></ncx>'
        ),
        'OPS/chapter.xhtml': xhtml('<h1>Safe chapter</h1>'),
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    assert any(row.get('text') == 'Safe chapter' for row in toc_candidates(package))
    blockers = read_json(package / 'audit' / 'extraction_audit.json')['hard_blockers']
    assert not any(row.get('kind') == 'epub_navigation_unsafe_xml' for row in blockers)
    manifest_data = read_json(package / 'package_manifest.json')
    inventory = read_json(package / 'runs' / manifest_data['active_run_id'] / 'source_inventory.json')
    assert inventory['metadata']['navigation_documents'][0]['external_doctype_removed_before_parse'] is True

    evidence = read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl')
    chapter = next(row for row in evidence if row.get('text') == 'Safe chapter')
    assert chapter['engine_version'] == 'xuanzang-epub-dom-v2.1'
    raw_xhtml = chapter['metadata']['raw_xhtml']
    assert raw_xhtml.startswith(f"runs/{manifest_data['active_run_id']}/assets/epub_tree/")
    assert (package / raw_xhtml).is_file()


def test_bare_html5_nav_doctype_is_removed_without_enabling_entities(tmp_path: Path) -> None:
    epub = tmp_path / 'bare-nav-doctype.epub'
    manifest = (
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        'OPS/nav.xhtml': (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<!DOCTYPE html>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li>'
            '<a href="chapter.xhtml">Safe HTML5 chapter</a>'
            '</li></ol></nav></body></html>'
        ),
        'OPS/chapter.xhtml': xhtml('<h1>Safe HTML5 chapter</h1>'),
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    assert any(row.get('text') == 'Safe HTML5 chapter' for row in toc_candidates(package))
    blockers = read_json(package / 'audit' / 'extraction_audit.json')['hard_blockers']
    assert not any(row.get('kind') == 'epub_navigation_unsafe_xml' for row in blockers)


def test_visual_only_epub_spine_binds_single_local_image_as_rendition(tmp_path: Path) -> None:
    epub = tmp_path / 'visual-only-rendition.epub'
    image_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8'
        b'\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    manifest = (
        '<item id="page" href="page.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="image" href="page.png" media-type="image/png"/>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="page"/>'),
        'OPS/page.xhtml': xhtml('<img src="page.png" alt="page image"/>'),
        'OPS/page.png': image_bytes,
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    surface = read_jsonl(package / 'ledger' / 'surfaces.jsonl')[0]
    assert surface['page_image_path']
    assert surface['page_image_sha256']
    assert (package / surface['page_image_path']).read_bytes() == image_bytes


def test_identical_sibling_nodes_receive_distinct_dom_paths_and_occurrence_ids(tmp_path: Path) -> None:
    epub = tmp_path / 'identical-siblings.epub'
    image_bytes = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8'
        b'\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    manifest = (
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="image" href="figure.png" media-type="image/png"/>'
    )
    write_epub(epub, {
        'META-INF/container.xml': container_xml(),
        'OPS/package.opf': package_opf(manifest=manifest, spine='<itemref idref="chapter"/>'),
        'OPS/chapter.xhtml': xhtml(
            '<p>Repeated text.</p><p>Repeated text.</p>'
            '<p><img src="figure.png"/></p><p><img src="figure.png"/></p>'
        ),
        'OPS/figure.png': image_bytes,
    })

    package = tmp_path / 'package'
    restore_epub(epub, package)
    evidence = [row for row in read_jsonl(package / 'ledger' / 'evidence_blocks.jsonl') if row['text'] == 'Repeated text.']
    assets = read_jsonl(package / 'ledger' / 'assets.jsonl')
    assert len(evidence) == 2 and len({tuple(row['metadata']['dom_path']) for row in evidence}) == 2
    assert len(assets) == 2 and len({tuple(row['dom_path']) for row in assets}) == 2
    assert len({row['occurrence_id'] for row in assets}) == 2


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
