from __future__ import annotations

import csv
import importlib.metadata
import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image


@dataclass
class OCRBlock:
    text: str
    bbox: list[float]
    confidence: float | None = None
    block_kind: str = 'text_candidate'
    metadata: dict[str, Any] | None = None


class OCRAdapter(Protocol):
    name: str

    def available(self) -> bool: ...

    def version(self) -> str | None: ...

    def recognize(self, image: Path, *, lang: str | None = None, page_id: str | None = None) -> list[OCRBlock]: ...


class MockOCRAdapter:
    name = 'mock'

    def available(self) -> bool:
        return True

    def version(self) -> str:
        return '2'

    def recognize(self, image: Path, *, lang: str | None = None, page_id: str | None = None) -> list[OCRBlock]:
        text = f'模拟 OCR 文本 {page_id or image.stem}' if (lang or '').startswith('zh') else f'Mock OCR text {page_id or image.stem}'
        with Image.open(image) as im:
            width, height = im.size
        return [OCRBlock(text=text, bbox=[0.0, 0.0, float(width), float(height)], confidence=1.0)]


class PaddleOCRAdapter:
    """Optional local PaddleOCR adapter supporting both v2 and v3 result shapes."""

    name = 'paddle'

    def __init__(self) -> None:
        self._engine = None

    def available(self) -> bool:
        try:
            import paddleocr  # noqa: F401
            return True
        except Exception:
            return False

    def version(self) -> str | None:
        try:
            return importlib.metadata.version('paddleocr')
        except importlib.metadata.PackageNotFoundError:
            return None

    def _get_engine(self, lang: str | None):
        if self._engine is None:
            from paddleocr import PaddleOCR
            kwargs: dict[str, Any] = {}
            if lang:
                kwargs['lang'] = 'ch' if lang.startswith('zh') else lang.split('-')[0]
            try:
                self._engine = PaddleOCR(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    **kwargs,
                )
            except TypeError:
                self._engine = PaddleOCR(use_angle_cls=False, show_log=False, **kwargs)
        return self._engine

    @staticmethod
    def _rect_from_polygon(poly: Any) -> list[float]:
        points = poly.tolist() if hasattr(poly, 'tolist') else poly
        if len(points) == 4 and all(isinstance(x, (int, float)) for x in points):
            return [float(x) for x in points]
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        return [min(xs), min(ys), max(xs), max(ys)]

    def recognize(self, image: Path, *, lang: str | None = None, page_id: str | None = None) -> list[OCRBlock]:
        engine = self._get_engine(lang)
        if hasattr(engine, 'predict'):
            result = engine.predict(str(image))[0]
            texts = list(result.get('rec_texts', []))
            scores = list(result.get('rec_scores', []))
            boxes = list(result.get('rec_boxes', result.get('dt_polys', [])))
            return [
                OCRBlock(
                    text=str(text),
                    bbox=self._rect_from_polygon(boxes[i]) if i < len(boxes) else [0.0, 0.0, 0.0, 0.0],
                    confidence=float(scores[i]) if i < len(scores) else None,
                )
                for i, text in enumerate(texts)
                if str(text).strip()
            ]
        raw = engine.ocr(str(image), cls=False)
        rows = raw[0] if raw and isinstance(raw[0], list) else raw
        blocks = []
        for row in rows or []:
            if not row or len(row) < 2:
                continue
            text, confidence = row[1]
            if str(text).strip():
                blocks.append(OCRBlock(str(text), self._rect_from_polygon(row[0]), float(confidence)))
        return blocks


