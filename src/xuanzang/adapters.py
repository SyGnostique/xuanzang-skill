from __future__ import annotations

import csv
import importlib.metadata
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageOps


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
            language = (lang or '').split('-')[0].lower()
            if language and language != 'zh':
                # The mobile detector is materially faster and more stable on
                # CPU while retaining the English v5 recognition model.
                kwargs['text_detection_model_name'] = 'PP-OCRv5_mobile_det'
                kwargs['text_det_limit_side_len'] = 1280
                if language == 'en':
                    kwargs['text_recognition_model_name'] = 'en_PP-OCRv5_mobile_rec'
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

    def retry_rotated_180_if_better(
        self,
        image: Path,
        primary: list[OCRBlock],
        *,
        lang: str | None = None,
        page_id: str | None = None,
    ) -> tuple[list[OCRBlock], bool]:
        primary_confidence, primary_chars = TesseractOCRAdapter._ocr_quality(primary)
        if not primary_chars or (primary_chars >= 80 and primary_confidence >= 0.82):
            return primary, False
        with Image.open(image) as source:
            width, height = source.size
            rotated = source.rotate(180, expand=False)
            with tempfile.TemporaryDirectory(prefix='xuanzang-paddle-orientation-') as tmp:
                rotated_path = Path(tmp) / 'rotated_180.png'
                rotated.save(rotated_path, dpi=(300, 300))
                candidate = self.recognize(rotated_path, lang=lang, page_id=page_id)

        candidate_confidence, candidate_chars = TesseractOCRAdapter._ocr_quality(candidate)
        enough_text = candidate_chars >= max(40, int(primary_chars * 0.75))
        clearly_better = candidate_confidence >= max(0.65, primary_confidence + 0.12)
        if not enough_text or not clearly_better:
            return primary, False
        for block in candidate:
            rotated_bbox = list(block.bbox)
            x0, y0, x1, y1 = rotated_bbox
            block.bbox = [
                float(width) - float(x1), float(height) - float(y1),
                float(width) - float(x0), float(height) - float(y0),
            ]
            block.metadata = {
                **(block.metadata or {}),
                'ocr_orientation_correction_degrees': 180,
                'source_rendition_orientation_preserved': True,
                'corrected_orientation_bbox': rotated_bbox,
                'orientation_primary_confidence': round(primary_confidence, 6),
                'orientation_candidate_confidence': round(candidate_confidence, 6),
                'orientation_primary_meaningful_chars': primary_chars,
                'orientation_candidate_meaningful_chars': candidate_chars,
                'page_id': page_id,
            }
        return candidate, True


