"""Verify animation, rest, permission, family and edge flows in an isolated window."""
from __future__ import annotations

import json
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from codex_bridge import atomic_json, publish_event


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--character', default='ho-chan')
    args = parser.parse_args()
    state = ROOT / 'build' / ('runtime-' + uuid.uuid4().hex[:8])
    state.mkdir(parents=True)
    process = subprocess.Popen([sys.executable, str(ROOT / 'hochan_pet.py'), '--status-file',
        str(state / 'codex-status.json'), '--no-codex-observer', '--qa-window', '--character', args.character], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=(state / 'stderr.log').open('w'), creationflags=subprocess.CREATE_NO_WINDOW)
    checks, snapshots = [], {}

    def wait_for(test, timeout=10):
        end, last = time.monotonic() + timeout, {}
        while time.monotonic() < end:
            if process.poll() is not None:
                raise AssertionError(f'Pet exited with {process.returncode}: {(state / "stderr.log").read_text()}')
            try:
                last = json.loads((state / 'pcr-heartbeat.json').read_text(encoding='utf-8'))
                if test(last):
                    return last
            except (OSError, ValueError):
                pass
            time.sleep(0.08)
        raise AssertionError('Runtime timeout: ' + json.dumps(last))

    def command(action, **values):
        identity = uuid.uuid4().hex
        atomic_json(state / 'qa-command.json', dict(id=identity, action=action, **values))
        if action != 'exit':
            wait_for(lambda h: identity in h.get('qa_commands', []))

    def capture(name):
        command('capture')
        paths = sorted((state / 'captures').glob('*.png'), key=lambda p: p.stat().st_mtime_ns)
        target = ROOT / 'preview' / ('native-' + name + '.png')
        if args.character != 'ho-chan':
            target = ROOT / 'preview/characters' / args.character / target.name
            target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(paths[-1], target)
        snapshots[name] = str(target.relative_to(ROOT))

    try:
        heartbeat = wait_for(lambda h: h.get('window_visible') and h.get('current_key') == 'idle')
        assert heartbeat['app'] == 'Ho-chan Desktop Pet'
        initial_frame = heartbeat['frame_index']
        wait_for(lambda h: h.get('current_key') == 'idle' and h.get('frame_index') != initial_frame)
        capture('idle')
        checks.append('Native transparent window starts and advances idle frames')
        publish_event(state, dict(session_id='runtime-test', turn_id='turn-1', event='UserPromptSubmit'))
        wait_for(lambda h: h.get('current_key') == 'reading')
        capture('thinking')
        checks.append('UserPromptSubmit selects the 07_walk thinking animation')
        publish_event(state, dict(session_id='runtime-test', turn_id='turn-1', event='PreToolUse'))
        wait_for(lambda h: h.get('current_key') == 'working')
        capture('working')
        checks.append('PreToolUse selects the 07_run tool animation')
        command('drag', enabled=True, direction=-1)
        wait_for(lambda h: h.get('current_key') == 'left')
        capture('drag-left')
        command('drag', enabled=True, direction=1)
        capture('drag-right')
        checks.append('Drag renders the floating clip in both directions')
        command('drag', enabled=False)
        wait_for(lambda h: h.get('current_key') == 'working')
        checks.append('Release restores the active tool animation')
        for key in ('idle', 'left', 'reading', 'working'):
            command('preview', key=key)
            wait_for(lambda h: h.get('current_key') == key)
        checks.append('All four preview actions are accepted by the native event loop')
        command('auto')
        publish_event(state, dict(session_id='runtime-test', turn_id='turn-1', event='PreCompact'))
        wait_for(lambda h: h.get('current_key', '').startswith('packing_'))
        capture('packing')
        checks.append('Compaction selects one of the Ho-chan packing variants')
        publish_event(state, dict(session_id='runtime-test', turn_id='turn-1', event='PostCompact'))
        wait_for(lambda h: h.get('current_key') == 'jump')
        capture('success')
        wait_for(lambda h: h.get('current_key') == 'idle')
        checks.append('Completion plays the selected character celebration once and returns to idle')
        publish_event(state, dict(session_id='runtime-test', turn_id='turn-2', event='UserPromptSubmit'))
        request_id = 'isolated-permission'
        request = dict(request_id=request_id, session_id='runtime-test', turn_id='turn-2',
                       summary='隔离测试：确认动画与气泡位置', created_at='2026-10-18T00:00:00+00:00')
        atomic_json(state / 'permission-requests' / (request_id+'.request.json'), request)
        publish_event(state, dict(session_id='runtime-test', turn_id='turn-2', event='PermissionRequest'))
        wait_for(lambda h: h.get('current_key') == 'question' and h.get('permission_request_id') == request_id)
        capture('permission')
        publish_event(state, dict(session_id='runtime-test', turn_id='turn-2', event='SessionEnd'))
        wait_for(lambda h: h.get('current_key') == 'idle' and not h.get('permission_request_id'))
        checks.append('An isolated permission fixture shows Ho-chan plus a bubble and clears on session end')
        command('rest')
        wait_for(lambda h: h.get('current_key') == 'sleep_body' and h.get('leisure_phase') == 'sleeping')
        capture('rest')
        command('sleep-click', wake=True)
        wait_for(lambda h: h.get('current_key') == 'wake')
        wait_for(lambda h: h.get('current_key') == 'idle' and h.get('leisure_phase') == 'awake')
        checks.append('Rest uses the no-weapon animation; wake waves once instead of floating')
        command('preview', key='bow')
        wait_for(lambda h: h.get('current_key') == 'bow')
        capture('bow')
        command('auto')
        publish_event(state, dict(session_id='runtime-test', turn_id='turn-3', event='UserPromptSubmit'))
        for i in range(3):
            publish_event(state, dict(session_id='runtime-test', turn_id='turn-3', event='SubagentStart', agent_id=f'child-{i}'))
        wait_for(lambda h: len(h.get('families', [])) == 4)
        capture('family')
        checks.append('Three child actors render using the same Ho-chan skin')
        for edge in ('left', 'right', 'top', 'bottom'):
            command('edge', edge=edge)
            hidden = wait_for(lambda h: h.get('presentation') == 'hidden' and h.get('tail_visible'))
            assert hidden['hidden_edge'] == edge
            command('reveal')
            wait_for(lambda h: h.get('presentation') == 'visible' and not h.get('tail_visible'))
        checks.append('All four edges hide with portrait handles and reveal using the Ho-chan clip')
        command('exit')
        assert process.wait(timeout=8) == 0
        assert not (state / 'stderr.log').read_text().strip()
        checks.append('Window exits without an orphan process or runtime exception')
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    report = dict(status='passed', isolated_state=str(state), checks=checks, captures=snapshots)
    report['character_id'] = args.character
    report_path = ROOT / 'build' / ('runtime-verification.json' if args.character == 'ho-chan' else f'runtime-verification-{args.character}.json')
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
