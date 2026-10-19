"""Check worker lookahead, generation changes, bounded memory and shutdown."""
from pathlib import Path
import sys
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import drag_renderer


class Frames:
    def __init__(self, root, specs, canvas_size=(640, 704)):
        self.root, self.specs, self.canvas_size = root, specs, canvas_size

    def __len__(self):
        return len(self.specs)

    def render(self, *key, offset=(0, 0)):
        entered.set()
        assert resume.wait(2), 'Worker did not resume'
        return key


entered, resume = threading.Event(), threading.Event()


def main():
    prepared = threading.Event()
    def pixels(canvas, scale):
        prepared.set()
        return repr(canvas).encode(), (640, 640)
    with patch.object(drag_renderer, 'Frames', Frames), patch.object(drag_renderer, 'prepare_pixels', pixels):
        worker = drag_renderer.DragRenderer(Frames(ROOT, [dict(drag_anchor=(i, i)) for i in range(40)]))
        try:
            assert worker.frames.canvas_size == (640, 704)
            worker.request(0, 2.25, False, seed=('first', b'pixels', (1440, 1440)))
            assert entered.wait(1)
            # The worker is blocked in rendering; reads and invalidation stay
            # available on the GUI thread, and old work cannot overwrite a flip.
            assert worker.get(0, 2.25, False)[0] == 'first'
            worker.request(39, 1.125, True)
            resume.set()
            with worker.condition:
                assert worker.condition.wait_for(lambda: len(worker.cache) == 4, timeout=1)
                assert set(worker.cache) == {(index, 1.125, True) for index in (39, 0, 1, 2)}
                assert len(worker.cache) <= worker.capacity
            assert prepared.is_set()
            worker.clear()
            with worker.condition:
                assert not worker.wanted and not worker.cache
        finally:
            resume.set()
            worker.close()
        assert not worker.thread.is_alive()
    print('Passed: nonblocking cache access, mirror/scale invalidation, loop lookahead, four-frame capacity, clear and shutdown')


if __name__ == '__main__':
    main()
