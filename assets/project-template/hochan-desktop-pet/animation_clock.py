"""Manifest clips and actor clocks. Selection never starts an animation."""
from __future__ import annotations
import bisect
import json
import math
import random
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from PIL import Image
from asset_storage import logical_frame


class Frames:
    # Images are decoded on demand; logical frames may be derived from hires.
    def __init__(self, root, specs, canvas_size=(640, 640)):
        self.root, self.specs = root, specs
        self.canvas_size = tuple(canvas_size)
        self.cache = OrderedDict()
        self.hires_cache = OrderedDict()

    def __len__(self):
        return len(self.specs)

    def __getitem__(self, index):
        if index not in self.cache:
            spec = self.specs[index]
            if spec.get('file'):
                with Image.open(self.root / spec['file']) as image:
                    frame = image.convert('RGBA')
            else:
                source = self.hires_cache.get(index)
                if source is not None:
                    self.hires_cache.move_to_end(index)
                    frame = logical_frame(source, spec['hires'], self.canvas_size,
                                          spec.get('logical_corrections', ()))
                else:
                    # A logical-only consumer retains the small result, not a
                    # second cache of large source images for every idle clip.
                    with Image.open(self.root / spec['hires']['file']) as image:
                        frame = logical_frame(image.convert('RGBA'), spec['hires'], self.canvas_size,
                                              spec.get('logical_corrections', ()))
            if frame.size != self.canvas_size:
                if frame.width > self.canvas_size[0] or frame.height > self.canvas_size[1]:
                    raise ValueError('Frame exceeds the rendering canvas')
                padded = Image.new('RGBA', self.canvas_size)
                padded.paste(frame, (0, 0))
                frame = padded
            self.cache[index] = frame
        self.cache.move_to_end(index)
        while len(self.cache) > 8:
            self.cache.popitem(last=False)
        return self.cache[index]

    def _hires(self, index):
        if index not in self.hires_cache:
            with Image.open(self.root / self.specs[index]['hires']['file']) as image:
                self.hires_cache[index] = image.convert('RGBA')
        self.hires_cache.move_to_end(index)
        while len(self.hires_cache) > 8:
            self.hires_cache.popitem(last=False)
        return self.hires_cache[index]

    def render(self, index, scale=1, mirrored=False, offset=(0, 0)):
        """Render artwork at physical resolution; metadata stays in 640px units."""
        sprite, origin, size = self.render_sprite(index, scale, mirrored, offset)
        canvas = Image.new('RGBA', size)
        if sprite is not None:
            canvas.alpha_composite(sprite, origin)
        return canvas

    def render_sprite(self, index, scale=1, mirrored=False, offset=(0, 0)):
        """Prepare only occupied pixels, keeping their physical canvas origin."""
        size = tuple(round(value*scale) for value in self.canvas_size)
        high = self.specs[index].get('hires') if scale > 1 else None
        if high:
            sprite = self._hires(index)
            x, y = high['origin']
            width, height = (v/high['scale'] for v in sprite.size)
            source_scale = high['scale']
        else:
            # Legacy/custom packs remain supported. Crop before resampling so
            # transparent margins do not consume the animation frame budget.
            frame = self[index]
            box = frame.getchannel('A').getbbox()
            if not box:
                return None, (0, 0), size
            x, y = max(0, box[0]-3), max(0, box[1]-3)
            right, bottom = min(frame.width, box[2]+3), min(frame.height, box[3]+3)
            sprite = frame.crop((x, y, right, bottom))
            width, height = sprite.size
            source_scale = 1
        if mirrored:
            sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            x = 820-x-width  # Reflect around the skeleton root x=410.
        x, y = x+offset[0], y+offset[1]
        # Anchor resampling to the global canvas grid. Rounding a moving crop's
        # origin and resizing its entire width would shift the sampling phase
        # between animation frames at fractional DPI/size combinations.
        left, top = math.ceil(x*scale), math.ceil(y*scale)
        right, bottom = math.floor((x+width)*scale), math.floor((y+height)*scale)
        target = (right-left, bottom-top)
        source_box = ((left/scale-x)*source_scale, (top/scale-y)*source_scale,
                      (right/scale-x)*source_scale, (bottom/scale-y)*source_scale)
        if sprite.size != target or source_box != (0, 0, *sprite.size):
            sprite = sprite.convert('RGBa').resize(target, Image.Resampling.LANCZOS, box=source_box).convert('RGBA')
        return sprite, (left, top), size


