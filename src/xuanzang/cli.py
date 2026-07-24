from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .contracts import RestorePolicy, RestoreRequest, detect_source_format
from .utils import write_json


def _source_type(path: Path) -> str:
    try:
        return detect_source_format(path)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _guard_v1_compat_write(package: Path, command: str) -> None:
    manifest = package / 'package_manifest.json'
    if not manifest.exists():
        return
    payload = json.loads(manifest.read_text(encoding='utf-8'))
    if payload.get('package_version') != 2:
        return
    if str(payload.get('review_revision', '0')) != '0' or payload.get('structure_review_decision_id'):
        raise ValueError(
            f'`{command}` is a v1 compatibility writer and cannot mutate a reviewed v2 package; '
            'submit a revision-bound structure review with `xuanzang review`'
        )
    print(
        f'warning: `{command}` writes compatibility-only proposals into an unreviewed v2 package; '
        'rerun `restore` before v2 review so immutable projections are restored',
        file=sys.stderr,
    )


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
    from .restoration import restore_source
    print('warning: `ledger` is a v1 compatibility alias; prefer `restore`', file=sys.stderr)
    policy = RestorePolicy(target='review', ocr=args.ocr, lang=args.lang, sidecar=getattr(args, 'sidecar', None))
    result = restore_source(RestoreRequest(Path(args.source), Path(args.out), policy, resume=True))
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))


def cmd_toc(args):
    from .toc import build_canonical_toc, harvest_toc_candidates
    package = Path(args.package)
    _guard_v1_compat_write(package, 'toc')
    harvest_toc_candidates(package)
    toc = build_canonical_toc(package)
    print({'items': len(toc.get('items', [])), 'toc_confidence': toc.get('toc_confidence')})


def cmd_split(args):
    from .split import build_boundary_candidates, resolve_boundaries, split_chapters
    package = Path(args.package)
    _guard_v1_compat_write(package, 'split')
    build_boundary_candidates(package)
    resolve_boundaries(package)
    audit = split_chapters(package)
    print(audit)


def cmd_clean(args):
    from .clean import build_rag_structure, repair_linewraps
    package = Path(args.package)
    repair_linewraps(package)
    result = build_rag_structure(package)
    manifest = package / 'package_manifest.json'
    if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8')).get('package_version') == 2:
        from .gates import evaluate_gates
        result = evaluate_gates(package, target='citation')
    print(result)


def cmd_validate(args):
    package = Path(args.package)
    manifest = package / 'package_manifest.json'
    if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8')).get('package_version') == 2:
        from .gates import evaluate_gates
        result = evaluate_gates(package, target='citation' if args.strict else 'hint')
    else:
        from .validate import validate_package
        result = validate_package(package, strict=args.strict)
    print(result)


def cmd_prep_translation(args):
    from .translation import prep_translation
    print(prep_translation(Path(args.package), target=args.target))


def cmd_translate(args):
    if args.provider != 'mock':
        raise SystemExit('v1 local skeleton supports provider=mock; real providers should be implemented through provider interface before use')
    from .translation import run_mock_translation
    print(run_mock_translation(Path(args.package), run_id=args.run_id))


def cmd_audit_translation(args):
    from .translation import semantic_audit_scaffold
    from .validate import validate_translation
    package = Path(args.package)
    run_dir = package / 'translation_runs' / args.run_id
    final = validate_translation(package, run_dir)
    semantic = semantic_audit_scaffold(package, args.run_id)
    print({'mechanical': final['status'], 'semantic_scaffold': semantic['status']})


def cmd_assemble_docx(args):
    from .assemble import assemble_docx
    print(assemble_docx(Path(args.package), args.run_id, Path(args.out)))


def cmd_reinsert_epub(args):
    from .assemble import reinsert_epub
    print(reinsert_epub(Path(args.package), args.run_id, Path(args.out)))


def _policy_from_args(args) -> RestorePolicy:
    return RestorePolicy(
        target=args.target, ocr=args.ocr, lang=args.lang, document_kind=args.document_kind,
        render_dpi=args.render_dpi, force_ocr=args.force_ocr, sidecar=args.sidecar,
        max_pages=args.max_pages, max_total_pixels=args.max_total_pixels,
        max_source_bytes=args.max_source_bytes,
        privacy=args.privacy, preserve_source=args.preserve_source,
        tenant_id=args.tenant_id, workspace_id=args.workspace_id,
        rights_basis=args.rights_basis, retention_policy=args.retention_policy,
        access_tags=tuple(args.access_tag or ()),
        transcription=args.transcription,
        allow_local_conversion=not args.no_local_conversion,
        allow_external_sources=args.allow_external_bundle_sources,
    )


def cmd_restore(args):
    from .restoration import restore_source
    policy = _policy_from_args(args)
    result = restore_source(RestoreRequest(
        source=Path(args.source), out=Path(args.out), policy=policy,
        resume=args.resume, new_run=args.new_run, accept_source_update=args.accept_source_update,
    ))
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))


