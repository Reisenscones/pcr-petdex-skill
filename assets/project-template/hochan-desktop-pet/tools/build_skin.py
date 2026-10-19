"""Build the Ho-chan skin with a shared Spine view, aliases and rest overlays."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import shutil
import sys
import uuid

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from character_catalog import discover_characters
from animation_clock import Frames
from asset_storage import logical_frame, pixel_corrections, save_lossless, deduplicate_frames, prune_animation_files, write_manifest
from spine_sources import query_animations, resolve_model


def source_names(spec):
    return spec['sequence'] if 'sequence' in spec else [spec['animation']]


def export_parts(cli, model, build, key, spec, known, fixed_view):
    """Export segments, optionally excluding a reset pose at a join endpoint."""
    parts = []
    for part_index, name in enumerate(source_names(spec)):
        source = known[name]
        raw = build / key / str(part_index)
        command = [str(cli), 'export', str(model), '--format', 'Frames', '--output', str(raw),
                   '--animations', name, '--fps', str(source['fps']), '--scale', '1',
                   '--fixed-view', fixed_view, '--color', '#00000000', '--margin', '0',
                   '--drop-last-frame', '--no-progress']
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise RuntimeError(f'Export failed: {name}\n{result.stdout}\n{result.stderr}')
        paths = sorted(raw.glob('*.png'))
        if not paths:
            raise ValueError(f'No frames exported: {name}')
        with Image.open(paths[0]) as first, Image.open(paths[-1]) as last:
            duplicate = len(paths) > 1 and first.tobytes() == last.tobytes()
        samples = source['durationSeconds'] * source['fps']
        endpoint = abs(samples-round(samples)) < .001 and len(paths) == round(samples)+1
        source_frame_count = len(paths)
        join_endpoint = (spec.get('drop_join_endpoints', False) and part_index < len(source_names(spec))-1 and endpoint)
        removed = join_endpoint or (spec.get('loop', True) and len(source_names(spec)) == 1 and (duplicate or endpoint))
        if removed:
            paths = paths[:-1]
        parts.append(dict(source=name, paths=paths, duration_ms=round(source['durationSeconds']*1000),
                          source_frame_count=source_frame_count, removed_join_endpoint=join_endpoint,
                          removed_duplicate_endpoint=duplicate and removed, removed_duration_endpoint=endpoint and removed))
    return parts


def make_edge_portraits(resource, manifest, crop=(365, 392, 458, 474)):
    frames = Frames(resource, manifest['animations']['idle']['frames'], manifest.get('render_size', [640, 640]))
    head = frames[0].crop(tuple(crop))
    head = ImageOps.fit(head, (52, 52), method=Image.Resampling.LANCZOS)
    mask = Image.new('L', (52, 52))
    ImageDraw.Draw(mask).ellipse((0, 0, 51, 51), fill=255)
    head.putalpha(Image.composite(head.getchannel('A'), Image.new('L', head.size), mask))
    directory = resource.parent / 'edge-tail'
    directory.mkdir(exist_ok=True)
    for edge, center in {'left': (52, 34), 'right': (16, 34), 'top': (34, 52), 'bottom': (34, 16)}.items():
        # The original geometry exposes only a 30px strip. Put the complete
        # portrait inside that strip rather than at the hidden canvas centre.
        badge = Image.new('RGBA', (136, 136))
        cx, cy = (value*2 for value in center)
        draw = ImageDraw.Draw(badge)
        draw.ellipse((cx-28, cy-28, cx+28, cy+28), fill='#fff1df', outline='#a85848', width=3)
        badge.alpha_composite(head, (cx-26, cy-26))
        badge.resize((68, 68), Image.Resampling.LANCZOS).save(directory / f'{edge}.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT.parent)
    parser.add_argument('--character', default='ho-chan', help='Id registered under characters/')
    parser.add_argument('--only', nargs='+', help='Rebuild selected unique clips; refresh aliases and portraits too')
    parser.add_argument('--output-dir', type=Path, help='Build a complete pack in a staging directory')
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    cli = source_root / '.tools/SpineViewer-v0.16.34/SpineViewerCLI.exe'
    catalog = discover_characters(strict=True)
    if args.character not in catalog:
        parser.error('Unknown character id')
    character = catalog[args.character]
    model = resolve_model(source_root / 'source/spine', character.model)
    config = json.loads(character.skin_path.read_text(encoding='utf-8'))
    animation_prefix = config.get('animation_prefix', character.id)
    if not isinstance(animation_prefix, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', animation_prefix):
        raise ValueError('Invalid animation directory prefix')
    if not cli.is_file() or not model.is_file():
        raise FileNotFoundError('The source Spine file and SpineViewerCLI are required to rebuild the skin.')
    known = query_animations(cli, model)
    fps = config.get('fps', 30)
    if not isinstance(fps, int) or not 1 <= fps <= 120:
        raise ValueError('Skin fps must be an integer between 1 and 120')
    for source in known.values():
        source['fps'] = fps
    for spec in config['animations'].values():
        for name in source_names(spec):
            if name not in known:
                raise ValueError('Animation not present in model: ' + name)
        if abs(sum(known[name]['durationSeconds'] for name in source_names(spec))-spec['duration_seconds']) > .0001:
            raise ValueError('Duration mismatch: ' + ' + '.join(source_names(spec)))
    if config['window_size'] != 640 or config['body_anchor'] != [410, 570]:
        raise ValueError('Runtime geometry requires a 640px canvas and body anchor [410, 570]')
    resource = args.output_dir.resolve() if args.output_dir else character.asset_dir
    resource.mkdir(parents=True, exist_ok=True)
    manifest_path = resource / 'animation-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else dict(
        format_version=1, window_size=640, body_anchor_x=410, body_anchor_bottom=570, animations={})
    view = config['fixed_view']
    factor = view['supersampling']
    size = config['window_size']
    render_size = config.get('render_size', [size, size])
    if render_size[0] != size or not size <= render_size[1] <= 1280:
        raise ValueError('Only transparent padding below the logical canvas is supported')
    fixed_view = f"w={size*factor},h={size*factor},x={view['center_x']},y={view['center_y']},s={view['scale']*factor}"
    build = ROOT / 'build' / ('skin-' + character.id + '-' + uuid.uuid4().hex[:8])
    report_path = (resource.parent / 'skin-report.json') if args.output_dir else ROOT / 'build' / ('skin-report.json' if character.id == 'ho-chan' else f'skin-report-{character.id}.json')
    report = json.loads(report_path.read_text(encoding='utf-8')) if args.only and report_path.exists() else dict(animations={})
    report.update(fixed_view=fixed_view, source_model=str(model), phase=config['phase'], character_id=character.id, character_name=character.name)
    expected_keys = set(config['animations']) | set(config.get('aliases', {}))
    manifest['animations'] = {key: value for key, value in manifest['animations'].items() if key in expected_keys}
    report['animations'] = {key: value for key, value in report['animations'].items() if key in config['animations']}
    if args.only and set(args.only) - set(config['animations']):
        raise ValueError('Unknown --only animation key')
    for key, spec in config['animations'].items():
        name = ' + '.join(source_names(spec))
        clip_view = dict(view, **spec.get('fixed_view', {}))
        if clip_view['supersampling'] != factor:
            raise ValueError('Per-clip supersampling must match the character')
        # Adding transparent space below must not move the skeleton origin.
        # SpineViewer centres its view, so counteract half of the added height.
        export_center_y = clip_view['center_y']-(render_size[1]-size)/(2*clip_view['scale'])
        clip_fixed_view = f"w={render_size[0]*factor},h={render_size[1]*factor},x={clip_view['center_x']},y={export_center_y},s={clip_view['scale']*factor}"
        if args.only and key not in args.only:
            if manifest['animations'].get(key, {}).get('source') != name:
                raise ValueError(f'Existing clip is missing or stale: {key}')
            manifest['animations'][key].update(label=spec['label'], loop=spec.get('loop', True))
            continue
        parts = export_parts(cli, model, build, key, spec, known, clip_fixed_view)
        paths = [path for part in parts for path in part['paths']]
        durations = [round((i+1)*part['duration_ms']/len(part['paths']))-round(i*part['duration_ms']/len(part['paths']))
                     for part in parts for i in range(len(part['paths']))]
        segments, offset = [], 0
        for part in parts:
            segments.append(dict(source=part['source'], start_frame=offset, frame_count=len(part['paths']), duration_ms=part['duration_ms'],
                                 source_frame_count=part['source_frame_count'], removed_join_endpoint=part['removed_join_endpoint']))
            offset += len(part['paths'])
        target = resource / 'animations' / (animation_prefix + '_' + key)
        target.mkdir(parents=True, exist_ok=True)
        frames, boxes = [], []
        total_ms = sum(durations)
        for index, path in enumerate(paths):
            with Image.open(path) as source:
                high = source.convert('RGBA')
                image = high.convert('RGBa').resize(tuple(render_size), Image.Resampling.LANCZOS).convert('RGBA')
            box = image.getchannel('A').getbbox()
            if not box or box[0] <= 0 or box[1] <= 0 or box[2] >= render_size[0] or box[3] >= render_size[1]:
                raise ValueError(f'Transparent or clipped frame: {path} ({box})')
            # Retain the original render, cropped on logical-pixel boundaries.
            # Enlarged pets can then sample source detail instead of a 640px PNG.
            high_box = high.getchannel('A').getbbox()
            crop_box = tuple(max(0, (v//factor-1)*factor) if i < 2 else min(render_size[i%2]*factor, (v//factor+2)*factor)
                             for i, v in enumerate(high_box))
            cropped = high.crop(crop_box)
            # Rebuilding a clip must not overwrite an old file shared by an
            # unchanged clip after deduplication.
            digest = hashlib.sha256(cropped.tobytes()).hexdigest()[:16]
            high_relative = f'animations/{animation_prefix}_{key}/{index:03d}@{factor}x-{digest}.webp'
            save_lossless(cropped, resource / high_relative)
            hires = dict(file=high_relative, scale=factor, origin=[crop_box[0]//factor, crop_box[1]//factor])
            frame = dict(duration_ms=durations[index], visible_bounds=list(box), hires=hires)
            corrections = pixel_corrections(image, logical_frame(cropped, hires, render_size))
            if corrections:
                frame['logical_corrections'] = corrections
            frames.append(frame)
            boxes.append(box)
        manifest['animations'][key] = dict(label=spec['label'], source=name, loop=spec.get('loop', True),
                                          timing='uniform_segments', segments=segments, fixed_view=clip_view, frames=frames)
        report['animations'][key] = dict(source=name, segments=segments, fixed_view=clip_fixed_view, frame_count=len(frames), duration_ms=total_ms,
            removed_duplicate_endpoint=any(part['removed_duplicate_endpoint'] for part in parts),
            removed_duration_endpoint=any(part['removed_duration_endpoint'] for part in parts),
            alpha_union=[min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)])
        print(f'{key} <- {name}: {len(frames)} frames, {total_ms} ms')
    if not args.only or 'left' in args.only or any('drag_anchor' not in frame for frame in manifest['animations']['left']['frames']):
        pwsh = shutil.which('pwsh')
        if not pwsh:
            raise RuntimeError('PowerShell 7 is required to rebuild the hand anchor metadata.')
        anchor_path = build / 'drag-hand-anchors.json'
        anchor_path.parent.mkdir(parents=True, exist_ok=True)
        hand_config = config.get('drag_anchor', {'slot': 'handB', 'palm_offset': [24, 7.5]})
        subprocess.run([pwsh, '-NoProfile', '-File', str(ROOT / 'tools/export_hand_anchors.ps1'),
            '-ModelPath', str(model), '-LibraryDirectory', str(cli.parent), '-OutputPath', str(anchor_path),
            '-Animation', config['animations']['left']['animation'], '-Slot', hand_config['slot'],
            '-FrameCount', str(len(manifest['animations']['left']['frames'])),
            '-Fps', str(known[config['animations']['left']['animation']]['fps']),
            '-WindowSize', str(size), '-CenterX', str(view['center_x']), '-CenterY', str(view['center_y']),
            '-Scale', str(view['scale']), '-PalmOffsetX', str(hand_config['palm_offset'][0]),
            '-PalmOffsetY', str(hand_config['palm_offset'][1])], check=True)
        anchors = json.loads(anchor_path.read_text(encoding='utf-8-sig'))
        for frame, anchor in zip(manifest['animations']['left']['frames'], anchors['frames'], strict=True):
            frame['drag_anchor'] = anchor['point']
    for key, source_key in config.get('aliases', {}).items():
        manifest['animations'][key] = dict(manifest['animations'][source_key], alias_of=source_key)
    manifest.update(format_version=2, character_id=character.id, character_name=character.name,
                    animation_prefix=animation_prefix, render_size=render_size, fps=fps)
    deduplicate_frames(resource, manifest)
    make_edge_portraits(resource, manifest, config.get('portrait_crop', (365, 392, 458, 474)))
    write_manifest(manifest_path, manifest)
    prune_animation_files(resource, manifest)
    (ROOT / 'build').mkdir(exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
