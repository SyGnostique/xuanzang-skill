from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import tempfile
import time
import unicodedata
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def sha256_path(path: Path) -> str:
    """Hash a file or directory tree, binding directory names and file bytes.

    Symlinks are rejected so a package cannot silently ingest bytes outside the
    declared source boundary.
    """
    if path.is_symlink():
        raise ValueError(f'symlink sources are not supported: {path}')
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise FileNotFoundError(path)
    rows = []
    for member in sorted(path.rglob('*')):
        if member.is_symlink():
            raise ValueError(f'symlink sources are not supported: {member}')
        if member.is_file():
            rows.append(f'{member.relative_to(path).as_posix()}:{sha256_file(member)}')
    return sha256_text('\n'.join(rows))


def validate_zip_archive(
    archive: zipfile.ZipFile,
    *,
    label: str,
    max_entries: int = 20_000,
    max_total_uncompressed: int = 4 * 1024**3,
    max_member_uncompressed: int = 1024**3,
    max_compression_ratio: float = 1_000.0,
) -> None:
    """Reject pathological ZIP containers before any member is materialized."""
    infos = archive.infolist()
    if len(infos) > max_entries:
        raise ValueError(f'{label} has too many archive members: {len(infos)} > {max_entries}')
    total = 0
    normalized_names: set[str] = set()
    normalized_files: set[str] = set()
    normalized_directories: set[str] = set()
    for info in infos:
        name = info.filename.replace('\\', '/')
        if name.startswith('/') or any(part == '..' for part in Path(name).parts):
            raise ValueError(f'{label} has an unsafe archive member path: {info.filename}')
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError(f'{label} symlink members are not allowed: {info.filename}')
        raw_parts = [part for part in Path(name).parts if part not in {'', '.'}]
        if not raw_parts:
            raise ValueError(f'{label} has an empty archive member path')
        canonical_parts = [
            unicodedata.normalize('NFC', unicodedata.normalize('NFC', part).casefold())
            for part in raw_parts
        ]
        normalized = '/'.join(canonical_parts)
        if normalized in normalized_names:
            raise ValueError(
                f'{label} has duplicate or case-colliding archive members '
                f'(including Unicode canonical collisions): {info.filename}'
            )
        prefixes = {'/'.join(canonical_parts[:index]) for index in range(1, len(canonical_parts))}
        if prefixes & normalized_files:
            raise ValueError(f'{label} has a file/directory prefix collision: {info.filename}')
        is_directory = info.is_dir() or name.endswith('/')
        if not is_directory and normalized in normalized_directories:
            raise ValueError(f'{label} has a file/directory prefix collision: {info.filename}')
        normalized_names.add(normalized)
        normalized_directories.update(prefixes)
        if is_directory:
            normalized_directories.add(normalized)
        else:
            normalized_files.add(normalized)
        if info.file_size < 0 or info.compress_size < 0:
            raise ValueError(f'{label} has invalid archive sizes: {info.filename}')
        if info.file_size > max_member_uncompressed:
            raise ValueError(f'{label} member exceeds safe size: {info.filename}')
        total += info.file_size
        if total > max_total_uncompressed:
            raise ValueError(f'{label} exceeds safe uncompressed size')
        if info.file_size and info.compress_size == 0:
            raise ValueError(f'{label} member has an invalid zero compressed size: {info.filename}')
        ratio = info.file_size / max(1, info.compress_size)
        if ratio > max_compression_ratio:
            raise ValueError(f'{label} member exceeds safe compression ratio: {info.filename}')


def assert_safe_xml_bytes(data: bytes, *, label: str, max_bytes: int = 16 * 1024**2) -> None:
    """Reject DTD/entity declarations before any XML parser sees untrusted bytes.

    XML permits UTF-8 and UTF-16 (and parsers commonly accept UTF-32). Removing
    NUL code-unit padding before the ASCII-token scan prevents UTF-16/32 from
    bypassing the fail-closed Xuanzang policy. The parser still receives the
    original bytes so declared encodings are preserved.
    """
    if len(data) > max_bytes:
        raise ValueError(f'{label} exceeds the safe XML member size')
    declaration_view = data.replace(b'\x00', b'').upper()
    if b'<!DOCTYPE' in declaration_view or b'<!ENTITY' in declaration_view:
        raise ValueError(f'{label} DTD/entity declarations are not allowed')


