"""PCR character selection, presentation clock, scaling and anchored dragging."""
from __future__ import annotations

import argparse
import ctypes
import copy
import hashlib
import os
import random
from pathlib import Path
import sys
import time

import pcr_pet as win
from animation_clock import AnimationClock, load_manifest, packing_keys
from codex_bridge import atomic_json
from character_catalog import discover_characters, startup_character, load_portraits, validate_pack
from context_menu import ContextMenuMixin, WM_MENU_RESULT, SIZE_OPTIONS, read_object
from drag_anchor import DragFacing, hand_anchor, window_at_hand, visible_frame_center
from drag_renderer import DragRenderer
from frame_renderer import FrameRenderer, PreparedFrame
from observer_worker import ObserverWorker
from rendering import PresentationClock, WM_PRESENT, prepare_pixels
from windows_pet import WindowsPet

ROOT = Path(__file__).resolve().parent
PREVIEWS = {'idle': '待机', 'left': '悬浮',
            'reading': '思考', 'working': '执行工具',
            'jump': '完成庆祝', 'question': '等待确认',
            'packing_01': '压缩 1', 'packing_02': '压缩 2',
            'packing_03': '压缩 3', 'packing_04': '压缩 4',
            'bow': '空闲随机 · 鞠躬', 'sleep_body': '休息', 'wake': '挥手唤醒', 'edge_reveal': '边缘展开'}
ONE_SHOTS = {'jump', 'wake', 'edge_reveal', 'bow', 'packing_03', 'packing_04'}


class DemoChoices:
    def __init__(self, clips):
        self.intro = iter(packing_keys(clips))

    def choice(self, keys):
        return next(self.intro, None) or random.choice(keys)


