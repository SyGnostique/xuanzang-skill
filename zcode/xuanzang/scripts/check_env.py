#!/usr/bin/env python3
from __future__ import annotations

import json

from xuanzang_zcode_cli import build_env_report


if __name__ == '__main__':
    print(json.dumps(build_env_report(), ensure_ascii=False, indent=2))
