#!/usr/bin/env python3
from pathlib import Path
import re
import sys

forbidden_ext = {'.epub', '.pdf', '.mobi', '.azw3', '.docx'}
secret_patterns = [re.compile(r'sk-[A-Za-z0-9_-]{16,}'), re.compile(r'(OPENAI|DEEPSEEK)_API_KEY\s*=')]
failures = []
for p in Path('.').rglob('*'):
    if '.git' in p.parts or p.is_dir():
        continue
    if p.suffix.lower() in forbidden_ext and 'tests' not in p.parts:
        failures.append(f'forbidden generated/private file: {p}')
    if p.suffix.lower() in {'.py', '.md', '.yaml', '.yml', '.toml', '.txt'}:
        text = p.read_text(encoding='utf-8', errors='ignore')
        if any(rx.search(text) for rx in secret_patterns):
            failures.append(f'possible secret in {p}')
if failures:
    print('\n'.join(failures))
    sys.exit(1)
print('security_scan PASS')
