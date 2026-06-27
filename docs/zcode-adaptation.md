# GLM ZCode / OpenClaw Adaptation Notes

## Sources Consulted

- GLM official skills repository: https://github.com/zai-org/GLM-skills
- GLM master skill: https://github.com/zai-org/GLM-skills/tree/main/skills/glm-master-skill
- GLM OCR skill example: https://github.com/zai-org/GLM-skills/blob/main/skills/glmocr/SKILL.md
- OpenClaw skill format documentation: https://docs.openclaw.ai/clawhub/skill-format

## Research Findings

The GLM official skills repository uses one directory per skill, with `SKILL.md` as the entry document and optional `scripts/` helpers. The README describes the collection as official GLM-family skills for agent architectures including Claude Code, OpenCode, OpenClaw, AutoClaw, and other coding agents.

Common GLM skill patterns observed in official skills:

- Frontmatter starts with `name` and a task-oriented `description`.
- OpenClaw metadata is placed under `metadata.openclaw`.
- API-backed skills declare `requires.env`, usually `ZHIPU_API_KEY`, and `primaryEnv` when the API key is mandatory.
- Documentation-only or local-only skills can declare empty `env` and `bins` arrays.
- The body includes explicit sections for when to use, dependencies, setup, security, mandatory restrictions, CLI reference, response format, and error handling.
- The skill asks agents to use fixed scripts in `{SKILL_DIR}/scripts/` rather than inventing execution paths.

## Adaptation Decision

`xuanzang-skill` remains a single Python implementation. The ZCode adapter is a thin skill package at `zcode/xuanzang` that calls the same `xuanzang.cli` commands as the Codex skill.

This avoids two dangerous failure modes:

- divergent behavior between Codex and GLM/ZCode workflows;
- unreviewed ad hoc shell instructions in the ZCode skill body.

The adapter does not require `ZHIPU_API_KEY` for local ledger, split, validation, mock translation, or assembly. It treats GLM/Zhipu model calls as optional and user-approved because book text can be private or copyrighted.

## File Layout

```text
zcode/xuanzang/
├── SKILL.md
├── assets/prompt_templates/
├── references/
└── scripts/
    ├── check_env.py
    └── xuanzang_zcode_cli.py
```

## Compatibility Contract

The ZCode adapter must satisfy these checks:

- `SKILL.md` has valid YAML frontmatter.
- `metadata.openclaw.requires.env` and `metadata.openclaw.requires.bins` are present.
- `homepage` and `source` point to the public repository.
- Local commands go through `scripts/xuanzang_zcode_cli.py`.
- The wrapper works from the repository without installation by discovering `src/`.
- If copied outside the repo, users can set `XUANZANG_REPO` or install with `pip install -e`.
- `check-env` emits JSON and never prints secret values.

## Best-Practice Mapping

| GLM/OpenClaw practice | xuanzang adaptation |
| --- | --- |
| One directory per skill | `zcode/xuanzang` |
| `metadata.openclaw` frontmatter | Declared in `zcode/xuanzang/SKILL.md` |
| Fixed helper scripts | `scripts/xuanzang_zcode_cli.py` and `scripts/check_env.py` |
| API key from env only | `ZHIPU_API_KEY` is optional and never echoed |
| Clear mandatory restrictions | Ledger-first, TOC-first, no mock semantic PASS, no hidden exemptions |
| Response and audit format | Durable JSON audits listed in the skill body |
| Error handling | Import, unsupported format, FAIL_REVIEW, and missing-key paths documented |

## Security Policy

Do not commit books, extracted text, translations, raw model responses, generated private packages, or API keys. The security scan now treats `ZHIPU_API_KEY=` assignments like other model-provider secrets.

## Validation

Run:

```bash
python3 zcode/xuanzang/scripts/xuanzang_zcode_cli.py check-env
python3 zcode/xuanzang/scripts/xuanzang_zcode_cli.py --help
pytest -q
python scripts/security_scan.py
python -m compileall -q src tests zcode
```
