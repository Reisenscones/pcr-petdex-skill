"""Prepare a bounded lookahead of drag frames without blocking mouse input."""
from collections import OrderedDict
import threading

from animation_clock import Frames
from drag_anchor import hand_lock_offset
from rendering import prepare_pixels


class DragRenderer:
    capacity = 4

    def __init__(self, frames):
        # The decoder caches belong to this worker, never to the GUI thread.
        self.frames = Frames(frames.root, frames.specs, frames.canvas_size)
        self.cache = OrderedDict()
        self.wanted = []
        self.condition = threading.Condition()
        self.stopped = False
        self.error = None
        self.thread = threading.Thread(target=self._run, name='HoChanDragRenderer', daemon=True)
        self.thread.start()

    def get(self, index, scale, mirrored):
        key = (index, scale, mirrored)
        with self.condition:
            result = self.cache.get(key)
            if result is not None:
                self.cache.move_to_end(key)
            return result

    def request(self, index, scale, mirrored, seed=None):
        keys = [((index+i) % len(self.frames), scale, mirrored) for i in range(self.capacity)]
        with self.condition:
            self.wanted = keys
            for key in list(self.cache):
                if key not in keys:
                    del self.cache[key]
            if seed is not None:
                self.cache[keys[0]] = seed
            self.condition.notify()

    def clear(self):
        with self.condition:
            self.wanted = []
            self.cache.clear()

    def close(self):
        with self.condition:
            self.stopped = True
            self.wanted = []
            self.cache.clear()
            self.condition.notify()
        self.thread.join(timeout=.2)

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped or any(key not in self.cache for key in self.wanted))
                if self.stopped:
                    return
                key = next(key for key in self.wanted if key not in self.cache)
            try:
                canvas = self.frames.render(*key, offset=hand_lock_offset(self.frames, key[0], key[2]))
                pixels, size = prepare_pixels(canvas, 1)
                result = canvas, pixels, size
            except Exception as error:
                with self.condition:
                    self.error = error
                    self.wanted = []
                return
            with self.condition:
                if not self.stopped and key in self.wanted:
                    self.cache[key] = result
                    self.condition.notify_all()

