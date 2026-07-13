from __future__ import annotations

import mimetypes
import posixpath
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup, NavigableString, Tag

from .utils import (
    assert_safe_xml_bytes,
    contained_path,
    ensure_dir,
    relpath,
    sha256_file,
    sha256_text,
    validate_zip_archive,
    write_json,
    write_jsonl,
)

NS = {
    'container': 'urn:oasis:names:tc:opendocument:xmlns:container',
    'opf': 'http://www.idpf.org/2007/opf',
}


def _safe_xml_root(path: Path, *, label: str) -> ET.Element:
    data = path.read_bytes()
    assert_safe_xml_bytes(data, label=label)
    return ET.fromstring(data)


def _local_reference(value: str) -> str | None:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return None
    return unquote(parsed.path)


def _safe_extract_epub(zf: zipfile.ZipFile, destination: Path) -> list[str]:
    """Extract EPUB entries without path traversal or symlink materialization."""
    destination = destination.resolve()
    try:
        validate_zip_archive(zf, label='EPUB')
    except ValueError as exc:
        if 'unsafe archive member path' in str(exc):
            raise ValueError(str(exc).replace('has an unsafe archive member path', 'contains unsafe EPUB member path')) from exc
        raise
    names = []
    for info in zf.infolist():
        name = info.filename.replace('\\', '/')
        if name.startswith('/') or any(part == '..' for part in Path(name).parts):
            raise ValueError(f'unsafe EPUB member path: {info.filename}')
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError(f'EPUB symlink members are not allowed: {info.filename}')
        try:
            target = contained_path(destination, name)
        except ValueError as exc:
            raise ValueError(f'unsafe EPUB member path: {info.filename}') from exc
        names.append(info.filename)
        if info.is_dir():
            ensure_dir(target)
            continue
        ensure_dir(target.parent)
        with zf.open(info) as src, target.open('wb') as dst:
            shutil.copyfileobj(src, dst)
    return names


def _find_opf(epub_tree: Path) -> Path:
    container = epub_tree / 'META-INF' / 'container.xml'
    if not container.exists():
        raise ValueError('EPUB missing META-INF/container.xml')
    root = _safe_xml_root(container, label='EPUB container')
    rootfiles = [
        el for el in root.findall('.//container:rootfile', NS)
        if el.attrib.get('full-path')
    ]
    if not rootfiles:
        raise ValueError('EPUB container missing rootfile full-path')
    if len(rootfiles) != 1:
        raise ValueError('EPUB multiple renditions require explicit rootfile selection before restoration')
    el = rootfiles[0]
    try:
        opf = contained_path(epub_tree, el.attrib['full-path'])
    except ValueError as exc:
        raise ValueError('EPUB rootfile path escapes the archive root') from exc
    if not opf.is_file():
        raise ValueError(f'EPUB rootfile does not exist: {el.attrib["full-path"]}')
    return opf


def _parse_opf(opf_path: Path, epub_tree: Path) -> dict[str, Any]:
    root = _safe_xml_root(opf_path, label='EPUB OPF')
    manifest = {}
    for item in root.findall('.//opf:manifest/opf:item', NS):
        item_id = item.attrib.get('id')
        if not item_id:
            continue
        manifest[item_id] = dict(item.attrib)
    spine = []
    for itemref in root.findall('.//opf:spine/opf:itemref', NS):
        idref = itemref.attrib.get('idref')
        if idref:
            spine.append({
                'idref': idref,
                **manifest.get(idref, {}),
                'itemref': dict(itemref.attrib),
            })
    metadata = {}
    metadata_properties = {}
    for child in root.findall('.//{*}metadata/*'):
        tag = child.tag.split('}', 1)[-1]
        text = (child.text or '').strip()
        if text and tag not in metadata:
            metadata[tag] = text
        prop = child.attrib.get('property')
        if text and prop:
            metadata_properties[prop] = text
    return {
        'manifest': manifest, 'spine': spine, 'metadata': metadata,
        'metadata_properties': metadata_properties,
        'opf_rel': relpath(opf_path, epub_tree),
    }


