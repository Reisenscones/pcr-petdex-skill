"""Stage lossless hires-only WebP packs, proving every original frame matches."""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys
import time
import uuid

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from animation_clock import load_manifest
from asset_storage import logical_frame, pixel_corrections, save_lossless, deduplicate_frames, prune_animation_files, write_manifest
from character_catalog import discover_characters, validate_pack


def convert(source_root, target_root, relative, records, canvas_size):
    source = (source_root / relative).resolve()
    if not source.is_relative_to(source_root):
        raise ValueError('Source image leaves its character directory')
    destination = (target_root / Path(relative).with_suffix('.webp')).resolve()
    if not destination.is_relative_to(target_root):
        raise ValueError('Output image leaves its staging directory')
    with Image.open(source) as opened:
        original = opened.convert('RGBA')
    valid = False
    if destination.is_file():
        try:
            with Image.open(destination) as opened:
                candidate = opened.convert('RGBA')
                valid = candidate.size == original.size and candidate.tobytes() == original.tobytes()
        except OSError:
            pass
    if not valid:
        save_lossless(original, destination)
    with Image.open(destination) as opened:
        decoded = opened.convert('RGBA')
    if decoded.size != original.size or decoded.tobytes() != original.tobytes():
        raise AssertionError('WebP changed hires pixels: '+relative)
    corrections = {}
    for logical_path, high in records.items():
        with Image.open(source_root / logical_path) as opened:
            reference = opened.convert('RGBA')
        if reference.size != tuple(canvas_size):
            padded = Image.new('RGBA', tuple(canvas_size))
            padded.paste(reference, (0, 0))
            reference = padded
        derived = logical_frame(decoded, high, canvas_size)
        patches = pixel_corrections(reference, derived)
        restored = logical_frame(decoded, high, canvas_size, patches)
        if restored.tobytes() != reference.tobytes():
            raise AssertionError('Derived logical pixels changed: '+logical_path)
        corrections[logical_path] = patches
    return dict(file=destination.relative_to(target_root).as_posix(), corrections=corrections)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    output = (args.output or ROOT / 'build' / ('asset-optimization-'+uuid.uuid4().hex[:8])).resolve()
    if not output.is_relative_to((ROOT / 'build').resolve()) or (output.exists() and not args.resume):
        raise ValueError('Use a new staging directory inside build/')
    output.mkdir(parents=True, exist_ok=args.resume)
    print('Staging: '+str(output), flush=True)
    reports = []
    began = time.monotonic()
    for character in discover_characters(strict=True).values():
        source_root = character.asset_dir.resolve()
        target_root = output / source_root.parent.name / 'animation-resources'
        target_root.mkdir(parents=True, exist_ok=args.resume)
        original = json.loads((source_root / 'animation-manifest.json').read_text(encoding='utf-8'))
        manifest = copy.deepcopy(original)
        canvas_size = manifest.get('render_size', [640, 640])
        jobs = {}
        for clip in original['animations'].values():
            for frame in clip['frames']:
                if not frame.get('file') or not frame.get('hires'):
                    raise ValueError('This migration expects the original normal/hires pack')
                jobs.setdefault(frame['hires']['file'], {})[frame['file']] = frame['hires']
        original_files = list((source_root / 'animations').rglob('*'))
        before = sum(path.stat().st_size for path in original_files if path.is_file())
        results = {}
        with ThreadPoolExecutor(max_workers=max(1, min(8, args.workers))) as executor:
            tasks = {executor.submit(convert, source_root, target_root, relative, records, canvas_size): relative
                     for relative, records in jobs.items()}
            for future in as_completed(tasks):
                relative = tasks[future]
                results[relative] = future.result()
                if len(results) % 100 == 0 or len(results) == len(jobs):
                    print(f'{character.id}: {len(results)}/{len(jobs)} hires images losslessly encoded and logical pixels verified', flush=True)
        corrected_frames = correction_pixels = 0
        for clip in manifest['animations'].values():
            for frame in clip['frames']:
                result = results[frame['hires']['file']]
                patches = result['corrections'][frame.pop('file')]
                frame['hires']['file'] = result['file']
                if patches:
                    frame['logical_corrections'] = patches
                    corrected_frames += 1
                    correction_pixels += len(patches)
        manifest['format_version'] = 2
        deduplicate_frames(target_root, manifest)
        write_manifest(target_root / 'animation-manifest.json', manifest)
        prune_animation_files(target_root, manifest)
        clips = load_manifest(target_root)
        validate_pack(clips)
        # Decode every logical frame through the actual runtime once more.
        logical_checks = 0
        for key, clip in clips.items():
            old_clip = original['animations'][key]
            assert clip.durations == [f['duration_ms'] for f in old_clip['frames']]
            for index, old_frame in enumerate(old_clip['frames']):
                with Image.open(source_root / old_frame['file']) as opened:
                    reference = opened.convert('RGBA')
                if reference.size != tuple(canvas_size):
                    padded = Image.new('RGBA', tuple(canvas_size))
                    padded.paste(reference, (0, 0))
                    reference = padded
                assert clip.frames[index].tobytes() == reference.tobytes(), (character.id, key, index)
                logical_checks += 1
        after = sum(path.stat().st_size for path in target_root.rglob('*') if path.is_file())
        report = dict(character=character.id, directory=str(target_root), before_bytes=before,
            after_bytes=after, saved_bytes=before-after, unique_webp_files=len(list(target_root.rglob('*.webp'))),
            logical_frame_checks=logical_checks, corrected_frames=corrected_frames, correction_pixels=correction_pixels,
            hires_checks=len(jobs), status='passed')
        reports.append(report)
        print(json.dumps(report), flush=True)
    report = dict(status='passed', stage=str(output), characters=reports, seconds=round(time.monotonic()-began, 1))
    write_manifest(output / 'verification.json', report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
