#!/usr/bin/env python3
"""Classify the archived v1 goal-loop scores without creating a release gate.

The pre-2.0 version of this script generated static scores and a passing summary
from hard-coded values. Keeping that behavior would allow a fresh timestamp to
look like current validation. V2 trust is derived by xuanzang.gates for each
package; repository release readiness is a recorded execution of the release
checklist. This compatibility script is intentionally read-only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'audit' / 'goal_loop_scores.jsonl'


def _archive_summary() -> dict[str, object]:
    records: list[dict[str, object]] = []
    parse_errors: list[int] = []
    if ARCHIVE.exists():
        for line_number, line in enumerate(ARCHIVE.read_text(encoding='utf-8').splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                parse_errors.append(line_number)
                continue
            if isinstance(payload, dict):
                records.append(payload)
            else:
                parse_errors.append(line_number)
    goal_ids = sorted({str(row.get('goal_id')) for row in records if row.get('goal_id')})
    recorded_at = sorted({str(row.get('recorded_at')) for row in records if row.get('recorded_at')})
    return {
        'status': 'invalid_or_unverified_for_v2',
        'release_authority': 'none',
        'gate_capability': False,
        'archive': str(ARCHIVE.relative_to(ROOT)),
        'record_count': len(records),
        'parse_error_lines': parse_errors,
        'historical_goal_ids': goal_ids,
        'historical_recorded_at': recorded_at,
        'reason': (
            'These are static v1 self-scores. Recompute package gates with the current CLI '
            'and execute docs/release_checklist.md against a clean commit.'
        ),
        'writes_performed': False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Report the non-authoritative classification of archived v1 goal-loop scores.'
    )
    parser.add_argument(
        '--require-v2-release-authority', action='store_true',
        help='Fail deliberately: the archived score file can never provide v2 release authority.',
    )
    args = parser.parse_args(argv)
    summary = _archive_summary()
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if args.require_v2_release_authority:
        print(
            'refusing to treat archived v1 self-scores as a v2 release gate',
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
