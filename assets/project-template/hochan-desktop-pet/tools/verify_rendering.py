"""Check pixel parity, DPI alpha and bounded render-message scheduling."""
from pathlib import Path
import random
import sys
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pcr_pet as win
from animation_clock import load_manifest
from rendering import prepare_pixels, PresentationClock


def main():
    rng = random.Random(42)
    random_image = Image.frombytes('RGBA', (47, 31), rng.randbytes(47*31*4))
    pixels, size = prepare_pixels(random_image, 1)
    assert size == random_image.size
    assert pixels == win.premultiplied_bgra(random_image)
    clips = load_manifest(ROOT / 'assets/characters/ho-chan/animation-resources')
    checked = 0
    for key in ('idle', 'left', 'reading', 'working'):
        clip = clips[key]
        for index in (0, len(clip.frames)//2, len(clip.frames)-1):
            image = clip.frames[index]
            assert prepare_pixels(image, 1)[0] == win.premultiplied_bgra(image)
            for scale in (.75, 1, 1.125, 1.25, 1.5, 1.875, 2, 2.25, 3):
                pixels, size = prepare_pixels(image, scale)
                assert size == (round(640*scale), round(640*scale))
                alpha = pixels[3::4]
                expected_alpha = image.convert('RGBa').resize(size, Image.Resampling.LANCZOS).getchannel('a').tobytes()
                assert alpha == expected_alpha
                assert pixels[:4] == b'\x00\x00\x00\x00'
                checked += 1
    # Dimensions alone would also pass the blurry renderer: check that native
    # export pixels survive loading and main-window composition.
    import tempfile
    from PIL import ImageChops
    import numpy as np
    from hochan_pet import HoChanPet
    with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
        pet = HoChanPet(clips, ROOT,
                       Path(directory) / 'codex-status.json', observe=False)
        for key in ('idle', 'left', 'reading', 'working'):
            frame = clips[key].frames
            spec = frame.specs[0]['hires']
            with Image.open(frame.root / spec['file']) as opened:
                source = opened.convert('RGBA')
            native = pet.compose(key, 0, render_scale=spec['scale'])
            x, y = (v*spec['scale'] for v in spec['origin'])
            actual = native.crop((x, y, x+source.width, y+source.height))
            assert not any(channel.getbbox() for channel in ImageChops.difference(actual, source).split()), key
            for scale in (1.125, 1.5, 1.875, 2.25, 3):
                rendered = pet.compose(key, 0, render_scale=scale)
                assert rendered.size == (round(640*scale),)*2
                pixel_data, _ = prepare_pixels(rendered, 1)
                assert pixel_data == win.premultiplied_bgra(rendered)
                assert not any(channel.getbbox() for channel in ImageChops.difference(frame.hires_cache[0], source).split())
                if scale == 2.25:
                    # Moving crops must use the full canvas's fixed sample grid.
                    expected = native.convert('RGBa').resize(rendered.size, Image.Resampling.LANCZOS).tobytes('raw', 'BGRa')
                    delta = np.frombuffer(pixel_data, dtype=np.uint8).astype(np.int16)-np.frombuffer(expected, dtype=np.uint8)
                    assert abs(delta).max() <= 3, (key, abs(delta).max())
            low = frame[0].convert('RGBa').resize(native.size, Image.Resampling.BILINEAR).convert('RGBA')
            assert ImageChops.difference(native, low).getbbox() is not None
            assert len(frame.hires_cache) <= 8
            for index in range(10):
                frame.render(index, 1.5)
            assert len(frame.hires_cache) == 8 and 0 not in frame.hires_cache
        from animation_clock import Frames
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as legacy_directory:
            frame[0].save(Path(legacy_directory) / 'legacy.png')
            legacy = Frames(Path(legacy_directory), [dict(file='legacy.png')])
            for scale in (.75, 1, 2.25):
                assert legacy.render(0, scale, mirrored=True).size == (round(640*scale),)*2
    sent = []
    def post(*message):
        sent.append(message)
        return True
    clock = PresentationClock(123, post, fps=60)
    clock.start()
    try:
        time.sleep(.12)
        assert len(sent) == 1, 'The clock must not queue frames while the GUI is busy'
        clock.pending.clear()
        time.sleep(.08)
        assert len(sent) == 2
    finally:
        clock.stop()
    assert not clock.thread.is_alive()
    stopped_count = len(sent)
    time.sleep(.04)
    assert len(sent) == stopped_count
    print(f'Passed: native hires pixels, {checked} DPI/alpha cases, legacy packs, bounded caches, single pending frame, clean clock shutdown')


if __name__ == '__main__':
    main()
