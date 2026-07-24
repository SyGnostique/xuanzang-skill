from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROMPTS = {
    'local_strict_rebuild.prompt.md': ['## Role', '## Inputs', '## Output', 'Completion predicate'],
    'book_architecture.prompt.md': ['## Role', '## Inputs', '## Output', 'hard_blockers'],
    'visual_toc_discovery.prompt.md': ['## Role', '## Inputs', '## Output', 'hard_blockers'],
    'visual_toc_transcription.prompt.md': ['## Role', '## Inputs', '## Output', 'hard_blockers'],
    'canonical_toc.prompt.md': ['## Role', '## Required Inputs', '## Output', 'hard_blockers'],
    'toc_hierarchy_adjudication.prompt.md': ['## Role', '## Inputs', '## Output', 'hard_blockers'],
    'boundary_candidate_assessment.prompt.md': ['## Role', '## Inputs', '## Output', 'hard_blockers'],
    'boundary_resolution.prompt.md': ['## Role', '## Required Inputs', '## Output', 'hard_blockers'],
    'image_caption_affiliation.prompt.md': ['## Role', '## Inputs', '## Output', 'hard_blockers'],
    'split_semantic_audit.prompt.md': ['## Role', '## Inputs', '## Output', 'hard_blockers'],
    'reverse_structure_audit.prompt.md': ['## Role', '## Inputs', '## Output', 'blocking_findings'],
    'unresolved_structure_revision.prompt.md': ['## Role', '## Inputs', '## Output', 'remaining_hard_blockers'],
    'stage_scoring.prompt.md': ['## Role', '## Inputs', '## Output', 'PASS_ADVANCE'],
    'score_feedback_learning.prompt.md': ['## Role', '## Required Inputs', '## Output', 'generalizable_failure'],
}


def _repo() -> Path:
    return Path(__file__).resolve().parents[1]


def test_semantic_visual_prompt_protocol_is_complete():
    prompt_dir = _repo() / 'skills' / 'xuanzang' / 'assets' / 'prompt_templates'
    index = (prompt_dir / 'README.md').read_text(encoding='utf-8')
    for name, required in PROMPTS.items():
        path = prompt_dir / name
        assert path.exists(), name
        text = path.read_text(encoding='utf-8')
        assert len(text.splitlines()) >= 60, f'{name} is still only a prompt stub'
        assert 'Return JSON only' in text, name
        assert 'confidence' in text.lower(), name
        assert 'evidence' in text.lower(), name
        for marker in required:
            assert marker in text, f'{name} missing {marker}'
        assert name in index


def test_prompt_protocol_encodes_core_strict_invariants():
    prompt_dir = _repo() / 'skills' / 'xuanzang' / 'assets' / 'prompt_templates'
    combined = '\n'.join((prompt_dir / name).read_text(encoding='utf-8') for name in PROMPTS)
    required_concepts = [
        'untrusted',
        'visual',
        'semantic',
        'canonical TOC',
        'container-only',
        'running header',
        'TOC residue',
        'start_block_inclusive',
        'end_block_exclusive',
        'image',
        'caption',
        'every section',
        'reverse',
        'source block',
        '98',
    ]
    for concept in required_concepts:
        assert concept.lower() in combined.lower(), concept


def test_codex_and_zcode_protocol_assets_are_identical():
    repo = _repo()
    codex_prompts = repo / 'skills' / 'xuanzang' / 'assets' / 'prompt_templates'
    zcode_prompts = repo / 'zcode' / 'xuanzang' / 'assets' / 'prompt_templates'
    names = set(PROMPTS) | {'README.md', 'semantic_audit.prompt.md', 'translation_request.prompt.md'}
    assert {p.name for p in codex_prompts.glob('*.md')} == names
    assert {p.name for p in zcode_prompts.glob('*.md')} == names
    for name in names:
        assert (codex_prompts / name).read_bytes() == (zcode_prompts / name).read_bytes(), name

    refs = [
        'toc-first-segmentation.md', 'book-type-variants.md', 'prompt-protocol.md',
        'score-feedback-learning.md', 'local-strict-workflow.md', 'failure-regressions.md',
    ]
    for name in refs:
        assert (repo / 'skills' / 'xuanzang' / 'references' / name).read_bytes() == (
            repo / 'zcode' / 'xuanzang' / 'references' / name
        ).read_bytes(), name