def cmd_batch(args):
    from .batch import restore_batch
    result = restore_batch(
        Path(args.source_dir), Path(args.out_root), policy=_policy_from_args(args),
        workers=args.workers, recursive=args.recursive, pattern=args.glob,
        limit=args.limit, fail_fast=args.fail_fast,
        accept_source_update=args.accept_source_update,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def cmd_review(args):
    from .review import apply_review
    result = apply_review(
        Path(args.package), Path(args.decisions), expected_revision=args.expected_revision,
        expected_tenant_id=args.expected_tenant_id,
        expected_workspace_id=args.expected_workspace_id,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def cmd_publish(args):
    from .publish import publish_package
    result = publish_package(
        Path(args.package), target=args.target, out=Path(args.out),
        expected_tenant_id=args.expected_tenant_id,
        expected_workspace_id=args.expected_workspace_id,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def cmd_verify_local_strict(args):
    from .acceptance import verify_local_strict
    result = verify_local_strict(Path(args.package), Path(args.export))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result.get('status') != 'PASS_STRICT':
        raise SystemExit(2)


def cmd_status(args):
    from .restoration import package_status
    print(json.dumps(package_status(
        Path(args.package), expected_tenant_id=args.expected_tenant_id,
        expected_workspace_id=args.expected_workspace_id, target=args.target,
    ), ensure_ascii=False, sort_keys=True))


def cmd_migrate_v1(args):
    from .migrate import migrate_v1
    print(json.dumps(migrate_v1(
        Path(args.old), Path(args.out), Path(args.source) if args.source else None,
    ), ensure_ascii=False, sort_keys=True))


def cmd_migrate_book_m1(args):
    from .migrate import migrate_book_m1
    result = migrate_book_m1(
        Path(args.ocr_root), Path(args.source), args.book_id, Path(args.out), copy_assets=args.copy_assets,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def cmd_revoke(args):
    from .lifecycle import revoke_package
    result = revoke_package(
        Path(args.package), reason=args.reason, out=Path(args.out) if args.out else None,
        expected_revision=args.expected_revision,
        expected_tenant_id=args.expected_tenant_id,
        expected_workspace_id=args.expected_workspace_id,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def build_parser():
    p = argparse.ArgumentParser(
        prog='xuanzang',
        description='Auditable document evidence restoration, ManualStrict review, and trust-gated publishing',
    )
    p.add_argument('--version', action='version', version=f'xuanzang {__version__}')
    sub = p.add_subparsers(dest='cmd', required=True)

    s = sub.add_parser('inspect')
    s.add_argument('source')
    s.add_argument('--out')
    s.set_defaults(func=cmd_inspect)

    s = sub.add_parser('ledger')
    s.add_argument('source')
    s.add_argument('--out', required=True)
    s.add_argument('--ocr', default='auto', help='auto|none|paddle|tesseract|mock|sidecar|plugin:NAME')
    s.add_argument('--lang', default=None)
    s.add_argument('--sidecar')
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

    s = sub.add_parser('restore', help='Build or resume a version-2 evidence package')
    s.add_argument('source')
    s.add_argument('--out', required=True)
    s.add_argument('--target', default='review', choices=['hint', 'review', 'citation'])
    s.add_argument('--ocr', default='auto', help='auto|none|paddle|tesseract|mock|sidecar|plugin:NAME')
    s.add_argument('--sidecar', help='Precomputed JSON/JSONL OCR or VLM evidence, including Unlimited-OCR')
    s.add_argument('--lang')
    s.add_argument('--document-kind', default='auto')
    s.add_argument('--render-dpi', type=int, default=200)
    s.add_argument('--max-pages', type=int, default=10000)
    s.add_argument('--max-total-pixels', type=int, default=10000000000)
    s.add_argument('--max-source-bytes', type=int, default=20 * 1024**3)
    s.add_argument('--force-ocr', action='store_true')
    s.add_argument('--privacy', default='local_only', choices=['local_only', 'workspace', 'tenant'])
    s.add_argument('--tenant-id')
    s.add_argument('--workspace-id')
    s.add_argument('--rights-basis', default='user_supplied_private')
    s.add_argument('--retention-policy', default='workspace_default')
    s.add_argument('--access-tag', action='append', default=[], help='Repeatable downstream authorization tag')
    s.add_argument(
        '--transcription', default='source',
        choices=['source', 'diplomatic', 'normalized', 'both'],
        help='Canonical text policy; source/diplomatic preserve source glyphs, normalized/both add reviewed normalization work',
    )
    s.add_argument('--preserve-source', action='store_true')
    s.add_argument('--no-local-conversion', action='store_true')
    s.add_argument(
        '--allow-external-bundle-sources', action='store_true',
        help='Explicitly allow a bundle manifest to reference sources outside its own directory',
    )
    s.add_argument('--resume', action='store_true')
    s.add_argument('--new-run', action='store_true')
    s.add_argument('--accept-source-update', action='store_true')
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser('batch', help='Incrementally restore a directory of documents as independent packages')
    s.add_argument('source_dir')
    s.add_argument('--out-root', required=True)
    s.add_argument('--target', default='hint', choices=['hint', 'review', 'citation'])
    s.add_argument('--ocr', default='auto', help='auto|none|paddle|tesseract|mock|sidecar|plugin:NAME')
    s.add_argument('--sidecar')
    s.add_argument('--lang')
    s.add_argument('--document-kind', default='auto')
    s.add_argument('--render-dpi', type=int, default=200)
    s.add_argument('--max-pages', type=int, default=10000)
    s.add_argument('--max-total-pixels', type=int, default=10000000000)
    s.add_argument('--max-source-bytes', type=int, default=20 * 1024**3)
    s.add_argument('--force-ocr', action='store_true')
    s.add_argument('--privacy', default='local_only', choices=['local_only', 'workspace', 'tenant'])
    s.add_argument('--tenant-id')
    s.add_argument('--workspace-id')
    s.add_argument('--rights-basis', default='user_supplied_private')
    s.add_argument('--retention-policy', default='workspace_default')
    s.add_argument('--access-tag', action='append', default=[])
    s.add_argument('--transcription', default='source', choices=['source', 'diplomatic', 'normalized', 'both'])
    s.add_argument('--preserve-source', action='store_true')
    s.add_argument('--no-local-conversion', action='store_true')
    s.add_argument('--allow-external-bundle-sources', action='store_true')
    s.add_argument('--workers', type=int, default=2)
    s.add_argument('--recursive', action=argparse.BooleanOptionalAction, default=True)
    s.add_argument('--glob', default='*')
    s.add_argument('--limit', type=int)
    s.add_argument('--fail-fast', action='store_true')
    s.add_argument('--accept-source-update', action='store_true')
    s.set_defaults(func=cmd_batch)

    s = sub.add_parser('review', help='Append semantic review decisions and recompute gates')
    s.add_argument('package')
    s.add_argument('--decisions', required=True)
    s.add_argument('--expected-revision')
    s.add_argument('--expected-tenant-id')
    s.add_argument('--expected-workspace-id')
    s.set_defaults(func=cmd_review)

    s = sub.add_parser('publish', help='Publish hint or citation-grade Markdown/chunks')
    s.add_argument('package')
    s.add_argument('--target', required=True, choices=['hint', 'citation'])
    s.add_argument('--out', required=True)
    s.add_argument('--expected-tenant-id')
    s.add_argument('--expected-workspace-id')
    s.set_defaults(func=cmd_publish)

    s = sub.add_parser(
        'verify-local-strict',
        help='Independently verify a citation export against its active package and strict Markdown contract',
    )
    s.add_argument('package')
    s.add_argument('--export', required=True)
    s.set_defaults(func=cmd_verify_local_strict)

    s = sub.add_parser('status', help='Recompute and print package trust state')
    s.add_argument('package')
    s.add_argument(
        '--target', default='citation', choices=['hint', 'review', 'citation'],
        help='Gate to recompute; citation remains the fail-closed default',
    )
    s.add_argument('--expected-tenant-id')
    s.add_argument('--expected-workspace-id')
    s.set_defaults(func=cmd_status)

    s = sub.add_parser('migrate-v1', help='Migrate a v1 package without rerunning OCR')
    s.add_argument('old')
    s.add_argument('--out', required=True)
    s.add_argument('--source', help='Explicit original source used to verify legacy source identity')
    s.set_defaults(func=cmd_migrate_v1)

    s = sub.add_parser('migrate-book-m1', help='Import AG Brain Book M1 OCR sidecars without rerunning OCR')
    s.add_argument('ocr_root')
    s.add_argument('--source', required=True)
    s.add_argument('--book-id', required=True)
    s.add_argument('--out', required=True)
    s.add_argument('--copy-assets', action='store_true')
    s.set_defaults(func=cmd_migrate_book_m1)

    s = sub.add_parser('revoke', help='Revoke a package and emit a downstream deletion tombstone')
    s.add_argument('package')
    s.add_argument('--reason', required=True)
    s.add_argument('--out', help='Optional external copy of the revocation tombstone')
    s.add_argument('--expected-revision')
    s.add_argument('--expected-tenant-id')
    s.add_argument('--expected-workspace-id')
    s.set_defaults(func=cmd_revoke)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as exc:
        print(json.dumps({'status': 'invalid_input', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(4) from exc
    except RuntimeError as exc:
        status = 'needs_review' if 'blocked by' in str(exc) else 'runtime_failure'
        code = 2 if status == 'needs_review' else 5
        print(json.dumps({'status': status, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(code) from exc


if __name__ == '__main__':
    main()
