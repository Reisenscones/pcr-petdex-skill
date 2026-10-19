"""Check turn recovery when compaction is followed by a session restart."""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from codex_bridge import publish_event
from codex_observer import CodexObserver
from family_store import FamilyStore


def main():
    def send(store, event, when, turn='turn-1', actor='compacted'):
        return store.ingest(dict(session_id=actor, turn_id=turn, event=event), when)

    def compacted():
        store = FamilyStore()
        for when, event in enumerate(('UserPromptSubmit', 'PreCompact', 'PostCompact'), 1):
            assert send(store, event, when)
        return store

    for restart in (False, True):
        store = compacted()
        if restart:
            assert send(store, 'SessionStart', 4, turn='')
        assert not send(store, 'PostToolUse', 5)
        assert send(store, 'PreToolUse', 6)
        store.reconcile(6)
        node = store.nodes['compacted']
        assert node.active and node.status == 'working' and node.completion is None
        assert store.selected == node.id and store.visual(node, 6) == 'working'
        assert send(store, 'PostToolUse', 7)

    # A real terminal event after compaction must prevent late tools reviving it.
    for terminal in ('Stop', 'SubagentStop', 'TaskCompleteFallback', 'SessionEnd'):
        store = compacted()
        assert send(store, 'SessionStart', 4, turn='')
        assert send(store, terminal, 5)
        assert not send(store, 'PreToolUse', 6)
        assert not send(store, 'PostToolUse', 7)
        assert not store.nodes['compacted'].active
        assert send(store, 'UserPromptSubmit', 8, turn='turn-2')
        assert not send(store, 'PreToolUse', 9, turn='turn-1')
        assert store.nodes['compacted'].active

    # Exercise event transport + observer, including concurrent conversation selection.
    with tempfile.TemporaryDirectory() as temporary:
        state = Path(temporary)
        store = FamilyStore()
        observer = CodexObserver(store, state, enabled=False)
        sequence = [('compacted', 'UserPromptSubmit', 'turn-1'),
                    ('compacted', 'PreCompact', 'turn-1'),
                    ('compacted', 'PostCompact', 'turn-1'),
                    ('compacted', 'SessionStart', ''),
                    ('compacted', 'PreToolUse', 'turn-1'),
                    ('other', 'UserPromptSubmit', 'other-turn')]
        for when, (actor, event, turn) in enumerate(sequence, 1):
            publish_event(state, dict(session_id=actor, event=event, turn_id=turn, received_at=when))
        observer.poll(now=10)
        assert all(store.nodes[actor].active for actor in ('compacted', 'other'))
        assert store.selected == 'other'
        publish_event(state, dict(session_id='other', event='Stop', turn_id='other-turn', received_at=11))
        observer.poll(now=12)
        assert store.selected == 'compacted'
        assert store.visual(store.nodes['compacted'], 12) == 'working'

    print('Passed: compaction restart recovery, terminal/stale-event guards, observer replay and conversation selection')


if __name__ == '__main__':
    main()
