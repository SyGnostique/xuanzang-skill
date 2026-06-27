#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _skill_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _repo_candidates() -> list[Path]:
    skill_dir = _skill_dir()
    candidates: list[Path] = []
    env_repo = os.environ.get('XUANZANG_REPO')
    if env_repo:
        candidates.append(Path(env_repo).expanduser())
    # Repository layout: <repo>/zcode/xuanzang/scripts/xuanzang_zcode_cli.py
    if len(skill_dir.parents) >= 2:
        candidates.append(skill_dir.parents[1])
    candidates.append(Path.cwd())
    return candidates


def _activate_repo_import_path() -> Path | None:
    for root in _repo_candidates():
        src = root / 'src'
        cli = src / 'xuanzang' / 'cli.py'
        if cli.exists():
            sys.path.insert(0, str(src))
            return root.resolve()
    return None


def _import_xuanzang_cli():
    repo_root = _activate_repo_import_path()
    try:
        from xuanzang.cli import main as xuanzang_main
        from xuanzang import __version__
    except Exception as exc:  # pragma: no cover - exercised through CLI process tests
        message = {
            'ok': False,
            'error': 'xuanzang package is not importable',
            'detail': str(exc),
            'fix': 'Run `pip install -e /path/to/xuanzang-skill` or set XUANZANG_REPO to the repository root.',
        }
        print(json.dumps(message, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)
    return xuanzang_main, __version__, repo_root


def build_env_report() -> dict[str, Any]:
    repo_root = _activate_repo_import_path()
    importable = True
    version = None
    import_error = None
    try:
        from xuanzang import __version__ as version
    except Exception as exc:  # pragma: no cover - platform dependent
        importable = False
        import_error = str(exc)
    return {
        'ok': importable,
        'skill_dir': str(_skill_dir()),
        'repo_root': str(repo_root) if repo_root else None,
        'python': sys.version.split()[0],
        'xuanzang_importable': importable,
        'xuanzang_version': version,
        'zhipu_api_key_present': bool(os.environ.get('ZHIPU_API_KEY')),
        'optional_env': ['ZHIPU_API_KEY', 'XUANZANG_REPO'],
        'import_error': import_error,
    }


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'check-env':
        print(json.dumps(build_env_report(), ensure_ascii=False, indent=2))
        return
    xuanzang_main, _version, _repo_root = _import_xuanzang_cli()
    xuanzang_main(argv)


if __name__ == '__main__':
    main()
