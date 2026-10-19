"""Check GUI detection and app-opening policy without closing Codex or the pet."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import codex_autostart as watcher


def main():
    checks = []
    for path in [r'C:\Program Files\WindowsApps\OpenAI.Codex_26.123_x64__id\app\ChatGPT.exe',
                 r'C:\Program Files\WindowsApps\OpenAI.Codex_27.0_x64__id\app\ChatGPT.exe',
                 r'C:\Users\User\AppData\Local\Programs\Codex\Codex.exe']:
        assert watcher.is_codex_desktop(path), path
    for path in [r'C:\Program Files\WindowsApps\OpenAI.ChatGPT_26_x64__id\app\ChatGPT.exe',
                 r'C:\Users\User\AppData\Local\OpenAI\Codex\bin\123\codex.exe',
                 r'C:\npm\codex.exe', r'C:\other\ChatGPT.exe',
                 r'C:\Program Files\Codex\codex-windows-sandbox-service.exe']:
        assert not watcher.is_codex_desktop(path), path
    assert watcher.desktop_roots({10: 1, 11: 10, 12: 10, 13: 11}) == {10}
    assert watcher.desktop_roots({10: 1, 11: 10, 20: 2}) == {10, 20}
    checks.append('GUI detection excludes ChatGPT, CLI and services; renderer changes are ignored')
    policy = watcher.LaunchPolicy()
    calls = []
    launch = lambda: calls.append('start')
    assert policy.update(set(), lambda: False, launch, 0) is None
    assert policy.update({10}, lambda: False, launch, 1) == 'pet-launched'
    assert policy.update({10}, lambda: False, launch, 2) is None
    assert calls == ['start']
    policy.update(set(), lambda: False, launch, 3)
    assert policy.update({20}, lambda: False, launch, 4) == 'pet-launched'
    assert calls == ['start', 'start']
    assert policy.update({30}, lambda: True, launch, 5) == 'pet-already-running'
    assert policy.update({30}, lambda: False, launch, 6) is None
    assert calls == ['start', 'start']
    checks.append('Starts once per opening; reuses running pet; respects manual exit until next opening')
    policy = watcher.LaunchPolicy()
    def fail():
        raise OSError('fixture launch failure')
    try:
        policy.update({10}, lambda: False, fail, 0)
    except OSError:
        pass
    else:
        raise AssertionError('Launch failure was not surfaced')
    assert policy.update({10}, lambda: False, launch, 29) is None
    assert policy.update({10}, lambda: False, launch, 30) == 'pet-launched'
    with patch.object(watcher.subprocess, 'Popen') as popen:
        watcher.launch_pet()
        args, kwargs = popen.call_args
        assert args[0] == [str(ROOT / '.venv/Scripts/pythonw.exe'), str(ROOT / 'hochan_pet.py')]
        assert kwargs['cwd'] == ROOT
        assert kwargs['creationflags'] == watcher.subprocess.CREATE_NO_WINDOW
    checks.append('Launch failures retry after cooldown; normal launch uses pythonw and no console')
    report = dict(status='passed', checks=checks, detected_codex_main_pids=sorted(watcher.desktop_processes()),
                  current_pet_running=watcher.pet_running())
    (ROOT / 'build/autostart-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
