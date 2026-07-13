# Historical goal-loop scores

`audit/goal_loop_scores.jsonl` is an archived v1 development self-assessment recorded on 2026-06-27. It contains static rubric scores and old local test-count claims. It has no authority for xuanzang 2.0 package trust, repository release readiness, semantic correctness, security, or deployment approval.

Do not regenerate, average, promote, or cite those values as a current gate. `scripts/score_goal_loops.py` now reports the archive classification and deliberately does not write a passing score or release decision.

Version 2 uses evidence-backed decisions:

- package hint/review/citation state: recompute `audit/gates/<target>.json` through the current CLI;
- citation authority: require `citation_grade` plus `PASS_STRICT` for the exact active source/run/canonical/review head;
- repository release: execute [release_checklist.md](release_checklist.md) against a clean commit and record current command evidence;
- trusted local pilot: pass a real authorized canary and downstream revocation exercise;
- public multi-tenant deployment: remains no-go until the service controls in [known_limitations.md](known_limitations.md) are implemented and verified.

The archive remains useful for understanding v1 intentions. It is not a migration input to v2 trust.
