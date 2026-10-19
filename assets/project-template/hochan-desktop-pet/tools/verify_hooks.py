"""Exercise installation and the actual PowerShell bridge in isolated stores."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from codex_bridge import actor_path, atomic_json

PS = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
BASE = [PS, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File']
HOOK = ROOT / 'hooks/codex-hochan-hook.ps1'
INSTALLER = ROOT / 'install-hooks.ps1'
EVENTS = dict(SessionStart='idle', UserPromptSubmit='thinking', PreToolUse='working',
              PostToolUse='working', Stop='success', Interrupt='interrupted',
              PreCompact='compacting', PostCompact='success', SubagentStart='working',
              SubagentStop='success', SessionEnd='idle')


def run(arguments, **kwargs):
    result = subprocess.run(BASE + list(map(str, arguments)), cwd=ROOT, capture_output=True,
                            encoding='utf-8', errors='replace', timeout=20, **kwargs)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert not result.stderr.strip(), result.stderr
    return result.stdout


def main():
    state = ROOT / 'build' / ('hooks-' + uuid.uuid4().hex[:8])
    state.mkdir(parents=True)
    checks = []
    config_dir = state / 'codex home with spaces'
    config_dir.mkdir()
    unrelated = {'matcher': 'Bash', 'custom_metadata': 'preserve me', 'hooks': [
        {'type': 'command', 'command': 'echo existing', 'timeout': 7}]}
    fixture = {'description': 'existing user configuration', 'custom': {'nested': [1, 2]},
               'hooks': {'PreToolUse': [unrelated], 'FutureEvent': []}}
    config_path = config_dir / 'hooks.json'
    atomic_json(config_path, fixture)
    install = [INSTALLER, '-CodexHome', config_dir, '-NoEnableHookFeature']
    run(install)
    installed = json.loads(config_path.read_text())
    assert installed['custom'] == fixture['custom']
    assert installed['description'] == fixture['description']
    assert installed['hooks']['PreToolUse'][1] == unrelated
    own = [handler for groups in installed['hooks'].values() for group in groups
           for handler in group['hooks'] if 'codex-hochan-hook.ps1' in handler.get('command', '')]
    assert len(own) == 12
    assert installed['hooks']['PermissionRequest'][0]['hooks'][0]['timeout'] == 600
    command = installed['hooks']['PreToolUse'][0]['hooks'][0]['command']
    # Execute the exact registered command, including its Windows quoting.
    probe = dict(hook_event_name='PreToolUse', session_id='installer-command-test', turn_id='t1')
    command = command.replace(str(ROOT / 'state').replace('\\', '/'), str(state / 'command store').replace('\\', '/'))
    probe_result = subprocess.run([PS, '-NoProfile', '-Command', command], input=json.dumps(probe),
                                  capture_output=True, encoding='utf-8', timeout=15)
    assert probe_result.returncode == 0 and json.loads(probe_result.stdout) == {}, probe_result.stderr
    assert json.loads(actor_path(state / 'command store', probe['session_id']).read_text())['status'] == 'working'
    checks.append('12 registered handlers; exact registered command works with a spaced state path')
    installed_bytes = config_path.read_bytes()
    run(install)
    assert config_path.read_bytes() == installed_bytes
    assert len(list(config_dir.glob('hooks.json.bak-hochan-*'))) == 1
    # Removal must preserve other handlers and metadata in a mixed matcher group.
    installed['hooks']['PreToolUse'][0]['matcher'] = '.*'
    installed['hooks']['PreToolUse'][0]['extra'] = 'keep'
    installed['hooks']['PreToolUse'][0]['hooks'].append({'type': 'command', 'command': 'echo mixed'})
    atomic_json(config_path, installed)
    run(install + ['-Remove'])
    removed = json.loads(config_path.read_text())
    assert removed['hooks']['PreToolUse'][0] == {
        'matcher': '.*', 'extra': 'keep', 'hooks': [{'type': 'command', 'command': 'echo mixed'}]}
    assert removed['hooks']['PreToolUse'][1] == unrelated
    assert 'codex-hochan-hook.ps1' not in json.dumps(removed)
    invalid = '{broken json'
    config_path.write_text(invalid)
    failure = subprocess.run(BASE + list(map(str, install)), capture_output=True, timeout=15)
    assert failure.returncode != 0 and config_path.read_text() == invalid
    checks.append('Install is idempotent, backs up changes, preserves mixed groups, and refuses invalid JSON')
    assert 'windows_hook_self_test=ok' in run([HOOK, '-SelfTest'])
    environment = dict(os.environ, PCR_STATE_DIR=str(state / 'unrelated-store'))
    for event, expected in EVENTS.items():
        payload = dict(hook_event_name=event, session_id='hook-fixture', turn_id='turn-1',
                       prompt='中文联动测试', tool_name='Bash')
        if event.startswith('Subagent'):
            payload['agent_id'] = 'child-fixture'
        output = run([HOOK, '-StateDirectory', state], input=json.dumps(payload, ensure_ascii=False), env=environment)
        assert json.loads(output) == {}
        actual = json.loads(actor_path(state, payload.get('agent_id') or payload['session_id']).read_text(encoding='utf-8'))
        assert actual['status'] == expected and actual['event'] == event, actual
        assert actual['source'] == 'codex-hook'
    assert not (state / 'unrelated-store').exists()
    checks.append('All 11 notification events and subagent identity work; an unrelated environment directory cannot override the explicit state path')
    permission = dict(hook_event_name='PermissionRequest', session_id='hook-permission', turn_id='turn-p',
                      tool_name='Bash', tool_input={'command': 'echo fixture'})
    assert json.loads(run([HOOK, '-StateDirectory', state], input=json.dumps(permission))) == {}
    assert not list((state / 'permission-requests').glob('*'))
    checks.append('A closed pet lets PermissionRequest return immediately to normal Codex approval')
    for decision in ('allow', 'deny'):
        atomic_json(state / 'pcr-heartbeat.json', dict(pid=os.getpid(), updated_at=datetime.now(timezone.utc).isoformat()))
        process = subprocess.Popen(BASE + [str(HOOK), '-StateDirectory', str(state)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8')
        process.stdin.write(json.dumps(permission))
        process.stdin.close()
        try:
            deadline = time.monotonic() + 8
            requests = []
            while time.monotonic() < deadline and not requests:
                requests = list((state / 'permission-requests').glob('*.request.json'))
                time.sleep(.05)
            assert requests, 'Permission IPC request missing'
            request = json.loads(requests[0].read_text(encoding='utf-8'))
            atomic_json(requests[0].with_name(request['request_id'] + '.response.json'),
                        dict(request_id=request['request_id'], decision=decision, message='fixture denial'))
            process.wait(timeout=5)
            result = json.loads(process.stdout.read())
            assert result['hookSpecificOutput']['decision']['behavior'] == decision
            assert process.returncode == 0 and not process.stderr.read().strip()
            assert not list((state / 'permission-requests').glob('*'))
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
    checks.append('Permission IPC round trips explicit allow/deny and cleans up request files')
    from animation_clock import load_manifest
    from hochan_pet import HoChanPet
    visual_state = state / 'visual-store'
    clips = load_manifest(ROOT / 'assets/characters/ho-chan/animation-resources')
    pet = HoChanPet(clips, ROOT,
                    visual_state / 'codex-status.json', observe=False)
    pet._resolve_visual()
    assert pet.current_key == 'idle'
    for event, expected in [('UserPromptSubmit', 'reading'), ('PreToolUse', 'working'),
                            ('PreCompact', 'packing_'), ('PostCompact', 'jump')]:
        run([HOOK, '-StateDirectory', visual_state], input=json.dumps(dict(
            hook_event_name=event, session_id='visual-fixture', turn_id='visual-turn')))
        pet._poll_bridge(force=True)
        pet._resolve_visual()
        assert pet.current_key.startswith(expected), (event, pet.current_key)
        assert pet.compose().getbbox()
    run([HOOK, '-StateDirectory', visual_state], input=json.dumps(dict(
        hook_event_name='UserPromptSubmit', session_id='visual-fixture', turn_id='next-turn')))
    run([HOOK, '-StateDirectory', visual_state], input=json.dumps(dict(
        hook_event_name='SubagentStart', session_id='visual-fixture', agent_id='visual-child', turn_id='next-turn')))
    pet._poll_bridge(force=True)
    pet._resolve_visual()
    assert pet.store.nodes['visual-child'].parent == 'visual-fixture'
    assert pet.compose().getbbox()
    checks.append('Actual PowerShell hook -> event files -> pet state/compositor: thinking, tools, compaction, completion, child actor')
    report = dict(status='passed', isolated_state=str(state), checks=checks)
    (ROOT / 'build/hook-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
