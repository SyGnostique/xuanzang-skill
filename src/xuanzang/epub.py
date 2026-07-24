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

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

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


_XML_ENCODING_RE = re.compile(
    br'^\s*<\?xml[^>]*\bencoding\s*=\s*["\']\s*([^"\']+)\s*["\']',
    re.IGNORECASE,
)
_HTML_META_CHARSET_RE = re.compile(
    br'<meta\b[^>]*\bcharset\s*=\s*["\']?\s*([^\s"\'/>;]+)',
    re.IGNORECASE,
)
_PRE_FRAGMENT_RE = re.compile(
    r'<pre\b[^>]*>.*?</pre\s*>',
    re.IGNORECASE | re.DOTALL,
)


def _decode_epub_xml_text(data: bytes, *, label: str) -> str:
    """Decode EPUB XML/XHTML without BeautifulSoup's HTML-era byte guesswork.

    EPUB XML content is Unicode. Some valid XHTML omits an XML declaration and
    declares UTF-8 only in an HTML ``meta`` element. Passing those bytes to
    BeautifulSoup's XML parser makes charset-normalizer guess Windows-1252,
    corrupting UTF-8 punctuation before DOM extraction. Honor BOM/declarations
    and otherwise use EPUB's UTF-8 default, failing closed on invalid bytes.
    """
    if b'\x00' not in data and b'<!DOCTYPE' in data.upper():
        matches = list(re.finditer(br'<!DOCTYPE\s+html\s*>', data, re.IGNORECASE))
        if len(matches) == 1 and b'<!ENTITY' not in data.upper():
            match = matches[0]
            data = data[:match.start()] + data[match.end():]
    assert_safe_xml_bytes(data, label=label)
    if data.startswith(b'\x00\x00\xfe\xff'):
        return data.decode('utf-32-be')
    if data.startswith(b'\xff\xfe\x00\x00'):
        return data.decode('utf-32-le')
    if data.startswith((b'\xfe\xff', b'\xff\xfe')):
        return data.decode('utf-16')
    if data.startswith(b'\xef\xbb\xbf'):
        return data.decode('utf-8-sig')
    prefix = data[:2048]
    match = _XML_ENCODING_RE.search(prefix) or _HTML_META_CHARSET_RE.search(prefix)
    encoding = match.group(1).decode('ascii') if match else 'utf-8'
    try:
        return data.decode(encoding)
    except (LookupError, UnicodeDecodeError) as exc:
        raise ValueError(f'{label} has invalid or unsupported text encoding {encoding!r}') from exc


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
        path.append(next((index for index, sibling in enumerate(siblings) if sibling is cur), 0))
        cur = cur.parent
    return list(reversed(path))


def _is_visible_text_node(node: NavigableString) -> bool:
    if isinstance(node, Comment):
        return False
    text = str(node)
    if not text.strip():
        return False
    parent = node.parent
    if not isinstance(parent, Tag):
        return False
    if parent.name in {'script', 'style', 'meta', 'title', 'math'} or parent.find_parent('math') is not None:
        return False
    return True


def _has_hidden_ancestor(node: Tag | NavigableString, hidden_tag_ids: set[int]) -> bool:
    current: Any = node if isinstance(node, Tag) else node.parent
    while isinstance(current, Tag):
        if id(current) in hidden_tag_ids:
            return True
        current = current.parent
    return False


def _css_hides_content(declarations: str) -> bool:
    compact = re.sub(r'\s+', '', declarations).casefold()
    return bool(
        re.search(r'(?:^|;)display:none(?:!important)?(?:;|$)', compact)
        or re.search(r'(?:^|;)visibility:hidden(?:!important)?(?:;|$)', compact)
    )


def _epub_stylesheets(
    soup: BeautifulSoup, *, src_path: Path, epub_tree: Path,
) -> list[tuple[str, str]]:
    """Return inline and local linked CSS available to one XHTML surface."""
    stylesheets: list[tuple[str, str]] = []
    for style in soup.find_all('style'):
        stylesheets.append(('inline-style', style.get_text('\n', strip=False)))
    for link in soup.find_all('link'):
        rel_values = link.get('rel', [])
        if isinstance(rel_values, str):
            rel_values = rel_values.split()
        if 'stylesheet' not in {str(value).casefold() for value in rel_values}:
            continue
        href = str(link.get('href') or '')
        local_href = _local_reference(href)
        if not local_href:
            continue
        try:
            stylesheet = contained_path(
                epub_tree,
                str((src_path.parent.relative_to(epub_tree) / local_href).as_posix()),
            )
        except ValueError:
            continue
        if not stylesheet.is_file():
            continue
        try:
            css_text = stylesheet.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            css_text = stylesheet.read_text(encoding='latin-1')
        stylesheets.append((relpath(stylesheet, epub_tree), css_text))
    return stylesheets