class HoChanPet(ContextMenuMixin, WindowsPet):
    @property
    def last_canvas(self):
        if isinstance(self._last_canvas, PreparedFrame):
            self._last_canvas = self._last_canvas.canvas()
        return self._last_canvas

    @last_canvas.setter
    def last_canvas(self, value):
        self._last_canvas = value

    @property
    def preview_labels(self):
        labels = {key: label for key, label in PREVIEWS.items() if key in self.animations}
        for index, key in enumerate(packing_keys(self.animations), 1):
            labels[key] = f'压缩 {index}'
        return labels

    @property
    def preview_one_shots(self):
        return ONE_SHOTS | {key for key in packing_keys(self.animations) if not self.animations[key].loop}

    def __init__(self, *args, character_id=None, **kwargs):
        self.presentation_clock = None
        self.compaction_demo_until = 0
        self.compaction_demo_clock = None
        self.dpi_scale = 1
        self.size_percent = 100
        self.drop_center_cursor = None
        self.drag_facing = None
        self.presented_drag = None
        self.drag_renderer = None
        self.frame_renderer = None
        self.presented_frame = None
        self.drag_entry_frames = {}
        self.presented_drag_bitmap = None
        self.characters = discover_characters()
        self.character_menu_commands = {}
        source = args[0]['idle'].source.resolve() if args else None
        self.character_id = character_id or next((c.id for c in self.characters.values() if c.asset_dir == source), '')
        self.character_name = self.characters[self.character_id].name if self.character_id in self.characters else '自定义角色'
        super().__init__(*args, **kwargs)
        self.settings_path = self.status_path.parent / 'pet-settings.json'
        settings = read_object(self.settings_path)
        self.hide_bubble_bar = settings.get('hide_bubble_bar') is True
        percent = settings.get('size_percent')
        if type(percent) is int and percent in SIZE_OPTIONS:
            self.size_percent = percent
        self.scale = self.dpi_scale * self.size_percent / 100

    def _refresh_characters(self):
        self.characters = discover_characters()
        if self.character_id in self.characters:
            self.character_name = self.characters[self.character_id].name

    def _load_edge_tail_assets(self):
        character = self.characters.get(self.character_id)
        if character:
            return load_portraits(character)
        return super()._load_edge_tail_assets()

    def _set_character(self, identity):
        if self.dragging or self.mouse_down or self.edge_transition:
            return False
        self._refresh_characters()
        character = self.characters.get(identity)
        if not character or not character.ready:
            self._menu_message('该角色的素材尚未构建完成。')
            return False
        if identity == self.character_id:
            return True
        # Validate and save before replacing any live state. A broken new pack
        # or an unwritable settings file leaves the current character intact.
        try:
            clips = load_manifest(character.asset_dir)
            validate_pack(clips)
            portraits = load_portraits(character)
            settings = read_object(self.settings_path)
            settings['character_id'] = identity
            atomic_json(self.settings_path, settings)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self._menu_message('无法切换角色：\n' + str(error))
            return False
        if self.drag_renderer:
            self.drag_renderer.close()
        self.drag_renderer = None
        if self.frame_renderer:
            self.frame_renderer.clear()
        self.presented_frame = None
        self.presented_drag = self.presented_drag_bitmap = None
        self.animations = clips
        if self.transient_key not in clips:
            self.transient_key = None
        self.edge_tail_assets = portraits
        self.character_id, self.character_name = character.id, character.name
        # Preserve real task/permission state and elapsed animation time, while
        # choosing compaction segments using this character's actual durations.
        clock = AnimationClock(clips)
        clock.tracks = copy.deepcopy(self.clock.tracks)
        for track in clock.tracks.values():
            track.packing = []
        self.clock = clock
        if self.compaction_demo_clock:
            demo = AnimationClock(clips, rng=DemoChoices(clips))
            demo.tracks = copy.deepcopy(self.compaction_demo_clock.tracks)
            for track in demo.tracks.values():
                track.packing = []
            self.compaction_demo_clock = demo
        self.child_rects.clear()
        self.child_sprite_cache.clear()
        self.child_sprite_bytes = 0
        self.last_canvas = None
        self._resolve_visual()
        self._render_current()
        if self.edge_placement:
            self._show_tail(self.edge_placement)
        elif self.hwnd:
            rect = self._window_rect(self.hwnd)
            monitor = self._interaction_monitor()
            if rect and monitor:
                bounds, work = self._current_content_local_bounds(), monitor.work
                origin = tuple(max(work[i]-bounds[i], min(rect[i],work[i+2]-bounds[i+2])) for i in (0,1))
                if origin != rect[:2]:
                    self._set_window_origin(self.hwnd, origin)
        if self.hwnd:
            self._write_heartbeat(force=True)
        return True

    def _set_hide_bubble_bar(self, hidden):
        settings = read_object(self.settings_path)
        settings['hide_bubble_bar'] = hidden
        try:
            atomic_json(self.settings_path, settings)
        except OSError as error:
            self._menu_message('无法保存气泡栏设置：\n' + str(error))
            return
        self.hide_bubble_bar = hidden
        self.selector_visible = False
        self.selector_rect, self.selector_rows = None, []
        self.selector_down = None
        self._render_current()

    def _set_size_percent(self, percent):
        if type(percent) is not int or percent not in SIZE_OPTIONS:
            raise ValueError('Unsupported pet size')
        if self.edge_transition:
            return
        settings = read_object(self.settings_path)
        settings['size_percent'] = percent
        try:
            atomic_json(self.settings_path, settings)
        except OSError as error:
            self._menu_message('无法保存大小设置：\n' + str(error))
            return
        rect = self._window_rect(self.hwnd) if self.hwnd else None
        monitor = self._interaction_monitor() if rect and not self.edge_placement else None
        previous_scale = self.scale
        self.size_percent = percent
        self.scale = self.dpi_scale * percent / 100
        if rect:
            # Keep the character's skeleton root at the same screen location.
            origin = (round(rect[0] + 410 * (previous_scale - self.scale)),
                      round(rect[1] + 570 * (previous_scale - self.scale)))
            self._set_window_origin(self.hwnd, origin)
            self._render_current()
            if self.edge_placement:
                self._show_tail(self.edge_placement)
            elif monitor:
                # Clamp visible content, rather than the transparent 640px canvas.
                bounds = self._current_content_local_bounds()
                work = monitor.work
                origin = tuple(max(work[i] - bounds[i], min(origin[i], work[i+2] - bounds[i+2]))
                               for i in (0, 1))
                self._set_window_origin(self.hwnd, origin)
            self._write_heartbeat(force=True)

    def _start_compaction_demo(self, seconds=40):
        now = time.monotonic()
        self.transient_key = None
        self.leisure.cancel()
        self.compaction_demo_clock = AnimationClock(self.animations, rng=DemoChoices(self.animations))
        self.compaction_demo_clock.update('demo', 'demo', 'packing', now)
        self.compaction_demo_until = now + seconds
        self._resolve_visual()

    def _resolve_visual(self):
        now = self.animation_time()
        if (now < self.compaction_demo_until and not self.dragging
                and not self.permission_request and not self.transient_key):
            self.position = self.compaction_demo_clock.position('demo', now)
            self.frame_index = self.position[1]
            return
        super()._resolve_visual()

    def _schedule_current(self):
        if self.hwnd and self.presentation_clock is None:
            self.observer_worker = ObserverWorker(self.observer)
            self.frame_renderer = FrameRenderer()
            post = win.user32.PostMessageW
            post.argtypes = [win.wintypes.HWND, win.wintypes.UINT, win.wintypes.WPARAM, win.wintypes.LPARAM]
            post.restype = win.wintypes.BOOL
            self.presentation_clock = PresentationClock(self.hwnd, post)
            self.presentation_clock.start()

    def _wndproc(self, hwnd, message, wparam, lparam):
        if message == WM_MENU_RESULT and hwnd == self.hwnd:
            self._finish_menu_job()
            return 0
        if message == WM_PRESENT and hwnd == self.hwnd:
            # The message has left the queue. Permit one successor while this
            # update is executing, without ever accumulating stale requests.
            now = time.monotonic()
            target = self.presentation_clock.target_time if self.presentation_clock else None
            self._presentation_time = target if target is not None and now-target < 2*self.presentation_clock.interval else now
            if self.presentation_clock:
                self.presentation_clock.pending.clear()
            try:
                self._advance()
            finally:
                self._presentation_time = None
            return 0
        if message == win.WM_DESTROY and hwnd == self.hwnd and self.presentation_clock:
            self.presentation_clock.stop()
        return super()._wndproc(hwnd, message, wparam, lparam)

    def run(self):
        try:
            super().run()
        finally:
            if self.presentation_clock:
                self.presentation_clock.stop()
            if self.drag_renderer:
                self.drag_renderer.close()
            if self.frame_renderer:
                self.frame_renderer.close()
            if self.observer_worker:
                self.observer_worker.close()
            for buffers in self.layered_buffers.values():
                buffers.close()
            self.layered_buffers.clear()

    def _warm_drag_entry(self):
        frames = self.animations['left'].frames
        variants = [FrameRenderer.identity(frames, self.scale, mirrored, True) for mirrored in (False, True)]
        if all(variant in self.drag_entry_frames for variant in variants):
            return
        # Prepare both directions before accepting a new drag. Keep these two
        # cropped frames across ordinary animation-cache/clip changes.
        self.drag_entry_frames = {
            variant: FrameRenderer.prepare(frames, 0, self.scale, mirrored, True)
            for variant, mirrored in zip(variants, (False, True))
        }

    def _prepared_bitmap(self):
        if self.frame_renderer is None:
            self.presented_frame = None
            return None
        key, index = self.position
        frames = self.animations[key].frames
        mirrored = key == 'left' and self.dragging and self.drag_mirrored
        locked = key == 'left' and self.dragging
        variant, bitmap = self.frame_renderer.request(frames, index, self.scale, mirrored, locked)
        if self.frame_renderer.error:
            self.presented_frame = None
            return None
        if bitmap is None:
            if self.presented_frame and self.presented_frame[0] == variant:
                _, index, bitmap = self.presented_frame
                self.position, self.frame_index = (key, index), index
            elif locked and index == 0 and variant in self.drag_entry_frames:
                bitmap = self.drag_entry_frames[variant]
            else:
                # A new clip/size/facing is shown immediately; subsequent
                # misses retain the last complete frame and never block input.
                bitmap = FrameRenderer.prepare(frames, index, self.scale, mirrored, locked)
        self.presented_frame = variant, index, bitmap
        self.last_canvas = bitmap
        return bitmap

    def _drag_bitmap(self):
        if not (self.dragging and self.mouse_down and self.drag_start_cursor is not None
                and not self.permission_request and not self.selector_visible
                and not self.store.children(self.store.selected, time.time())):
            self.presented_drag_bitmap = None
            return None
        if self.drag_renderer is None:
            self.drag_renderer = DragRenderer(self.animations['left'].frames)
        if self.drag_renderer.error is not None:
            return None
        index, scale, mirrored = self.frame_index, self.scale, self.drag_mirrored
        bitmap = self.drag_renderer.get(index, scale, mirrored)
        if bitmap is None:
            if (self.presented_drag is not None and self.presented_drag_bitmap is not None
                    and self.presented_drag[1:] == (mirrored, scale)):
                # Keep moving the displayed frame while its successor is being
                # prepared. Never make pointer events wait for decoding or resizing.
                bitmap = self.presented_drag_bitmap
                self.frame_index = self.presented_drag[0]
                self.position = ('left', self.frame_index)
            else:
                canvas = self.compose(render_scale=scale)
                pixels, size = prepare_pixels(canvas, 1)
                bitmap = canvas, pixels, size
                self.drag_renderer.request(index, scale, mirrored, seed=bitmap)
                return bitmap
        self.drag_renderer.request(index, scale, mirrored)
        self.last_canvas = bitmap[0]
        return bitmap

    def _render_current(self):
        if not self.hwnd:
            return
        # Sample source artwork directly at DPI times pet size. Logical UI and
        # input coordinates remain independent of the physical output bitmap.
        get_dpi = win.user32.GetDpiForWindow
        get_dpi.argtypes = [win.wintypes.HWND]
        get_dpi.restype = ctypes.c_uint
        self.dpi_scale = (get_dpi(self.hwnd) or 96) / 96
        self.scale = self.dpi_scale * self.size_percent / 100
        if self.drag_facing is not None and self.dragging and self.mouse_down:
            point = win.POINT()
            if win.user32.GetCursorPos(ctypes.byref(point)):
                self.drag_direction = self.drag_facing.update(point.x, time.monotonic(), self.scale)
        prepared = self._prepared_bitmap()
        bitmap = None
        overlays = (self.current_key == 'jump' or self.permission_request or self.selector_visible
                    or self.store.children(self.store.selected, time.time()))
        if prepared is not None and not overlays:
            self.child_rects.clear()
            pixels = prepared
            width, height = prepared.canvas_size
        elif prepared is not None:
            canvas = self.compose(render_scale=self.scale, artwork=prepared.canvas())
            pixels = PreparedFrame.from_canvas(canvas)
            width, height = canvas.size
        else:
            bitmap = self._drag_bitmap()
            if bitmap is None:
                canvas = self.compose(render_scale=self.scale)
                pixels = PreparedFrame.from_canvas(canvas)
                width, height = canvas.size
            else:
                canvas, pixels, (width, height) = bitmap
        # Sample the pointer after pixel preparation, then submit position and
        # bitmap together. Never move the old bitmap to the new frame's anchor.
        origin = self._drag_origin(self.frame_index, self.drag_mirrored, self.scale)
        if not self.dragging and self.drop_center_cursor is not None and not self.edge_transition:
            # Restore the action and its calibrated drop position in the same
            # upload, using the frame actually selected by the renderer.
            key, index = self.position
            center = visible_frame_center(self.animations[key].frames[index], self.drag_direction)
            origin = window_at_hand(self.drop_center_cursor, center, self.scale)
        if origin is None and not self.scaled_once:
            rect = self._window_rect(self.hwnd)
            if rect:
                logical_size = round(640*self.scale)
                origin = (rect[0]+640-logical_size, rect[1]+640-logical_size)
        # Invoke only the native upload, bypassing the redundant DPI pipeline.
        self._render_layered_window(self.hwnd, pixels, width, height, origin=origin)
        self.scaled_once = True
        self.presented_drag = (self.frame_index, self.drag_mirrored, self.scale) if origin is not None and self.dragging else None
        self.presented_drag_bitmap = bitmap if self.presented_drag is not None else None
        if not self.dragging:
            self._warm_drag_entry()


    def _drag_origin(self, index, mirrored, scale):
        if not (self.hwnd and self.dragging and self.mouse_down and self.drag_start_cursor is not None):
            return None
        point = win.POINT()
        if not win.user32.GetCursorPos(ctypes.byref(point)):
            return None
        # The bitmap moves the palm to frame zero at subpixel precision. Keep
        # this physical origin constant while the pointer remains stationary.
        anchor = hand_anchor(self.animations['left'], 0, mirrored)
        return window_at_hand((point.x, point.y), anchor, scale)

    def _align_drag_hand(self):
        if self.presented_drag is None:
            return
        # Fast pointer events may reposition only the bitmap already on screen.
        origin = self._drag_origin(*self.presented_drag)
        if origin is None:
            return
        rect = self._window_rect(self.hwnd)
        if rect and rect[:2] != origin:
            buffers = self.layered_buffers.get(self.hwnd)
            if buffers:
                buffers.move(self.hwnd, origin)

    def _handle_mouse_move(self, wparam):
        if self.permission_button_down is not None:
            self._render_current()
            return
        if (self.permission_bubble_down or not self.hwnd or not self.mouse_down
                or not wparam & win.MK_LBUTTON or self.drag_start_cursor is None):
            return
        point = win.POINT()
        win.user32.GetCursorPos(ctypes.byref(point))
        dx, dy = point.x-self.drag_start_cursor[0], point.y-self.drag_start_cursor[1]
        if not self.dragging:
            if abs(dx) < win.DRAG_THRESHOLD_PIXELS and abs(dy) < win.DRAG_THRESHOLD_PIXELS:
                return
            self.dragging = True
            self.selector_visible = False
            self.success_effect_started = None
            if dx:
                self.drag_direction = 1 if dx > 0 else -1
            self.drag_facing = DragFacing(point.x, self.drag_direction)
            if self.drag_sleep_phase == 'sleeping':
                self.leisure.reset(time.monotonic())
            else:
                self.leisure.cancel()
            self._switch_visual('left')
            return
        previous_direction = self.drag_direction
        if self.drag_facing is not None:
            self.drag_direction = self.drag_facing.update(point.x, time.monotonic(), self.scale)
        # The next presentation tick advances the frame. Mouse movement only
        # moves the existing image, except when a flip requires new pixels.
        if previous_direction != self.drag_direction:
            self._render_current()
        else:
            self._align_drag_hand()

    def _handle_left_button_up(self):
        self.drop_center_cursor = None
        if self.mouse_down and self.dragging and self.drag_previous is not None and self.drag_start_cursor is not None:
            point = win.POINT()
            if win.user32.GetCursorPos(ctypes.byref(point)):
                self.drop_center_cursor = (point.x, point.y)
        if self.mouse_down and not self.dragging and self.leisure.phase in ('entering', 'sleeping'):
            # Rest uses a standing clip, so a click always gives visible feedback.
            self.leisure.click(time.monotonic(), wake=True)
        try:
            super()._handle_left_button_up()
        finally:
            self.drop_center_cursor = None
            self.drag_facing = None
            self.presented_drag = None
            self.presented_drag_bitmap = None
            if self.drag_renderer:
                self.drag_renderer.clear()

    def _cancel_mouse_drag(self):
        try:
            super()._cancel_mouse_drag()
        finally:
            self.drag_facing = None
            self.presented_drag = None
            self.presented_drag_bitmap = None
            if self.drag_renderer:
                self.drag_renderer.clear()

    def _restore_after_drag(self, previous):
        # Rendering applies the drop origin atomically before the inherited
        # mouse-up path checks whether the restored pet touches an edge.
        super()._restore_after_drag(previous)
        if self.drop_center_cursor is not None and self.hwnd:
            self._write_heartbeat(force=True)

    def _qa_control(self):
        # Use the actual drag selection/composition in isolated runtime tests.
        if os.environ.get('PCR_QA_WINDOW') == '1' and not self.observer.enabled:
            command = win.read_json_file(self.status_path.parent / 'qa-command.json')
            if command and command.get('action') in ('drag', 'auto') and command.get('id') not in self.qa_commands:
                self.qa_commands.add(command['id'])
                atomic_json(self.status_path.parent / 'qa-consumed.json', {'ids': sorted(self.qa_commands)})
                if command['action'] == 'drag':
                    self.dragging = bool(command.get('enabled'))
                    self.drag_direction = int(command.get('direction', -1))
                else:
                    self.transient_key = None
                    self.leisure.cancel()
                self.selector_visible = False
                self._resolve_visual()
                return
        super()._qa_control()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-dir', type=Path, help='Override a registered character with an external resource pack')
    parser.add_argument('--character', help='Character id registered under characters/')
    parser.add_argument('--status-file', type=Path, default=ROOT / 'state/codex-status.json')
    parser.add_argument('--no-codex-observer', action='store_true')
    parser.add_argument('--qa-window', action='store_true')
    parser.add_argument('--preview', choices=list(PREVIEWS), help='Loop one animation without reading real Codex state')
    parser.add_argument('--demo-compacting', type=float, nargs='?', const=40, help='Simulate the compaction scene for N seconds (default 40)')
    args = parser.parse_args()
    if args.demo_compacting is not None and (args.demo_compacting <= 0 or args.preview):
        parser.error('--demo-compacting needs a positive duration and cannot be combined with --preview')
    if args.qa_window:
        os.environ['PCR_QA_WINDOW'] = '1'
    status = args.status_file.resolve()
    status.parent.mkdir(parents=True, exist_ok=True)
    if args.asset_dir and args.character:
        parser.error('--asset-dir and --character cannot be combined')
    try:
        character = None if args.asset_dir else startup_character(
            read_object(status.parent / 'pet-settings.json'), args.character)
    except (ValueError, KeyError) as error:
        parser.error(str(error))
    win.APP_NAME = 'Ho-chan Desktop Pet'
    win.CLASS_NAME = 'HoChanDesktopPetWindow'
    mutex_name = 'Local\\HoChanDesktopPet-' + hashlib.sha256(str(status).encode()).hexdigest()[:12]
    mutex = win.kernel32.CreateMutexW(None, False, mutex_name)
    if not mutex or win.kernel32.GetLastError() == 183:
        return
    clips = load_manifest(args.asset_dir.resolve() if args.asset_dir else character.asset_dir)
    validate_pack(clips)
    if args.preview and args.preview not in clips:
        parser.error('This character does not have the requested preview animation')
    pet = HoChanPet(clips, ROOT, status,
                    observe=not (args.no_codex_observer or args.preview),
                    character_id=character.id if character else None)
    pet.allow_codex_observer = not args.no_codex_observer
    if args.preview:
        pet.transient_key = args.preview
        pet.transient_once = False
        pet._resolve_visual()
    if args.demo_compacting:
        pet._start_compaction_demo(args.demo_compacting)
    try:
        pet.run()
    finally:
        win.kernel32.CloseHandle(mutex)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        win.log_exception(ROOT / 'startup-error.log')
        raise
