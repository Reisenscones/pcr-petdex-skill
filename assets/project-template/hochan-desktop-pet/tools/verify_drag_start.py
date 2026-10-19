"""Check the first drag upload with cold animation caches and no real input."""
import ctypes
import json
from pathlib import Path
import sys
import threading
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from context_menu import SIZE_OPTIONS
from drag_anchor import hand_anchor
from frame_renderer import FrameRenderer
import hochan_pet
import pcr_pet as win


def main():
    state = ROOT / 'build' / ('drag-start-' + uuid.uuid4().hex[:8])
    state.mkdir(parents=True)
    cursor, checks, failures = [0, 0], [], []
    prepare, request = FrameRenderer.prepare, FrameRenderer.request

    def fake_cursor(pointer):
        point = ctypes.cast(pointer, ctypes.POINTER(win.POINT)).contents
        point.x, point.y = cursor
        return True

    def no_gui_prepare(*args, **kwargs):
        assert threading.current_thread() is not threading.main_thread(), 'First drag frame decoded on the mouse event instead of being ready'
        return prepare(*args, **kwargs)

    def cold_request(*args, **kwargs):
        variant, _ = request(*args, **kwargs)
        return variant, None

    class Probe(hochan_pet.HoChanPet):
        checking_entry = False
        entry_uploads = 0

        def _wndproc(self, hwnd, message, wparam, lparam):
            try:
                return super()._wndproc(hwnd, message, wparam, lparam)
            except Exception as error:
                failures.append(error)
                win.user32.DestroyWindow(hwnd)
                return 0

        def _set_window_origin(self, hwnd, origin):
            assert not self.checking_entry, 'Moved a visible image before the first drag upload'
            return super()._set_window_origin(hwnd, origin)

        def _render_layered_window(self, hwnd, pixels, width, height, origin=None):
            if self.checking_entry and hwnd == self.hwnd:
                assert self.current_key == 'left' and self.frame_index == 0
                assert pixels.canvas().tobytes() == self.expected_entry
                anchor = hand_anchor(self.animations['left'], 0, self.drag_mirrored)
                assert origin is not None
                assert max(abs(origin[i]+anchor[i]*self.scale-cursor[i]) for i in (0, 1)) <= .500001
                self.entry_uploads += 1
            return super()._render_layered_window(hwnd, pixels, width, height, origin=origin)

        def _advance(self):
            for character in ('ho-chan', 'kyouka-gothic'):
                assert self._set_character(character)
                for percent in SIZE_OPTIONS:
                    self._set_size_percent(percent)
                    for direction in (-1, 1):
                        initial = ('idle', 'reading', 'working')[len(checks) % 3]
                        self._switch_visual(initial)
                        self._set_window_origin(self.hwnd, (100, 40))
                        cursor[:] = [round(100+410*self.scale), round(40+470*self.scale)]
                        self._handle_left_button_down()
                        cursor[0] += direction
                        self._handle_mouse_move(win.MK_LBUTTON)
                        assert not self.dragging
                        self.expected_entry = self.animations['left'].frames.render(0, self.scale, direction < 0).tobytes()
                        self.frame_renderer.clear()
                        self.entry_uploads = 0
                        self.checking_entry = True
                        try:
                            with patch.object(FrameRenderer, 'prepare', side_effect=no_gui_prepare), \
                                    patch.object(FrameRenderer, 'request', new=cold_request):
                                cursor[0] += direction*40
                                self._handle_mouse_move(win.MK_LBUTTON)
                        finally:
                            self.checking_entry = False
                        assert self.dragging and self.entry_uploads == 1
                        checks.append(dict(character=character, size_percent=percent,
                                           direction=direction, previous_action=initial))
                        self._handle_left_button_up()
            win.user32.DestroyWindow(self.hwnd)

    with patch.object(hochan_pet, 'HoChanPet', Probe), \
            patch.object(sys, 'argv', ['verify-drag-start', '--status-file', str(state / 'codex-status.json'), '--no-codex-observer']), \
            patch.object(win.user32, 'GetCursorPos', fake_cursor), \
            patch.object(win.user32, 'SetCapture', lambda _: 0), \
            patch.object(win.user32, 'ReleaseCapture', lambda: True):
        hochan_pet.main()
    if failures:
        raise failures[0]
    assert len(checks) == 16
    report = dict(status='passed', first_frame_cases=checks, real_cursor_untouched=True)
    (ROOT / 'build/drag-start-verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
