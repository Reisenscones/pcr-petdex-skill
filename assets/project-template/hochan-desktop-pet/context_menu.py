"""Ho-chan's native context menu, local settings and log-file action."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

import pcr_pet as win

ROOT = Path(__file__).resolve().parent
WM_MENU_RESULT = 0x8002
MF_POPUP = 0x10
DISABLED = 0x1
SIZE_OPTIONS = (75, 100, 125, 150)
CHARACTER_COMMAND_BASE = 400
ADD_CHARACTER_COMMAND = 190


def read_object(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


class ContextMenuMixin:
    def __init__(self, *args, **kwargs):
        self.autostart_pending = False
        self.menu_results = queue.Queue()
        self.context_menu_active = False
        super().__init__(*args, **kwargs)

    def _autostart_enabled(self):
        return read_object(ROOT / 'state/codex-autostart.json').get('enabled') is True

    def _create_context_menu(self):
        menu = win.user32.CreatePopupMenu()
        if not menu:
            raise ctypes.WinError()

        def item(parent, command, label, *, checked=False, disabled=False):
            flags = win.MF_STRING | (win.MF_CHECKED if checked else 0) | (DISABLED if disabled else 0)
            if not win.user32.AppendMenuW(parent, flags, command, label):
                raise ctypes.WinError()

        def submenu(label, parent=menu):
            child = win.user32.CreatePopupMenu()
            if not child:
                raise ctypes.WinError()
            if not win.user32.AppendMenuW(parent, MF_POPUP, child, label):
                win.user32.DestroyMenu(child)
                raise ctypes.WinError()
            return child

        try:
            settings = submenu('设置')
            item(settings, 150, '正在更新启动设置…' if self.autostart_pending else '随 Codex 启动',
                 checked=self._autostart_enabled(), disabled=self.autostart_pending)
            item(settings, 151, '隐藏气泡栏', checked=self.hide_bubble_bar)
            sizes = submenu('大小', settings)
            for index, percent in enumerate(SIZE_OPTIONS):
                item(sizes, 300 + index, f'{percent}%', checked=self.size_percent == percent,
                     disabled=bool(self.edge_transition))

            previews = submenu('动作预览')
            if self.transient_key or time.monotonic() < self.compaction_demo_until:
                item(previews, 100, '恢复 Codex 状态联动')
            resting = self.leisure.phase in ('entering', 'sleeping')
            busy = bool(self.store.work_tokens() or self.permission_request or self.current_key == 'jump')
            item(previews, 110, '唤醒' if resting else '进入休息模式', disabled=busy)
            item(previews, 115, '演示压缩场景（40秒）')
            win.user32.AppendMenuW(previews, win.MF_SEPARATOR, 0, None)
            for index, (key, label) in enumerate(self.preview_labels.items()):
                item(previews, 201 + index, label, checked=self.transient_key == key)

            characters = submenu('切换角色')
            self._refresh_characters()
            self.character_menu_commands = {}
            for index, character in enumerate(self.characters.values()):
                command = CHARACTER_COMMAND_BASE + index
                self.character_menu_commands[command] = character.id
                item(characters, command, character.name, checked=self.character_id == character.id,
                     disabled=not character.ready or bool(self.edge_transition or self.dragging or self.mouse_down))
            win.user32.AppendMenuW(characters, win.MF_SEPARATOR, 0, None)
            item(characters, ADD_CHARACTER_COMMAND, '添加更多角色…')

            item(menu, 161, '日志')
            item(menu, 180, '关于')
            item(menu, 199, '退出')
            return menu
        except Exception:
            win.user32.DestroyMenu(menu)
            raise

    def _show_menu(self, owner_hwnd=None):
        owner = owner_hwnd or self.hwnd or self.tail_hwnd
        if not owner or self.context_menu_active:
            return
        menu = self._create_context_menu()
        self._restore_topmost()
        # TPM_NONOTIFY suppresses the menu notifications used by the native
        # window layer. Cover the entire modal call explicitly so neither the
        # main window nor the edge avatar can be raised above our popup.
        self.context_menu_active = True
        try:
            cursor = win.POINT()
            win.user32.GetCursorPos(ctypes.byref(cursor))
            win.user32.SetForegroundWindow(owner)
            command = win.user32.TrackPopupMenu(menu, win.TPM_RETURNCMD | win.TPM_NONOTIFY | win.TPM_RIGHTBUTTON,
                cursor.x, cursor.y, 0, owner, None)
        finally:
            # DestroyMenu also releases all attached submenus.
            win.user32.DestroyMenu(menu)
            self.context_menu_active = False
        if command:
            self._handle_menu_command(command, owner)
        if command != 199:
            self._restore_after_menu_dismissal()

    def _menu_message(self, text, title='Ho-chan 桌宠', owner=None):
        win.user32.MessageBoxW(owner or self.hwnd or self.tail_hwnd, text, title, 0)

    def _open_log(self):
        path = (self.status_path.parent / 'codex-hook-events.jsonl').resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.touch(exist_ok=True)
            try:
                os.startfile(str(path))
            except OSError:
                # JSONL may have no file association on a fresh Windows install.
                notepad = Path(os.environ['SystemRoot']) / 'System32/notepad.exe'
                subprocess.Popen([str(notepad), str(path)], cwd=ROOT)
        except OSError as error:
            self._menu_message('无法打开日志：\n' + str(path) + '\n\n' + str(error))

    def _toggle_autostart(self):
        if self.autostart_pending:
            return
        remove = self._autostart_enabled()
        self.autostart_pending = True
        owner = self.hwnd

        def work():
            error = ''
            try:
                powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
                command = [str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                           str(ROOT / 'install-codex-autostart.ps1')]
                if remove:
                    command.append('-Remove')
                result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=25,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode:
                    error = (result.stderr or result.stdout).decode('utf-8', errors='replace').strip()
            except Exception as exc:
                error = str(exc)
            self.menu_results.put(error)
            win.user32.PostMessageW(owner, WM_MENU_RESULT, 0, 0)

        threading.Thread(target=work, name='hochan-autostart-setting', daemon=True).start()

    def _finish_menu_job(self):
        try:
            error = self.menu_results.get_nowait()
        except queue.Empty:
            return
        self.autostart_pending = False
        if error:
            self._menu_message('启动设置未能完成：\n' + error)

    def _handle_menu_command(self, command, owner=None):
        if command == 199:
            win.user32.DestroyWindow(self.hwnd)
        elif command == 150:
            self._toggle_autostart()
        elif command == 151:
            self._set_hide_bubble_bar(not self.hide_bubble_bar)
        elif command == 161:
            self._open_log()
        elif 300 <= command < 300 + len(SIZE_OPTIONS):
            self._set_size_percent(SIZE_OPTIONS[command - 300])
        elif command in getattr(self, 'character_menu_commands', {}):
            self._set_character(self.character_menu_commands[command])
        elif command == ADD_CHARACTER_COMMAND:
            path = ROOT / 'characters/README.md'
            try:
                os.startfile(str(path))
            except OSError:
                self._menu_message('添加角色说明位于：\n' + str(path), owner=owner)
        elif command == 180:
            character = getattr(self, 'characters', {}).get(getattr(self, 'character_id', ''))
            self._menu_message('Ho-chan 桌宠\n自定义 Windows 版\n'
                               '当前角色：' + getattr(self, 'character_name', 'ホウオウ') + '\n\n'
                               'PCR 桌宠 · Windows 版\n'
                               '角色素材来源：' + (getattr(character, 'source_url', '') or 'https://redive.estertion.win/') + '\n'
                               '素材版权：' + (getattr(character, 'copyright', '') or '© Cygames') + '\n\n'
                               '程序许可与素材说明见项目中的 LICENSE、ASSET-NOTICE.md 和 UPSTREAM.md。',
                               '关于 Ho-chan', owner)
        elif command == 100:
            self.compaction_demo_until = 0
            if getattr(self, 'allow_codex_observer', False):
                self.observer.enabled = True
            self.transient_key = None
            self.leisure.cancel()
            self._poll_bridge(force=True)
            self._resolve_visual()
            self._render_current()
        elif command == 110 and not self.store.work_tokens() and not self.permission_request and self.current_key != 'jump':
            self.compaction_demo_until = 0
            self.transient_key = None
            if self.leisure.phase in ('entering', 'sleeping'):
                self.leisure.click(time.monotonic(), wake=True)
            else:
                self.leisure.enter(time.monotonic())
            self._resolve_visual()
            self._render_current()
        elif command == 115:
            self._start_compaction_demo()
        elif 201 <= command < 201 + len(self.preview_labels):
            self.compaction_demo_until = 0
            key = list(self.preview_labels)[command-201]
            self._switch_visual(key, once=key in self.preview_one_shots)
