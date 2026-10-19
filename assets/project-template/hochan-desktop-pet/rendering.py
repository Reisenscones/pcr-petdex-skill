"""Fast premultiplied output and a presentation clock independent of render cost."""
from __future__ import annotations

import threading
import time

from PIL import Image


WM_PRESENT = 0x8001


def prepare_pixels(canvas: Image.Image, scale: float):
    """Premultiply once, resize in premultiplied space, encode BGRA in Pillow C."""
    image = canvas.convert('RGBa')
    size = (round(canvas.width * scale), round(canvas.height * scale))
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return image.tobytes('raw', 'BGRa'), size


class PresentationClock:
    """Post at absolute deadlines; keep at most one pending GUI render request."""
    def __init__(self, hwnd, post_message, fps=60):
        self.hwnd, self.post_message = hwnd, post_message
        self.interval = 1 / fps
        self.pending = threading.Event()
        self.stopped = threading.Event()
        self.target_time = None
        self.thread = threading.Thread(target=self._run, name='HoChanPresentationClock', daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(timeout=.2)

    def _run(self):
        deadline = time.perf_counter() + self.interval
        while not self.stopped.is_set():
            delay = deadline - time.perf_counter()
            if delay > 0:
                # Python uses a high-resolution waitable timer on Windows;
                # Event.wait can quantize 60 Hz deadlines to the system tick.
                time.sleep(delay)
            if self.stopped.is_set():
                return
            if not self.pending.is_set():
                self.target_time = deadline
                self.pending.set()
                if not self.post_message(self.hwnd, WM_PRESENT, 0, 0):
                    self.pending.clear()
            deadline += self.interval
            now = time.perf_counter()
            if deadline <= now:
                # Never build up a queue of late frames after a long UI action.
                deadline = now + self.interval
