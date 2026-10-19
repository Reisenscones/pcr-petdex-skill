"""Recover native pet/tail Z order in isolated state without changing focus."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hochan_pet
import pcr_pet as win

user = win.user32
user.GetWindow.argtypes = [w.HWND, w.UINT]
user.GetWindow.restype = w.HWND
user.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
user.GetWindowLongW.restype = w.LONG
user.GetForegroundWindow.restype = w.HWND
user.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
user.FindWindowExW.restype = w.HWND
user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
user.GetWindowThreadProcessId.restype = w.DWORD
user.EndMenu.restype = w.BOOL
NO_CHANGE = win.SWP_NOMOVE | win.SWP_NOSIZE | win.SWP_NOACTIVATE


def above(first, second):
    hwnd = user.GetWindow(first, 2)  # GW_HWNDNEXT: windows below first.
    while hwnd:
        if hwnd == second:
            return True
        hwnd = user.GetWindow(hwnd, 2)
    return False


def topmost(hwnd):
    return bool(user.GetWindowLongW(hwnd, -20) & win.WS_EX_TOPMOST)


def require(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def main():
    checks, failures = [], []
    ROOT.joinpath('build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='topmost-', dir=ROOT / 'build') as temp:
        class Probe(hochan_pet.HoChanPet):
            scenario = None
            next_step = 0
            blocker = None
            checking_menu = False

            def _wndproc(self, hwnd, message, wparam, lparam):
                try:
                    if message == win.WM_TIMER and wparam == 90:
                        self.inspect_menu()
                        return 0
                    return super()._wndproc(hwnd, message, wparam, lparam)
                except Exception as error:
                    failures.append(error)
                    if self.checking_menu:
                        user.EndMenu()
                    else:
                        user.DestroyWindow(self.hwnd)
                    return 0

            def _advance(self):
                super()._advance()
                if self.checking_menu:
                    return
                if self.scenario is None:
                    self.scenario = self.exercise()
                if time.monotonic() < self.next_step:
                    return
                try:
                    delay = next(self.scenario)
                    self.next_step = time.monotonic() + delay
                except StopIteration:
                    user.DestroyWindow(self.hwnd)

            def inspect_menu(self):
                elapsed = time.monotonic() - self.menu_started
                if elapsed < 1.2:
                    return
                windows = []
                hwnd = None
                thread = user.GetWindowThreadProcessId(self.hwnd, None)
                while hwnd := user.FindWindowExW(None, hwnd, '#32768', None):
                    if user.GetWindowThreadProcessId(hwnd, None) == thread and user.IsWindowVisible(hwnd):
                        windows.append(hwnd)
                assert windows, 'Native popup never became visible'
                for menu in windows:
                    for pet_window in (self.hwnd, self.tail_hwnd):
                        if user.IsWindowVisible(pet_window):
                            assert above(menu, pet_window), 'Pet covered its native context menu'
                if not self.submenu_requested:
                    self.submenu_requested = True
                    for key in (0x28, 0x27):  # Down selects Settings; Right opens it.
                        user.PostMessageW(self.menu_owner, 0x0100, key, 0)
                        user.PostMessageW(self.menu_owner, 0x0101, key, 0)
                if elapsed >= 3.0:
                    assert len(windows) >= 2, 'Settings submenu never became visible'
                    self.menu_verified = True
                    user.EndMenu()

            def exercise_native_menu(self, owner):
                self.checking_menu = True
                self.menu_owner = owner
                self.menu_started = time.monotonic()
                self.submenu_requested = self.menu_verified = False
                # Place the popup over the pet without moving the real mouse.
                rect = self._window_rect(owner)
                point = (rect[0]+round(410*self.scale), rect[1]+round(500*self.scale)) if owner == self.hwnd else (rect[2]-5, rect[1]+5)

                def cursor(pointer):
                    value = ctypes.cast(pointer, ctypes.POINTER(win.POINT)).contents
                    value.x, value.y = point
                    return True

                require(user.SetTimer(self.hwnd, 90, 100, None))
                try:
                    with patch.object(user, 'GetCursorPos', cursor):
                        self._show_menu(owner)
                    if failures:
                        raise failures[-1]
                    assert self.menu_verified, 'Menu closed before validation'
                    assert self.menu_loop_depth == 0
                finally:
                    user.KillTimer(self.hwnd, 90)
                    self.checking_menu = False

            def exercise(self):
                rect = self._window_rect(self.hwnd)
                self.blocker = require(user.CreateWindowExW(
                    win.WS_EX_TOOLWINDOW | win.WS_EX_NOACTIVATE,
                    'STATIC', 'Topmost regression fixture', win.WS_POPUP,
                    rect[0], rect[1], rect[2]-rect[0], rect[3]-rect[1],
                    None, None, win.kernel32.GetModuleHandleW(None), None))
                try:
                    require(user.SetWindowPos(self.blocker, None, 0, 0, 0, 0,
                                              NO_CHANGE | win.SWP_SHOWWINDOW))
                    assert topmost(self.hwnd) and above(self.hwnd, self.blocker)
                    checks.append('Pet stays above an ordinary window')

                    for presentation in ('pet', 'tail'):
                        if presentation == 'tail':
                            monitor = win.enumerate_monitor_infos()[0]
                            bounds = self._current_pet_local_bounds()
                            self._set_window_origin(self.hwnd,
                                (monitor.frame[0]-bounds[0]-2,
                                 (monitor.work[1]+monitor.work[3])//2-bounds[1]))
                            assert self._begin_edge_hide_if_needed()
                            yield 1.0
                            assert not user.IsWindowVisible(self.hwnd)
                            assert user.IsWindowVisible(self.tail_hwnd)
                        target = self.hwnd if presentation == 'pet' else self.tail_hwnd
                        for disturbance in ('demoted', 'covered'):
                            if disturbance == 'demoted':
                                require(user.SetWindowPos(target, ctypes.c_void_p(-2),
                                                          0, 0, 0, 0, NO_CHANGE))
                                assert not topmost(target)
                            else:
                                require(user.SetWindowPos(self.blocker, win.HWND_TOPMOST,
                                                          0, 0, 0, 0, NO_CHANGE))
                                assert not above(target, self.blocker)
                            original_rect = self._window_rect(target)
                            foreground = user.GetForegroundWindow()
                            yield 1.6  # Let the real maintenance timer recover it.
                            assert topmost(target), (presentation, disturbance, 'lost topmost')
                            assert above(target, self.blocker), (presentation, disturbance, 'covered')
                            assert self._window_rect(target) == original_rect
                            assert user.GetForegroundWindow() == foreground, 'Recovery stole focus'
                            if presentation == 'tail':
                                assert not user.IsWindowVisible(self.hwnd)
                            else:
                                assert not user.IsWindowVisible(self.tail_hwnd)
                            checks.append(f'{presentation}: {disturbance} window recovers without moving, resizing or activating')

                        # Menu-loop notifications must work for both HWNDs.
                        user.SendMessageW(target, win.WM_ENTERMENULOOP, 1, 0)
                        require(user.SetWindowPos(self.blocker, win.HWND_TOPMOST,
                                                  0, 0, 0, 0, NO_CHANGE))
                        yield 1.6
                        assert not above(target, self.blocker), 'Maintenance disturbed an open menu'
                        user.SendMessageW(target, win.WM_EXITMENULOOP, 1, 0)
                        assert above(target, self.blocker)
                        assert self.menu_loop_depth == 0
                        checks.append(f'{presentation}: maintenance pauses during menus and resumes on dismissal')
                        self.exercise_native_menu(target)
                        checks.append(f'{presentation}: real context menu and Settings submenu stay above the pet across maintenance ticks')

                    # Both windows hidden must remain hidden across maintenance.
                    user.ShowWindow(self.tail_hwnd, win.SW_HIDE)
                    yield 1.6
                    assert not user.IsWindowVisible(self.hwnd)
                    assert not user.IsWindowVisible(self.tail_hwnd)
                    checks.append('Maintenance never shows deliberately hidden windows')

                    require(user.SetWindowPos(self.hwnd, ctypes.c_void_p(-2),
                                              0, 0, 0, 0, NO_CHANGE))
                    assert self._begin_edge_reveal(play_reveal_animation=True)
                    assert topmost(self.hwnd) and above(self.hwnd, self.blocker)
                    yield 1.0
                    assert self.edge_placement is None and user.IsWindowVisible(self.hwnd)
                    user.ShowWindow(self.hwnd, win.SW_HIDE)
                    require(user.SetWindowPos(self.hwnd, ctypes.c_void_p(-2),
                                              0, 0, 0, 0, NO_CHANGE))
                    self._restore_after_menu_dismissal()
                    assert topmost(self.hwnd) and above(self.hwnd, self.blocker)
                    checks.append('Edge reveal and menu restoration reassert topmost immediately')
                finally:
                    user.DestroyWindow(self.blocker)
                    self.blocker = None

        with patch.object(hochan_pet, 'HoChanPet', Probe), patch.object(sys, 'argv', [
                'verify_topmost', '--status-file', str(Path(temp) / 'codex-status.json'),
                '--no-codex-observer']), patch.object(user, 'KillTimer', wraps=user.KillTimer) as kill:
            # Keep real production window styles, not the activatable QA style.
            with patch.dict(os.environ):
                os.environ.pop('PCR_QA_WINDOW', None)
                hochan_pet.main()
            assert any(call.args[1] == 3 for call in kill.call_args_list)
        if failures:
            raise failures[0]
    checks.append('Maintenance timer is released when the pet closes')
    report = dict(status='passed', checks=checks)
    (ROOT / 'build/topmost-verification.json').write_text(
        json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