class Clip:
    def __init__(self, root, key, spec, canvas_size=(640, 640)):
        self.key, self.label, self.source = key, spec['label'], root
        self.alias_of = spec.get('alias_of')
        self.loop = spec.get('loop', True)
        self.frames = Frames(root, spec['frames'], canvas_size)
        self.durations = [f['duration_ms'] for f in spec['frames']]
        self.source_indices = list(range(len(self.frames)))
        self.loop_start = spec.get('loop_start', 0)
        self.ends = []
        total = 0
        for duration in self.durations:
            if duration <= 0:
                raise ValueError('Nonpositive frame duration')
            total += duration
            self.ends.append(total)
        self.total_duration = total
        self.sample_ends = self.ends
        if spec.get('timing') == 'uniform_segments':
            # Integer duration_ms remains interoperable, while native 60 Hz
            # sampling must not alternate between 16/17 ms frame boundaries.
            # Each source segment retains its exact overall duration.
            self.sample_ends = []
            start = 0
            for segment in spec['segments']:
                count, duration = segment['frame_count'], segment['duration_ms']
                self.sample_ends.extend(start+duration*(i+1)/count for i in range(count))
                start += duration
            if len(self.sample_ends) != len(self.frames) or start != total:
                raise ValueError('Uniform frame segments do not match the clip')

    def frame(self, seconds, hold=False):
        ms = max(0, seconds * 1000)
        if hold:
            ms = min(ms, self.total_duration - .001)
        elif ms >= self.total_duration:
            intro = sum(self.durations[:self.loop_start])
            ms = intro + (ms - intro) % (self.total_duration - intro)
        return min(len(self.frames)-1, bisect.bisect_right(self.sample_ends, ms))


def load_manifest(root: Path):
    data = json.loads((root / 'animation-manifest.json').read_text(encoding='utf-8'))
    if data['format_version'] not in (1, 2) or data['window_size'] != 640:
        raise ValueError('Unsupported animation manifest')
    canvas_size = data.get('render_size', (640, 640))
    if (not isinstance(canvas_size, (list, tuple)) or len(canvas_size) != 2
            or any(type(v) is not int for v in canvas_size) or canvas_size[0] != 640 or not 640 <= canvas_size[1] <= 1280):
        raise ValueError('Unsupported rendering canvas')
    return {key: Clip(root, key, spec, canvas_size) for key, spec in data['animations'].items()}


def packing_keys(clips):
    return sorted(key for key, clip in clips.items() if key.startswith('packing_') and not clip.alias_of)


@dataclass
class Track:
    turn: str
    state: str
    epoch: float
    carried: dict = field(default_factory=dict)
    packing: list = field(default_factory=list)


class AnimationClock:
    def __init__(self, clips, rng=None):
        self.clips, self.rng = clips, rng or random.Random()
        self.tracks = {}

    def update(self, actor, turn, state, now, age=0):
        changed = now - max(0, age)
        track = self.tracks.get(actor)
        if track is None or track.turn != turn:
            self.tracks[actor] = Track(turn, state, changed)
        elif state != track.state:
            transition = max(track.epoch, min(now, changed))
            track.carried[track.state] = track.carried.get(track.state, 0) + transition-track.epoch
            track.state, track.epoch = state, transition

    def position(self, actor, now):
        track = self.tracks.get(actor)
        if track is None:
            return None
        elapsed = track.carried.get(track.state, 0) + max(0, now-track.epoch)
        key, local = track.state, elapsed
        if key == 'packing':
            keys = packing_keys(self.clips)
            if not track.packing:
                track.packing.append((self.rng.choice(keys), 0))
            while elapsed >= track.packing[-1][1] + self.clips[track.packing[-1][0]].total_duration/1000:
                last, start = track.packing[-1]
                track.packing.append((self.rng.choice(keys), start+self.clips[last].total_duration/1000))
            key, start = track.packing[-1]
            local = elapsed-start
        if key == 'jump' and elapsed >= self.clips[key].total_duration/1000:
            return None
        return key, self.clips[key].frame(local, hold=key in ('jump','question'))
