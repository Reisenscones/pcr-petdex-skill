"""Codex task families, animation selection, scene composition and permission UI."""
from __future__ import annotations
import ctypes
import os
import time
from collections import OrderedDict
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFilter
import pcr_pet as win
from animation_clock import AnimationClock
from drag_anchor import hand_lock_offset
from family_store import FamilyStore
from codex_observer import CodexObserver
from leisure import Leisure
from codex_bridge import atomic_json

SLOTS = [(310,575),(410,615),(510,575)]
APP_VERSION = '0.5.1-windows'
APP_BUILD = '20261019.1-compact-assets'


@lru_cache(maxsize=4)
def permission_surface(rect):
    left,top,right,bottom = rect
    height = bottom-top
    mask_large = Image.new('L',(1920,1920))
    shape = ImageDraw.Draw(mask_large)
    shape.rounded_rectangle(tuple(v*3 for v in rect),60,fill=255)
    shape.polygon([(402*3,(bottom-1)*3),(418*3,(bottom-1)*3),(410*3,(bottom+10)*3)],fill=255)
    mask = mask_large.resize((640,640),Image.Resampling.LANCZOS)
    inside = mask.filter(ImageFilter.MinFilter(5))
    gradient = Image.new('RGBA',(640,640))
    pixels = gradient.load()
    for y in range(max(0,top),bottom+14):
        for x in range(left,right+1):
            t = min(1,((x-left)*320+(y-top)*(height+10))/(320**2+(height+10)**2))
            pixels[x,y] = (round(253-2*t),round(249-19*t),round(246-11*t),255)
    shadow = Image.new('RGBA',(640,640),(0,0,0,0))
    shadow.putalpha(mask.filter(ImageFilter.GaussianBlur(8)).point(lambda v:round(v*.18)))
    canvas = Image.new('RGBA',(640,640))
    canvas.alpha_composite(shadow,(0,4))
    border = Image.new('RGBA',(640,640),(231,169,188,255))
    canvas.alpha_composite(Image.composite(border,Image.new('RGBA',(640,640)),mask))
    canvas.alpha_composite(Image.composite(gradient,Image.new('RGBA',(640,640)),inside))
    return canvas


def union(rects):
    return (min(r[0] for r in rects),min(r[1] for r in rects),max(r[2] for r in rects),max(r[3] for r in rects))


def resize_alpha(image, size):
    return image.convert('RGBa').resize(size,Image.Resampling.BILINEAR).convert('RGBA')


def family_tail_rects(edge, main, screen, count, scale=1):
    rects = [main]
    vertical = edge in ('left','right')
    side, gap = round(32*scale), round(4*scale)
    start = main[3]+gap if vertical else main[2]+gap
    low, high = (screen[1],screen[3]) if vertical else (screen[0],screen[2])
    # Shift the entire along-edge group to retain ordering at either corner.
    total = round(68*scale)+count*(side+gap)
    begin = max(low+4,min((main[1] if vertical else main[0]),high-total-4))
    shift = begin-(main[1] if vertical else main[0])
    rects[0] = (main[0],main[1]+shift,main[2],main[3]+shift) if vertical else (main[0]+shift,main[1],main[2]+shift,main[3])
    start += shift
    for i in range(count):
        along = start+i*(side+gap)
        if edge == 'left':
            rect = (screen[0]-round(18*scale),along,screen[0]+round(14*scale),along+side)
        elif edge == 'right':
            rect = (screen[2]-round(14*scale),along,screen[2]+round(18*scale),along+side)
        elif edge == 'top':
            rect = (along,screen[1]-round(18*scale),along+side,screen[1]+round(14*scale))
        else:
            rect = (along,screen[3]-round(14*scale),along+side,screen[3]+round(18*scale))
        rects.append(rect)
    return rects