def _node_path(node: Tag | NavigableString) -> list[int]:
    path = []
    cur: Any = node
    while getattr(cur, 'parent', None) is not None and getattr(cur.parent, 'name', None) != '[document]':
        siblings = [x for x in cur.parent.contents if not (isinstance(x, NavigableString) and not str(x).strip())]
        try:
            path.append(siblings.index(cur))
        except ValueError:
            path.append(0)
        cur = cur.parent
    return list(reversed(path))


def _is_visible_text_node(node: NavigableString) -> bool:
    text = str(node)
    if not text.strip():
        return False
    parent = node.parent
    if not isinstance(parent, Tag):
        return False
    if parent.name in {'script', 'style', 'meta', 'title'}:
        return False
    return True


def _iter_visible_text_nodes(soup: BeautifulSoup):
    body = soup.find('body') or soup
    for node in body.descendants:
        if isinstance(node, NavigableString) and _is_visible_text_node(node):
            yield node


def _classify_block(text: str, parent: Tag | None = None) -> str:
    t = ' '.join(text.split())
    tag = parent.name if parent else ''
    cls = ' '.join(parent.get('class', [])) if parent and parent.has_attr('class') else ''
    low = t.lower()
    if tag in {'h1', 'h2', 'h3', 'h4'}:
        return 'heading_candidate'
    if re.match(r'^(chapter|part|book|section)\b', low) or re.match(r'^(第[一二三四五六七八九十百0-9]+[章节部篇])', t):
        return 'heading_candidate'
    if any(k in low for k in ['contents', 'bibliography', 'notes', 'index', 'acknowledgements', 'glossary']):
        return 'structure_candidate'
    if 'caption' in cls or tag in {'figcaption'}:
        return 'caption_candidate'
    return 'text_candidate'


