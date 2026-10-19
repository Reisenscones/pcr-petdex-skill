"""Exercise every pet size in a real window without moving the user's mouse."""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import sys
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hochan_pet
import pcr_pet as win
from context_menu import SIZE_OPTIONS
from drag_anchor import hand_anchor


def main():
    state = ROOT / 'build' / ('size-' + uuid.uuid4().hex[:8])
    state.mkdir(parents=True)
    cursor = [-10000, -10000]
    records = []
    failures = []
    base = hochan_pet.HoChanPet

    def fake_cursor(pointer):
        point = ctypes.cast(pointer, ctypes.POINTER(win.POINT)).contents
        point.x, point.y = cursor
        return True

    class ProbePet(base):
        stage = 0
        next_stage = 0

        def _wndproc(self, hwnd, message, wparam, lparam):
            try:
                return super()._wndproc(hwnd, message, wparam, lparam)
            except Exception as error:
                failures.append(error)
                win.user32.DestroyWindow(hwnd)
                return 0

        def _advance(self):
            now = time.monotonic()
            if now >= self.next_stage and self.stage < len(SIZE_OPTIONS):
                percent = SIZE_OPTIONS[self.stage]
                self._handle_menu_command(300 + self.stage)
                rect = self._window_rect(self.hwnd)
                expected = round(640 * self.dpi_scale * percent / 100)
                assert (rect[2]-rect[0], rect[3]-rect[1]) == (expected, expected)
                assert abs(self.scale-self.dpi_scale*percent/100) < 1e-9
                saved = json.loads(self.settings_path.read_text(encoding='utf-8'))
                assert saved['size_percent'] == percent
                cursor[:] = [round(rect[0]+410*self.scale), round(rect[1]+530*self.scale)]
                point = self._cursor_window_position()
                assert max(abs(point[i]-target) for i, target in enumerate((410, 530))) <= 1
                anchor_errors = []
                self.dragging = self.mouse_down = True
                self.drag_start_cursor = (1200, 800)
                cursor[:] = [1200, 800]
                for direction in (-1, 1):
                    self.drag_direction = direction
                    for frame in (0, len(self.animations['left'].frames)//2):
                        self.position, self.frame_index = ('left', frame), frame
                        self._render_current()
                        displayed, mirrored, scale = self.presented_drag
                        assert mirrored == (direction < 0) and scale == self.scale
                        anchor = hand_anchor(self.animations['left'], 0, mirrored)
                        current = self._window_rect(self.hwnd)
                        error = max(abs(current[i]+anchor[i]*self.scale-cursor[i]) for i in (0, 1))
                        assert error <= .500001, (percent, direction, frame, error)
                        anchor_errors.append(error)
                self.dragging = self.mouse_down = False
                self.drag_start_cursor = None
                self.permission_request = {'summary': 'Isolated size verification'}
                self.permission_request_id = 'size-fixture'
                self._resolve_visual()
                self._render_current()
                for button in self.permission_buttons.values():
                    target = ((button[0]+button[2])//2, (button[1]+button[3])//2)
                    current = self._window_rect(self.hwnd)
                    cursor[:] = [round(current[i]+target[i]*self.scale) for i in (0, 1)]
                    assert self._point_in_rect(self._cursor_window_position(), button)
                self.permission_request = None
                self.permission_request_id = ''
                cursor[:] = [-10000, -10000]
                self._resolve_visual()
                self._write_heartbeat(force=True)
                heartbeat = json.loads(self.heartbeat_path.read_text(encoding='utf-8'))
                assert heartbeat['dpi_scale'] == self.dpi_scale
                assert heartbeat['size_percent'] == percent
                assert heartbeat['render_scale'] == self.scale
                records.append(dict(percent=percent, dpi_scale=self.dpi_scale, render_scale=self.scale,
                                    window_side=expected, max_hand_error_px=round(max(anchor_errors), 6)))
                self.stage += 1
                self.next_stage = time.monotonic() + .3
            super()._advance()
            if self.stage == len(SIZE_OPTIONS) and time.monotonic() >= self.next_stage:
                win.user32.DestroyWindow(self.hwnd)

    hochan_pet.HoChanPet = ProbePet
    sys.argv = [sys.argv[0], '--status-file', str(state / 'codex-status.json'), '--no-codex-observer']
    with patch.object(win.user32, 'GetCursorPos', fake_cursor):
        hochan_pet.main()
    if failures:
        raise failures[0]
    assert len(records) == 4
    report = dict(status='passed', native_sizes=records,
                  checks=['Native dimensions follow DPI times pet size at every setting',
                          'Mouse coordinate conversion and permission buttons match the scaled image',
                          'Animated right-hand tracking works in both directions at all four sizes',
                          'Persisted settings and heartbeat distinguish pet size from monitor DPI',
                          'Real mouse was not moved or captured'])
    (ROOT / 'build/size-verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