def _css_hidden_tags(
    soup: BeautifulSoup, *, src_path: Path, epub_tree: Path,
) -> tuple[set[int], dict[str, Any]]:
    """Resolve explicit EPUB CSS visibility rules into an auditable DOM mask.

    Navigation documents are sometimes placed in the reading spine for device
    compatibility while their semantic ``nav`` trees are hidden by CSS. Those
    nodes remain preserved in the source tree and navigation ledger, but are
    not visible prose and must not enter the canonical text projection.
    """
    stylesheets = _epub_stylesheets(soup, src_path=src_path, epub_tree=epub_tree)

    hidden_tag_ids: set[int] = set()
    matched_selectors: list[dict[str, Any]] = []
    for tag in soup.find_all(True):
        if tag.has_attr('hidden') or _css_hides_content(str(tag.get('style') or '')):
            hidden_tag_ids.add(id(tag))
    for stylesheet_path, css_text in stylesheets:
        without_comments = re.sub(r'/\*.*?\*/', '', css_text, flags=re.DOTALL)
        for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', without_comments):
            declarations = match.group(2)
            if not _css_hides_content(declarations):
                continue
            for selector in match.group(1).split(','):
                selector = selector.strip()
                if not selector or selector.startswith('@'):
                    continue
                try:
                    matched = list(soup.select(selector))
                except Exception:
                    continue
                if not matched:
                    continue
                hidden_tag_ids.update(id(tag) for tag in matched)
                matched_selectors.append({
                    'stylesheet': stylesheet_path,
                    'selector': selector,
                    'matched_elements': len(matched),
                })
    return hidden_tag_ids, {
        'stylesheet_paths': [path for path, _text in stylesheets],
        'hidden_selectors': matched_selectors,
        'hidden_element_roots': len(hidden_tag_ids),
    }


def _css_block_tags(
    soup: BeautifulSoup, *, src_path: Path, epub_tree: Path,
) -> set[int]:
    """Resolve explicit ``display:block`` rules for text-boundary recovery.

    EPUB prose often uses inline ``span`` elements as visually separate chapter
    title lines or figure-credit lines. XML text-node concatenation cannot see
    that CSS boundary, so retain the matched elements for DOM-container text
    reconstruction.
    """
    block_tag_ids = {
        id(tag) for tag in soup.find_all(True)
        if re.search(
            r'(?:^|;)display:block(?:!important)?(?:;|$)',
            re.sub(r'\s+', '', str(tag.get('style') or '')).casefold(),
        )
    }
    for _stylesheet_path, css_text in _epub_stylesheets(
        soup, src_path=src_path, epub_tree=epub_tree,
    ):
        without_comments = re.sub(r'/\*.*?\*/', '', css_text, flags=re.DOTALL)
        for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', without_comments):
            declarations = re.sub(r'\s+', '', match.group(2)).casefold()
            if not re.search(r'(?:^|;)display:block(?:!important)?(?:;|$)', declarations):
                continue
            for selector in match.group(1).split(','):
                selector = selector.strip()
                if not selector or selector.startswith('@'):
                    continue
                try:
                    block_tag_ids.update(id(tag) for tag in soup.select(selector))
                except Exception:
                    continue
    return block_tag_ids


def _iter_visible_text_nodes(soup: BeautifulSoup, hidden_tag_ids: set[int] | None = None):
    hidden_tag_ids = hidden_tag_ids or set()
    body = soup.find('body') or soup
    for node in body.descendants:
        if _has_hidden_ancestor(node, hidden_tag_ids):
            continue
        if isinstance(node, Tag) and node.name == 'math':
            yield node
            continue
        if isinstance(node, Tag) and node.name in {'img', 'image'} and _is_callout_image(node):
            yield node
            continue
        if isinstance(node, NavigableString) and _is_visible_text_node(node):
            yield node


