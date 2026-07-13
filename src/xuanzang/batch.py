from __future__ import annotations

import time
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .contracts import RestorePolicy, RestoreRequest, SUPPORTED_FORMATS
from .restoration import restore_source
from .utils import append_jsonl, ensure_dir, package_lock, sha256_text, slugify, utc_now, write_json


def restore_batch(
    source_dir: Path,
    out_root: Path,
    *,
    policy: RestorePolicy,
    workers: int = 2,
    recursive: bool = True,
    pattern: str = '*',
    limit: int | None = None,
    fail_fast: bool = False,
    accept_source_update: bool = False,
) -> dict[str, Any]:
    policy.validate()
    if policy.ocr == 'sidecar':
        raise ValueError('batch mode requires per-document sidecars through separate restore calls or an OCR plugin')
    if not 1 <= workers <= 32:
        raise ValueError('workers must be between 1 and 32')
    if limit is not None and limit < 1:
        raise ValueError('limit must be positive')
    source_dir = source_dir.resolve()
    out_root = out_root.resolve()
    if not source_dir.is_dir():
        raise ValueError(f'batch source_dir is not a directory: {source_dir}')
    if out_root == source_dir or source_dir in out_root.parents:
        raise ValueError('batch output root must be outside source_dir')
    iterator = source_dir.rglob(pattern) if recursive else source_dir.glob(pattern)
    candidates = []
    for path in sorted(iterator):
        if path.is_symlink():
            raise ValueError(f'batch source symlink is not allowed: {path}')
        if path.is_file() and path.suffix.lower() in SUPPORTED_FORMATS:
            candidates.append(path)
    if limit is not None:
        candidates = candidates[:limit]
    ensure_dir(out_root)
    batch_id = f"batch_{sha256_text(str(source_dir) + policy.fingerprint)[:20]}"
    results_path = out_root / 'batch_results.jsonl'

    def source_identity(source: Path) -> tuple[str, str]:
        relative = source.relative_to(source_dir).as_posix()
        package_name = f"{slugify(source.stem, 'document')[:64]}_{sha256_text(relative)[:12]}"
        return relative, package_name

    def process(source: Path) -> dict[str, Any]:
        relative, package_name = source_identity(source)
        package = out_root / 'packages' / package_name
        started = time.monotonic()
        try:
            restored = restore_source(RestoreRequest(
                source=source,
                out=package,
                policy=policy,
                resume=True,
                accept_source_update=accept_source_update,
            ))
            restored_payload = restored.to_dict()
            restored_payload['package'] = (
                restored_payload['package'] if policy.privacy == 'local_only'
                else f'packages/{package_name}'
            )
            return {
                'batch_id': batch_id, 'source_rel': relative, 'package_rel': f'packages/{package_name}',
                'status': 'complete', **restored_payload,
                'elapsed_seconds': round(time.monotonic() - started, 3), 'completed_at': utc_now(),
            }
        except Exception as exc:
            error = str(exc)
            if policy.privacy != 'local_only':
                error = error.replace(str(source_dir), '<source_root>').replace(str(out_root), '<out_root>')
            return {
                'batch_id': batch_id, 'source_rel': relative, 'package_rel': f'packages/{package_name}',
                'status': 'failed', 'error_type': type(exc).__name__, 'error': error,
                'elapsed_seconds': round(time.monotonic() - started, 3), 'completed_at': utc_now(),
            }

    rows = []
    with package_lock(out_root):
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='xuanzang-batch') as executor:
            futures = {executor.submit(process, source): source for source in candidates}
            aborting = False
            for future in as_completed(futures):
                try:
                    row = future.result()
                except CancelledError:
                    relative, package_name = source_identity(futures[future])
                    row = {
                        'batch_id': batch_id, 'source_rel': relative,
                        'package_rel': f'packages/{package_name}', 'status': 'cancelled',
                        'completed_at': utc_now(),
                    }
                rows.append(row)
                append_jsonl(results_path, row)
                if fail_fast and row['status'] == 'failed' and not aborting:
                    aborting = True
                    for pending in futures:
                        if pending is not future:
                            pending.cancel()
        rows.sort(key=lambda row: row['source_rel'])
        summary = {
            'schema_version': 2,
            'batch_id': batch_id,
            'source_root': str(source_dir) if policy.privacy == 'local_only' else source_dir.name,
            'target': policy.target,
            'policy_fingerprint': policy.fingerprint,
            'workers': workers,
            'selected': len(candidates),
            'completed': sum(row['status'] == 'complete' for row in rows),
            'failed': sum(row['status'] == 'failed' for row in rows),
            'cancelled': sum(row['status'] == 'cancelled' for row in rows),
            'packages': [
                {
                    'source_rel': row['source_rel'], 'package_rel': row['package_rel'],
                    'status': row['status'], 'trust_status': row.get('trust_status'),
                    'gate_status': row.get('gate_status'),
                }
                for row in rows
            ],
            'updated_at': utc_now(),
        }
        write_json(out_root / 'batch_manifest.json', summary)
    return summary
