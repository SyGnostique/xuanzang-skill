#!/usr/bin/env python3
"""Run the repository-local Xuanzang CLI without requiring installation."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / 'src'
if not (SRC / 'xuanzang' / 'cli.py').is_file():
    raise SystemExit(f'xuanzang repository runtime not found: {SRC}')
sys.path.insert(0, str(SRC))

from xuanzang.cli import main  # noqa: E402


if __name__ == '__main__':
    main()
