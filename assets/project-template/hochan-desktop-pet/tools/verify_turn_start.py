"""Check observed turn starts stay in thinking until an actual tool event."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from codex_bridge import publish_event
from codex_observer import CodexObserver
from family_store import FamilyStore


def main():
    checks = []
    for previous in ('new', 'completed', 'interrupted', 'working', 'hook-first'):
        with tempfile.TemporaryDirectory(prefix='turn-start-') as temporary:
            directory = Path(temporary)
            home, state = directory / 'home', directory / 'state'
            home.mkdir()
            rollout = directory / 'rollout.jsonl'
            actor, turn = 'fixture', 'new-turn'
            with closing(sqlite3.connect(home / 'state_1.sqlite')) as db:
                db.execute('CREATE TABLE threads (id TEXT, title TEXT, rollout_path TEXT, updated_at INTEGER)')
                db.execute('INSERT INTO threads VALUES (?, ?, ?, ?)', (actor, 'fixture', str(rollout), 100))
                db.commit()
            store = FamilyStore()
            observer = CodexObserver(store, state, home=home)

            def send(event, when, identity=turn):
                publish_event(state, dict(session_id=actor, turn_id=identity,
                                         event=event, received_at=when))

            def lifecycle(kind, when):
                with rollout.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(dict(timestamp=datetime.fromtimestamp(when, timezone.utc).isoformat(),
                        type='event_msg', payload=dict(type=kind, turn_id=turn)))+'\n')

            def visual(when):
                observer.poll(now=when)
                node = store.nodes[actor]
                assert store.selected == actor
                return store.visual(node, when)

            if previous in ('completed', 'interrupted', 'working'):
                send('UserPromptSubmit', 90, 'old-turn')
                send({'completed': 'Stop', 'interrupted': 'Interrupt', 'working': 'PreToolUse'}[previous], 91, 'old-turn')
                observer.poll(now=92)
            if previous == 'hook-first':
                send('UserPromptSubmit', 99)
                assert visual(99.5) == 'reading'
            lifecycle('task_started', 100)
            assert visual(100.5) == 'reading', (previous, store.nodes[actor].status)
            assert store.nodes[actor].active and store.nodes[actor].completion is None
            send('UserPromptSubmit', 101)
            assert visual(101.5) == 'reading'
            send('SessionStart', 102)
            assert visual(102.5) == 'reading'
            send('PreToolUse', 103)
            assert visual(103.5) == 'working'
            # A late/repeated lifecycle start cannot overwrite precise hooks.
            lifecycle('task_started', 104)
            assert visual(104.5) == 'working'
            send('PostToolUse', 105)
            assert visual(105.5) == 'working'
            send('PreToolUse', 106, 'old-turn')
            assert visual(106.5) == 'working' and store.nodes[actor].turn == turn
            lifecycle('task_complete', 107)
            assert visual(107.5) == 'jump'
            checks.append(previous)

    store = FamilyStore()
    assert store.ingest(dict(session_id='direct', turn_id='t', event='ResumeDetected'), 1)
    assert store.visual(store.nodes['direct'], 1) == 'reading'
    print(json.dumps(dict(status='passed', start_cases=checks,
        checks=['Lifecycle-first and hook-first starts use thinking without an intermediate tool state',
                'New turns retire previous completed, interrupted and active turns',
                'Actual tool hooks still use working; late starts and stale turns cannot override them',
                'Lifecycle completion still celebrates; bare ResumeDetected defaults to thinking']), indent=2))


if __name__ == '__main__':
    main()
