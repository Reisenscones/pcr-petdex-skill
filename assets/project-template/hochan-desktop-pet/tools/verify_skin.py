"""Verify decoded resources, event-driven switching, drag rendering and previews."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from animation_clock import load_manifest
from codex_bridge import publish_event
from hochan_pet import HoChanPet


def make_preview(clips, config):
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 18)
    small = ImageFont.truetype('C:/Windows/Fonts/consola.ttf', 12)
    names = ['idle', 'left', 'reading', 'working']
    images = []
    # Four seconds shows multiple complete loops at the actual playback speed.
    for frame in range(120):
        seconds = frame / 30
        canvas = Image.new('RGBA', (1200, 440), '#f5f3ef')
        draw = ImageDraw.Draw(canvas)
        for column, key in enumerate(names):
            x = column * 300
            draw.rectangle((x, 0, x+299, 439), outline='#d7d1c8')
            draw.text((x+18, 10), config['animations'][key]['label'], font=font, fill='#2a3038')
            draw.text((x+18, 40), config['animations'][key]['animation'], font=small, fill='#6b7179')
            draw.line((x+35, 410, x+265, 410), fill='#d7d1c8')
            clip = clips[key]
            sprite = clip.frames[clip.frame(seconds)].crop((280, 220, 560, 600))
            canvas.alpha_composite(sprite, (x+10, 60))
        images.append(canvas.convert('RGB'))
    preview = ROOT / 'preview'
    preview.mkdir(exist_ok=True)
    images[0].save(preview / 'four-states.png')
    images[0].save(preview / 'four-states.webp', save_all=True, append_images=images[1:],
                   duration=[round((i+1)*1000/30)-round(i*1000/30) for i in range(len(images))], loop=0, quality=90, method=4)
    names = list(config['animations'])
    grid = Image.new('RGBA', (1280, ((len(names)+3)//4)*400), '#f5f3ef')
    draw = ImageDraw.Draw(grid)
    for cell, key in enumerate(names):
        x, y = cell % 4 * 320, cell // 4 * 400
        draw.rectangle((x, y, x+319, y+399), outline='#d7d1c8')
        draw.text((x+14, y+10), config['animations'][key]['label'], font=font, fill='#2a3038')
        draw.text((x+14, y+39), config['animations'][key]['animation'], font=small, fill='#6b7179')
        clip = clips[key]
        image = clip.frames[clip.frame(clip.total_duration/2000)].crop((240, 180, 620, 620))
        image = image.convert('RGBa').resize((285, 330), Image.Resampling.LANCZOS).convert('RGBA')
        grid.alpha_composite(image, (x+17, y+60))
    grid.convert('RGB').save(preview / 'all-states.png')


def main():
    resource = ROOT / 'assets/characters/ho-chan/animation-resources'
    config = json.loads((ROOT / 'skin.json').read_text(encoding='utf-8'))
    manifest = json.loads((resource / 'animation-manifest.json').read_text(encoding='utf-8'))
    clips = load_manifest(resource)
    checks = []
    for key, spec in config['animations'].items():
        clip = clips[key]
        assert manifest['animations'][key]['source'] == spec['animation']
        assert clip.total_duration == round(spec['duration_seconds'] * 1000)
        for index in range(len(clip.frames)):
            image = clip.frames[index]
            assert image.size == (640, 640) and image.mode == 'RGBA'
            alpha = image.getchannel('A')
            box = alpha.getbbox()
            assert box and min(box) > 0 and max(box) < 640, (key, index, box)
            assert alpha.getpixel((0, 0)) == 0
            high = clip.frames.specs[index]['hires']
            assert high['scale'] == config['fixed_view']['supersampling'] == 3
            with Image.open(resource / high['file']) as high_image:
                assert high_image.mode == 'RGBA'
                assert all(v % high['scale'] == 0 for v in high_image.size)
                high_box = high_image.getchannel('A').getbbox()
                assert high_box and min(high_box) > 0
                assert high_box[2] < high_image.width and high_box[3] < high_image.height
                assert all(0 <= high['origin'][i]+high_image.size[i]/high['scale'] <= 640 for i in (0, 1))
        assert clip.frame(0) == clip.frame(clip.total_duration/1000 + 0.000001)
        assert len(clip.frames.cache) <= 8
        checks.append(f'{key}: decoded {len(clip.frames)} logical and 3x RGBA frames, no clipping, correct duration and looping')
    expected = set(config['animations']) | set(config['aliases'])
    assert set(manifest['animations']) == expected
    for key, source in config['aliases'].items():
        assert manifest['animations'][key]['frames'] == manifest['animations'][source]['frames']
        assert manifest['animations'][key]['alias_of'] == source
    from collections import Counter
    expected_packing = {'07_standBy', '07_multi_standBy', '134701_skill1', '134701_skill2'}
    packing_sources = Counter(spec['source'] for key, spec in manifest['animations'].items() if key.startswith('packing_'))
    assert set(packing_sources) == expected_packing
    assert set(packing_sources.values()) == {1}
    from animation_clock import AnimationClock
    import random
    clock = AnimationClock(clips, rng=random.Random(42))
    clock.update('packing-test', 'turn', 'packing', 0)
    selected = {manifest['animations'][clock.position('packing-test', n*.5)[0]]['source'] for n in range(200)}
    assert selected == expected_packing
    checks.append('Packing randomly plays all four equally represented sources; bow is absent')
    assert all(frame['hires']['file'].startswith('animations/hochan_') for spec in manifest['animations'].values() for frame in spec['frames'])
    for edge, box in {'left': (38,0,68,68), 'right': (0,0,30,68), 'top': (0,38,68,68), 'bottom': (0,0,68,30)}.items():
        with Image.open(resource.parent / 'edge-tail' / (edge+'.png')) as image:
            assert image.size == (68, 68) and image.crop(box).getchannel('A').getbbox()
    checks.append(f'All {len(clips)} clips reference character artwork; all four edge portraits are visible')
    with tempfile.TemporaryDirectory(prefix='verify-', dir=ROOT / 'build') as temporary:
        status = Path(temporary) / 'codex-status.json'
        pet = HoChanPet(clips, ROOT, status, observe=False)
        pet._resolve_visual()
        assert pet.current_key == 'idle'
        publish_event(status.parent, dict(session_id='skin-test', turn_id='t1', event='UserPromptSubmit'))
        pet._poll_bridge(force=True)
        pet._resolve_visual()
        assert pet.current_key == 'reading'
        publish_event(status.parent, dict(session_id='skin-test', turn_id='t1', event='PreToolUse'))
        pet._poll_bridge(force=True)
        pet._resolve_visual()
        assert pet.current_key == 'working'
        pet.dragging = True
        pet._resolve_visual()
        assert pet.current_key == 'left'
        original = pet.compose()
        pet.drag_direction = 1
        mirrored = pet.compose()
        assert mirrored.getbbox() and original.getbbox()
        original_box, mirrored_box = original.getbbox(), mirrored.getbbox()
        assert abs((820-original_box[2])-mirrored_box[0]) <= 1
        assert abs((820-original_box[0])-mirrored_box[2]) <= 1
        assert original_box[1] == mirrored_box[1]
        pet.dragging = False
        pet._resolve_visual()
        assert pet.current_key == 'working'
        checks.append('Real event files switch idle -> reading -> working; drag overrides to left and restores working')
        checks.append('Dragging mirrors around x=410 and preserves vertical position')
        publish_event(status.parent, dict(session_id='skin-test', turn_id='t1', event='PreCompact'))
        pet._poll_bridge(force=True)
        pet._resolve_visual()
        assert pet.current_key.startswith('packing_')
        publish_event(status.parent, dict(session_id='skin-test', turn_id='t1', event='PostCompact'))
        pet._poll_bridge(force=True)
        pet._resolve_visual()
        assert pet.current_key == 'jump'
        track = pet.clock.tracks['skin-test']
        assert pet.clock.position('skin-test', track.epoch+clips['jump'].total_duration/1000+.01) is None
        publish_event(status.parent, dict(session_id='skin-test', turn_id='t2', event='UserPromptSubmit'))
        publish_event(status.parent, dict(session_id='skin-test', turn_id='t2', event='PermissionRequest'))
        pet._poll_bridge(force=True)
        pet._resolve_visual()
        assert pet.current_key == 'question'
        assert clips['question'].frame(100, True) == len(clips['question'].frames)-1
        checks.append('Compaction selects packing; completion celebrates once; permission holds a Ho-chan pose')
        from leisure import Leisure
        rest = Leisure(0)
        rest.enter(0)
        assert rest.position(clips, 0)[0] == 'sleep_entry'
        entered = clips['sleep_entry'].total_duration/1000 + .1
        assert rest.position(clips, entered)[0] == 'sleep_body'
        rest.click(entered, wake=True)
        assert rest.position(clips, entered)[0] == 'wake'
        assert rest.position(clips, entered+clips['wake'].total_duration/1000+.1) is None
        assert rest.phase == 'awake'
        checks.append('Rest enters the no-weapon loop, then waves once on wake and returns to idle')
        rest.phase, rest.action_epoch = 'bowing', 0
        assert rest.position(clips, .1)[0] == 'bow'
        assert rest.position(clips, clips['bow'].total_duration/1000+.1) is None
        # Render the real composition function for every replacement state.
        for key in config['animations']:
            assert pet.compose(key, 0).size == (640, 640)
    make_preview(clips, config)
    report = dict(status='passed', checked_at=time.strftime('%Y-%m-%d %H:%M:%S'), checks=checks)
    (ROOT / 'build/verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