def contained_path(base: Path, *parts: str) -> Path:
    """Resolve an archive or manifest-relative path and enforce containment."""
    root = base.resolve()
    target = root.joinpath(*parts).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f'path escapes declared root: {"/".join(parts)}')
    return target


def validate_opaque_id(value: str, *, label: str = 'identifier') -> str:
    value = str(value)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value) or '..' in value:
        raise ValueError(f'invalid {label}: {value!r}')
    return value


def assert_expected_scope(
    manifest: dict[str, Any], *, expected_tenant_id: str | None = None,
    expected_workspace_id: str | None = None,
) -> None:
    scope = manifest.get('scope', {})
    if expected_tenant_id is not None and scope.get('tenant_id') != expected_tenant_id:
        raise ValueError('package tenant scope does not match caller expectation')
    if expected_workspace_id is not None and scope.get('workspace_id') != expected_workspace_id:
        raise ValueError('package workspace scope does not match caller expectation')


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """Append an immutable audit/event row and fsync it before returning."""
    ensure_dir(path.parent)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
        f.flush()
        os.fsync(f.fileno())


def atomic_write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


@contextmanager
def package_lock(package: Path):
    """Single-writer filesystem lock for local/workspace packages."""
    ensure_dir(package)
    lock = package / '.xuanzang.lock'
    token = uuid.uuid4().hex
    payload = {
        'token': token, 'pid': os.getpid(), 'host': socket.gethostname(),
        'created_at': utc_now(),
    }
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + '\n')
                f.flush()
                os.fsync(f.fileno())
            break
        except FileExistsError:
            try:
                current = read_json(lock)
            except Exception:
                raise RuntimeError(f'package is locked by an unreadable lock file: {lock}')
            stale = False
            if current.get('host') == socket.gethostname() and isinstance(current.get('pid'), int):
                try:
                    os.kill(int(current['pid']), 0)
                except ProcessLookupError:
                    stale = True
                except PermissionError:
                    stale = False
            if not stale:
                raise RuntimeError(f'package is locked by pid={current.get("pid")} host={current.get("host")}')
            archived = package / f'.xuanzang.lock.stale.{int(time.time())}'
            os.replace(lock, archived)
    try:
        yield payload
    finally:
        try:
            current = read_json(lock)
            if current.get('token') == token:
                lock.unlink()
        except FileNotFoundError:
            pass


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def slugify(value: str, fallback: str = 'book') -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", '-', value)
    value = re.sub(r'-+', '-', value).strip('-')
    return value or fallback


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def relpath(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def cjk_ratio(text: str) -> float:
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return 0.0
    cjk = sum(1 for ch in chars if '\u4e00' <= ch <= '\u9fff')
    return cjk / len(chars)


def looks_like_secret(text: str) -> bool:
    patterns = [
        r'sk-[A-Za-z0-9_-]{16,}',
        r'api[_-]?key\s*[:=]\s*[A-Za-z0-9_-]{16,}',
        r'DEEPSEEK_API_KEY\s*=',
        r'OPENAI_API_KEY\s*=',
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def copytree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def copytree_no_follow(
    src: Path, dst: Path, *, max_files: int = 200_000, max_bytes: int = 20 * 1024**3,
) -> dict[str, int]:
    """Copy an evidence snapshot without following symlinks or unbounded growth."""
    src = src.resolve()
    if dst.exists():
        raise FileExistsError(dst)
    files = 0
    total = 0
    members = sorted(src.rglob('*'))
    for member in members:
        if member.is_symlink():
            raise ValueError(f'symlink rejected while snapshotting legacy package: {member}')
        if not member.is_file():
            continue
        files += 1
        total += member.stat().st_size
        if files > max_files or total > max_bytes:
            raise ValueError('legacy package snapshot exceeds configured safety quota')
    ensure_dir(dst)
    for member in members:
        rel = member.relative_to(src)
        target = dst / rel
        if member.is_dir():
            ensure_dir(target)
        elif member.is_file():
            ensure_dir(target.parent)
            shutil.copy2(member, target, follow_symlinks=False)
    return {'files': files, 'bytes': total}
