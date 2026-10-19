"""Lossless character storage and logical frames derived from hires crops."""
import hashlib
import json
from pathlib import Path
import uuid

import numpy as np
from PIL import Image


def logical_frame(image, high, canvas_size, corrections=()):
    """Reproduce full-canvas Lanczos downsampling on an aligned padded crop."""
    factor = high['scale']
    if factor <= 0:
        raise ValueError('Hires scale must be positive')
    x, y = high['origin']
    width, height = image.width/factor, image.height/factor
    if any(value != int(value) for value in (factor, x, y, width, height)):
        raise ValueError('Hires crops must align to the logical pixel grid')
    factor, x, y, width, height = map(int, (factor, x, y, width, height))
    left, top = max(0, x-3), max(0, y-3)
    right, bottom = min(canvas_size[0], x+width+3), min(canvas_size[1], y+height+3)
    # Three transparent logical pixels retain the complete Lanczos support.
    # Keeping this crop on the full canvas grid avoids shifted sampling phases.
    padded = Image.new('RGBa', ((right-left)*factor, (bottom-top)*factor))
    padded.paste(image.convert('RGBa'), ((x-left)*factor, (y-top)*factor))
    resized = padded.resize((right-left, bottom-top), Image.Resampling.LANCZOS).convert('RGBA')
    frame = Image.new('RGBA', tuple(canvas_size))
    frame.paste(resized, (left, top))
    for x, y, *rgba in corrections:
        frame.putpixel((x, y), tuple(rgba))
    return frame


def pixel_corrections(reference, derived):
    """Preserve the few rounding differences from full-canvas resampling."""
    original, result = np.asarray(reference), np.asarray(derived)
    rows, columns = np.nonzero(np.any(original != result, axis=2))
    return [[int(x), int(y), *map(int, original[y, x])] for y, x in zip(rows, columns)]


def save_lossless(image, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format='WEBP', lossless=True, exact=True, quality=100, method=6)


def write_manifest(path, manifest):
    path = Path(path)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def frame_files(frame):
    if frame.get('file'):
        yield frame['file']
    if frame.get('hires'):
        yield frame['hires']['file']


def deduplicate_frames(resource, manifest):
    """Share identical stored bytes within one character; keep frame metadata."""
    resource = Path(resource).resolve()
    seen, canonical = {}, {}
    for clip in manifest['animations'].values():
        for frame in clip['frames']:
            high = frame.get('hires')
            if not high:
                continue
            relative = high['file']
            if relative not in canonical:
                path = (resource / relative).resolve()
                if not path.is_relative_to(resource):
                    raise ValueError('Frame path leaves its character resource directory')
                digest = hashlib.sha256(path.read_bytes()).digest()
                canonical[relative] = seen.setdefault(digest, relative)
            high['file'] = canonical[relative]


def prune_animation_files(resource, manifest):
    """Remove only unreferenced images inside this resolved animation tree."""
    resource = Path(resource).resolve()
    directory = (resource / 'animations').resolve()
    if not directory.is_relative_to(resource):
        raise ValueError('Animation directory leaves the resource directory')
    referenced = {(resource / name).resolve() for clip in manifest['animations'].values()
                  for frame in clip['frames'] for name in frame_files(frame)}
    removed = 0
    for path in directory.rglob('*'):
        resolved = path.resolve()
        if not resolved.is_relative_to(directory):
            raise ValueError('Animation path leaves its character directory')
        if path.is_file() and path.suffix.lower() in {'.png', '.webp'} and resolved not in referenced:
            removed += path.stat().st_size
            path.unlink()
    for path in sorted(directory.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return removed
