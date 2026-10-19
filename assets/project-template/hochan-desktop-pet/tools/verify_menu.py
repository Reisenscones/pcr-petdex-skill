"""Check native submenu structure, actions and safe settings dispatch in isolation."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import context_menu as menus
from animation_clock import load_manifest
from codex_bridge import atomic_json, publish_event
from hochan_pet import HoChanPet, PREVIEWS
import pcr_pet as win

user = win.user32
user.GetMenuItemCount.argtypes = [w.HMENU]
user.GetSubMenu.argtypes = [w.HMENU, ctypes.c_int]
user.GetSubMenu.restype = w.HMENU
user.GetMenuStringW.argtypes = [w.HMENU, w.UINT, w.LPWSTR, ctypes.c_int, w.UINT]
user.GetMenuItemID.argtypes = [w.HMENU, ctypes.c_int]
user.GetMenuItemID.restype = w.UINT
user.GetMenuState.argtypes = [w.HMENU, w.UINT, w.UINT]
user.IsMenu.argtypes = [w.HMENU]


def labels(menu):
    result = []
    for index in range(user.GetMenuItemCount(menu)):
        buffer = ctypes.create_unicode_buffer(256)
        user.GetMenuStringW(menu, index, buffer, len(buffer), 0x400)
        result.append(buffer.value)
    return result


def main():
    clips = load_manifest(ROOT / 'assets/characters/ho-chan/animation-resources')
    checks = []
    with tempfile.TemporaryDirectory(prefix='menu-', dir=ROOT / 'build') as temp:
        state = Path(temp)
        pet = HoChanPet(clips, ROOT,
                        state / 'codex-status.json', observe=False)
        pet.allow_codex_observer = False
        pet._resolve_visual()
        with patch.object(pet, '_autostart_enabled', return_value=True):
            menu = pet._create_context_menu()
            children = [user.GetSubMenu(menu, i) for i in range(3)]
            sizes = user.GetSubMenu(children[0], 2)
            try:
                assert labels(menu) == ['设置', '动作预览', '切换角色', '日志', '关于', '退出']
                assert labels(children[0]) == ['随 Codex 启动', '隐藏气泡栏', '大小']
                assert user.GetMenuState(children[0], 150, 0) & win.MF_CHECKED
                assert not user.GetMenuState(children[0], 151, 0) & win.MF_CHECKED
                assert labels(sizes) == ['75%', '100%', '125%', '150%']
                assert user.GetMenuState(sizes, 301, 0) & win.MF_CHECKED
                assert labels(children[2])[:2] == ['ホウオウ', 'キョウカ（ゴシック）']
                assert user.GetMenuState(children[2], 400, 0) & win.MF_CHECKED
                assert not user.GetSubMenu(menu, 3)
                assert '恢复 Codex 状态联动' not in labels(children[1])
                assert len([user.GetMenuItemID(children[1], i) for i in range(user.GetMenuItemCount(children[1]))
                            if 201 <= user.GetMenuItemID(children[1], i) < 201 + len(PREVIEWS)]) == 14
            finally:
                user.DestroyMenu(menu)
            assert not user.IsMenu(menu) and not any(user.IsMenu(child) for child in children + [sizes])
        checks.append('Six main entries; character submenu discovers both names; Logs is a direct action; all menu handles are released')

        bounds = pet._logical_pet_bounds()
        point = ((bounds[0]+bounds[2])//2, (bounds[1]+bounds[3])//2)
        with patch.object(pet, '_cursor_window_position', return_value=point), \
                patch.object(pet, '_render_current') as render:
            pet._update_hover()
            assert pet.selector_visible
            pet.compose()
            assert pet.selector_rect
            pet._handle_menu_command(151)
            render.assert_called_once_with()
            assert pet.hide_bubble_bar and not pet.selector_visible
            assert pet.selector_rect is None and not pet.selector_rows
            pet._update_hover()
            assert not pet.selector_visible
        menu = pet._create_context_menu()
        try:
            assert user.GetMenuState(user.GetSubMenu(menu, 0), 151, 0) & win.MF_CHECKED
        finally:
            user.DestroyMenu(menu)
        with patch.object(pet, '_composite_selector') as selector, \
                patch.object(pet, '_composite_permission_bubble') as permission:
            pet.permission_request = {'summary': 'fixture'}
            pet.compose()
            selector.assert_not_called()
            permission.assert_called_once()
            pet.permission_request = None
        checks.append('Hide bubble bar sits between autostart and size; toggling redraws immediately and suppresses hover while preserving permission bubbles')

        for index, percent in enumerate(menus.SIZE_OPTIONS):
            pet._handle_menu_command(300 + index)
            assert pet.size_percent == percent
            assert json.loads(pet.settings_path.read_text(encoding='utf-8'))['size_percent'] == percent
        restored = HoChanPet(clips, ROOT, state / 'codex-status.json', observe=False)
        assert restored.size_percent == 150
        assert restored.hide_bubble_bar
        with patch.object(pet, '_cursor_window_position', return_value=point):
            pet._handle_menu_command(151)
            pet._update_hover()
            assert not pet.hide_bubble_bar and pet.selector_visible
        restored = HoChanPet(clips, ROOT, state / 'codex-status.json', observe=False)
        assert not restored.hide_bubble_bar and restored.size_percent == 150
        with patch('hochan_pet.atomic_json', side_effect=OSError('fixture failure')), \
                patch.object(pet, '_menu_message') as failed:
            pet._handle_menu_command(151)
            assert not pet.hide_bubble_bar and 'fixture failure' in failed.call_args.args[0]
        checks.append('Bubble bar preference survives size changes and restart; disabling restores hover; save failures retain the previous preference')
        atomic_json(pet.settings_path, {'size_percent': 200})
        restored = HoChanPet(clips, ROOT, state / 'codex-status.json', observe=False)
        assert restored.size_percent == 100
        pet._set_size_percent(100)
        checks.append('Size selections persist across a fresh pet instance; obsolete 175/200 percent values fall back to 100 percent')

        pet._handle_menu_command(203)
        assert pet.current_key == 'reading' and pet.transient_key == 'reading'
        menu = pet._create_context_menu()
        try:
            assert labels(user.GetSubMenu(menu, 1))[0] == '恢复 Codex 状态联动'
        finally:
            user.DestroyMenu(menu)
        pet._handle_menu_command(100)
        assert pet.current_key == 'idle' and not pet.transient_key and not pet.observer.enabled
        pet._handle_menu_command(115)
        assert pet.current_key.startswith('packing_')
        pet._handle_menu_command(100)
        pet._handle_menu_command(110)
        assert pet.leisure.phase == 'entering'
        pet._handle_menu_command(110)
        assert pet.current_key == 'wake'
        pet._handle_menu_command(100)
        publish_event(state, dict(session_id='menu-fixture', turn_id='t1', event='UserPromptSubmit'))
        pet._poll_bridge(force=True)
        pet._resolve_visual()
        menu = pet._create_context_menu()
        try:
            assert user.GetMenuState(user.GetSubMenu(menu, 1), 110, 0) & menus.DISABLED
        finally:
            user.DestroyMenu(menu)
        pet._handle_menu_command(110)
        assert pet.leisure.phase == 'awake'
        checks.append('Preview/automatic mode, compaction demo, rest and wake dispatch correctly; busy tasks cannot enter rest')

        fake_root = state / 'project'
        atomic_json(fake_root / 'state/codex-autostart.json', {'enabled': False})
        log_path = (state / 'codex-hook-events.jsonl').resolve()
        log_path.write_text('existing log\n', encoding='utf-8')
        with patch.object(menus, 'ROOT', fake_root):
            messages = []
            with patch.object(pet, '_menu_message', side_effect=lambda *args: messages.append(args)):
                pet._handle_menu_command(180)
                assert 'Ho-chan' in messages[-1][0]
            with patch.object(menus.os, 'startfile') as opened:
                pet._handle_menu_command(161)
                opened.assert_called_once_with(str(log_path))
                assert log_path.read_text(encoding='utf-8') == 'existing log\n'
            with patch.object(menus.os, 'startfile', side_effect=OSError('no association')), \
                    patch.object(menus.subprocess, 'Popen') as fallback:
                pet._handle_menu_command(161)
                assert fallback.call_args.args[0][-1] == str(log_path)
                assert Path(fallback.call_args.args[0][0]).name == 'notepad.exe'
            for enabled in (True, False):
                atomic_json(fake_root / 'state/codex-autostart.json', {'enabled': enabled})
                with patch.object(menus.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, \
                        patch.object(user, 'PostMessageW', return_value=True):
                    pet._handle_menu_command(150)
                    end = time.monotonic() + 3
                    while pet.menu_results.empty() and time.monotonic() < end:
                        time.sleep(.01)
                    assert not pet.menu_results.empty()
                    pet._finish_menu_job()
                    assert not pet.autostart_pending
                    assert ('-Remove' in run.call_args.args[0]) == enabled
                    assert run.call_args.kwargs['creationflags'] == menus.subprocess.CREATE_NO_WINDOW
            with patch.object(menus.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr=b'fixture failure', stdout=b'')), \
                    patch.object(user, 'PostMessageW', return_value=True), patch.object(pet, '_menu_message') as failed:
                pet._handle_menu_command(150)
                end = time.monotonic() + 3
                while pet.menu_results.empty() and time.monotonic() < end:
                    time.sleep(.01)
                pet._finish_menu_job()
                assert not pet.autostart_pending and 'fixture failure' in failed.call_args.args[0]
        checks.append('Logs opens the absolute JSONL file path without replacing contents; missing associations fall back to Notepad')
        checks.append('Autostart toggles run off the GUI thread, select enable/remove correctly, and display failures without changing real startup settings')
    report = dict(status='passed', checks=checks)
    (ROOT / 'build/context-menu-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
