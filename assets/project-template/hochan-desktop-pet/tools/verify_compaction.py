"""Check full skill concatenation, playback boundaries and per-character menus."""
import ctypes
import json
from pathlib import Path
import random
import sys
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from animation_clock import AnimationClock, load_manifest, packing_keys
from character_catalog import discover_characters
from hochan_pet import DemoChoices, HoChanPet
import pcr_pet as win


def make_preview(character, clips):
    keys = packing_keys(clips)
    canvas = Image.new('RGB', (1440, len(keys)*270), '#f5f3ef')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 18)
    for row, key in enumerate(keys):
        clip = clips[key]
        indices = sorted({round(i*(len(clip.frames)-1)/5) for i in range(6)})
        if character.id == 'kyouka-gothic' and key != 'packing_01':
            fps = json.loads(character.skin_path.read_text(encoding='utf-8')).get('fps',30)
            indices = [round(v*fps/30) for v in (0,16,31,32,55)] + [len(clip.frames)-1]
        for column, index in enumerate(indices):
            x, y = column*240, row*270
            draw.text((x+8, y+3), f'压缩 {row+1} / {index+1}', font=font, fill='#30343b')
            sprite = clip.frames[index].copy()
            sprite.thumbnail((240, 240), Image.Resampling.LANCZOS)
            canvas.paste(sprite, (x, y+26), sprite)
    directory = ROOT / 'preview/characters' / character.id
    directory.mkdir(parents=True, exist_ok=True)
    canvas.save(directory / 'packing-states.png')
    if character.id == 'ho-chan':
        canvas.save(ROOT / 'preview/packing-states.png')


