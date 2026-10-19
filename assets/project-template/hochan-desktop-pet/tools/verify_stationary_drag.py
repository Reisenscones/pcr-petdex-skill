"""Verify a fixed pointer keeps the native window still across complete loops."""
import ctypes
import json
from pathlib import Path
import sys
import uuid
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from animation_clock import Frames
from context_menu import SIZE_OPTIONS
from drag_anchor import hand_anchor, hand_lock_offset
from drag_renderer import DragRenderer
import hochan_pet
import pcr_pet as win


def main():
    state = ROOT / 'build' / ('profile-stationary-' + uuid.uuid4().hex[:8])
    state.mkdir(parents=True)
    specs = []
    for index, shift in enumerate((0, 1, -2)):
        image = Image.new('RGBA', (640, 640))
        ImageDraw.Draw(image).ellipse((420+shift, 310-shift, 450+shift, 340-shift), fill=(200, 70, 90, 255))
        image.save(state / f'{index}.png')
        specs.append(dict(file=f'{index}.png', drag_anchor=(435.25+shift, 325.125-shift)))
    frames = Frames(state, specs)
    pixel_checks = 0
    for scale in (1.125, 1.5, 1.875, 2.25):
        for mirrored in (False, True):
            reference = frames.render(0, scale, mirrored)
            for index in (1, 2):
                fixed = frames.render(index, scale, mirrored, offset=hand_lock_offset(frames, index, mirrored))
                assert all(channel.getbbox() is None for channel in ImageChops.difference(reference, fixed).split())
                pixel_checks += 1
    cursor = (1200, 800)
    checks, failures = [], []
    base = hochan_pet.HoChanPet

    def fixed_cursor(pointer):
        point = ctypes.cast(pointer, ctypes.POINTER(win.POINT)).contents
        point.x, point.y = cursor
        return True

    class Probe(base):
        def _wndproc(self, hwnd, message, wparam, lparam):
            try:
                return super()._wndproc(hwnd, message, wparam, lparam)
            except Exception as error:
                failures.append(error)
                win.user32.DestroyWindow(hwnd)
                return 0

        def _advance(self):
            self.dragging = self.mouse_down = True
            self.drag_start_cursor = cursor
            self.selector_visible = False
            clip = self.animations['left']
            for percent in SIZE_OPTIONS:
                self.size_percent = percent
                self.scale = self.dpi_scale*percent/100
                for direction in (-1, 1):
                    self.drag_direction = direction
                    origins, error = set(), 0
                    for index in range(len(clip.frames)):
                        # Await the test frame only in this isolated harness;
                        # production never waits for background preparation.
                        self.frame_renderer.request(clip.frames, index, self.scale, direction < 0, True)
                        with self.frame_renderer.condition:
                            assert self.frame_renderer.condition.wait_for(
                                lambda: index in self.frame_renderer.cache
                                    or self.frame_renderer.error is not None, timeout=2)
                        assert self.frame_renderer.error is None
                        self.position, self.frame_index = ('left', index), index
                        self._render_current()
                        assert self.frame_index == index
                        rect = self._window_rect(self.hwnd)
                        origins.add(rect[:2])
                        anchor = hand_anchor(clip, 0, direction < 0)
                        error = max(error, *(abs(rect[i]+anchor[i]*self.scale-cursor[i]) for i in (0, 1)))
                    assert len(origins) == 1, (percent, direction, origins)
                    assert error <= .500001
                    checks.append(dict(size_percent=percent, direction=direction, frames=len(clip.frames),
                                       distinct_window_origins=len(origins), max_hand_error_px=round(error, 6)))
            win.user32.DestroyWindow(self.hwnd)

    hochan_pet.HoChanPet = Probe
    sys.argv = [sys.argv[0], '--status-file', str(state / 'codex-status.json'), '--no-codex-observer']
    with patch.object(win.user32, 'GetCursorPos', fixed_cursor):
        hochan_pet.main()
    if failures:
        raise failures[0]
    assert len(checks) == 8
    result = dict(status='passed', translated_pixel_checks=pixel_checks, stationary_native_cases=checks,
                  real_cursor_untouched=True)
    (ROOT / 'build/stationary-drag-verification.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
