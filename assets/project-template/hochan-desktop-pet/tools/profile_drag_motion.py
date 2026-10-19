"""Measure moving-pointer responsiveness in an isolated native window."""
import argparse
import ctypes
import json
from pathlib import Path
import statistics
import sys
import threading
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hochan_pet
import pcr_pet as win
from codex_bridge import atomic_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='current')
    args = parser.parse_args()
    state = ROOT / 'build' / ('profile-drag-' + uuid.uuid4().hex[:8])
    atomic_json(state / 'pet-settings.json', dict(size_percent=150))
    renders, moves, failures = [], [], []
    stop = threading.Event()
    started = [None]
    frame_count = [0]
    base = hochan_pet.HoChanPet

    def cursor(pointer):
        elapsed = max(0, time.perf_counter()-(started[0] or time.perf_counter()))
        point = ctypes.cast(pointer, ctypes.POINTER(win.POINT)).contents
        point.x, point.y = round(900+180*min(elapsed, 4)), 700
        return True

    class Probe(base):
        def _wndproc(self, hwnd, message, wparam, lparam):
            try:
                return super()._wndproc(hwnd, message, wparam, lparam)
            except Exception as error:
                failures.append(error)
                win.user32.DestroyWindow(hwnd)
                return 0

        def _render_current(self):
            frame_count[0] = len(self.animations['left'].frames)
            began = time.perf_counter()
            super()._render_current()
            ended = time.perf_counter()
            if self.dragging:
                renders.append((ended, (ended-began)*1000, self.frame_index))
                moves.append(ended)

        def _align_drag_hand(self):
            before = self._window_rect(self.hwnd)
            super()._align_drag_hand()
            if self.dragging and self._window_rect(self.hwnd) != before:
                moves.append(time.perf_counter())

        def _advance(self):
            if started[0] is None:
                self._handle_left_button_down()
                started[0] = time.perf_counter()
                def send():
                    while not stop.wait(.008):
                        win.user32.PostMessageW(self.hwnd, win.WM_MOUSEMOVE, win.MK_LBUTTON, 0)
                self.sender = threading.Thread(target=send, daemon=True)
                self.sender.start()
            super()._advance()
            if time.perf_counter()-started[0] > 4.5:
                stop.set()
                win.user32.DestroyWindow(self.hwnd)

    hochan_pet.HoChanPet = Probe
    sys.argv = [sys.argv[0], '--status-file', str(state / 'codex-status.json'), '--no-codex-observer']
    try:
        with patch.object(win.user32, 'GetCursorPos', cursor), \
             patch.object(win.user32, 'SetCapture', lambda _: 0), \
             patch.object(win.user32, 'ReleaseCapture', lambda: True):
            hochan_pet.main()
    finally:
        stop.set()
    if failures:
        raise failures[0]
    warmed = [(t, ms, index) for t, ms, index in renders if .4 < t-started[0] < 3.8]
    moved = [t for t in moves if .4 < t-started[0] < 3.8]
    def summary(values):
        return dict(median=round(statistics.median(values), 3),
                    p95=round(sorted(values)[int(len(values)*.95)], 3), max=round(max(values), 3))
    result = dict(label=args.label, size_percent=150,
                  render_ms=summary([ms for _, ms, _ in warmed]),
                  render_interval_ms=summary([(b[0]-a[0])*1000 for a, b in zip(warmed, warmed[1:])]),
                  window_move_interval_ms=summary([(b-a)*1000 for a, b in zip(moved, moved[1:])]),
                  renders_per_second=round((len(warmed)-1)/(warmed[-1][0]-warmed[0][0]), 2),
                  unique_source_frames=len({index for _, _, index in warmed}),
                  repeated_frame_renders=sum(a[2] == b[2] for a, b in zip(warmed, warmed[1:])),
                  source_frames_skipped=sum(max(0, (b[2]-a[2]) % frame_count[0]-1) for a, b in zip(warmed, warmed[1:])),
                  real_cursor_untouched=True)
    (ROOT / 'build' / ('drag-motion-' + args.label + '.json')).write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