class WindowsPet(win.PcrPet):
    def __init__(self, animations, app_dir, status_path, observe=True):
        self.store = FamilyStore()
        self.observer = CodexObserver(self.store,status_path.parent,enabled=observe)
        self.observer_worker = None
        self.clock = AnimationClock(animations)
        self.leisure = Leisure(time.monotonic())
        self.position = ('idle',0)
        self.visual_epoch = time.monotonic()
        self.idle_epoch = self.visual_epoch
        self.hidden_tokens = set()
        self.known_work = set()
        self.drag_direction = -1
        self.child_positions, self.child_rects = {}, {}
        self.hide_bubble_bar = False
        self.selector_visible, self.selector_last_hover = False, 0
        self.selector_rect, self.selector_rows = None, []
        self.selector_scroll, self.selector_down = 0, None
        self.focused_child = ''
        self.permission_page, self.permission_viewed = 0, set()
        self.permission_actors = set()
        self.permission_visual_epoch = time.monotonic()
        self.permission_lines_key, self.permission_lines = None, []
        self.last_canvas = None
        self.child_sprite_cache = OrderedDict()
        self.child_sprite_bytes = 0
        self.last_family_poll = 0
        self.scale = 1
        self.scaled_once = False
        self.qa_commands = set()
        if os.environ.get('PCR_QA_WINDOW') == '1' and not observe:
            seen = win.read_json_file(status_path.parent/'qa-consumed.json')
            self.qa_commands = set(seen.get('ids',[])) if seen else set()
        super().__init__(animations,app_dir,status_path)

    @property
    def current_key(self):
        return self.position[0]

    @property
    def drag_mirrored(self):
        # Ho-chan's floating source faces right; mirror for leftward movement.
        return self.drag_direction < 0

    @property
    def can_hide_at_desktop_edge(self):
        return self.edge_placement is None and self.edge_transition is None and bool(self.edge_tail_assets)

    @property
    def activity_requires_visible_pet(self):
        return bool(self.permission_request or self.store.work_tokens()-self.hidden_tokens)

    def _apply_bridge_payload(self,payload):
        # Legacy events have their own actor, never occupy another task's slot.
        if not payload.get('session_id') and payload.get('token'):
            p = dict(payload,session_id='legacy')
            return self.store.ingest(p,time.time())
        return False

    def _switch_visual(self,key,once=False):
        self.transient_key, self.transient_once = key, once
        self.visual_epoch = time.monotonic()
        self._resolve_visual()
        self._render_current()
        self._schedule_current()

    def _poll_bridge(self,force=False):
        now = time.monotonic()
        if not force and now-self.last_family_poll < .2:
            return False
        self.last_family_poll = now
        if self.observer_worker:
            self.observer_worker.poll()
        else:
            self.observer.poll()
        legacy = win.read_status(self.status_path)
        self._apply_bridge_payload(legacy)
        tokens = self.store.work_tokens()
        if tokens-self.known_work:
            self.leisure.reset(now)
            if not self.dragging and not self.edge_transition:
                self.transient_key = None
        self.known_work |= tokens
        self._sync_family_permission()
        if self.permission_request:
            self.leisure.cancel()
            if not self.dragging and not self.edge_transition:
                self.transient_key = None
        wall = time.time()
        for node in self.store.nodes.values():
            state = 'question' if node.id in self.permission_actors else self.store.visual(node,wall)
            parent = self.store.nodes.get(node.parent)
            changed = max(node.changed,parent.changed) if parent and self.store.paused(node) else node.changed
            self.clock.update(node.id,node.turn,state,now,max(0,wall-changed))
        self._reveal_for_activity_if_needed()
        return False

    def _sync_family_permission(self):
        now = time.time()
        node = self.store.nodes.get(self.focused_child) or self.store.nodes.get(self.store.selected)
        candidates = ([node] if node else []) + self.store.children(self.store.selected,now)
        if self.permission_request_id:
            actor = self.permission_request.get('agent_id') or self.permission_request.get('session_id')
            old = self.store.nodes.get(actor)
            if old in candidates:
                candidates = [old]+[n for n in candidates if n is not old]
        pending = {}
        for file in sorted(self.permission_dir.glob('*.request.json')):
            p = win.read_json_file(file)
            if not p:
                continue
            request_id = p.get('request_id','')
            actor = p.get('agent_id') or p.get('session_id')
            actor_node = self.store.nodes.get(actor)
            expired = self._permission_request_expired(p)
            requested_turn = p.get('turn_id')
            different_turn = bool(actor_node and requested_turn and actor_node.turn and requested_turn != actor_node.turn)
            # A request can arrive before the background observer delivers its
            # new-turn event. Only a retired turn is known to be stale; do not
            # delete a future turn's IPC file against an older GUI snapshot.
            stale = bool(actor_node and (
                different_turn and requested_turn in actor_node.retired or
                not different_turn and (actor_node.status == 'interrupted' or actor_node.completion is not None)))
            helper_pid = p.get('hook_pid')
            dead = False
            if helper_pid:
                open_process = win.kernel32.OpenProcess
                open_process.argtypes = [ctypes.c_uint,ctypes.c_bool,ctypes.c_uint]
                open_process.restype = win.wintypes.HANDLE
                handle = open_process(0x1000,False,int(helper_pid))
                dead = not bool(handle)
                if handle:
                    code = ctypes.c_uint()
                    get_exit = win.kernel32.GetExitCodeProcess
                    get_exit.argtypes = [win.wintypes.HANDLE,ctypes.POINTER(ctypes.c_uint)]
                    dead = bool(get_exit(handle,ctypes.byref(code))) and code.value != 259
                    win.kernel32.CloseHandle(handle)
            if expired or stale or dead:
                file.unlink(missing_ok=True)
                self._permission_response_path(request_id).unlink(missing_ok=True)
                if actor_node and actor_node.status=='permission' and not stale:
                    self.store.ingest(dict(actor_node.payload,status='idle',event='PermissionNoDecision',token='expired-'+request_id,permission_request_id=''),time.time())
                continue
            if different_turn:
                continue
            if not self._permission_response_path(request_id).exists():
                pending.setdefault(actor,[]).append(p)
        request = None
        self.permission_actors = set(pending)
        for actor in candidates:
            requests = pending.get(actor.id,[])
            if requests:
                request = min(requests,key=lambda p:p.get('created_at',''))
                break
        old_id = self.permission_request_id
        self.permission_request = request
        self.permission_request_id = request.get('request_id','') if request else ''
        if old_id != self.permission_request_id:
            self.permission_page = 0
            self.permission_button_down = None
            self.permission_visual_epoch = time.monotonic()

    def animation_time(self):
        target = getattr(self, '_presentation_time', None)
        return time.monotonic() if target is None else target

    def _resolve_visual(self):
        now, wall = self.animation_time(),time.time()
        if self.dragging:
            self.position = ('left',self.animations['left'].frame(now-self.visual_epoch))
        elif self.transient_key:
            clip = self.animations[self.transient_key]
            elapsed = now-self.visual_epoch
            if self.transient_once and elapsed >= clip.total_duration/1000:
                self.transient_key = None
                return self._resolve_visual()
            self.position = (clip.key,clip.frame(elapsed,self.transient_once))
        elif self.permission_request:
            self.position = ('question',self.animations['question'].frame(now-self.permission_visual_epoch,True))
        else:
            selected = self.store.nodes.get(self.store.selected)
            state = self.store.visual(selected,wall) if selected else 'idle'
            active = bool(self.store.work_tokens())
            if active or selected and (selected.active or state == 'jump' and self.clock.position(selected.id,now)):
                self.leisure.cancel()
                self.position = self.clock.position(selected.id,now) if selected else None
            else:
                self.leisure.tick(now,not self.mouse_down and self.edge_placement is None and self.edge_transition is None)
                self.position = self.leisure.position(self.animations,now)
            self.position = self.position or ('idle',self.animations['idle'].frame(now-self.idle_epoch))
        self.frame_index = self.position[1]

    def _advance(self):
        self._qa_control()
        self._poll_bridge()
        self._resolve_visual()
        self._update_hover()
        self._render_current()
        self._write_heartbeat()
        self._schedule_current()

    def _qa_control(self):
        # Explicit isolated developer mode; never reads commands in production.
        if os.environ.get('PCR_QA_WINDOW') != '1' or self.observer.enabled:
            return
        path = self.status_path.parent/'qa-command.json'
        command = win.read_json_file(path)
        if not command or command.get('id') in self.qa_commands:
            return
        self.qa_commands.add(command.get('id'))
        atomic_json(self.status_path.parent/'qa-consumed.json',{'ids':sorted(self.qa_commands)})
        action = command.get('action')
        if action == 'preview' and command.get('key') in self.animations:
            self._switch_visual(command['key'],once=bool(command.get('once')))
        elif action == 'rest' and not self.store.work_tokens():
            self.transient_key=None
            self.leisure.enter(time.monotonic())
        elif action == 'sleep-click':
            self.leisure.click(time.monotonic(),command.get('wake'))
        elif action == 'edge':
            edge = command.get('edge')
            monitor = win.enumerate_monitor_infos()[0]
            bounds = self._current_pet_local_bounds()
            rect = self._window_rect(self.hwnd)
            x,y = rect[:2]
            if edge=='left': x=monitor.frame[0]-bounds[0]-2
            elif edge=='right': x=monitor.frame[2]-bounds[2]+2
            elif edge=='top': y=monitor.frame[1]-bounds[1]-2
            elif edge=='bottom': y=monitor.frame[3]-bounds[3]+2
            else: return
            self._set_window_origin(self.hwnd,(x,y))
            self._begin_edge_hide_if_needed()
        elif action == 'reveal':
            self._begin_edge_reveal(True)
        elif action == 'select' and command.get('actor') in self.store.nodes:
            self.store.select(command['actor'])
            self.focused_child=''
        elif action == 'capture':
            target = self.status_path.parent/'captures'
            target.mkdir(exist_ok=True)
            self.compose().save(target/(str(len(self.qa_commands))+'.png'))
        elif action == 'exit':
            win.user32.DestroyWindow(self.hwnd)


    def compose(self,key=None,index=None,render_scale=1,artwork=None):
        now = self.animation_time()
        key, index = (key,index) if key is not None else self.position
        frames = self.animations[key].frames
        mirrored = key == 'left' and self.dragging and self.drag_mirrored
        offset = hand_lock_offset(frames, index, mirrored) if key == 'left' and self.dragging else (0, 0)
        if artwork is None:
            artwork = frames.render(index, render_scale, mirrored=mirrored, offset=offset)
        # UI and hit rectangles retain their logical coordinates. Only artwork
        # samples the high-resolution export, before the two layers are joined.
        canvas = artwork if render_scale == 1 else Image.new('RGBA',frames.canvas_size)
        if key == 'jump':
            node = self.store.nodes.get(self.store.selected)
            self.success_effect_started = now-max(0,time.time()-node.completion) if node and node.completion else self.visual_epoch
            self._composite_success_effects(canvas)
        children = self.store.children(self.store.selected,time.time())
        self.child_rects = {}
        for i,node in enumerate(children[:3]):
            target = SLOTS[i]
            old = self.child_positions.get(node.id,target)
            point = tuple(a+.14*(b-a) for a,b in zip(old,target))
            self.child_positions[node.id] = point
            if self.dragging:
                child_key,child_index = 'left',self.animations['left'].frame(now-self.visual_epoch)
            elif self.edge_transition:
                child_key,child_index = 'edge_reveal',self.animations['edge_reveal'].frame(now-self.visual_epoch,True)
            else:
                pos = self.clock.position(node.id,now)
                if not pos:
                    continue
                child_key,child_index = pos
                if child_key == 'working':
                    child_index = self.animations['working'].frame(max(0,time.time()-node.changed)*1.25)
            child_frames = self.animations[child_key].frames
            child_mirrored = self.dragging and self.drag_mirrored
            sprite_key = (id(child_frames), child_index, child_mirrored)
            sprite = self.child_sprite_cache.get(sprite_key)
            if sprite is None:
                sprite = child_frames[child_index]
                # Keep the whole artwork coordinate system while resizing.
                sprite = resize_alpha(sprite,(round(sprite.width*261/640),round(sprite.height*307/640)))
                if child_mirrored:
                    sprite = sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                self.child_sprite_cache[sprite_key] = sprite
                self.child_sprite_bytes += sprite.width*sprite.height*4
                while self.child_sprite_bytes > 32*1024*1024:
                    _, old = self.child_sprite_cache.popitem(last=False)
                    self.child_sprite_bytes -= old.width*old.height*4
            self.child_sprite_cache.move_to_end(sprite_key)
            if child_mirrored:
                anchor_x = 261-410*.408
            else:
                anchor_x = 410*.408
            origin = (round(point[0]-anchor_x),round(point[1]-570*.48))
            canvas.alpha_composite(sprite,origin)
            bounds = sprite.getbbox()
            if bounds:
                self.child_rects[node.id] = tuple(bounds[j]+origin[j%2] for j in range(4))
        if len(children)>3:
            ImageDraw.Draw(canvas).text((540,570),'+'+str(len(children)-3),font=win.load_ui_font(16,True),fill=(96,84,88,255))
        if self.selector_visible and not self.hide_bubble_bar:
            self._composite_selector(canvas)
        if self.permission_request:
            self._composite_permission_bubble(canvas)
        if render_scale != 1:
            bounds = canvas.getchannel('A').getbbox()
            if bounds:
                # Resize only the occupied overlay, preserving its coordinates.
                box = (max(0,bounds[0]-3),max(0,bounds[1]-3),min(canvas.width,bounds[2]+3),min(canvas.height,bounds[3]+3))
                dest = tuple(round(v*render_scale) for v in box)
                overlay = canvas.crop(box).convert('RGBa').resize(
                    (dest[2]-dest[0],dest[3]-dest[1]),Image.Resampling.LANCZOS).convert('RGBA')
                artwork.alpha_composite(overlay,dest[:2])
            canvas = artwork
        self.last_canvas = canvas
        return canvas


    def run(self):
        # Per-monitor awareness must precede the first HWND. Coordinates passed
        # to Win32 stay physical; rendering and hit testing use 640-point units.
        try:
            win.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError,OSError):
            pass
        super().run()


    def _cursor_window_position(self):
        point = super()._cursor_window_position()
        return (round(point[0]/self.scale),round(point[1]/self.scale)) if point else None

    def _composite_selector(self,canvas):
        roots = self.store.roots(time.time())
        count = max(1,min(6,len(roots)))
        left,bottom,width,height = 270,425,280,count*34+12
        top = bottom-height
        self.selector_rect = (left,top,left+width,bottom)
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(self.selector_rect,12,fill=(220,218,222,237),outline=(245,242,245,245),width=1)
        self.selector_scroll = min(self.selector_scroll,max(0,len(roots)-6))
        self.selector_rows = []
        font = win.load_ui_font(14)
        if not roots:
            draw.text((left+18,top+12),'当前好像没有任务唔～',font=font,fill=(95,89,96,255))
        for i,node in enumerate(roots[self.selector_scroll:self.selector_scroll+6]):
            rect = (left+6,top+6+i*34,left+width-6,top+40+i*34)
            if node.id == self.store.selected:
                draw.rounded_rectangle(rect,7,fill=(245,240,246,235))
            if node.unread:
                draw.ellipse((left+12,rect[1]+13,left+19,rect[1]+20),fill=(47,137,229,255))
            title = node.title
            while title and draw.textlength(title,font=font)>width-48:
                title = title[:-2]+'…' if not title.endswith('…') else title[:-2]+'…'
            draw.text((left+28,rect[1]+7),title,font=font,fill=(78,72,80,255))
            self.selector_rows.append((rect,node.id))

    def _update_hover(self):
        if self.hide_bubble_bar or self.permission_request:
            self.selector_visible = False
            return
        point = self._cursor_window_position()
        if point and self.edge_placement is None and not self.dragging:
            hit = self._point_in_rect(point,self._logical_pet_bounds()) or self._point_in_rect(point,self.selector_rect if self.selector_visible else None)
            # The small corridor connects the character and fixed panel without flicker.
            hit = hit or self.selector_visible and self._point_in_rect(point,(270,420,550,445))
            if hit:
                self.selector_visible,self.selector_last_hover = True,time.monotonic()
            elif time.monotonic()-self.selector_last_hover >= .4:
                self.selector_visible = False
        else:
            self.selector_visible = False

    def _composite_permission_bubble(self,canvas):
        draw = ImageDraw.Draw(canvas)
        font, title_font = win.load_ui_font(14),win.load_ui_font(11)
        request = self.permission_request
        detail = str(request.get('summary') or 'Codex 请求权限')
        if detail != self.permission_lines_key:
            self.permission_lines_key = detail
            self.permission_lines = win.wrap_text_by_width(draw,detail,font,280,10000)
        lines = self.permission_lines
        self.permission_page = min(self.permission_page,max(0,len(lines)-11))
        visible = lines[self.permission_page:self.permission_page+11]
        height = 104+max(1,len(visible))*20
        left,right,bottom,top = 250,570,348,348-height
        rect = (left,top,right,bottom)
        self.permission_bubble_rect = (left,top,right,bottom+10)
        canvas.alpha_composite(permission_surface(rect))
        draw = ImageDraw.Draw(canvas)
        rose = (176,124,129,255)
        draw.ellipse((left+20,top+21,left+26,top+27),fill=rose)
        draw.text((left+34,top+17),'CODEX · 需要你的确认',font=title_font,fill=rose)
        for i,line in enumerate(visible):
            draw.text((left+20,top+43+i*20),line,font=font,fill=(76,67,70,255))
        long = len(lines)>11
        if not long or self.permission_page+11 >= len(lines):
            self.permission_viewed.add(self.permission_request_id)
        button_y = bottom-48
        buttons = {'deny':(left+20,button_y,left+120,bottom-16),'allow':(right-136,button_y,right-20,bottom-16)}
        self.permission_buttons = buttons
        for action,button in buttons.items():
            disabled = action == 'allow' and self.permission_request_id not in self.permission_viewed
            fill = (223,207,214,255) if disabled else rose if action == 'allow' else (242,238,231,255)
            draw.rounded_rectangle(button,10,fill=fill)
            draw.text(((button[0]+button[2])/2,(button[1]+button[3])/2),{'allow':'允许一次','deny':'拒绝'}[action],font=win.load_ui_font(13),anchor='mm',fill=(255,255,255,255) if action=='allow' and not disabled else (82,76,76,255))

    def _write_permission_decision(self,decision):
        if decision == 'allow' and self.permission_request_id not in self.permission_viewed:
            return
        if decision in {'allow','deny'} and self.permission_request_id:
            atomic_json(self._permission_response_path(self.permission_request_id),{'request_id':self.permission_request_id,'decision':decision,'updated_at':win.utc_timestamp(),'source':'pcr-pet','message':'用户从 PCR 桌宠拒绝本次请求。' if decision=='deny' else ''})
            self.permission_request = None
            self.permission_request_id = ''

    def _logical_pet_bounds(self):
        frames = self.animations[self.position[0]].frames
        bounds = frames.specs[self.position[1]].get('visible_bounds')
        if bounds is None:
            bounds = frames[self.position[1]].getbbox()
        rects = [bounds or (334,436,486,570)]
        rects.extend(self.child_rects.values())
        return union(rects)

    def _current_pet_local_bounds(self):
        return tuple(round(v*self.scale) for v in self._logical_pet_bounds())

    def _current_content_local_bounds(self):
        # Always reserve three slots on reveal, including when no children exist yet.
        rects = [self._logical_pet_bounds(),(266,505,554,620)]
        if self.permission_request and self.permission_bubble_rect:
            rects.append(self.permission_bubble_rect)
        return tuple(round(v*self.scale) for v in union(rects))

    def _edge_bottom_drop(self,edge,pet_bounds):
        return 0.0 # The reserved family must remain inside the work area.

    def _begin_edge_hide_if_needed(self):
        self.hidden_tokens = self.store.work_tokens().copy()
        self.leisure.cancel()
        return super()._begin_edge_hide_if_needed()

    def _show_tail(self,placement):
        if not self.tail_hwnd:
            return
        count = min(3,len(self.store.children(self.store.selected,time.time())))
        main = placement.tail_rect
        scale = self.scale
        side, overlap = round(68*scale),round(30*scale)
        screen = placement.monitor.frame
        if placement.edge in ('left','right'):
            y = (main[1]+main[3]-side)//2
            x = screen[0]-(side-overlap) if placement.edge=='left' else screen[2]-overlap
        else:
            x = (main[0]+main[2]-side)//2
            y = screen[1]-(side-overlap) if placement.edge=='top' else screen[3]-overlap
        main = (x,y,x+side,y+side)
        rects = family_tail_rects(placement.edge,main,screen,count,scale)
        bounds = union(rects)
        image = Image.new('RGBA',(bounds[2]-bounds[0],bounds[3]-bounds[1]))
        for i,rect in enumerate(rects):
            source = self.edge_tail_assets[placement.edge]
            source = resize_alpha(source,(rect[2]-rect[0],rect[3]-rect[1]))
            image.alpha_composite(source,(rect[0]-bounds[0],rect[1]-bounds[1]))
        win.user32.SetWindowPos(self.tail_hwnd,win.HWND_TOPMOST,bounds[0],bounds[1],image.width,image.height,win.SWP_NOACTIVATE|win.SWP_SHOWWINDOW)
        self._render_layered_window(self.tail_hwnd,win.premultiplied_bgra(image),image.width,image.height)
        win.user32.ShowWindow(self.tail_hwnd,win.SW_SHOW)

    def _handle_left_button_down(self):
        point = self._cursor_window_position()
        if self.permission_request and point and self._point_in_rect(point,self.permission_bubble_rect):
            super()._handle_left_button_down()
            return
        if point:
            for rect,actor in self.selector_rows if self.selector_visible else []:
                if self._point_in_rect(point,rect):
                    self.selector_down = actor
                    win.user32.SetCapture(self.hwnd)
                    return
            for actor,rect in self.child_rects.items():
                if self._point_in_rect(point,rect) and self.store.nodes[actor].status=='permission':
                    self.focused_child = actor
                    self._sync_family_permission()
                    return
        self.drag_sleep_phase = self.leisure.phase
        super()._handle_left_button_down()
        self.click_feedback_enabled = not self.store.work_tokens() and not self.permission_request


    def _restore_after_drag(self,previous):
        self.transient_key = None
        self._poll_bridge(force=True)
        self._resolve_visual()
        self._render_current()

    def _handle_left_button_up(self):
        if self.selector_down:
            actor,self.selector_down = self.selector_down,None
            point = self._cursor_window_position()
            win.user32.ReleaseCapture()
            if any(n==actor and self._point_in_rect(point,rect) for rect,n in self.selector_rows) if point else False:
                self.store.select(actor)
                self.focused_child = ''
                node = self.store.nodes[actor]
                if node.unread:
                    try:
                        # ShellExecute reports failure if the URL handler is absent.
                        result = win.ctypes.windll.shell32.ShellExecuteW(None,'open','codex://threads/'+actor,None,None,1)
                        if result <= 32:
                            raise OSError('Codex URL handler unavailable')
                        node.unread = False
                        self.observer.opened.add(actor)
                    except OSError:
                        win.user32.MessageBoxW(self.hwnd,'无法打开 Codex 线程，请复制线程 ID：\n'+actor,'PCR 桌宠',0)
            return
        if self.mouse_down and not self.dragging and self.leisure.click(time.monotonic()):
            self.mouse_down=False
            win.user32.ReleaseCapture()
            self._resolve_visual()
            return
        if self.mouse_down and not self.dragging and self.leisure.phase=='bowing':
            self.leisure.cancel()
        super()._handle_left_button_up()


    def _write_heartbeat(self,force=False):
        now = time.monotonic()
        if not force and now-self.last_heartbeat < 1:
            return
        self.last_heartbeat = now
        p = dict(app=win.APP_NAME,pid=os.getpid(),updated_at=win.utc_timestamp(),status_path=str(self.status_path),current_key=self.current_key,
            version=APP_VERSION,build=APP_BUILD,frame_index=self.frame_index,selected_family=self.store.selected,
            families=[{'id':n.id,'parent':n.parent,'turn':n.turn,'status':n.status,'unread':n.unread} for n in self.store.nodes.values()],
            leisure_phase=self.leisure.phase,selector_visible=self.selector_visible,hidden_work_tokens=sorted(self.hidden_tokens),unread_sync=self.observer.unread_supported,
            dpi_scale=getattr(self,'dpi_scale',self.scale),render_scale=self.scale,size_percent=getattr(self,'size_percent',100),
            character_id=getattr(self,'character_id',''),character_name=getattr(self,'character_name',''),
            presentation=(self.edge_transition or 'hidden') if self.edge_placement else 'visible',
            tail_visible=bool(self.tail_hwnd and win.user32.IsWindowVisible(self.tail_hwnd)))
        if os.environ.get('PCR_QA_WINDOW') == '1' and not self.observer.enabled:
            p['qa_commands'] = sorted(self.qa_commands)
            p['permission_request_id'] = self.permission_request_id
        if self.hwnd:
            p.update(hwnd=int(self.hwnd),window_rect=self._window_rect(self.hwnd),window_visible=bool(win.user32.IsWindowVisible(self.hwnd)))
            content = self._screen_bounds_for_local(self._current_content_local_bounds())
            if content:
                p['content_screen_rect'] = content
                monitors = win.enumerate_monitor_infos()
                monitor = self.edge_placement.monitor if self.edge_placement else (
                    max(monitors,key=lambda m:win.rect_intersection_area(content,m.frame)) if monitors else None)
                if monitor:
                    p['monitor_work'] = monitor.work
        if self.tail_hwnd:
            p.update(tail_hwnd=int(self.tail_hwnd),tail_rect=self._window_rect(self.tail_hwnd))
        if self.edge_placement:
            p['hidden_edge'] = self.edge_placement.edge
        try:
            atomic_json(self.heartbeat_path,p)
        except OSError:
            pass

    def _wndproc(self,hwnd,message,wparam,lparam):
        if hwnd==self.hwnd and message==0x020A: # WM_MOUSEWHEEL
            delta = ctypes.c_short((wparam>>16)&0xffff).value
            point = self._cursor_window_position()
            if self.permission_request and point and self._point_in_rect(point,self.permission_bubble_rect):
                self.permission_page=max(0,self.permission_page+(-3 if delta>0 else 3))
            elif self.selector_visible:
                self.selector_scroll=max(0,self.selector_scroll+(-1 if delta>0 else 1))
            return 0
        return super()._wndproc(hwnd,message,wparam,lparam)
