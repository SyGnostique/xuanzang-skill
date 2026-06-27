from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import fitz
from PIL import Image


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env['PYTHONPATH'] = str(cwd / 'src') + os.pathsep + env.get('PYTHONPATH', '')
    return subprocess.run([sys.executable, '-m', 'xuanzang.cli', *args], cwd=cwd, text=True, capture_output=True, check=True, env=env)


def make_epub(path: Path) -> None:
    work = path.parent / 'epub_src'
    (work / 'META-INF').mkdir(parents=True)
    (work / 'OEBPS' / 'images').mkdir(parents=True)
    (work / 'mimetype').write_text('application/epub+zip', encoding='utf-8')
    (work / 'META-INF' / 'container.xml').write_text('''<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
''', encoding='utf-8')
    Image.new('RGB', (16, 16), color=(200, 20, 20)).save(work / 'OEBPS' / 'images' / 'pixel.png')
    (work / 'OEBPS' / 'content.opf').write_text('''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Synthetic Book</dc:title><dc:creator>Tester</dc:creator></metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="img" href="images/pixel.png" media-type="image/png"/>
  </manifest>
  <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>
''', encoding='utf-8')
    (work / 'OEBPS' / 'nav.xhtml').write_text('''<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc"><ol><li><a href="ch1.xhtml">Chapter 1: Alpha</a></li><li><a href="ch2.xhtml">Chapter 2: Beta</a></li></ol></nav></body></html>''', encoding='utf-8')
    (work / 'OEBPS' / 'ch1.xhtml').write_text('''<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Chapter 1: Alpha</h1><p>Alpha begins with a sentence.</p><figure><img src="images/pixel.png"/><figcaption>Figure 1. Red square.</figcaption></figure></body></html>''', encoding='utf-8')
    (work / 'OEBPS' / 'ch2.xhtml').write_text('''<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Chapter 2: Beta</h1><p>Beta closes the book.</p><section><h2>Notes</h2><p>One note.</p></section></body></html>''', encoding='utf-8')
    with zipfile.ZipFile(path, 'w') as zf:
        zf.write(work / 'mimetype', 'mimetype', compress_type=zipfile.ZIP_STORED)
        for p in sorted(work.rglob('*')):
            if p.is_file() and p.name != 'mimetype':
                zf.write(p, str(p.relative_to(work)))


def make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), 'Chapter 1: PDF Alpha')
    page.insert_text((72, 110), 'This is born digital PDF text.')
    doc.save(path)


def test_epub_full_local_pipeline(tmp_path: Path):
    epub = tmp_path / 'book.epub'
    make_epub(epub)
    package = tmp_path / 'package'
    repo = Path(__file__).resolve().parents[1]
    run_cli('ledger', str(epub), '--out', str(package), cwd=repo)
    assert json.loads((package / 'audit' / 'source_integrity.json').read_text())['status'] == 'PASS'
    run_cli('toc', str(package), cwd=repo)
    toc = json.loads((package / 'toc' / 'canonical_toc.json').read_text())
    assert len(toc['items']) >= 2
    run_cli('split', str(package), cwd=repo)
    split = json.loads((package / 'audit' / 'split_coverage.json').read_text())
    assert split['status'] == 'PASS'
    run_cli('clean', str(package), cwd=repo)
    assert json.loads((package / 'audit' / 'pass_fail.json').read_text())['status'] == 'PASS_STRICT'
    run_cli('validate', str(package), '--strict', cwd=repo)
    assert json.loads((package / 'audit' / 'validation.json').read_text())['status'] == 'PASS'
    run_cli('prep-translation', str(package), cwd=repo)
    run_cli('translate', str(package), '--provider', 'mock', '--run-id', 'mock_v1', cwd=repo)
    run_cli('audit-translation', str(package), '--run-id', 'mock_v1', cwd=repo)
    final = json.loads((package / 'translation_runs' / 'mock_v1' / 'audit' / 'final_translation_run_audit.json').read_text())
    assert final['status'] == 'PASS'
    docx = tmp_path / 'out.docx'
    run_cli('assemble-docx', str(package), '--run-id', 'mock_v1', '--out', str(docx), cwd=repo)
    assert docx.exists()
    out_epub = tmp_path / 'out.epub'
    run_cli('reinsert-epub', str(package), '--run-id', 'mock_v1', '--out', str(out_epub), cwd=repo)
    assert out_epub.exists()


