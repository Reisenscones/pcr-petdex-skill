"""Worker-owned image decoders and a byte-bounded cache of presentation pixels."""
from collections import OrderedDict
from dataclasses import dataclass
import threading

from PIL import Image

from animation_clock import Frames
from drag_anchor import hand_lock_offset
from rendering import prepare_pixels


@dataclass(frozen=True)
class PreparedFrame:
    sprite: Image.Image | None
    pixels: bytes
    origin: tuple
    size: tuple
    canvas_size: tuple

    @property
    def byte_size(self):
        return len(self.pixels) * 2  # RGBA crop plus immutable premultiplied BGRA.

    def canvas(self):
        image = Image.new('RGBA', self.canvas_size)
        if self.sprite is not None:
            image.alpha_composite(self.sprite, self.origin)
        return image

    @classmethod
    def from_canvas(cls, canvas):
        box = canvas.getbbox()
        if not box:
            return cls(None, b'', (0, 0), (0, 0), canvas.size)
        sprite = canvas.crop(box)
        pixels, size = prepare_pixels(sprite, 1)
        return cls(sprite, pixels, box[:2], size, canvas.size)


class FrameRenderer:
    lookahead = 6

    def __init__(self, max_bytes=128*1024*1024):
        self.max_bytes = max_bytes
        self.cache = OrderedDict()
        self.bytes_used = 0
        self.variant = None
        self.wanted = []
        self.frames = None
        self.condition = threading.Condition()
        self.stopped = False
        self.error = None
        self.thread = threading.Thread(target=self._run, name='HoChanFrameRenderer', daemon=True)
        self.thread.start()

    @staticmethod
    def identity(frames, scale, mirrored, locked):
        return (frames.root, id(frames.specs), scale, mirrored, locked)

    def request(self, frames, index, scale, mirrored=False, locked=False):
        variant = self.identity(frames, scale, mirrored, locked)
        with self.condition:
            if self.variant != variant:
                self.variant = variant
                # Only this worker uses the decoder. Requests publish a new
                # instance without modifying the decoder currently in flight.
                self.frames = Frames(frames.root, frames.specs, frames.canvas_size)
                self.cache.clear()
                self.bytes_used = 0
                self.error = None
            self.wanted = [(index+i) % len(frames) for i in range(min(self.lookahead, len(frames)))]
            self.condition.notify()
            result = self.cache.get(index)
            if result is not None:
                self.cache.move_to_end(index)
            return variant, result

    def clear(self):
        with self.condition:
            self.variant = None
            self.frames = None
            self.wanted = []
            self.cache.clear()
            self.bytes_used = 0

    def close(self):
        with self.condition:
            self.stopped = True
            self.wanted = []
            self.cache.clear()
            self.bytes_used = 0
            self.condition.notify()
        self.thread.join(timeout=1)

    @staticmethod
    def prepare(frames, index, scale, mirrored=False, locked=False):
        offset = hand_lock_offset(frames, index, mirrored) if locked else (0, 0)
        sprite, origin, canvas_size = frames.render_sprite(index, scale, mirrored, offset)
        if sprite is None:
            return PreparedFrame(None, b'', origin, (0, 0), canvas_size)
        pixels, size = prepare_pixels(sprite, 1)
        return PreparedFrame(sprite, pixels, origin, size, canvas_size)

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped or any(i not in self.cache for i in self.wanted))
                if self.stopped:
                    return
                index = next(i for i in self.wanted if i not in self.cache)
                variant, frames = self.variant, self.frames
            try:
                result = self.prepare(frames, index, *variant[2:])
            except Exception as error:
                with self.condition:
                    if self.variant == variant:
                        self.error = error
                        self.wanted = []
                continue
            with self.condition:
                if self.stopped or self.variant != variant:
                    continue
                # Never allow a single unusually large custom frame to exceed
                # the cache budget; leave it for the synchronous fallback.
                if result.byte_size > self.max_bytes:
                    self.error = ValueError('Prepared frame exceeds cache budget')
                    self.wanted = []
                    continue
                self.cache[index] = result
                self.bytes_used += result.byte_size
                while self.bytes_used > self.max_bytes:
                    old, value = self.cache.popitem(last=False)
                    self.bytes_used -= value.byte_size
                    # Insufficient room for the lookahead must not cause an
                    # endless decode/evict loop while the GUI is idle.
                    if old in self.wanted:
                        self.wanted.remove(old)
                self.condition.notify_all()
