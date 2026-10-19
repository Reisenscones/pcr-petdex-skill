"""Read Codex files off the GUI thread and replay events onto GUI-owned state."""
import copy
import threading
import time

from codex_observer import CodexObserver
from family_store import FamilyStore


class RecordingObserver(CodexObserver):
    def ingest(self, value):
        self.events.append(dict(value))
        return super().ingest(value)


class ObserverWorker:
    def __init__(self, foreground):
        self.foreground = foreground
        self.observer = RecordingObserver(FamilyStore(), foreground.state_dir,
                                          home=foreground.home, enabled=foreground.enabled)
        self.condition = threading.Condition()
        self.request = None
        self.result = None
        self.busy = False
        self.stopped = False
        self.error = None
        self.thread = threading.Thread(target=self._run, name='HoChanCodexObserver', daemon=True)
        self.thread.start()

    def poll(self):
        foreground = self.foreground
        with self.condition:
            result, self.result = self.result, None
        if result is not None:
            metadata, events, expired, unread, supported = result
            foreground.metadata = metadata
            # Apply in order through the existing turn/token guards. A result
            # obtained before a GUI permission action cannot overwrite a newer
            # event, and selection always remains owned by the GUI.
            for event in events:
                foreground.ingest(event)
            for actor, before, when in expired:
                node = foreground.store.nodes.get(actor)
                if node and node.last_event == before and node.active:
                    foreground.store.expire_unconfirmed_start(actor, when)
            for actor, completion, value in unread:
                node = foreground.store.nodes.get(actor)
                if node and node.completion == completion and node.result:
                    node.unread = value and actor not in foreground.opened
            for actor, node in foreground.store.nodes.items():
                meta = metadata.get(actor)
                if meta:
                    for field, key in (('title','thread_title'),('parent','parent_thread_id'),('rollout','rollout')):
                        if meta.get(key):
                            setattr(node, field, meta[key])
            foreground.unread_supported = supported
            foreground.store.reconcile(time.time())
        with self.condition:
            if not self.busy and not self.stopped:
                # No shared mutable FamilyStore, PNG cache or database handle.
                self.request = (copy.deepcopy(foreground.store), set(foreground.opened),
                                foreground.enabled, foreground.state_dir)
                self.busy = True
                self.condition.notify()

    def close(self):
        with self.condition:
            self.stopped = True
            self.condition.notify()
        # A bounded archive scan may still be finishing. It owns no GUI state;
        # cancellation discards its result and its files close normally.
        self.thread.join(timeout=.2)

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped or self.request is not None)
                if self.stopped:
                    return
                store, opened, enabled, state_dir = self.request
                self.request = None
            observer = self.observer
            observer.store, observer.opened = store, opened
            observer.enabled, observer.state_dir = enabled, state_dir
            observer.events = []
            before = {n.id:n.observation_expired for n in store.nodes.values()}
            try:
                observer.poll()
                self.error = None
                result = (observer.metadata, observer.events,
                    [(n.id,n.last_event,n.changed) for n in store.nodes.values() if n.observation_expired and not before.get(n.id)],
                    [(n.id,n.completion,n.unread) for n in store.nodes.values() if n.result], observer.unread_supported)
            except Exception as error:
                self.error = error
                # Events already marked consumed must still reach the GUI if
                # a later metadata adapter fails during this polling pass.
                result = (observer.metadata, observer.events, [], [], observer.unread_supported)
            with self.condition:
                if self.stopped:
                    return
                self.result = result
                self.busy = False