def extract_epub(source: Path, out_dir: Path) -> dict[str, Any]:
    source = source.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f'refusing to delete or overwrite existing package: {out_dir}')
    ensure_dir(out_dir)
    ensure_dir(out_dir / 'source')
    epub_tree = ensure_dir(out_dir / 'source' / 'epub_tree').resolve()
    with zipfile.ZipFile(source) as zf:
        names = _safe_extract_epub(zf, epub_tree)
    opf_path = _find_opf(epub_tree)
    opf = _parse_opf(opf_path, epub_tree)
    opf_base = opf_path.parent

    raw_dir = ensure_dir(out_dir / 'source' / 'raw_xhtml')
    blocks = []
    images = []
    toc_candidates = []
    text_counter = 0
    image_counter = 0
    spine_count = 0

    for spine_index, item in enumerate(opf['spine'], start=1):
        href = item.get('href')
        media_type = item.get('media-type', '')
        if not href or 'html' not in media_type and not href.lower().endswith(('.xhtml', '.html', '.htm')):
            continue
        spine_count += 1
        local_href = _local_reference(href)
        if not local_href:
            raise ValueError(f'EPUB spine item is not a local archive member: {href}')
        try:
            src_path = contained_path(epub_tree, str((opf_base.relative_to(epub_tree) / local_href).as_posix()))
        except ValueError as exc:
            raise ValueError(f'EPUB spine path escapes the archive root: {href}') from exc
        if not src_path.exists():
            continue
        raw_name = f's{spine_index:03d}__{Path(href).name}'
        raw_path = raw_dir / raw_name
        shutil.copy2(src_path, raw_path)
        html_bytes = src_path.read_bytes()
        assert_safe_xml_bytes(html_bytes, label=f'EPUB spine XHTML {href}')
        soup = BeautifulSoup(html_bytes, 'lxml-xml')
        for img in soup.find_all(['img', 'image']):
            ref = img.get('src') or img.get('href') or img.get('xlink:href')
            if not ref:
                continue
            image_counter += 1
            image_id = f'img{image_counter:05d}'
            local_ref = _local_reference(ref)
            if local_ref is None:
                image_path = None
            else:
                try:
                    image_path = contained_path(epub_tree, str((src_path.parent.relative_to(epub_tree) / local_ref).as_posix()))
                except ValueError as exc:
                    raise ValueError(f'EPUB image path escapes the archive root: {ref}') from exc
            images.append({
                'image_id': image_id,
                'source_type': 'epub',
                'spine_index': spine_index,
                'href': href,
                'src': ref,
                'asset_path': relpath(image_path, epub_tree) if image_path is not None and image_path.exists() else ref,
                'exists': bool(image_path is not None and image_path.exists()),
                'external_reference': local_ref is None,
                'dom_path': _node_path(img),
                'marker': f'[[IMAGE {image_id} src="{ref}"]]',
            })
        for node in _iter_visible_text_nodes(soup):
            parent = node.parent if isinstance(node.parent, Tag) else None
            text = str(node).strip()
            text_counter += 1
            block_id = f'b{text_counter:06d}'
            block_kind = _classify_block(text, parent)
            block = {
                'block_id': block_id,
                'source_type': 'epub',
                'spine_index': spine_index,
                'href': href,
                'raw_xhtml': relpath(raw_path, out_dir),
                'dom_path': _node_path(node),
                'tag': parent.name if parent else None,
                'class': parent.get('class', []) if parent and parent.has_attr('class') else [],
                'text': text,
                'normalized_text': ' '.join(text.split()),
                'block_kind': block_kind,
                'text_sha256': sha256_text(text),
            }
            blocks.append(block)
            if block_kind in {'heading_candidate', 'structure_candidate'}:
                toc_candidates.append({
                    'candidate_id': f'toc_cand_{len(toc_candidates)+1:05d}',
                    'text': block['normalized_text'],
                    'source': 'xhtml_text',
                    'block_id': block_id,
                    'spine_index': spine_index,
                    'href': href,
                    'score': 0.8 if block_kind == 'heading_candidate' else 0.65,
                    'evidence': [block_id, href],
                })

    inventory = {
        'source_path': str(source),
        'source_sha256': sha256_file(source),
        'format': 'epub',
        'zip_entries': len(names),
        'spine_items': len(opf['spine']),
        'spine_xhtml_extracted': spine_count,
        'metadata': opf['metadata'],
        'opf': opf,
    }
    ensure_dir(out_dir / 'ledger')
    write_jsonl(out_dir / 'ledger' / 'source_blocks.jsonl', blocks)
    write_jsonl(out_dir / 'ledger' / 'image_blocks.jsonl', images)
    write_json(out_dir / 'source' / 'source_inventory.json', inventory)
    write_json(out_dir / 'toc' / 'toc_candidates_seed.json', {'candidates': toc_candidates})
    manifest = {
        'package_version': 1,
        'created_by': 'xuanzang-skill',
        'source': inventory,
        'counts': {'text_blocks': len(blocks), 'image_blocks': len(images), 'toc_seed_candidates': len(toc_candidates)},
    }
    write_json(out_dir / 'package_manifest.json', manifest)
    missing_images = [img for img in images if not img['exists']]
    audit = {
        'status': 'PASS' if not missing_images and blocks else 'FAIL_REVIEW',
        'format': 'epub',
        'zip_entries': len(names),
        'spine_xhtml_extracted': spine_count,
        'text_blocks': len(blocks),
        'image_blocks': len(images),
        'missing_images': missing_images,
        'hard_blockers': [] if not missing_images and blocks else ['missing_image_asset' if missing_images else 'source_coverage_gap'],
    }
    write_json(out_dir / 'audit' / 'source_integrity.json', audit)
    ensure_dir(out_dir / 'audit')
    (out_dir / 'audit' / 'source_integrity.md').write_text(
        f"# Source Integrity\n\n- status: {audit['status']}\n- format: epub\n- zip_entries: {len(names)}\n- text_blocks: {len(blocks)}\n- image_blocks: {len(images)}\n- missing_images: {len(missing_images)}\n",
        encoding='utf-8',
    )
    return audit