def _is_callout_image(node: Tag) -> bool:
    anchor = _nearest_ancestor(node, 'a')
    href = str(anchor.get('href') or '') if anchor else ''
    src = str(node.get('src') or node.get('href') or node.get('xlink:href') or '')
    try:
        width = int(float(str(node.get('width') or '0').replace('px', '')))
        height = int(float(str(node.get('height') or '0').replace('px', '')))
    except ValueError:
        width = height = 0
    numeric_asset = bool(re.fullmatch(r'\d+', Path(urlsplit(src).path).stem))
    tiny = bool(width and height and width <= 32 and height <= 32)
    return href.startswith('#') and (numeric_asset or tiny)


def _preformatted_payloads(
    html_text: str, soup: BeautifulSoup, *, label: str,
) -> dict[tuple[int, ...], dict[str, str]]:
    """Bind each parsed ``pre`` node to its byte-decoded source fragment.

    ``lxml-xml`` deliberately removes whitespace-only text nodes between inline
    elements.  In ordinary prose that is useful, but in a program listing those
    nodes are indentation and therefore evidence.  Recover code text from the
    original XHTML fragment with the HTML parser, which preserves preformatted
    whitespace, while retaining the exact source XML as a second representation.
    """
    parsed_pres = soup.find_all('pre')
    raw_fragments = _PRE_FRAGMENT_RE.findall(html_text)
    if len(parsed_pres) != len(raw_fragments):
        raise ValueError(
            f'{label} has {len(parsed_pres)} parsed pre elements but '
            f'{len(raw_fragments)} recoverable source fragments'
        )
    payloads: dict[tuple[int, ...], dict[str, str]] = {}
    for parsed_pre, raw_xml in zip(parsed_pres, raw_fragments):
        fragment_soup = BeautifulSoup(raw_xml, 'lxml')
        source_pre = fragment_soup.find('pre')
        if source_pre is None:
            raise ValueError(f'{label} contains an unreadable preformatted source fragment')
        for image in source_pre.find_all(['img', 'image']):
            if not _is_callout_image(image):
                continue
            source_ref = str(image.get('src') or image.get('href') or image.get('xlink:href') or '')
            callout_label = str(image.get('alt') or '').strip() or Path(urlsplit(source_ref).path).stem
            image.replace_with(f'[[Callout {callout_label}]]')
        payloads[tuple(_node_path(parsed_pre))] = {
            'pre_xml': raw_xml,
            'pre_text': source_pre.get_text('', strip=False),
        }
    return payloads


def _mathml_readable(node: Tag) -> str:
    """Render common presentation MathML into compact reversible notation."""
    name = str(node.name or '').split(':')[-1]
    children = [child for child in node.children if isinstance(child, Tag)]
    if name in {'mi', 'mn', 'mo', 'mtext', 'ms'}:
        return ' '.join(node.stripped_strings)
    rendered = [value for child in children if (value := _mathml_readable(child))]
    if name == 'msup' and len(rendered) >= 2:
        return f'{rendered[0]}^{{{rendered[1]}}}'
    if name == 'msub' and len(rendered) >= 2:
        return f'{rendered[0]}_{{{rendered[1]}}}'
    if name == 'msubsup' and len(rendered) >= 3:
        return f'{rendered[0]}_{{{rendered[1]}}}^{{{rendered[2]}}}'
    if name == 'mfrac' and len(rendered) >= 2:
        return f'({rendered[0]})/({rendered[1]})'
    if name == 'msqrt' and rendered:
        return f'sqrt({" ".join(rendered)})'
    if name == 'mroot' and len(rendered) >= 2:
        return f'root[{rendered[1]}]({rendered[0]})'
    if name in {'munder', 'mover'} and len(rendered) >= 2:
        marker = '_' if name == 'munder' else '^'
        return f'{rendered[0]}{marker}{{{rendered[1]}}}'
    if name == 'munderover' and len(rendered) >= 3:
        return f'{rendered[0]}_{{{rendered[1]}}}^{{{rendered[2]}}}'
    if name == 'mfenced':
        return f'{node.get("open") or "("}{" ".join(rendered)}{node.get("close") or ")"}'
    return ' '.join(rendered) or ' '.join(node.stripped_strings)


