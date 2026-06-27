# v1.0 Release Checklist

- [ ] G0 repo and skill foundation score >= 98
- [ ] G1 source ledger score >= 98
- [ ] G2 OCR/text quality score >= 98
- [ ] G3 TOC-first segmentation score >= 98
- [ ] G4 cleaning/RAG strict score >= 98
- [ ] G5 translation prep score >= 98
- [ ] G6 translation execution score >= 98
- [ ] G7 semantic audit scaffold/terminology score >= 98
- [ ] G8 assembly/reinsertion score >= 98
- [ ] G9 tests/docs/forward-test readiness score >= 98
- [ ] CI green
- [ ] Security scan green
- [ ] No private sources, generated translations, or API keys committed

## v1.1 ZCode Adapter Checklist

- [ ] `zcode/xuanzang/SKILL.md` has valid GLM/OpenClaw frontmatter
- [ ] `metadata.openclaw.requires.env` and `metadata.openclaw.requires.bins` are explicit
- [ ] ZCode wrapper can run `check-env` from a fresh checkout
- [ ] ZCode wrapper routes to the same `xuanzang.cli` implementation
- [ ] README documents the GLM ZCode/OpenClaw adapter
- [ ] Security scan covers Zhipu key assignments
- [ ] Tests cover ZCode metadata and wrapper behavior
- [ ] CI compiles `zcode/` and runs `check-env`
