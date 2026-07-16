# xuanzang-skill v2.1 Semantic/Visual Prompt Protocol Score

- scope: prompt assets, routing, schemas, portability, and automated contract checks
- minimum_score: 98.0
- score: 99.2
- hard_blockers: 0
- important_limit: this score evaluates the reusable protocol, not the reconstruction quality of an untested real book

| Dimension | Weight | Earned | Evidence |
| --- | ---: | ---: | --- |
| Whole-book architecture reasoning | 8 | 8.0 | `book_architecture.prompt.md` |
| Visual TOC discovery and transcription | 12 | 11.9 | `visual_toc_discovery.prompt.md`, `visual_toc_transcription.prompt.md` |
| Canonical TOC completeness contract | 12 | 11.9 | `canonical_toc.prompt.md` |
| Hierarchy and materialization adjudication | 10 | 9.9 | `toc_hierarchy_adjudication.prompt.md` |
| Candidate classification and exact boundaries | 16 | 15.9 | `boundary_candidate_assessment.prompt.md`, `boundary_resolution.prompt.md` |
| Image and auxiliary-block affiliation | 8 | 7.9 | `image_caption_affiliation.prompt.md` |
| Exhaustive local and global audit closure | 14 | 13.9 | `split_semantic_audit.prompt.md`, `reverse_structure_audit.prompt.md` |
| Evidence-bounded revision discipline | 6 | 6.0 | `unresolved_structure_revision.prompt.md` |
| Hard-blocker scoring and 98 gate | 5 | 5.0 | `stage_scoring.prompt.md` |
| Book-family coverage | 4 | 3.8 | `references/book-type-variants.md` |
| Codex/ZCode portability and routing | 3 | 3.0 | both skill packages, `tests/test_prompt_protocol.py` |
| Automated validation and security | 2 | 2.0 | 67 tests, compileall, check-env, security scan |
| **Total** | **100** | **99.2** | |

## Hard-Blocker Review

- No prompt remains a one-line stub in the semantic/visual reconstruction sequence.
- Every role requires structured output, evidence, confidence, unresolved states, and strict self-checks.
- Printed TOC interpretation explicitly requires visual evidence where OCR loses layout.
- Canonical hierarchy, exact boundaries, and media affiliation are separate decisions.
- Post-split review is exhaustive, followed by independent whole-book reverse audit.
- Low-confidence TOC items or boundaries cannot advance.
- Codex and ZCode protocol assets are byte-identical.

## Validation Evidence

- `pytest -q tests/test_prompt_protocol.py`: 4 passed
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`: 67 passed
- `python3 -m compileall -q src tests zcode scripts`: PASS
- `python3 zcode/xuanzang/scripts/xuanzang_zcode_cli.py check-env`: PASS, version 2.1.0
- `python3 scripts/security_scan.py`: PASS
- `git diff --check`: PASS

## Remaining Non-Blocking Debt

- The prompts define provider-neutral JSON contracts; provider-specific tool calling and context-window orchestration remain adapter work.
- Real-book performance must be scored per book after complete source evidence is supplied. A protocol score cannot replace that execution evidence.
