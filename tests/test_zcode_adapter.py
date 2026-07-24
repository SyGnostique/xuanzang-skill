from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding='utf-8')
    assert text.startswith('---\n')
    raw = text.split('---\n', 2)[1]
    return yaml.safe_load(raw)


def test_zcode_skill_openclaw_metadata():
    repo = Path(__file__).resolve().parents[1]
    skill = repo / 'zcode' / 'xuanzang' / 'SKILL.md'
    meta = _frontmatter(skill)
    assert meta['name'] == 'xuanzang'
    assert 'GLM ZCode' in meta['description']
    openclaw = meta['metadata']['openclaw']
    assert openclaw['requires']['env'] == []
    assert 'python3' in openclaw['requires']['bins']
    assert openclaw['homepage'] == 'https://github.com/SyGnostique/xuanzang-skill'
    assert openclaw['source'].endswith('/zcode/xuanzang')
    body = skill.read_text(encoding='utf-8')
    for required in ['When to Use', 'Security Notes', 'Mandatory Restrictions', 'CLI Reference', 'Response Format', 'Error Handling']:
        assert required in body


def test_zcode_wrapper_check_env_and_help():
    repo = Path(__file__).resolve().parents[1]
    script = repo / 'zcode' / 'xuanzang' / 'scripts' / 'xuanzang_zcode_cli.py'
    env = os.environ.copy()
    env.pop('ZHIPU_API_KEY', None)
    result = subprocess.run([sys.executable, str(script), 'check-env'], cwd=repo, text=True, capture_output=True, check=True, env=env)
    report = json.loads(result.stdout)
    assert report['ok'] is True
    assert report['xuanzang_importable'] is True
    assert report['xuanzang_version'] == '2.2.0'
    assert report['zhipu_api_key_present'] is False
    assert 'ZHIPU_API_KEY' in report['optional_env']

    help_result = subprocess.run([sys.executable, str(script), '--help'], cwd=repo, text=True, capture_output=True, check=True, env=env)
    assert 'Auditable document evidence restoration' in help_result.stdout