def main():
    catalog = discover_characters(strict=True)
    references = json.loads((ROOT.parent / 'source/reference-frames/manifest.json').read_text(encoding='utf-8'))
    expected = {'packing_01': ['139001_skill2'],
                'packing_02': ['139001_skill1', '139001_skill1_1'],
                'packing_03': ['139001_skill1', '139001_skill1_2']}
    gothic = catalog['kyouka-gothic']
    manifest = json.loads((gothic.asset_dir / 'animation-manifest.json').read_text(encoding='utf-8'))
    clips = load_manifest(gothic.asset_dir)
    assert manifest['render_size'] == [640, 704]
    assert clips['idle'].frames.canvas_size == (640, 704)
    skin = json.loads(gothic.skin_path.read_text(encoding='utf-8'))
    fps = manifest.get('fps',30)
    source_counts = {item['animation']:round(item['durationSeconds']*fps)+1
                     for item in references if item['model'] == '139031.skel'}
    assert packing_keys(clips) == list(expected)
    assert [key for key in clips if key.startswith('packing_')] == list(expected)
    checks = []
    for key, names in expected.items():
        spec, clip = manifest['animations'][key], clips[key]
        assert [segment['source'] for segment in spec['segments']] == names
        assert not clip.loop and clip.total_duration == 2667
        assert len(clip.frames) == sum(source_counts[name] for name in names)-(len(names)-1)
        # All previews use the idle skeleton origin; padding extends down only.
        assert spec['fixed_view'] == skin['fixed_view']
        idle_bottom = clips['idle'].frames[0].getbbox()[3]
        assert abs(clip.frames[0].getbbox()[3]-idle_bottom) <= 2
        assert abs(clip.frames[len(clip.frames)-1].getbbox()[3]-idle_bottom) <= 2
        for scale in (1, 1.5, 2.25, 3):
            assert clip.frames.render(0, scale).size == (round(640*scale), round(704*scale))
        offset, milliseconds = 0, 0
        for segment in spec['segments']:
            removed = segment is not spec['segments'][-1]
            count = source_counts[segment['source']]-int(removed)
            assert segment['source_frame_count'] == source_counts[segment['source']]
            assert segment['removed_join_endpoint'] == removed
            assert segment['start_frame'] == offset and segment['frame_count'] == count
            assert sum(clip.durations[offset:offset+count]) == segment['duration_ms']
            assert clip.frame(milliseconds/1000) == offset
            milliseconds += segment['duration_ms']
            assert clip.frame((milliseconds-.001)/1000) == offset+count-1
            offset += count
        assert clip.frame(2.667) == 0
        checks.append(dict(key=key, sequence=names, frames=len(clip.frames), duration_ms=clip.total_duration))
    assert max(frame['visible_bounds'][3] for frame in manifest['animations']['packing_02']['frames']) > 640
    # Both branches keep the same opening, omitting its exported reset endpoint.
    for index in range(source_counts['139001_skill1']-1):
        assert clips['packing_02'].frames[index].tobytes() == clips['packing_03'].frames[index].tobytes()
        left, right = (clips[key].frames.specs[index] for key in ('packing_02', 'packing_03'))
        assert left['duration_ms'] == right['duration_ms'] and left['hires']['origin'] == right['hires']['origin']
        assert (gothic.asset_dir / left['hires']['file']).read_bytes() == (gothic.asset_dir / right['hires']['file']).read_bytes()
    # Random playback receives each canonical key once; legacy aliases do not
    # change the relative probabilities or introduce an extra animation.
    for character in catalog.values():
        pack = load_manifest(character.asset_dir)
        keys = packing_keys(pack)
        assert len(keys) == (3 if character.id == 'kyouka-gothic' else 4)
        class Choices:
            def choice(self, candidates):
                assert candidates == keys
                return random.choice(candidates)
        clock = AnimationClock(pack, rng=Choices())
        clock.update('actor', 'turn', 'packing', 0)
        selected = {clock.position('actor', moment/10)[0] for moment in range(2000)}
        assert selected == set(keys)
        demo = DemoChoices(pack)
        assert [demo.choice(keys) for _ in keys] == keys
        make_preview(character, pack)
    with tempfile.TemporaryDirectory(prefix='compaction-', dir=ROOT / 'build') as temporary:
        pet = HoChanPet(load_manifest(catalog['ho-chan'].asset_dir), ROOT,
                        Path(temporary) / 'codex-status.json', observe=False)
        pet._resolve_visual()
        pet.transient_key = 'packing_04'
        pet._resolve_visual()
        assert pet._set_character('kyouka-gothic')
        assert pet.transient_key is None
        for identity, count in (('kyouka-gothic', 3), ('ho-chan', 4), ('kyouka-gothic', 3)):
            assert pet._set_character(identity)
            assert [value for key, value in pet.preview_labels.items() if key.startswith('packing_')] == [f'压缩 {i}' for i in range(1, count+1)]
            menu = pet._create_context_menu()
            try:
                win.user32.GetSubMenu.argtypes = [win.wintypes.HMENU, ctypes.c_int]
                win.user32.GetSubMenu.restype = win.wintypes.HMENU
                submenu = win.user32.GetSubMenu(menu, 1)
                win.user32.GetMenuItemCount.argtypes = [win.wintypes.HMENU]
                win.user32.GetMenuStringW.argtypes = [win.wintypes.HMENU, win.wintypes.UINT, win.wintypes.LPWSTR, ctypes.c_int, win.wintypes.UINT]
                labels = []
                for index in range(win.user32.GetMenuItemCount(submenu)):
                    buffer = ctypes.create_unicode_buffer(256)
                    win.user32.GetMenuStringW(submenu, index, buffer, len(buffer), 0x400)
                    if buffer.value.startswith('压缩 '):
                        labels.append(buffer.value)
                assert labels == [f'压缩 {i}' for i in range(1, count+1)]
            finally:
                win.user32.DestroyMenu(menu)
            pet._start_compaction_demo()
            clock = pet.compaction_demo_clock
            epoch = clock.tracks['demo'].epoch
            visited = {clock.position('demo', epoch+step*.1)[0] for step in range(400)}
            assert visited == set(packing_keys(pet.animations))
        # The opened umbrella must survive the complete composition path,
        # including the area below the old 640px boundary at fractional DPI.
        clip = pet.animations['packing_02']
        index = max(range(len(clip.frames)), key=lambda i: clip.frames.specs[i]['visible_bounds'][3])
        for scale in (1, 1.5, 2.25, 3):
            canvas = pet.compose('packing_02', index, render_scale=scale)
            assert canvas.size == (round(640*scale), round(704*scale))
            assert canvas.getbbox()[3] > round(640*scale)
            if scale == 3:
                high = clip.frames.specs[index]['hires']
                with Image.open(clip.source / high['file']) as source:
                    x, y = (v*3 for v in high['origin'])
                    actual = canvas.crop((x, y, x+source.width, y+source.height))
                    assert not any(band.getbbox() for band in ImageChops.difference(actual, source).split())
    result = dict(status='passed', clips=checks,
                  checks=['Source frame counts with reset endpoints excluded at joins', 'Identical skill1 prefix including 3x PNGs',
                          'Idle skeleton origin retained with transparent bottom padding at all display scales',
                          'Complete umbrella below the old canvas boundary survives composition and native 3x pixel sampling',
                          'Canonical random choices and demos', 'Native menus show 3/4 numbered actions',
                          'Switching during preview and compaction demo'])
    (ROOT / 'build/compaction-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