def _classify_block(text: str, parent: Tag | None = None) -> str:
    t = ' '.join(text.split())
    tag = parent.name if parent else ''
    cls = ' '.join(_class_values(parent)) if parent and parent.has_attr('class') else ''
    low = t.lower()
    ancestors = list(parent.parents) if parent else []
    if tag == 'math':
        return 'equation_candidate'
    if tag in {'img', 'image'} and parent is not None and _is_callout_image(parent):
        return 'callout_candidate'
    if tag == 'pre' or any(getattr(node, 'name', None) == 'pre' for node in ancestors):
        return 'code_candidate'
    if tag in {'td', 'th', 'caption'} or any(getattr(node, 'name', None) == 'table' for node in ancestors):
        return 'table_candidate'
    if any(
        _is_figure_caption(node)
        for node in ([parent] if parent is not None else []) + ancestors
        if isinstance(node, Tag)
    ):
        return 'caption_candidate'
    if tag in {'h1', 'h2', 'h3', 'h4'}:
        return 'heading_candidate'
    if re.match(r'^(chapter|part|book|section)\b', low) or re.match(r'^(第[一二三四五六七八九十百0-9]+[章节部篇])', t):
        return 'heading_candidate'
    if any(k in low for k in ['contents', 'bibliography', 'notes', 'index', 'acknowledgements', 'glossary']):
        return 'structure_candidate'
    if 'caption' in cls or tag in {'figcaption'}:
        return 'caption_candidate'
    return 'text_candidate'


def _nearest_ancestor(node: Tag | NavigableString, name: str) -> Tag | None:
    current = node.parent
    while isinstance(current, Tag):
        if current.name == name:
            return current
        current = current.parent
    return None


_TEXT_CONTAINER_TAGS = {
    'p', 'li', 'dt', 'dd', 'td', 'th', 'caption', 'figcaption',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'blockquote',
}


def _dom_container_text(
    node: Tag | NavigableString, block_tag_ids: set[int] | None = None,
) -> str | None:
    current: Any = node if isinstance(node, Tag) else node.parent
    while isinstance(current, Tag) and current.name not in _TEXT_CONTAINER_TAGS:
        current = current.parent
    if not isinstance(current, Tag):
        return None
    block_tag_ids = block_tag_ids or set()

    def render_children(tag: Tag) -> str:
        parts: list[str] = []
        for child in tag.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            if child.name == 'br':
                parts.append('\n')
                continue
            is_css_block = id(child) in block_tag_ids
            if is_css_block:
                parts.append('\n')
            parts.append(render_children(child))
            if is_css_block:
                parts.append('\n')
        return ''.join(parts)

    text = render_children(current)
    if current.name == 'pre':
        return text.strip('\n')
    return re.sub(r'\s+', ' ', text).strip()


def _class_values(tag: Tag) -> list[str]:
    value = tag.get('class', [])
    if isinstance(value, str):
        return value.split()
    return [str(item) for item in value]


def _class_tokens(tag: Tag) -> set[str]:
    return {value.casefold() for value in _class_values(tag)}


def _is_figure_container(tag: Tag) -> bool:
    return bool(
        tag.name == 'figure'
        or (
            tag.name == 'div'
            and _class_tokens(tag) & {'fig', 'table', 'cover_image', 'title_image'}
        )
    )


def _nearest_figure_container(node: Tag | NavigableString) -> Tag | None:
    current = node.parent
    while isinstance(current, Tag):
        if _is_figure_container(current):
            return current
        current = current.parent
    return None


def _is_figure_caption(tag: Tag) -> bool:
    if tag.name == 'figcaption':
        return True
    if tag.name in {'h5', 'h6'} and _nearest_figure_container(tag) is not None:
        return True
    return bool(
        tag.name in {'p', 'div'}
        and _class_tokens(tag) & {'image_caption', 'table_caption', 'figcaption', 'caption'}
        and _nearest_figure_container(tag) is not None
    )


def _find_figure_caption(container: Tag) -> Tag | None:
    return next(
        (tag for tag in container.find_all(['figcaption', 'h5', 'h6', 'p', 'div']) if _is_figure_caption(tag)),
        None,
    )


def _epub_type(tag: Tag) -> str:
    return str(tag.get('epub:type') or tag.get('type') or '')


