"""Verify pack pixels, character switching, persistence and native drag/edges."""
import ctypes
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest.mock import patch
import uuid

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from character_catalog import discover_characters, startup_character, validate_pack, load_portraits
from animation_clock import load_manifest
from codex_bridge import atomic_json, publish_event
from drag_anchor import hand_anchor, window_at_hand
from drag_renderer import DragRenderer
import hochan_pet
import pcr_pet as win


def verify_resources(character):
    clips = load_manifest(character.asset_dir)
    validate_pack(clips)
    skin = json.loads(character.skin_path.read_text(encoding='utf-8'))
    visible_frames = 0
    grid = Image.new('RGBA', (1200, 1400), '#f5f3ef')
    draw = ImageDraw.Draw(grid)
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 18)
    draw.text((16, 10), character.name, font=font, fill='#30343b')
    for cell, (key, spec) in enumerate(skin['animations'].items()):
        clip = clips[key]
        assert clip.total_duration == round(spec['duration_seconds']*1000)
        for index in range(len(clip.frames)):
            image = clip.frames[index]
            assert image.size == clip.frames.canvas_size and image.mode == 'RGBA'
            box = image.getchannel('A').getbbox()
            assert box and min(box) > 0 and box[2] < image.width and box[3] < image.height, (character.id, key, index, box)
            high = clip.frames.specs[index]['hires']
            assert high['scale'] == 3
            with Image.open(clip.source / high['file']) as source:
                source.load()
                assert source.mode == 'RGBA' and all(v % 3 == 0 for v in source.size)
                assert all(0 <= high['origin'][i]+source.size[i]/3 <= clip.frames.canvas_size[i] for i in (0, 1))
            visible_frames += 1
        x, y = cell % 4 * 300, cell // 4 * 340 + 44
        draw.text((x+12, y), spec['label'], font=font, fill='#30343b')
        image = clip.frames[clip.frame(clip.total_duration/2000)].copy()
        image.thumbnail((288, 288), Image.Resampling.LANCZOS)
        grid.alpha_composite(image, (x+6, y+28))
        assert len(clip.frames.cache) <= 8
    for index in range(len(clips['left'].frames)):
        point = hand_anchor(clips['left'], index)
        assert clips['left'].frames[index].getpixel(tuple(round(v) for v in point))[3] > 128
        for scale in (1.125, 1.5, 1.875, 2.25):
            for mirrored in (False, True):
                anchor = hand_anchor(clips['left'], index, mirrored)
                origin = window_at_hand((900, 700), anchor, scale)
                assert max(abs(origin[i]+anchor[i]*scale-(900, 700)[i]) for i in (0, 1)) <= .500001
    for alias, source in skin['aliases'].items():
        assert clips[alias].frames.specs == clips[source].frames.specs
    portraits = load_portraits(character)
    assert all(image.getbbox() for image in portraits.values())
    output = ROOT / 'preview/characters' / character.id
    output.mkdir(parents=True, exist_ok=True)
    grid.convert('RGB').save(output / 'all-states.png')
    return dict(id=character.id, name=character.name, visible_frames=visible_frames,
                hand_geometry_cases=len(clips['left'].frames)*8)


