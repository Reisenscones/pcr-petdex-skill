"""Verify pixel-exact derived frames, deduplication and safe partial rebuilds."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from animation_clock import Frames, load_manifest
from asset_storage import logical_frame, pixel_corrections, save_lossless, deduplicate_frames, prune_animation_files, write_manifest
import build_skin


def main():
    checks = []
    with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='storage-') as temporary:
        directory = Path(temporary)
        high = Image.new('RGBA', (1920, 2112))
        draw = ImageDraw.Draw(high)
        draw.ellipse((940, 1120, 1420, 1900), fill=(127, 62, 182, 227))
        draw.line((1000, 1200, 1387, 1889), fill=(250, 221, 171, 255), width=17)
        reference = high.convert('RGBa').resize((640, 704), Image.Resampling.LANCZOS).convert('RGBA')
        cropped = high.crop((927, 1107, 1437, 1917))
        metadata = dict(file='animations/test_idle/000@3x.webp', scale=3, origin=[309, 369])
        derived = logical_frame(cropped, metadata, reference.size)
        corrections = pixel_corrections(reference, derived)
        assert logical_frame(cropped, metadata, reference.size, corrections).tobytes() == reference.tobytes()
        # Correction metadata also preserves invisible RGB and alpha changes.
        changed = reference.copy()
        changed.putpixel((0, 0), (25, 45, 65, 0))
        patches = pixel_corrections(changed, derived)
        assert logical_frame(cropped, metadata, reference.size, patches).tobytes() == changed.tobytes()
        save_lossless(cropped, directory / metadata['file'])
        reference.save(directory / 'legacy.png')
        compact_spec = dict(hires=metadata, duration_ms=16, logical_corrections=corrections)
        legacy_spec = dict(compact_spec, file='legacy.png')
        compact, legacy = Frames(directory, [compact_spec], (640, 704)), Frames(directory, [legacy_spec], (640, 704))
        assert compact[0].tobytes() == legacy[0].tobytes()
        assert len(compact.cache) == 1 and not compact.hires_cache
        for scale in (.75, 1, 1.125, 1.5, 1.875, 2.25, 3):
            for mirrored in (False, True):
                assert compact.render(0, scale, mirrored).tobytes() == legacy.render(0, scale, mirrored).tobytes()
        checks.append('Derived and legacy frames match every RGBA byte at seven scales and both directions')

        duplicate = directory / 'animations/test_other/001@3x.webp'
        duplicate.parent.mkdir()
        duplicate.write_bytes((directory / metadata['file']).read_bytes())
        other = copy.deepcopy(compact_spec)
        other['duration_ms'], other['hires']['file'], other['hires']['origin'] = 33, duplicate.relative_to(directory).as_posix(), [310, 370]
        manifest = dict(format_version=2, window_size=640, render_size=[640, 704], animations={
            'idle': dict(label='idle', frames=[compact_spec]), 'other': dict(label='other', frames=[other])})
        deduplicate_frames(directory, manifest)
        assert other['hires']['file'] == metadata['file']
        assert other['duration_ms'] == 33 and other['hires']['origin'] == [310, 370]
        write_manifest(directory / 'animation-manifest.json', manifest)
        prune_animation_files(directory, manifest)
        assert not duplicate.exists() and (directory / 'legacy.png').exists()
        assert load_manifest(directory)['idle'].frames[0].tobytes() == reference.tobytes()
        checks.append('Deduplication shares artwork while preserving per-frame duration/origin; pruning stays inside animations')

        # Exercise the real builder with a synthetic export and a shared old
        # file. Rebuilding idle must leave the unchanged wake/left pixels intact.
        app = directory / 'app'
        resource = app / 'assets/characters/fixture/animation-resources'
        resource.mkdir(parents=True)
        old_relative = 'animations/fixture_idle/000@3x.webp'
        old = Image.new('RGBA', (300, 300), (170, 30, 40, 255))
        save_lossless(old, resource / old_relative)
        old_bytes = (resource / old_relative).read_bytes()
        old_frame = dict(duration_ms=1000, visible_bounds=[100, 100, 200, 200], drag_anchor=[150, 150],
                         hires=dict(file=old_relative, scale=3, origin=[100, 100]))
        config = dict(phase=2, fps=1, window_size=640, body_anchor=[410, 570], animation_prefix='fixture',
            fixed_view=dict(center_x=-225, center_y=625, scale=.4, supersampling=3), aliases={},
            animations={key: dict(animation='source_'+key, label=key, duration_seconds=1)
                        for key in ('idle', 'left', 'wake')})
        skin = app / 'skin.json'
        skin.write_text(json.dumps(config), encoding='utf-8')
        existing = dict(format_version=2, window_size=640, render_size=[640, 640], animations={
            key: dict(source='source_'+key, label=key, frames=[copy.deepcopy(old_frame)]) for key in config['animations']})
        write_manifest(resource / 'animation-manifest.json', existing)
        for path in (app / '.tools/SpineViewer-v0.16.34/SpineViewerCLI.exe', app / 'source/spine/fixture.skel'):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        raw = app / 'export.png'
        new = Image.new('RGBA', (1920, 1920))
        ImageDraw.Draw(new).rectangle((1080, 1200, 1380, 1650), fill=(20, 70, 210, 255))
        new.save(raw)
        character = SimpleNamespace(id='fixture', name='Fixture', model='fixture', skin_path=skin, asset_dir=resource)
        part = dict(source='source_idle', paths=[raw], duration_ms=1000, source_frame_count=1,
                    removed_join_endpoint=False, removed_duplicate_endpoint=False, removed_duration_endpoint=False)
        known = {spec['animation']: dict(durationSeconds=1) for spec in config['animations'].values()}
        with patch.object(build_skin, 'ROOT', app), \
                patch.object(build_skin, 'discover_characters', return_value={'fixture': character}), \
                patch.object(build_skin, 'query_animations', return_value=known), \
                patch.object(build_skin, 'export_parts', return_value=[part]), \
                patch.object(sys, 'argv', ['build-skin', '--source-root', str(app), '--character', 'fixture', '--only', 'idle']):
            build_skin.main()
        built = json.loads((resource / 'animation-manifest.json').read_text(encoding='utf-8'))
        assert built['format_version'] == 2
        assert all('file' not in frame for clip in built['animations'].values() for frame in clip['frames'])
        assert built['animations']['idle']['frames'][0]['hires']['file'] != old_relative
        assert built['animations']['wake']['frames'][0]['hires']['file'] == old_relative
        assert (resource / old_relative).read_bytes() == old_bytes
        assert load_manifest(resource)['idle'].frames[0].tobytes() == new.convert('RGBa').resize((640, 640), Image.Resampling.LANCZOS).convert('RGBA').tobytes()
        checks.append('Real partial builder emits hires-only WebP and never overwrites an unchanged clip sharing an older image')
    print(json.dumps(dict(status='passed', checks=checks), indent=2))


if __name__ == '__main__':
    main()