class TesseractOCRAdapter:
    name = 'tesseract'

    def available(self) -> bool:
        return shutil.which('tesseract') is not None

    def version(self) -> str | None:
        if not self.available():
            return None
        cp = subprocess.run(['tesseract', '--version'], text=True, capture_output=True, check=False)
        return cp.stdout.splitlines()[0].strip() if cp.stdout else None

    def recognize(self, image: Path, *, lang: str | None = None, page_id: str | None = None) -> list[OCRBlock]:
        tess_lang = 'chi_sim+eng' if (lang or '').startswith('zh') else (lang.split('-')[0] if lang else 'eng')
        cp = subprocess.run(
            ['tesseract', str(image), 'stdout', '-l', tess_lang, '--psm', '3', 'tsv'],
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        if cp.returncode != 0:
            raise RuntimeError(f'tesseract failed: {cp.stderr[-500:]}')
        blocks = []
        for row in csv.DictReader(cp.stdout.splitlines(), delimiter='\t'):
            text = (row.get('text') or '').strip()
            if not text:
                continue
            try:
                left, top = float(row['left']), float(row['top'])
                width, height = float(row['width']), float(row['height'])
                conf = float(row['conf'])
            except (KeyError, TypeError, ValueError):
                continue
            blocks.append(OCRBlock(text, [left, top, left + width, top + height], None if conf < 0 else conf / 100.0))
        return blocks


class SidecarOCRAdapter:
    """Read precomputed OCR/VLM evidence without invoking a remote or GPU model.

    Accepted JSONL rows contain page_id or page, text, bbox, confidence, and optional
    block_kind/metadata. This is the integration seam for Unlimited-OCR and other
    local or externally approved engines.
    """

    def __init__(self, path: Path):
        self.path = path
        self._rows: list[dict[str, Any]] | None = None
        self.name = 'sidecar'
        self._claimed_engine: str | None = None
        self._claimed_version: str | None = None
        self.requires_anchor_attestation = True

    def available(self) -> bool:
        return self.path.is_file()

    def version(self) -> str | None:
        return '1'

    def _load(self) -> list[dict[str, Any]]:
        if self._rows is None:
            if self.path.suffix.lower() == '.json':
                payload = json.loads(self.path.read_text(encoding='utf-8'))
                if isinstance(payload, list):
                    self._rows = payload
                else:
                    self._rows = payload.get('blocks', [])
                    self._claimed_engine = str(payload.get('engine') or payload.get('producer', {}).get('engine') or '') or None
                    self._claimed_version = payload.get('engine_version') or payload.get('producer', {}).get('version')
            else:
                self._rows = [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines() if line.strip()]
                producers = {str(row.get('engine')) for row in self._rows if row.get('engine')}
                if len(producers) == 1:
                    self._claimed_engine = producers.pop()
                versions = {str(row.get('engine_version')) for row in self._rows if row.get('engine_version')}
                if len(versions) == 1:
                    self._claimed_version = versions.pop()
            if not isinstance(self._rows, list):
                raise ValueError('OCR sidecar blocks must be a list')
            for index, row in enumerate(self._rows, start=1):
                if not isinstance(row, dict):
                    raise ValueError(f'OCR sidecar row {index} must be an object')
                if row.get('page_id') is None and row.get('page') is None and row.get('page_anchor') is None:
                    raise ValueError(f'OCR sidecar row {index} requires page_id, page, or page_anchor')
                bbox = row.get('bbox')
                if not isinstance(bbox, list) or len(bbox) != 4:
                    raise ValueError(f'OCR sidecar row {index} requires a four-number bbox')
                try:
                    numeric_bbox = [float(value) for value in bbox]
                except (TypeError, ValueError) as exc:
                    raise ValueError(f'OCR sidecar row {index} has a non-numeric bbox') from exc
                if not all(math.isfinite(value) for value in numeric_bbox):
                    raise ValueError(f'OCR sidecar row {index} has a non-finite bbox')
                if row.get('page') is not None:
                    try:
                        if int(row['page']) < 1:
                            raise ValueError
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f'OCR sidecar row {index} has an invalid page number') from exc
        return self._rows

    def recognize(self, image: Path, *, lang: str | None = None, page_id: str | None = None) -> list[OCRBlock]:
        page_number = int(page_id.rsplit('_', 1)[-1]) if page_id and page_id.rsplit('_', 1)[-1].isdigit() else None
        out = []
        for row in self._load():
            if row.get('page_id') not in {None, page_id}:
                continue
            if row.get('page_anchor') not in {None, page_id}:
                continue
            if row.get('page') is not None and page_number is not None and int(row['page']) != page_number:
                continue
            text = str(row.get('text', '')).strip()
            if text:
                out.append(OCRBlock(
                    text=text,
                    bbox=[float(x) for x in row.get('bbox', [0, 0, 0, 0])],
                    confidence=float(row['confidence']) if row.get('confidence') is not None else None,
                    block_kind=row.get('block_kind', 'text_candidate'),
                    metadata={
                        **(row.get('metadata') or {}),
                        'sidecar_producer': {
                            'claimed_engine': row.get('engine') or self._claimed_engine,
                            'claimed_version': row.get('engine_version') or self._claimed_version,
                        },
                        **{key: row.get(key) for key in ('source_image_sha256', 'page_image_sha256', 'page_anchor', 'window_id') if row.get(key) is not None},
                    },
                ))
        return out


def choose_ocr_adapter(mode: str, sidecar: str | None = None) -> OCRAdapter | None:
    if mode == 'none':
        return None
    if mode == 'mock':
        return MockOCRAdapter()
    if mode == 'paddle':
        adapter = PaddleOCRAdapter()
        if not adapter.available():
            raise RuntimeError('PaddleOCR requested but not installed')
        return adapter
    if mode == 'tesseract':
        adapter = TesseractOCRAdapter()
        if not adapter.available():
            raise RuntimeError('Tesseract requested but not available')
        return adapter
    if mode == 'sidecar':
        adapter = SidecarOCRAdapter(Path(sidecar or ''))
        if not adapter.available():
            raise RuntimeError(f'OCR sidecar not found: {sidecar}')
        return adapter
    if mode == 'auto':
        paddle = PaddleOCRAdapter()
        if paddle.available():
            return paddle
        tesseract = TesseractOCRAdapter()
        if tesseract.available():
            return tesseract
        return None
    if mode.startswith('plugin:'):
        name = mode.split(':', 1)[1]
        if not name:
            raise ValueError('plugin OCR mode requires a name')
        try:
            candidates = importlib.metadata.entry_points(group='xuanzang.ocr_adapters')
        except TypeError:
            candidates = importlib.metadata.entry_points().get('xuanzang.ocr_adapters', [])
        entry = next((ep for ep in candidates if ep.name == name), None)
        if entry is None:
            raise RuntimeError(f'OCR adapter plugin not installed: {name}')
        adapter = entry.load()()
        if not adapter.available():
            raise RuntimeError(f'OCR adapter plugin unavailable: {name}')
        # Third-party adapters cross a trust boundary. They cannot opt out of
        # source-image attestation or provenance review by omitting an
        # attribute from their implementation.
        setattr(adapter, 'requires_anchor_attestation', True)
        setattr(adapter, 'requires_provenance_review', True)
        setattr(adapter, 'xuanzang_plugin_name', name)
        return adapter
    raise ValueError(f'unknown OCR mode: {mode}')