def test_skill_routes_agents_to_full_prompt_protocol():
    repo = _repo()
    for skill in [repo / 'skills' / 'xuanzang' / 'SKILL.md', repo / 'zcode' / 'xuanzang' / 'SKILL.md']:
        text = skill.read_text(encoding='utf-8')
        assert 'references/prompt-protocol.md' in text
        assert 'assets/prompt_templates/README.md' in text
        assert 'references/book-type-variants.md' in text
        assert 'references/score-feedback-learning.md' in text
        assert 'references/local-strict-workflow.md' in text
        assert 'references/failure-regressions.md' in text
        assert 'verify-local-strict' in text


def test_local_strict_is_the_default_and_scoring_is_optional():
    repo = _repo()
    for skill in [repo / 'skills' / 'xuanzang' / 'SKILL.md', repo / 'zcode' / 'xuanzang' / 'SKILL.md']:
        text = skill.read_text(encoding='utf-8').lower()
        assert 'source-faithful' in text
        assert 'exactly one h1' in text
        assert 'h2/h3' in text
        assert 'do not call a scorer by default' in text
        assert 'local_strict_acceptance.json' in text


def test_codex_skill_bundles_a_repository_local_cli():
    repo = _repo()
    script = repo / 'skills' / 'xuanzang' / 'scripts' / 'xuanzang_local_cli.py'
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    result = subprocess.run(
        [sys.executable, str(script), '--version'],
        cwd=repo.parent,
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
    assert result.stdout.strip() == 'xuanzang 2.2.0'


def test_score_feedback_protocol_keeps_formal_attempts_outside_restorable_package():
    repo = _repo()
    for path in [
        repo / 'skills' / 'xuanzang' / 'references' / 'score-feedback-learning.md',
        repo / 'skills' / 'xuanzang' / 'assets' / 'prompt_templates' / 'score_feedback_learning.prompt.md',
    ]:
        text = path.read_text(encoding='utf-8')
        assert 'restore --new-run' in text
        assert 'durable' in text.lower()
        assert 'outside the restorable package root' in text.lower()


def test_prescore_protocol_uses_artifact_appropriate_coverage_and_asset_order():
    repo = _repo()
    paths = [
        repo / 'skills' / 'xuanzang' / 'SKILL.md',
        repo / 'skills' / 'xuanzang' / 'references' / 'score-feedback-learning.md',
        repo / 'skills' / 'xuanzang' / 'assets' / 'prompt_templates' / 'score_feedback_learning.prompt.md',
    ]
    combined = '\n'.join(path.read_text(encoding='utf-8') for path in paths).lower()
    assert 'artifact-appropriate' in combined
    assert 'reference_only' in combined
    assert 'excluded' in combined
    assert 'immutable source order' in combined
    assert 'caption-linked and unlinked' in combined
    assert 'unsupported caption' in combined


def test_formal_scoring_excludes_noninformational_publication_matter():
    repo = _repo()
    paths = [
        repo / 'skills' / 'xuanzang' / 'SKILL.md',
        repo / 'skills' / 'xuanzang' / 'references' / 'prompt-protocol.md',
        repo / 'skills' / 'xuanzang' / 'references' / 'score-feedback-learning.md',
        repo / 'skills' / 'xuanzang' / 'assets' / 'prompt_templates' / 'stage_scoring.prompt.md',
    ]
    combined = '\n'.join(path.read_text(encoding='utf-8') for path in paths).lower()
    for concept in [
        'informational body',
        'contributor',
        'acknowledgment',
        'publication',
        'copyright',
        'promotional cover',
        'author biographies',
        'printed contents',
        'index/locator',
        'outside formal scoring',
    ]:
        assert concept in combined, concept
    assert 'require no repair' in combined or 'requires neither repair' in combined


def test_formal_scorer_contract_requires_schema_and_validator_smoke_tests():
    repo = _repo()
    for skill in [repo / 'skills' / 'xuanzang' / 'SKILL.md', repo / 'zcode' / 'xuanzang' / 'SKILL.md']:
        text = skill.read_text(encoding='utf-8').lower()
        assert 'schema transport smoke test' in text
        assert 'output-validator self-test' in text
        assert 'explicit types' in text
        assert 'process_failure' in text
