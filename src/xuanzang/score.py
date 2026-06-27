from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import ensure_dir, utc_now


def append_score(package_or_repo: Path, record: dict[str, Any]) -> None:
    audit = ensure_dir(package_or_repo / 'audit')
    record = dict(record)
    record.setdefault('recorded_at', utc_now())
    with (audit / 'goal_loop_scores.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')


def score_record(stage_id: str, loop_id: str, loop_name: str, dimensions: list[dict[str, Any]], hard_blockers: list[str], required_artifacts: list[str], next_stage: str | None = None) -> dict[str, Any]:
    total = round(sum(float(d.get('score', 0)) for d in dimensions), 2)
    status = 'PASS_ADVANCE' if total >= 98 and not hard_blockers else 'REPAIR_REQUIRED'
    return {
        'goal_id': 'xuanzang-v1.0',
        'stage_id': stage_id,
        'loop_id': loop_id,
        'loop_name': loop_name,
        'attempt': 1,
        'score': total,
        'status': status,
        'hard_blockers': hard_blockers,
        'dimensions': dimensions,
        'required_artifacts': required_artifacts,
        'repairs_applied': [],
        'remaining_debt': [] if status == 'PASS_ADVANCE' else ['repair required before advancement'],
        'next_stage': next_stage,
    }
