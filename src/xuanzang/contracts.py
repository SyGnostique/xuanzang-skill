from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .utils import sha256_text

PACKAGE_VERSION = 2
PIPELINE_VERSION = '2.0.0'

TrustTarget = Literal['hint', 'review', 'citation']
TrustStatus = Literal['hint_only', 'needs_review', 'citation_grade']
OCRMode = str

SUPPORTED_FORMATS = {
    '.pdf': 'pdf',
    '.epub': 'epub',
    '.docx': 'docx',
    '.txt': 'text',
    '.md': 'markdown',
    '.html': 'html',
    '.htm': 'html',
    '.png': 'image',
    '.jpg': 'image',
    '.jpeg': 'image',
    '.tif': 'image',
    '.tiff': 'image',
    '.bmp': 'image',
    '.webp': 'image',
    '.mobi': 'mobi',
    '.azw3': 'mobi',
    '.json': 'bundle_manifest',
    '.yaml': 'bundle_manifest',
    '.yml': 'bundle_manifest',
}


@dataclass(frozen=True)
class RestorePolicy:
    target: TrustTarget = 'review'
    ocr: OCRMode = 'auto'
    lang: str | None = None
    document_kind: str = 'auto'
    render_dpi: int = 200
    max_pages: int = 10_000
    max_total_pixels: int = 10_000_000_000
    max_source_bytes: int = 20 * 1024**3
    force_ocr: bool = False
    sidecar: str | None = None
    privacy: str = 'local_only'
    tenant_id: str | None = None
    workspace_id: str | None = None
    rights_basis: str = 'user_supplied_private'
    retention_policy: str = 'workspace_default'
    access_tags: tuple[str, ...] = ()
    transcription: str = 'source'
    preserve_source: bool = False
    allow_local_conversion: bool = True
    allow_external_sources: bool = False

    def validate(self) -> None:
        if self.target not in {'hint', 'review', 'citation'}:
            raise ValueError(f'unsupported target: {self.target}')
        if self.ocr not in {'auto', 'none', 'paddle', 'tesseract', 'mock', 'sidecar'} and not self.ocr.startswith('plugin:'):
            raise ValueError(f'unsupported OCR mode: {self.ocr}')
        if not 72 <= int(self.render_dpi) <= 600:
            raise ValueError('render_dpi must be between 72 and 600')
        if self.max_pages < 1 or self.max_total_pixels < 1 or self.max_source_bytes < 1:
            raise ValueError('resource limits must be positive')
        if self.document_kind not in {'auto', 'book', 'paper', 'report', 'article', 'manuscript', 'archive', 'image_sequence'}:
            raise ValueError(f'unsupported document_kind: {self.document_kind}')
        if self.ocr == 'sidecar' and not self.sidecar:
            raise ValueError('ocr=sidecar requires a sidecar path')
        if self.sidecar and self.ocr != 'sidecar':
            raise ValueError('a sidecar path is valid only with ocr=sidecar; plugins require their own bound provenance manifest')
        if self.privacy not in {'local_only', 'workspace', 'tenant'}:
            raise ValueError(f'unsupported privacy scope: {self.privacy}')
        if self.privacy == 'workspace' and not self.workspace_id:
            raise ValueError('privacy=workspace requires workspace_id')
        if self.privacy == 'tenant' and not self.tenant_id:
            raise ValueError('privacy=tenant requires tenant_id')
        if any(not str(tag).strip() or len(str(tag)) > 128 for tag in self.access_tags):
            raise ValueError('access tags must be non-empty strings of at most 128 characters')
        if self.transcription not in {'source', 'diplomatic', 'normalized', 'both'}:
            raise ValueError(f'unsupported transcription policy: {self.transcription}')

    @property
    def fingerprint(self) -> str:
        policy = asdict(self)
        policy['access_tags'] = sorted(set(policy.get('access_tags', ())))
        payload = {'pipeline_version': PIPELINE_VERSION, **policy}
        return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


@dataclass(frozen=True)
class RestoreRequest:
    source: Path
    out: Path
    policy: RestorePolicy
    resume: bool = False
    new_run: bool = False
    accept_source_update: bool = False


@dataclass(frozen=True)
class ReviewerContext:
    """Authentication-derived reviewer identity supplied by a trusted orchestrator."""

    reviewer_id: str
    reviewer_type: str
    review_session_id: str
    tenant_id: str | None = None
    workspace_id: str | None = None
    verified: bool = False

    def validate(self, scope: dict) -> None:
        if not self.verified:
            raise ValueError('orchestrator reviewer context must be verified')
        if self.reviewer_type not in {'human', 'agent_semantic'}:
            raise ValueError('unsupported reviewer_type in orchestrator context')
        if not self.reviewer_id or not self.review_session_id:
            raise ValueError('reviewer context requires reviewer_id and review_session_id')
        if scope.get('tenant_id') and self.tenant_id != scope.get('tenant_id'):
            raise ValueError('reviewer context tenant does not match package scope')
        if scope.get('workspace_id') and self.workspace_id != scope.get('workspace_id'):
            raise ValueError('reviewer context workspace does not match package scope')


@dataclass(frozen=True)
class RestoreResult:
    package: Path
    run_id: str
    trust_status: TrustStatus
    gate_status: str
    evaluation_status: str
    reused: bool = False

    def to_dict(self) -> dict:
        return {
            'package': str(self.package),
            'run_id': self.run_id,
            'trust_status': self.trust_status,
            'gate_status': self.gate_status,
            'evaluation_status': self.evaluation_status,
            'reused': self.reused,
        }


def detect_source_format(source: Path) -> str:
    if source.is_dir():
        return 'image_directory'
    fmt = SUPPORTED_FORMATS.get(source.suffix.lower())
    if fmt:
        return fmt
    raise ValueError(f'unsupported source format: {source.suffix.lower() or "<none>"}')
