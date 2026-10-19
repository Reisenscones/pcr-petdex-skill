"""Verify palm tracking and actual window movement without moving the real cursor."""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import sys
import time
import uuid
from unittest.mock import patch
from PIL import ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from animation_clock import load_manifest
from drag_anchor import DragFacing, hand_anchor, hand_lock_offset, window_at_hand, visible_frame_center
from context_menu import SIZE_OPTIONS
from codex_bridge import atomic_json, publish_event
import hochan_pet
import pcr_pet as win


def main():
    for scale in (.75, 1, 1.5, 2.25):
        for direction in (-1, 1):
            facing = DragFacing(100, direction)
            for step in range(1, 11):
                assert facing.update(100+step*direction*scale, step*.01, scale) == direction
            extreme = facing.extreme
            for step in range(20):
                # Repeated small movements and long pauses must not flip.
                x = extreme-direction*(3 if step % 2 else 6)*scale
                assert facing.update(x, .2+step*.02, scale) == direction
            x = extreme-direction*20*scale
            facing.update(extreme, .7, scale)
            assert facing.update(x, .8, scale) == direction
            assert facing.update(x, .84, scale) == direction
            assert facing.update(x, .87, scale) == -direction
            # Returning to the extreme cancels an unconfirmed reversal.
            assert facing.update(x+direction*20*scale, .9, scale) == -direction
            assert facing.update(x-direction*scale, .92, scale) == -direction
            assert facing.update(x+direction*20*scale, .94, scale) == -direction
            assert facing.update(x+direction*20*scale, 1.01, scale) == direction
    clips = load_manifest(ROOT / 'assets/characters/ho-chan/animation-resources')
    clip = clips['left']
    cases = 0
    for index in range(len(clip.frames)):
        image = clip.frames[index]
        x, y = hand_anchor(clip, index)
        assert image.getpixel((round(x), round(y)))[3] > 128, (index, x, y)
        for mirrored in (False, True):
            anchor = hand_anchor(clip, index, mirrored)
            for scale in (1, 1.25, 1.5, 2):
                cursor = (1000+index*3, 700-index*2)
                origin = window_at_hand(cursor, anchor, scale)
                assert max(abs(origin[i]+anchor[i]*scale-cursor[i]) for i in (0, 1)) <= .500001
                cases += 1
    state = ROOT / 'build' / ('drag-anchor-' + uuid.uuid4().hex[:8])
    state.mkdir(parents=True)
    cursor = [0, 0]
    positions, directions, errors, releases = set(), set(), [], []
    atomic_uploads, release_uploads = [], []
    failures = []
    base = hochan_pet.HoChanPet

    def fake_cursor(pointer):
        point = ctypes.cast(pointer, ctypes.POINTER(win.POINT)).contents
        point.x, point.y = cursor
        return True

    class ProbePet(base):
        began = None
        reversed = False
        released = False
        edge_case = False
        expected_key = 'idle'
        release_to_right = False
        returning = False
        cached_frame_checked = False

        def _wndproc(self, hwnd, message, wparam, lparam):
            try:
                return super()._wndproc(hwnd, message, wparam, lparam)
            except Exception as error:
                failures.append(error)
                win.user32.DestroyWindow(hwnd)
                return 0

        def _set_window_origin(self, hwnd, origin):
            assert not (self.dragging and self.mouse_down), 'Drag pointer movement bypassed the bitmap submission'
            assert self.drop_center_cursor is None or self.edge_transition, 'Moved a visible bitmap separately during drop'
            return super()._set_window_origin(hwnd, origin)

        def _render_layered_window(self, hwnd, pixels, width, height, origin=None):
            if hwnd == self.hwnd and self.drop_center_cursor is not None and not self.edge_transition:
                assert origin is not None, 'Uploaded restored action at the old drag position before centering'
                key, index = self.position
                center = visible_frame_center(self.animations[key].frames[index], self.drag_direction)
                error = max(abs(origin[i]+center[i]*self.scale-self.drop_center_cursor[i]) for i in (0, 1))
                assert error <= .500001, ('Misaligned intermediate drop frame', error)
                release_uploads.append((self.size_percent, self.drag_direction, key))
            return super()._render_layered_window(hwnd, pixels, width, height, origin=origin)

        def _begin_edge_hide_if_needed(self):
            if self.drop_center_cursor is not None:
                key, index = self.position
                center = visible_frame_center(self.animations[key].frames[index], self.drag_direction)
                rect = self._window_rect(self.hwnd)
                error = max(abs(rect[i]+center[i]*self.scale-self.drop_center_cursor[i]) for i in (0, 1))
                assert error <= .500001, error
                releases.append(dict(size_percent=self.size_percent, restored_action=key,
                                     edge_case=self.edge_case, direction=self.drag_direction,
                                     center_error_px=round(error, 6)))
            return super()._begin_edge_hide_if_needed()

        def _render_current(self):
            super()._render_current()
            if self.dragging and self.mouse_down:
                anchor = hand_anchor(self.animations['left'], 0, self.drag_direction < 0)
                frames = self.animations['left'].frames
                expected = frames.render(self.frame_index, self.scale, mirrored=self.drag_direction < 0,
                                         offset=hand_lock_offset(frames, self.frame_index, self.drag_direction < 0))
                diff = ImageChops.difference(self.last_canvas, expected)
                assert diff.getbbox() is None, (self.position, self.frame_index, self.last_canvas.size, diff.getbbox(), self.drag_direction)
                rect = self._window_rect(self.hwnd)
                error = max(abs(rect[i]+anchor[i]*self.scale-cursor[i]) for i in (0, 1))
                assert error <= .500001, error
                assert self.presented_drag == (self.frame_index, self.drag_mirrored, self.scale)
                atomic_uploads.append(self.presented_drag)
                errors.append(error)
                positions.add(rect[:2])
                directions.add(self.drag_direction)

        def _advance(self):
            now = time.monotonic()
            if self.began is None:
                self.began = now
                self._set_window_origin(self.hwnd, (200, 50))
                cursor[:] = [round(200+410*self.scale), round(50+470*self.scale)]
                self._handle_left_button_down()
                cursor[0] += 1
                self._handle_mouse_move(win.MK_LBUTTON)
                assert not self.dragging
                cursor[0] += 40
                cursor[1] += 10
                self._handle_mouse_move(win.MK_LBUTTON)
                assert self.dragging and self.current_key == 'left'
            elif now-self.began > .4 and not self.cached_frame_checked:
                # A newly selected frame must not change the anchor until its
                # bitmap is uploaded. Pointer events move the displayed frame.
                index, mirrored, scale = self.presented_drag
                saved_position, saved_index = self.position, self.frame_index
                self.frame_index = (index+10) % len(self.animations['left'].frames)
                self.position = ('left', self.frame_index)
                cursor[0] += 2
                self._handle_mouse_move(win.MK_LBUTTON)
                anchor = hand_anchor(self.animations['left'], 0, mirrored)
                rect = self._window_rect(self.hwnd)
                assert max(abs(rect[i]+anchor[i]*scale-cursor[i]) for i in (0, 1)) <= .500001
                self.position, self.frame_index = saved_position, saved_index
                self.cached_frame_checked = True
            elif now-self.began > .9 and not self.reversed:
                cursor[0] -= 80
                self._handle_mouse_move(win.MK_LBUTTON)
                self.reversed = True
            elif now-self.began > 1.6 and not self.returning:
                assert self.drag_direction == -1
                if self.release_to_right:
                    cursor[0] += 80
                    self._handle_mouse_move(win.MK_LBUTTON)
                if self.edge_case:
                    monitor = win.enumerate_monitor_infos()[0]
                    cursor[:] = [monitor.frame[2]-1, (monitor.work[1]+monitor.work[3])//2]
                    self._handle_mouse_move(win.MK_LBUTTON)
                self.returning = True
            elif now-self.began > 1.8 and not self.released:
                assert self.drag_direction == (1 if self.release_to_right or self.edge_case else -1)
                self._handle_left_button_up()
                assert not self.dragging and not self.mouse_down
                if self.edge_case:
                    assert self.edge_placement and self.edge_placement.edge == 'right'
                else:
                    assert self.current_key == self.expected_key
                self.released_origin = self._window_rect(self.hwnd)[:2]
                cursor[0] += 300
                self._handle_mouse_move(0)
                self.released = True
            super()._advance()
            if self.released and not self.edge_case:
                assert self._window_rect(self.hwnd)[:2] == self.released_origin
            if now-self.began > 2.6:
                if self.edge_case:
                    assert self.edge_transition is None and self.edge_placement
                    assert win.user32.IsWindowVisible(self.tail_hwnd)
                win.user32.DestroyWindow(self.hwnd)

    hochan_pet.HoChanPet = ProbePet
    # Substitute API inputs only inside this isolated process. No cursor warping
    # or actual mouse capture is performed on the user's desktop.
    with patch.object(win.user32, 'GetCursorPos', fake_cursor), \
         patch.object(win.user32, 'SetCapture', lambda _: 0), \
         patch.object(win.user32, 'ReleaseCapture', lambda: True):
        cases_to_run = ([(percent, 'idle') for percent in SIZE_OPTIONS]
                        + [(percent, 'right') for percent in SIZE_OPTIONS]
                        + [(125, 'working'), (100, 'edge')])
        for percent, kind in cases_to_run:
            case_state = state / f'{percent}-{kind}'
            atomic_json(case_state / 'pet-settings.json', dict(size_percent=percent))
            if kind == 'working':
                publish_event(case_state, dict(session_id='drop-test', turn_id='t1', event='UserPromptSubmit'))
                publish_event(case_state, dict(session_id='drop-test', turn_id='t1', event='PreToolUse'))
            ProbePet.edge_case = kind == 'edge'
            ProbePet.release_to_right = kind == 'right'
            ProbePet.expected_key = 'working' if kind == 'working' else 'idle'
            sys.argv = [sys.argv[0], '--status-file', str(case_state / 'codex-status.json'), '--no-codex-observer']
            hochan_pet.main()
            if failures:
                raise failures[0]
            unregister = win.user32.UnregisterClassW
            unregister.argtypes = [win.wintypes.LPCWSTR, win.wintypes.HINSTANCE]
            assert unregister(win.CLASS_NAME, win.kernel32.GetModuleHandleW(None))
    assert directions == {-1, 1}
    assert len(positions) > 5 and len(errors) > 30
    assert len(releases) == 10
    assert len(release_uploads) == len(releases), 'Drop must submit exactly one positioned frame'
    for percent in SIZE_OPTIONS:
        assert {record['direction'] for record in releases if record['size_percent'] == percent} == {-1, 1}
    result = dict(status='passed', anchor_cases=cases, native_render_checks=len(errors),
                  atomic_position_and_bitmap_uploads=len(atomic_uploads),
                  atomic_release_uploads=len(release_uploads),
                  max_physical_error_px=round(max(errors), 6), directions=sorted(directions),
                  release_cases=releases,
                  checks=['palm lies on visible hand in all frames', '100/125/150/200 percent DPI geometry',
                          'leftward movement mirrors the right-facing source; rightward movement keeps the source',
                          'drag threshold and both facing directions', 'stationary pointer tracks animated palm',
                          'direction reversals require distance and time; small repeated movements do not flip',
                          'all pointer movement submits the displayed bitmap and origin together',
                          'the first restored frame uses the final drop position in a single upload, with no intermediate movement',
                          'pointer events follow the displayed frame even when a different frame is selected',
                          'both drop directions preserve the current manual calibration at all four sizes',
                          'release restores the active tool animation and stops following the cursor',
                          'edge hide is checked after centering and still shows the edge portrait',
                          'real cursor was not moved or captured'])
    (ROOT / 'build/drag-anchor-verification.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