def _node_metadata(
    node: Tag | NavigableString,
    preformatted_payloads: dict[tuple[int, ...], dict[str, str]] | None = None,
    block_tag_ids: set[int] | None = None,
) -> dict[str, Any]:
    ancestors: list[Tag] = []
    current = node.parent
    while isinstance(current, Tag):
        ancestors.append(current)
        current = current.parent
    ancestor_ids = [str(tag.get('id')) for tag in ancestors if tag.get('id')]
    ancestor_tags = [str(tag.name) for tag in ancestors if tag.name]
    epub_types = [value for tag in ancestors if (value := _epub_type(tag))]
    data_types = [str(tag.get('data-type')) for tag in ancestors if tag.get('data-type')]
    nav = next((tag for tag in ancestors if tag.name == 'nav'), None)
    anchor = next((tag for tag in ancestors if tag.name == 'a'), None)
    figure = next((tag for tag in ancestors if _is_figure_container(tag)), None)
    figcaption = next((tag for tag in ancestors if _is_figure_caption(tag)), None)
    table = next((tag for tag in ancestors if tag.name == 'table'), None)
    pre = node if isinstance(node, Tag) and node.name == 'pre' else next(
        (tag for tag in ancestors if tag.name == 'pre'), None
    )
    cell = next((tag for tag in ancestors if tag.name in {'td', 'th'}), None)
    row = _nearest_ancestor(cell, 'tr') if cell else None
    metadata: dict[str, Any] = {
        'ancestor_ids': ancestor_ids,
        'ancestor_tags': ancestor_tags,
        'epub_types': epub_types,
        'data_types': data_types,
        'source_role': 'auxiliary_navigation' if nav is not None else 'primary',
    }
    dom_container_text = _dom_container_text(node, block_tag_ids)
    if dom_container_text is not None:
        metadata['dom_container_text'] = dom_container_text
    if anchor is not None:
        anchor_style = str(anchor.get('style') or '').replace(' ', '').casefold()
        parent_style = str(anchor.parent.get('style') or '').replace(' ', '').casefold() if isinstance(anchor.parent, Tag) else ''
        anchor_text = ' '.join(anchor.get_text(' ', strip=True).split())
        if (
            anchor_text.casefold().startswith('translated by ')
            and ('font-size:' in anchor_style or 'font-size:' in parent_style)
            and ('text-align:right' in parent_style or 'color:#ccc' in anchor_style)
        ):
            metadata['source_role'] = 'recurring_footer'
    if anchor is not None and anchor.get('href'):
        metadata['link_href'] = str(anchor.get('href'))
        metadata['link_text'] = ' '.join(anchor.get_text(' ', strip=True).split())
        metadata['link_rel'] = list(anchor.get('rel', [])) if anchor.has_attr('rel') else []
    if isinstance(node, Tag) and node.name in {'img', 'image'} and _is_callout_image(node):
        source_ref = str(node.get('src') or node.get('href') or node.get('xlink:href') or '')
        metadata.update({
            'source_role': 'code_callout',
            'callout_dom_path': _node_path(node),
            'callout_src': source_ref,
            'callout_label': str(node.get('alt') or '').strip() or Path(urlsplit(source_ref).path).stem,
            'callout_target': str(anchor.get('href') or '') if anchor else None,
            'callout_anchor_id': str(anchor.get('id') or '') or None if anchor else None,
            'callout_anchor_dom_path': _node_path(anchor) if anchor else None,
        })
    for prefix, tag in (('figure', figure), ('figcaption', figcaption), ('table', table)):
        if tag is not None:
            metadata[f'{prefix}_id'] = str(tag.get('id') or '') or None
            metadata[f'{prefix}_dom_path'] = _node_path(tag)
    if table is not None:
        caption = table.find('caption')
        metadata['table_caption'] = ' '.join(caption.get_text(' ', strip=True).split()) if caption else None
    if cell is not None:
        rows = table.find_all('tr') if table else []
        cells = row.find_all(['th', 'td'], recursive=False) if row else []
        metadata.update({
            'table_row_index': next((index for index, item in enumerate(rows) if item is row), None),
            'table_cell_index': next((index for index, item in enumerate(cells) if item is cell), None),
            'table_cell_tag': cell.name,
            'rowspan': str(cell.get('rowspan') or '1'),
            'colspan': str(cell.get('colspan') or '1'),
        })
    if pre is not None:
        payload = (preformatted_payloads or {}).get(tuple(_node_path(pre)), {})
        pre_xml = str(payload.get('pre_xml') or pre)
        pre_text = str(payload.get('pre_text') or pre.get_text('', strip=False))
        classes = _class_values(pre)
        code = pre.find('code')
        if code is not None:
            classes.extend(_class_values(code))
        language = str(pre.get('data-code-language') or '').strip() or next(
            (
                match.group(1) for value in classes
                if (match := re.search(r'(?:language-|lang-)([A-Za-z0-9_+-]+)', value))
            ),
            None,
        )
        metadata.update({
            'pre_dom_path': _node_path(pre),
            'pre_xml': pre_xml,
            'pre_xml_sha256': sha256_text(pre_xml),
            'pre_text': pre_text,
            'pre_text_sha256': sha256_text(pre_text),
            'code_language': language,
        })
    math = node if isinstance(node, Tag) and node.name == 'math' else next(
        (tag for tag in ancestors if tag.name == 'math'), None
    )
    if math is not None:
        mathml_xml = str(math)
        metadata.update({
            'mathml_dom_path': _node_path(math),
            'mathml_xml': mathml_xml,
            'mathml_sha256': sha256_text(mathml_xml),
            'mathml_alttext': str(math.get('alttext') or '').strip() or None,
            'mathml_display': str(math.get('display') or '').strip() or None,
        })
    return metadata


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
    visibility_audit = {
        'hidden_text_nodes': 0,
        'hidden_image_occurrences': 0,
        'surfaces': [],
    }

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
        html_text = _decode_epub_xml_text(html_bytes, label=f'EPUB spine XHTML {href}')
        soup = BeautifulSoup(html_text, 'lxml-xml')
        hidden_tag_ids, surface_visibility = _css_hidden_tags(
            soup, src_path=src_path, epub_tree=epub_tree,
        )
        block_tag_ids = _css_block_tags(
            soup, src_path=src_path, epub_tree=epub_tree,
        )
        hidden_nodes = [
            node for node in (soup.find('body') or soup).descendants
            if isinstance(node, NavigableString)
            and _is_visible_text_node(node)
            and _has_hidden_ancestor(node, hidden_tag_ids)
        ]
        hidden_text_nodes = len(hidden_nodes)
        hidden_images = sum(
            _has_hidden_ancestor(image, hidden_tag_ids)
            for image in soup.find_all(['img', 'image'])
        )
        visibility_audit['hidden_text_nodes'] += hidden_text_nodes
        visibility_audit['hidden_image_occurrences'] += hidden_images
        if hidden_text_nodes or hidden_images:
            visibility_audit['surfaces'].append({
                'spine_index': spine_index,
                'href': href,
                'hidden_text_nodes': hidden_text_nodes,
                'hidden_image_occurrences': hidden_images,
                'hidden_text_dom_paths': [_node_path(node) for node in hidden_nodes],
                **surface_visibility,
            })
        preformatted_payloads = _preformatted_payloads(
            html_text, soup, label=f'EPUB spine XHTML {href}',
        )
        for img in soup.find_all(['img', 'image']):
            if _has_hidden_ancestor(img, hidden_tag_ids):
                continue
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
            figure = _nearest_figure_container(img)
            figcaption = _find_figure_caption(figure) if figure else None
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
                'alt_text': str(img.get('alt') or '').strip() or None,
                'figure_id': str(figure.get('id') or '') or None if figure else None,
                'figure_dom_path': _node_path(figure) if figure else None,
                'caption_text': (
                    ' '.join((_dom_container_text(figcaption, block_tag_ids) or '').split())
                    if figcaption else None
                ),
                'caption_dom_path': _node_path(figcaption) if figcaption else None,
                'callout_role': 'code_callout' if _is_callout_image(img) else None,
                'callout_target': str((_nearest_ancestor(img, 'a') or {}).get('href') or '') or None,
                'callout_anchor_id': str((_nearest_ancestor(img, 'a') or {}).get('id') or '') or None,
                'marker': f'[[IMAGE {image_id} src="{ref}"]]',
            })
        for node in _iter_visible_text_nodes(soup, hidden_tag_ids):
            parent = node if isinstance(node, Tag) else (node.parent if isinstance(node.parent, Tag) else None)
            if isinstance(node, Tag) and node.name == 'math':
                text = re.sub(r'\s+', ' ', _mathml_readable(node)).strip()
            elif isinstance(node, Tag) and node.name in {'img', 'image'}:
                source_ref = str(node.get('src') or node.get('href') or node.get('xlink:href') or '')
                label = str(node.get('alt') or '').strip() or Path(urlsplit(source_ref).path).stem
                text = f'Callout {label}'.strip()
            else:
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
                'class': _class_values(parent) if parent and parent.has_attr('class') else [],
                'text': text,
                'normalized_text': ' '.join(text.split()),
                'block_kind': block_kind,
                'text_sha256': sha256_text(text),
                **_node_metadata(node, preformatted_payloads, block_tag_ids),
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
        'visibility_audit': visibility_audit,
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
