from __future__ import annotations

from pathlib import Path


PROMPTS = {
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

    refs = ['toc-first-segmentation.md', 'book-type-variants.md', 'prompt-protocol.md']
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