def test_pdf_ledger_and_ocr_audit(tmp_path: Path):
    pdf = tmp_path / 'book.pdf'
    make_pdf(pdf)
    package = tmp_path / 'pdf_package'
    repo = Path(__file__).resolve().parents[1]
    run_cli('ledger', str(pdf), '--out', str(package), '--lang', 'en', cwd=repo)
    source = json.loads((package / 'audit' / 'source_integrity.json').read_text())
    assert source['status'] == 'PASS'
    ocr = json.loads((package / 'audit' / 'ocr_audit.json').read_text())
    assert ocr['status'] == 'PASS'


def test_translation_validator_rejects_missing_unit(tmp_path: Path):
    epub = tmp_path / 'book.epub'
    make_epub(epub)
    package = tmp_path / 'package'
    repo = Path(__file__).resolve().parents[1]
    for args in [('ledger', str(epub), '--out', str(package)), ('toc', str(package)), ('split', str(package)), ('prep-translation', str(package)), ('translate', str(package), '--provider', 'mock', '--run-id', 'bad')]:
        run_cli(*args, cwd=repo)
    translated = package / 'translation_runs' / 'bad' / 'translated_md' / 'chapter_001.md'
    lines = translated.read_text(encoding='utf-8').splitlines()
    translated.write_text('\n'.join(lines[1:]) + '\n', encoding='utf-8')
    run_cli('audit-translation', str(package), '--run-id', 'bad', cwd=repo)
    final = json.loads((package / 'translation_runs' / 'bad' / 'audit' / 'final_translation_run_audit.json').read_text())
    assert final['status'] == 'FAIL_REVIEW'


def make_dirty_epub(path: Path) -> None:
    work = path.parent / 'dirty_epub_src'
    (work / 'META-INF').mkdir(parents=True)
    (work / 'OEBPS').mkdir(parents=True)
    (work / 'mimetype').write_text('application/epub+zip', encoding='utf-8')
    (work / 'META-INF' / 'container.xml').write_text('''<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
''', encoding='utf-8')
    (work / 'OEBPS' / 'content.opf').write_text('''<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Dirty EPUB</dc:title></metadata><manifest><item id="both" href="both.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="both"/></spine></package>''', encoding='utf-8')
    (work / 'OEBPS' / 'both.xhtml').write_text('''<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Chapter 1: One File</h1><p>First chapter text.</p><h1>Chapter 2: Same File</h1><p>Second chapter text.</p><h1>Bibliography</h1><p>One citation.</p></body></html>''', encoding='utf-8')
    with zipfile.ZipFile(path, 'w') as zf:
        zf.write(work / 'mimetype', 'mimetype', compress_type=zipfile.ZIP_STORED)
        for p in sorted(work.rglob('*')):
            if p.is_file() and p.name != 'mimetype':
                zf.write(p, str(p.relative_to(work)))


def test_dirty_epub_multi_chapter_spine(tmp_path: Path):
    epub = tmp_path / 'dirty.epub'
    make_dirty_epub(epub)
    package = tmp_path / 'dirty_package'
    repo = Path(__file__).resolve().parents[1]
    run_cli('ledger', str(epub), '--out', str(package), cwd=repo)
    run_cli('toc', str(package), cwd=repo)
    run_cli('split', str(package), cwd=repo)
    toc = json.loads((package / 'toc' / 'canonical_toc.json').read_text())
    assert len(toc['items']) == 3
    assert toc['items'][-1]['section_type'] == 'bibliography'
    split = json.loads((package / 'audit' / 'split_coverage.json').read_text())
    assert split['status'] == 'PASS'


def make_blank_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page()
    doc.save(path)


def test_mock_chinese_ocr_path(tmp_path: Path):
    pdf = tmp_path / 'blank.pdf'
    make_blank_pdf(pdf)
    package = tmp_path / 'ocr_package'
    repo = Path(__file__).resolve().parents[1]
    run_cli('ledger', str(pdf), '--out', str(package), '--ocr', 'mock', '--lang', 'zh', cwd=repo)
    ocr = json.loads((package / 'audit' / 'ocr_audit.json').read_text())
    assert ocr['status'] == 'PASS'
    assert ocr['engine_counts']['mock'] == 1
    assert ocr['cjk_ratio_avg'] > 0.25
