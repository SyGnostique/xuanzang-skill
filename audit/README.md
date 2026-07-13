# Audit archive classification

The files currently committed in this directory are historical development records:

- `goal_loop_scores.jsonl`: v1.0 static self-scored rubric rows;
- `v1_score_summary.md`: v1.0 summary generated from those rows;
- `zcode_adapter_score.md`: v1.1 adapter self-assessment.

All three are classified `invalid_or_unverified_for_v2`. They have no authority for:

- xuanzang 2.0 release readiness;
- package `hint_only`, `needs_review`, or `citation_grade` trust;
- `PASS_STRICT` citation status;
- semantic correctness, security, privacy, or multi-tenant deployment;
- migration of old status into a version-2 package.

The old scores are preserved only as project history. Old evidence labels, test counts, timestamps, and `hard_blockers: 0` statements describe the earlier self-assessment and must not be presented as current validation.

Current package gates live inside each generated package at `audit/gates/<target>.json` and must be recomputed from that package's active evidence and decisions. Current repository release evidence follows `docs/release_checklist.md` and should be recorded against a commit and built artifact outside these legacy files.
