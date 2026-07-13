# xuanzang-skill v1.1 ZCode Adapter Score

> Historical archive only. Classification: `invalid_or_unverified_for_v2`. Release authority: none. The scores and command results below are a v1.1 self-assessment and have not been reverified for the current v2 tree.

- recorded_at: 2026-06-27
- adapter: `zcode/xuanzang`
- minimum_score: 98.5
- hard_blockers: 0

| Dimension | Score | Evidence |
| --- | ---: | --- |
| GLM/OpenClaw source research | 100 | `docs/zcode-adaptation.md` |
| Frontmatter and metadata compatibility | 100 | `zcode/xuanzang/SKILL.md`, `tests/test_zcode_adapter.py` |
| Fixed script entrypoint | 99 | `zcode/xuanzang/scripts/xuanzang_zcode_cli.py` |
| Workflow parity with core CLI | 99 | wrapper delegates to `xuanzang.cli` |
| Environment and key safety | 99 | optional `ZHIPU_API_KEY`, `scripts/security_scan.py` |
| Standalone-copy fallback | 98.5 | `XUANZANG_REPO` path discovery and importable-package fallback |
| Documentation clarity | 99 | `README.md`, `docs/zcode-adaptation.md`, `zcode/xuanzang/SKILL.md` |
| Automated validation | 98.5 | `pytest -q`, `compileall`, `check-env`, security scan |

## Validation Evidence

The entries below are historical claims retained for provenance. They are not current test evidence.

- `python3 zcode/xuanzang/scripts/xuanzang_zcode_cli.py check-env`: PASS
- `python3 zcode/xuanzang/scripts/xuanzang_zcode_cli.py --help`: PASS
- `python3 -m compileall -q src tests zcode scripts`: PASS
- `python3 scripts/security_scan.py`: PASS
- `pytest -q`: 7 passed

## Non-blocking Debt

- Real GLM/Zhipu translation or OCR provider calls are intentionally not implemented in this adapter until the user supplies provider policy, model choice, and privacy authorization for sending book text to a remote API.

## V2 status

The adapter now routes to the shared v2 CLI, but this score does not validate that code. Use the current commands and acceptance criteria in `docs/release_checklist.md`. Public multi-tenant deployment remains blocked by `docs/known_limitations.md`.
