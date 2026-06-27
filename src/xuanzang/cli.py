from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .assemble import assemble_docx, reinsert_epub
from .clean import build_rag_structure, repair_linewraps
from .epub import extract_epub
from .ocr import audit_ocr
from .pdf import extract_pdf
from .split import build_boundary_candidates, resolve_boundaries, split_chapters
from .toc import build_canonical_toc, harvest_toc_candidates
from .translation import prep_translation, run_mock_translation, semantic_audit_scaffold
from .utils import write_json
from .validate import validate_package, validate_translation


def _source_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == '.epub':
        return 'epub'
    if ext == '.pdf':
        return 'pdf'
    raise SystemExit(f'unsupported source format: {ext}')


def cmd_inspect(args):
    src = Path(args.source)
    if not src.exists():
        raise SystemExit(f'source not found: {src}')
    info = {'path': str(src.resolve()), 'format': _source_type(src), 'size_bytes': src.stat().st_size, 'version': __version__}
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        write_json(out / 'inspect.json', info)
    print(info)


def cmd_ledger(args):
    src = Path(args.source)
    out = Path(args.out)
    fmt = _source_type(src)
    if fmt == 'epub':
        audit = extract_epub(src, out)
    else:
        audit = extract_pdf(src, out, ocr=args.ocr, lang=args.lang)
        audit_ocr(out, lang=args.lang)
    print(audit)


def cmd_toc(args):
    package = Path(args.package)
    harvest_toc_candidates(package)
    toc = build_canonical_toc(package)
    print({'items': len(toc.get('items', [])), 'toc_confidence': toc.get('toc_confidence')})


def cmd_split(args):
    package = Path(args.package)
    build_boundary_candidates(package)
    resolve_boundaries(package)
    audit = split_chapters(package)
    print(audit)


def cmd_clean(args):
    package = Path(args.package)
    repair_linewraps(package)
    result = build_rag_structure(package)
    print(result)


def cmd_validate(args):
    result = validate_package(Path(args.package), strict=args.strict)
    print(result)


def cmd_prep_translation(args):
    print(prep_translation(Path(args.package), target=args.target))


def cmd_translate(args):
    if args.provider != 'mock':
        raise SystemExit('v1 local skeleton supports provider=mock; real providers should be implemented through provider interface before use')
    print(run_mock_translation(Path(args.package), run_id=args.run_id))


def cmd_audit_translation(args):
    package = Path(args.package)
    run_dir = package / 'translation_runs' / args.run_id
    final = validate_translation(package, run_dir)
    semantic = semantic_audit_scaffold(package, args.run_id)
    print({'mechanical': final['status'], 'semantic_scaffold': semantic['status']})


def cmd_assemble_docx(args):
    print(assemble_docx(Path(args.package), args.run_id, Path(args.out)))


def cmd_reinsert_epub(args):
    print(reinsert_epub(Path(args.package), args.run_id, Path(args.out)))


def build_parser():
    p = argparse.ArgumentParser(prog='xuanzang', description='Strict book reconstruction and translation workflow')
    p.add_argument('--version', action='version', version=f'xuanzang {__version__}')
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('inspect')
    s.add_argument('source')
    s.add_argument('--out')
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser('ledger')
    s.add_argument('source')
    s.add_argument('--out', required=True)
    s.add_argument('--ocr', default='auto', choices=['auto', 'mock', 'none'])
    s.add_argument('--lang', default=None)
    s.set_defaults(func=cmd_ledger)

    s = sub.add_parser('toc')
    s.add_argument('package')
    s.set_defaults(func=cmd_toc)

    s = sub.add_parser('split')
    s.add_argument('package')
    s.set_defaults(func=cmd_split)

    s = sub.add_parser('clean')
    s.add_argument('package')
    s.set_defaults(func=cmd_clean)

    s = sub.add_parser('validate')
    s.add_argument('package')
    s.add_argument('--strict', action='store_true')
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser('prep-translation')
    s.add_argument('package')
    s.add_argument('--target', default='zh-CN')
    s.set_defaults(func=cmd_prep_translation)

    s = sub.add_parser('translate')
    s.add_argument('package')
    s.add_argument('--provider', default='mock')
    s.add_argument('--run-id', default='mock_v1')
    s.set_defaults(func=cmd_translate)

    s = sub.add_parser('audit-translation')
    s.add_argument('package')
    s.add_argument('--run-id', default='mock_v1')
    s.set_defaults(func=cmd_audit_translation)

    s = sub.add_parser('assemble-docx')
    s.add_argument('package')
    s.add_argument('--run-id', default='mock_v1')
    s.add_argument('--out', required=True)
    s.set_defaults(func=cmd_assemble_docx)

    s = sub.add_parser('reinsert-epub')
    s.add_argument('package')
    s.add_argument('--run-id', default='mock_v1')
    s.add_argument('--out', required=True)
    s.set_defaults(func=cmd_reinsert_epub)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == '__main__':
    main()
