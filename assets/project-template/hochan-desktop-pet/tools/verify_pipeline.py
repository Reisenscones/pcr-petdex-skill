"""Check crop pixels, async state isolation, cache bounds and reusable DIBs."""
import ctypes
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from animation_clock import Frames, Clip, load_manifest
from character_catalog import discover_characters
from codex_bridge import publish_event
from codex_observer import CodexObserver
from family_store import FamilyStore
from frame_renderer import FrameRenderer, PreparedFrame
from observer_worker import ObserverWorker, RecordingObserver
from rendering import PresentationClock, prepare_pixels
import hochan_pet
import pcr_pet as win


def wait_for(condition, test, timeout=3):
    with condition:
        assert condition.wait_for(test, timeout), 'Timed out waiting for worker'


def main():
    checks = []
    spec = dict(label='60fps',timing='uniform_segments',
                frames=[dict(file='unused',duration_ms=round((i+1)*600/36)-round(i*600/36)) for i in range(36)],
                segments=[dict(frame_count=36,duration_ms=600)])
    clip = Clip(ROOT,'test',spec)
    for phase in (.0001,.004,.012):
        assert [clip.frame(i/60+phase) for i in range(180)] == [i%36 for i in range(180)]
    checks.append('Native 60Hz clip sampling stays uniform across integer 16/17ms durations and loop boundaries')
    with tempfile.TemporaryDirectory(prefix='pipeline-', dir=ROOT/'build') as temporary:
        directory = Path(temporary)
        # Slow disk work cannot hold the GUI store or cause a late old turn to
        # overwrite an event already accepted on the foreground thread.
        store = FamilyStore()
        foreground = CodexObserver(store, directory, enabled=False)
        entered, resume = threading.Event(), threading.Event()
        original = RecordingObserver.poll
        def blocked(observer):
            entered.set()
            assert resume.wait(3)
            return original(observer)
        publish_event(directory, dict(session_id='actor',turn_id='old',event='UserPromptSubmit',token='old'))
        with patch.object(RecordingObserver, 'poll', blocked):
            worker = ObserverWorker(foreground)
            try:
                began = time.perf_counter()
                worker.poll()
                assert time.perf_counter()-began < .1
                assert entered.wait(1)
                foreground.ingest(dict(session_id='actor',turn_id='new',event='UserPromptSubmit',
                                       received_at=time.time()+1,token='new'))
                node = store.nodes['actor']
                assert worker.observer.store is not store
                resume.set()
                wait_for(worker.condition, lambda: not worker.busy)
                worker.poll()
                assert store.nodes['actor'] is node and node.turn == 'new'
            finally:
                resume.set()
                worker.close()
            assert not worker.thread.is_alive()
        # Normal async event replay and late file discovery, including with the
        # optional real Codex observer disabled.
        worker = ObserverWorker(foreground)
        try:
            publish_event(directory, dict(session_id='second',turn_id='t',event='PreToolUse'))
            worker.poll()
            wait_for(worker.condition, lambda: not worker.busy)
            worker.poll()
            assert store.nodes['second'].status == 'working'
        finally:
            worker.close()
        checks.append('Slow observation never shares GUI state; newer turns survive; hooks replay asynchronously')

        frames = load_manifest(discover_characters()['kyouka-gothic'].asset_dir)['working'].frames
        renderer = FrameRenderer(max_bytes=8*1024*1024)
        try:
            for scale, mirrored in ((1.5,False),(2.25,True)):
                variant, _ = renderer.request(frames,0,scale,mirrored)
                wait_for(renderer.condition, lambda: 0 in renderer.cache or renderer.error is not None)
                assert renderer.error is None
                _, prepared = renderer.request(frames,0,scale,mirrored)
                expected = frames.render(0,scale,mirrored)
                assert prepare_pixels(prepared.canvas(),1) == prepare_pixels(expected,1)
                assert renderer.bytes_used <= renderer.max_bytes
            renderer.clear()
            assert renderer.bytes_used == 0 and not renderer.cache
        finally:
            renderer.close()
        assert not renderer.thread.is_alive()
        checks.append('Cropped pixels match full-canvas premultiplication; mirror/size invalidation; byte bound; worker shutdown')

        # Bound the queue while allowing one successor during an executing
        # update. Processing slightly over a deadline must not halve the rate.
        messages = queue.Queue()
        def post(*args):
            messages.put(time.perf_counter())
            return True
        clock = PresentationClock(0,post,fps=60)
        clock.start()
        timestamps = []
        try:
            for _ in range(35):
                messages.get(timeout=1)
                clock.pending.clear()  # WM_PRESENT acknowledges on dequeue.
                timestamps.append(time.perf_counter())
                time.sleep(.018)
                assert messages.qsize() <= 1
        finally:
            clock.stop()
        rate = (len(timestamps)-1)/(timestamps[-1]-timestamps[0])
        assert rate > 42, rate
        checks.append('At most one queued presentation; 18ms work does not force a 30Hz scheduling plateau')

        failures = []
        class Probe(hochan_pet.HoChanPet):
            def _wndproc(self,hwnd,message,wparam,lparam):
                try:
                    return super()._wndproc(hwnd,message,wparam,lparam)
                except Exception as error:
                    failures.append(error)
                    win.user32.DestroyWindow(hwnd)
                    return 0

            def _advance(self):
                source = self.animations['working'].frames
                for scale in (1.5,2.25,1.5):
                    previous_dcs = None
                    for index in (0,1,2,3):
                        frame = FrameRenderer.prepare(source,index,scale)
                        width,height = frame.canvas_size
                        self._render_layered_window(self.hwnd,frame,width,height)
                        buffers = self.layered_buffers[self.hwnd]
                        dcs = tuple(surface[0] for surface in buffers.surfaces)
                        assert len(set(dcs)) == 2
                        if previous_dcs:
                            assert previous_dcs == dcs
                        previous_dcs = dcs
                        front = buffers.surfaces[1-buffers.back]
                        actual = ctypes.string_at(front[3],width*height*4)
                        expected = prepare_pixels(frame.canvas(),1)[0]
                        assert actual == expected
                        for origin in ((120, 70), (240, 130)):
                            back = buffers.back
                            assert buffers.move(self.hwnd, origin)
                            assert self._window_rect(self.hwnd)[:2] == origin
                            assert buffers.back == back
                            assert ctypes.string_at(front[3],width*height*4) == expected
                    # Transparent regions from the previous sprite are gone.
                    transparent = PreparedFrame(None,b'',(0,0),(0,0),(width,height))
                    self._render_layered_window(self.hwnd,transparent,width,height)
                    front = buffers.surfaces[1-buffers.back]
                    assert ctypes.string_at(front[3],width*height*4) == bytes(width*height*4)
                win.user32.DestroyWindow(self.hwnd)
                assert not self.layered_buffers
        with patch.object(hochan_pet,'HoChanPet',Probe), patch.object(sys,'argv',[
                'verify_pipeline','--status-file',str(directory/'native/codex-status.json'),
                '--no-codex-observer']):
            hochan_pet.main()
        if failures:
            raise failures[0]
        checks.append('Real DIB pixel parity, atomic moves preserve displayed pixels, transparency clearing, two reused DCs, resize allocation and destruction cleanup')
    result = dict(status='passed',checks=checks,over_budget_clock_rate=round(rate,2))
    (ROOT/'build/pipeline-verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