class TesseractOCRAdapter:
    name = 'tesseract'

    def available(self) -> bool:
        return shutil.which('tesseract') is not None

    def version(self) -> str | None:
        if not self.available():
            return None
        cp = subprocess.run(['tesseract', '--version'], text=True, capture_output=True, check=False)
        return cp.stdout.splitlines()[0].strip() if cp.stdout else None

    @staticmethod
    def _parse_tsv_lines(tsv: str, *, psm: int) -> list[OCRBlock]:
        lines: dict[tuple[int, int, int, int], dict[str, Any]] = {}
        for ordinal, row in enumerate(csv.DictReader(tsv.splitlines(), delimiter='\t')):
            text = (row.get('text') or '').strip()
            if not text:
                continue
            try:
                level = int(row.get('level') or 0)
                page_num = int(row.get('page_num') or 0)
                block_num = int(row.get('block_num') or 0)
                par_num = int(row.get('par_num') or 0)
                line_num = int(row.get('line_num') or 0)
                word_num = int(row.get('word_num') or ordinal)
                left, top = float(row['left']), float(row['top'])
                width, height = float(row['width']), float(row['height'])
                confidence = float(row['conf'])
            except (KeyError, TypeError, ValueError):
                continue
            if level != 5 or width <= 0 or height <= 0:
                continue
            key = (page_num, block_num, par_num, line_num)
            line = lines.setdefault(key, {
                'words': [],
                'bbox': [left, top, left + width, top + height],
                'weighted_confidence': 0.0,
                'confidence_weight': 0,
                'first_ordinal': ordinal,
            })
            line['words'].append((word_num, ordinal, text))
            line['bbox'][0] = min(line['bbox'][0], left)
            line['bbox'][1] = min(line['bbox'][1], top)
            line['bbox'][2] = max(line['bbox'][2], left + width)
            line['bbox'][3] = max(line['bbox'][3], top + height)
            if confidence >= 0:
                weight = max(len(text), 1)
                line['weighted_confidence'] += confidence * weight
                line['confidence_weight'] += weight

        blocks = []
        for key, line in sorted(lines.items(), key=lambda item: item[1]['first_ordinal']):
            words = sorted(line['words'], key=lambda item: (item[0], item[1]))
            text = ' '.join(word[2] for word in words).strip()
            if not text:
                continue
            weight = line['confidence_weight']
            confidence = line['weighted_confidence'] / (100.0 * weight) if weight else None
            blocks.append(OCRBlock(
                text=text,
                bbox=line['bbox'],
                confidence=confidence,
                metadata={
                    'tesseract_psm': psm,
                    'tesseract_line_key': list(key),
                    'word_count': len(words),
                },
            ))
        return blocks

    @staticmethod
    def _run_tsv(image: Path, *, tess_lang: str, psm: int) -> str:
        cp = subprocess.run(
            ['tesseract', str(image), 'stdout', '-l', tess_lang, '--psm', str(psm), 'tsv'],
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        if cp.returncode != 0:
            raise RuntimeError(f'tesseract failed with psm {psm}: {cp.stderr[-500:]}')
        return cp.stdout

    @staticmethod
    def _tess_language(lang: str | None) -> str:
        language = (lang or 'en').split('-')[0].lower()
        return {
            'en': 'eng', 'zh': 'chi_sim+eng', 'de': 'deu', 'fr': 'fra',
            'es': 'spa', 'it': 'ita', 'pt': 'por', 'ja': 'jpn', 'ko': 'kor',
            'ru': 'rus',
        }.get(language, language)

    @classmethod
    def _recognize_default(cls, image: Path, *, tess_lang: str) -> list[OCRBlock]:
        for psm in (3, 11):
            blocks = cls._parse_tsv_lines(cls._run_tsv(image, tess_lang=tess_lang, psm=psm), psm=psm)
            if blocks:
                return blocks
        return []

    @staticmethod
    def _ocr_quality(blocks: list[OCRBlock]) -> tuple[float, int]:
        weighted_confidence = 0.0
        confidence_weight = 0
        meaningful_total = 0
        for block in blocks:
            meaningful = sum(ch.isalnum() for ch in block.text)
            meaningful_total += meaningful
            if block.confidence is not None and meaningful:
                weighted_confidence += float(block.confidence) * meaningful
                confidence_weight += meaningful
        return (
            weighted_confidence / confidence_weight if confidence_weight else 0.0,
            meaningful_total,
        )

    def retry_rotated_180_if_better(
        self,
        image: Path,
        primary: list[OCRBlock],
        *,
        lang: str | None = None,
        page_id: str | None = None,
    ) -> tuple[list[OCRBlock], bool]:
        """Retry upside-down scans while retaining source-image coordinates.

        The retry is deliberately conservative: a 180-degree candidate must
        contain substantial text and beat the primary OCR confidence by a
        clear margin. The source rendition itself is never rotated.
        """
        primary_confidence, primary_chars = self._ocr_quality(primary)
        if primary_chars >= 80 and primary_confidence >= 0.82:
            return primary, False

        with Image.open(image) as source:
            width, height = source.size
            rotated = source.rotate(180, expand=False)
            with tempfile.TemporaryDirectory(prefix='xuanzang-tess-orientation-') as tmp:
                rotated_path = Path(tmp) / 'rotated_180.png'
                rotated.save(rotated_path, dpi=(300, 300))
                candidate = self._recognize_default(
                    rotated_path, tess_lang=self._tess_language(lang),
                )

        candidate_confidence, candidate_chars = self._ocr_quality(candidate)
        enough_text = candidate_chars >= max(40, int(primary_chars * 0.75))
        clearly_better = (
            candidate_confidence >= max(0.65, primary_confidence + 0.12)
            or (
                primary_chars < 40
                and candidate_chars >= 120
                and candidate_confidence >= 0.75
            )
        )
        if not enough_text or not clearly_better:
            return primary, False

        for block in candidate:
            rotated_bbox = list(block.bbox)
            x0, y0, x1, y1 = rotated_bbox
            block.bbox = [
                float(width) - float(x1), float(height) - float(y1),
                float(width) - float(x0), float(height) - float(y0),
            ]
            block.metadata = {
                **(block.metadata or {}),
                'ocr_orientation_correction_degrees': 180,
                'source_rendition_orientation_preserved': True,
                'corrected_orientation_bbox': rotated_bbox,
                'orientation_primary_confidence': round(primary_confidence, 6),
                'orientation_candidate_confidence': round(candidate_confidence, 6),
                'orientation_primary_meaningful_chars': primary_chars,
                'orientation_candidate_meaningful_chars': candidate_chars,
                'page_id': page_id,
            }
        return candidate, True

    @staticmethod
    def _overlap_ratio(first: list[float], second: list[float]) -> float:
        x0, y0 = max(first[0], second[0]), max(first[1], second[1])
        x1, y1 = min(first[2], second[2]), min(first[3], second[3])
        intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
        second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
        return intersection / max(1.0, min(first_area, second_area))

    @classmethod
    def merge_supplemental_blocks(
        cls, primary: list[OCRBlock], supplemental: list[OCRBlock],
    ) -> list[OCRBlock]:
        merged = list(primary)
        normalized = {' '.join(block.text.lower().split()) for block in primary}
        for block in supplemental:
            text_key = ' '.join(block.text.lower().split())
            if not text_key or text_key in normalized:
                continue
            if any(cls._overlap_ratio(block.bbox, prior.bbox) >= 0.75 for prior in merged):
                continue
            merged.append(block)
            normalized.add(text_key)
        return sorted(merged, key=lambda block: (block.bbox[1], block.bbox[0]))

    def recognize_back_cover_regions(
        self, image: Path, *, lang: str | None = None, page_id: str | None = None,
    ) -> list[OCRBlock]:
        tess_lang = self._tess_language(lang)
        with Image.open(image) as source:
            grayscale = source.convert('L')
            width, height = grayscale.size
            regions = [
                ('upper_panel', (0, 0, width, int(height * 0.43)), 80, 1.5),
                ('footer_left', (
                    int(width * 0.12), int(height * 0.84), int(width * 0.54), int(height * 0.96),
                ), 90, 2.0),
                ('footer_right', (
                    int(width * 0.56), int(height * 0.82), int(width * 0.90), int(height * 0.96),
                ), 70, 2.0),
            ]
            out = []
            with tempfile.TemporaryDirectory(prefix='xuanzang-tess-regions-') as tmp:
                tmp_path = Path(tmp)
                for region_name, (x0, y0, x1, y1), threshold, scale in regions:
                    crop = grayscale.crop((x0, y0, x1, y1))
                    enhanced = ImageOps.invert(ImageOps.autocontrast(crop, cutoff=1))
                    enhanced = enhanced.point(lambda pixel, cutoff=threshold: 0 if pixel < cutoff else 255)
                    if scale != 1.0:
                        enhanced = enhanced.resize(
                            (max(1, round(enhanced.width * scale)), max(1, round(enhanced.height * scale))),
                            Image.Resampling.LANCZOS,
                        )
                    target = tmp_path / f'{region_name}.png'
                    enhanced.save(target, dpi=(300, 300))
                    for block in self._parse_tsv_lines(
                        self._run_tsv(target, tess_lang=tess_lang, psm=6), psm=6,
                    ):
                        meaningful = sum(ch.isalnum() for ch in block.text)
                        looks_like_isbn = bool(re.match(r'^[TI1]?SBN\b', block.text, re.I))
                        looks_like_url = bool(re.search(r'(?:www\.|\.(?:edu|com|org)\b)', block.text, re.I))
                        minimum_confidence = 0.20 if (looks_like_isbn or looks_like_url) else 0.55
                        if meaningful < 4 or block.confidence is None or block.confidence < minimum_confidence:
                            continue
                        block.bbox = [
                            x0 + block.bbox[0] / scale,
                            y0 + block.bbox[1] / scale,
                            x0 + block.bbox[2] / scale,
                            y0 + block.bbox[3] / scale,
                        ]
                        block.metadata = {
                            **(block.metadata or {}),
                            'supplemental_variant': 'inverted_autocontrast_threshold',
                            'source_region': region_name,
                            'source_crop_box': [x0, y0, x1, y1],
                            'threshold': threshold,
                            'render_scale': scale,
                        }
                        out.append(block)
        return out

    def recognize(self, image: Path, *, lang: str | None = None, page_id: str | None = None) -> list[OCRBlock]:
        return self._recognize_default(image, tess_lang=self._tess_language(lang))


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
        preferred = os.environ.get('XUANZANG_AUTO_OCR_PREFERRED', '').strip().casefold()
        if preferred == 'tesseract':
            tesseract = TesseractOCRAdapter()
            if tesseract.available():
                return tesseract
        elif preferred not in {'', 'paddle'}:
            raise ValueError(
                'XUANZANG_AUTO_OCR_PREFERRED must be paddle or tesseract'
            )
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
