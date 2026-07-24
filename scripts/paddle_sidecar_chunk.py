#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from xuanzang.adapters import PaddleOCRAdapter


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='Build one restart-safe PaddleOCR sidecar page chunk.')
    parser.add_argument('--pages-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--start', type=int, required=True)
    parser.add_argument('--end', type=int, required=True)
    parser.add_argument('--lang', default='en')
    args = parser.parse_args()
    if args.start < 1 or args.end < args.start:
        raise SystemExit('invalid page range')

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f'chunk_{args.start:04d}_{args.end:04d}'
    final_jsonl = args.output_dir / f'{stem}.jsonl'
    final_manifest = args.output_dir / f'{stem}.manifest.json'
    if final_jsonl.is_file() and final_manifest.is_file():
        manifest = json.loads(final_manifest.read_text(encoding='utf-8'))
        if (
            manifest.get('status') == 'complete'
            and manifest.get('sidecar_sha256') == sha256_file(final_jsonl)
            and manifest.get('start_page') == args.start
            and manifest.get('end_page') == args.end
        ):
            print(json.dumps({'status': 'reused', 'manifest': str(final_manifest)}), flush=True)
            return

    adapter = PaddleOCRAdapter()
    version = adapter.version() or 'unknown'
    page_reports: list[dict[str, Any]] = []
    row_count = 0
    with tempfile.TemporaryDirectory(prefix=f'.{stem}.', dir=args.output_dir) as tmp:
        tmp_jsonl = Path(tmp) / final_jsonl.name
        with tmp_jsonl.open('w', encoding='utf-8') as output:
            for page_number in range(args.start, args.end + 1):
                page_id = f'page_{page_number:04d}'
                image = args.pages_dir / f'{page_id}.png'
                if not image.is_file():
                    raise FileNotFoundError(image)
                image_sha = sha256_file(image)
                primary = adapter.recognize(image, lang=args.lang, page_id=page_id)
                blocks, corrected = adapter.retry_rotated_180_if_better(
                    image, primary, lang=args.lang, page_id=page_id,
                )
                for ordinal, block in enumerate(blocks, start=1):
                    row = {
                        'page_id': page_id,
                        'page': page_number,
                        'page_anchor': page_id,
                        'text': block.text,
                        'bbox': [float(value) for value in block.bbox],
                        'confidence': block.confidence,
                        'block_kind': block.block_kind,
                        'source_image_sha256': image_sha,
                        'engine': 'PaddleOCR',
                        'engine_version': version,
                        'metadata': {
                            **(block.metadata or {}),
                            'sidecar_chunk': stem,
                            'sidecar_ordinal': ordinal,
                            'source_image_path': str(image),
                        },
                    }
                    output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
                    row_count += 1
                output.flush()
                os.fsync(output.fileno())
                page_reports.append({
                    'page_id': page_id,
                    'page': page_number,
                    'source_image_path': str(image),
                    'source_image_sha256': image_sha,
                    'block_count': len(blocks),
                    'orientation_corrected_degrees': 180 if corrected else 0,
                })
                print(json.dumps({
                    'page': page_number, 'blocks': len(blocks),
                    'orientation_corrected': corrected,
                }), flush=True)
        sidecar_sha = sha256_file(tmp_jsonl)
        os.replace(tmp_jsonl, final_jsonl)

    manifest = {
        'status': 'complete',
        'producer': {
            'engine': 'PaddleOCR',
            'version': version,
            'detector': 'PP-OCRv5_mobile_det',
            'recognizer': 'en_PP-OCRv5_mobile_rec' if args.lang.startswith('en') else 'language_default',
            'language': args.lang,
            'execution': 'local_chunked_cpu',
        },
        'start_page': args.start,
        'end_page': args.end,
        'page_count': len(page_reports),
        'row_count': row_count,
        'sidecar_path': str(final_jsonl),
        'sidecar_sha256': sidecar_sha,
        'pages': page_reports,
    }
    tmp_manifest = final_manifest.with_suffix(final_manifest.suffix + '.tmp')
    write_json(tmp_manifest, manifest)
    os.replace(tmp_manifest, final_manifest)
    print(json.dumps({'status': 'complete', 'manifest': str(final_manifest)}), flush=True)


if __name__ == '__main__':
    main()