def main():
    catalog = discover_characters(strict=True)
    assert [catalog[key].name for key in ('ho-chan', 'kyouka-gothic')] == ['ホウオウ', 'キョウカ（ゴシック）']
    resources = [verify_resources(character) for character in catalog.values()]
    assert startup_character({'character_id': ['invalid']}).id == 'ho-chan'
    assert startup_character({'character_id': 'missing'}).id == 'ho-chan'
    assert startup_character({'character_id': 'kyouka-gothic'}).id == 'kyouka-gothic'
    # Authoring a third descriptor is sufficient for discovery; broken author
    # folders do not suppress working descriptors or alter production settings.
    with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
        temporary = Path(directory)
        future = temporary / 'characters/future'
        future.mkdir(parents=True)
        (future / 'skin.json').write_text('{}', encoding='utf-8')
        atomic_json(future / 'character.json', dict(id='future', name='Future', model='123456',
                    skin='skin.json', asset_dir='assets/future/animation-resources'))
        invalid = temporary / 'characters/unfinished'
        invalid.mkdir()
        (invalid / 'character.json').write_text('{', encoding='utf-8')
        assert list(discover_characters(temporary)) == ['future']
        assert not discover_characters(temporary)['future'].ready
    state = ROOT / 'build' / ('characters-' + uuid.uuid4().hex[:8])
    atomic_json(state / 'pet-settings.json', dict(size_percent=150, keep='existing-setting'))
    base = hochan_pet.HoChanPet
    failures, native = [], []

    class Probe(base):
        pass_number = 0
        stage = 0
        began = None

        def _poll_bridge(self, force=False):
            if self.pass_number == 1:
                return False
            return super()._poll_bridge(force=force)

        def _wndproc(self, hwnd, message, wparam, lparam):
            try:
                return super()._wndproc(hwnd, message, wparam, lparam)
            except Exception as error:
                traceback.print_exc()
                failures.append(error)
                win.user32.DestroyWindow(hwnd)
                return 0

        def _advance(self):
            if self.began is None:
                self.began = time.monotonic()
            assert time.monotonic()-self.began < 12, 'Native character test timed out'
            if self.stage == 0:
                self._set_window_origin(self.hwnd, (100, 0))
                assert self.size_percent == 150
                if self.pass_number == 0:
                    assert self.character_id == 'ho-chan'
                    publish_event(state, dict(session_id='character-test', turn_id='t1', event='UserPromptSubmit'))
                    publish_event(state, dict(session_id='character-test', turn_id='t1', event='PreToolUse'))
                    publish_event(state, dict(session_id='character-test', turn_id='t1', event='SubagentStart', agent_id='child-test'))
                    self._poll_bridge(force=True)
                    if self.observer_worker:
                        with self.observer_worker.condition:
                            assert self.observer_worker.condition.wait_for(lambda: not self.observer_worker.busy, timeout=3)
                        self._poll_bridge(force=True)
                    self._resolve_visual()
                    assert self.current_key == 'working'
                    old_node = self.store.nodes['character-test']
                    menu = self._create_context_menu()
                    win.user32.DestroyMenu(menu)
                    self._render_current()
                    before = self.last_canvas.tobytes()
                    old_worker = self.drag_renderer = DragRenderer(self.animations['left'].frames)
                    old_worker.request(0, self.scale, False)
                    self._handle_menu_command(401)
                    assert self.character_id == 'kyouka-gothic' and old_worker.stopped
                    assert self.drag_renderer is None and self.presented_drag_bitmap is None
                    assert self.store.nodes['character-test'] is old_node and self.current_key == 'working'
                    assert self.child_rects and self.animations['working'].source == catalog['kyouka-gothic'].asset_dir
                    assert self.last_canvas.tobytes() != before
                    saved = json.loads(self.settings_path.read_text(encoding='utf-8'))
                    assert saved == dict(size_percent=150, keep='existing-setting', character_id='kyouka-gothic')
                    # A write failure cannot change the live character or its clocks.
                    clock = self.clock
                    with patch.object(hochan_pet, 'atomic_json', side_effect=OSError('read-only fixture')), patch.object(self, '_menu_message'):
                        assert not self._set_character('ho-chan')
                    assert self.character_id == 'kyouka-gothic' and self.clock is clock
                    self.permission_request = {'summary': 'Isolated character confirmation fixture'}
                    self.permission_request_id = 'character-permission'
                    assert self._set_character('ho-chan')
                    assert self.permission_request_id == 'character-permission'
                    assert self.current_key == 'question' and self.permission_buttons
                    self.permission_request, self.permission_request_id = None, ''
                    self.dragging = True
                    assert not self._set_character('kyouka-gothic')
                    self.dragging = False
                    self.edge_transition = 'hiding'
                    assert not self._set_character('kyouka-gothic')
                    self.edge_transition = None
                    assert self._set_character('kyouka-gothic')
                    # Real menu previews and their automatic return must keep
                    # the window origin stable, including the padded canvas.
                    preview_origin = self._window_rect(self.hwnd)[:2]
                    for key in ('packing_01', 'packing_02', 'packing_03'):
                        self._handle_menu_command(201+list(self.preview_labels).index(key))
                        assert self.transient_once and self.current_key == key
                        self._render_current()
                        assert self._window_rect(self.hwnd)[:2] == preview_origin
                        clip = self.animations[key]
                        self.visual_epoch = self.animation_time()-clip.total_duration/1000-.01
                        self._resolve_visual()
                        self._render_current()
                        assert self.current_key == 'working' and self.transient_key is None
                        assert self._window_rect(self.hwnd)[:2] == preview_origin
                        assert self.last_canvas.size == (round(640*self.scale), round(704*self.scale))
                    native.append('All three native compaction previews and automatic returns keep the same screen origin')
                    # Native animated palm tracking, with substituted input only.
                    def cursor(pointer):
                        point = ctypes.cast(pointer, ctypes.POINTER(win.POINT)).contents
                        point.x, point.y = 900, 700
                        return True
                    self.dragging = self.mouse_down = True
                    self.drag_start_cursor = (900, 700)
                    with patch.object(win.user32, 'GetCursorPos', cursor):
                        for direction in (-1, 1):
                            self.drag_direction = direction
                            positions = []
                            for index in (0, 10, 20, 30):
                                self.position, self.frame_index = ('left', index), index
                                self._render_current()
                                rect = self._window_rect(self.hwnd)
                                anchor = hand_anchor(self.animations['left'], 0, direction < 0)
                                assert max(abs(rect[i]+anchor[i]*self.scale-(900, 700)[i]) for i in (0, 1)) <= .500001
                                positions.append(rect[:2])
                            assert len(set(positions)) == 1
                    self.dragging = self.mouse_down = False
                    self.drag_start_cursor = None
                    self._resolve_visual()
                    self._render_current()
                    native.append('Menu switches live task and child; settings preserved; old worker released; permission retained; failed save rolls back; native gothic palm stays fixed')
                    self.stage = 1
                else:
                    assert self.character_id == 'kyouka-gothic'
                    assert self.animations['idle'].source == catalog['kyouka-gothic'].asset_dir
                    # Hide while idle, then change portraits without revealing.
                    for node in self.store.nodes.values():
                        node.active, node.completion = False, None
                    self.store.nodes.clear()
                    self.store.selected = ''
                    self._resolve_visual()
                    monitor = win.enumerate_monitor_infos()[0]
                    bounds = self._current_pet_local_bounds()
                    self._set_window_origin(self.hwnd, (monitor.frame[2]-bounds[2]+2, 0))
                    self._begin_edge_hide_if_needed()
                    self.stage = 2
            elif self.stage == 2 and self.edge_placement and self.edge_transition is None:
                assert win.user32.IsWindowVisible(self.tail_hwnd)
                old = self.edge_tail_assets['right'].tobytes()
                assert self._set_character('ho-chan')
                assert self.edge_tail_assets['right'].tobytes() != old
                assert win.user32.IsWindowVisible(self.tail_hwnd) and self.edge_placement
                assert self._set_character('kyouka-gothic')
                native.append('Fresh process restores gothic selection; hidden-edge portraits switch with the character')
                self.stage = 3
            super()._advance()
            if self.stage == 1 and time.monotonic()-self.began > .7 or self.stage == 3:
                win.user32.DestroyWindow(self.hwnd)

    hochan_pet.HoChanPet = Probe
    for number in (0, 1):
        Probe.pass_number = number
        sys.argv = [sys.argv[0], '--status-file', str(state / 'codex-status.json'), '--no-codex-observer']
        hochan_pet.main()
        assert not failures, failures
        unregister = win.user32.UnregisterClassW
        unregister.argtypes = [win.wintypes.LPCWSTR, win.wintypes.HINSTANCE]
        assert unregister(win.CLASS_NAME, win.kernel32.GetModuleHandleW(None))
    result = dict(status='passed', resources=resources, native_checks=native,
                  startup='Saved selection, malformed settings, unknown ids and future pack discovery checked',
                  isolated_state=str(state))
    (ROOT / 'build/characters-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
