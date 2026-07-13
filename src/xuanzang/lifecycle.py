from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import (
    append_jsonl,
    assert_expected_scope,
    atomic_write_text,
    package_lock,
    read_json,
    sha256_text,
    utc_now,
    write_json,
)


def revoke_package(
    package: Path,
    *,
    reason: str,
    out: Path | None = None,
    expected_revision: str | None = None,
    expected_tenant_id: str | None = None,
    expected_workspace_id: str | None = None,
) -> dict[str, Any]:
    if not reason.strip():
        raise ValueError('revocation requires a non-empty reason')
    package = package.resolve()
    output = out.resolve() if out is not None else None
    if output is not None and (output == package or package in output.parents):
        raise ValueError('external tombstone output must be outside the package')
    with package_lock(package):
        manifest_path = package / 'package_manifest.json'
        manifest = read_json(manifest_path)
        assert_expected_scope(
            manifest, expected_tenant_id=expected_tenant_id,
            expected_workspace_id=expected_workspace_id,
        )
        current_revision = str(manifest.get('review_revision', '0'))
        if expected_revision is not None and expected_revision != current_revision:
            raise ValueError(
                f'revocation revision conflict: expected {expected_revision}, current {current_revision}'
            )
        lifecycle = manifest.get('lifecycle', {})
        if lifecycle.get('state') == 'revoked':
            tombstone = read_json(package / 'audit' / 'revocation_tombstone.json')
        else:
            revoked_at = utc_now()
            seed = json.dumps({
                'package_id': manifest.get('package_id'),
                'source_sha256': manifest.get('source', {}).get('sha256'),
                'run_id': manifest.get('active_run_id'),
                'review_revision': current_revision,
                'reason': reason.strip(),
            }, ensure_ascii=False, sort_keys=True)
            revocation_id = f'revoke_{sha256_text(seed)[:20]}'
            tombstone = {
                'schema_version': 2,
                'revocation_id': revocation_id,
                'state': 'revoked',
                'package_id': manifest.get('package_id'),
                'source_sha256': manifest.get('source', {}).get('sha256'),
                'active_run_id': manifest.get('active_run_id'),
                'canonical_revision': manifest.get('canonical_revision'),
                'review_revision': current_revision,
                'scope': manifest.get('scope', {}),
                'reason': reason.strip(),
                'revoked_at': revoked_at,
                'downstream_actions': [
                    'remove all chunks and vectors matching package_id from tenant/workspace namespaces',
                    'invalidate cached answers and evidence packets referencing source_sha256',
                    'delete or quarantine prior exports according to retention_policy',
                    'record per-system deletion acknowledgements against revocation_id',
                ],
                'acknowledgements_required': True,
            }
            write_json(package / 'audit' / 'revocation_tombstone.json', tombstone)
            manifest['lifecycle'] = {
                'state': 'revoked', 'revocation_id': revocation_id,
                'revoked_at': revoked_at, 'reason': reason.strip(),
            }
            manifest['trust_status'] = 'needs_review'
            manifest['updated_at'] = revoked_at
            write_json(manifest_path, manifest)
            append_jsonl(package / 'history' / 'events.jsonl', {
                'event': 'package_revoked', 'revocation_id': revocation_id,
                'reason': reason.strip(), 'at': revoked_at,
            })
        if out is not None:
            assert output is not None
            atomic_write_text(output, json.dumps(tombstone, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
        return tombstone
