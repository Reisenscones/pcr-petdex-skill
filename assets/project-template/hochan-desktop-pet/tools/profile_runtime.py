"""Measure actual presentation intervals in a short-lived isolated Win32 window."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hochan_pet
import pcr_pet as win


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='current')
    parser.add_argument('--seconds', type=float, default=7)
    parser.add_argument('--observe', action='store_true')
    parser.add_argument('--character', default='ho-chan')
    parser.add_argument('--size-percent', type=int, choices=(75, 100, 125, 150), default=100)
    parser.add_argument('--asset-dir', type=Path, help='Measure a staged resource pack')
    parser.add_argument('--clip', default='working')
    parser.add_argument('--warmup', type=float, default=1.5)
    parser.add_argument('--children', type=int, choices=(0,1,2,3), default=0)
    parser.add_argument('--observe-events', action='store_true', help='Read production events without writing production state')
    parser.add_argument('--fixed-clip', action='store_true', help='Hold one clip while measuring observer I/O')
    args = parser.parse_args()
    samples, elapsed = [], []
    frame_count = [18]
    memory = {}
    directory = ROOT / 'build' / ('profile-' + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    (directory / 'pet-settings.json').write_text(json.dumps(dict(size_percent=args.size_percent)), encoding='utf-8')
    base = hochan_pet.HoChanPet

    class ProfilePet(base):
        def _resolve_visual(self):
            if args.fixed_clip:
                clip = self.animations[args.clip]
                self.position = (args.clip,clip.frame(self.animation_time()-self.visual_epoch))
                self.frame_index = self.position[1]
            else:
                super()._resolve_visual()

        def __init__(self,*a,**kw):
            super().__init__(*a,**kw)
            if args.observe_events:
                self.observer.state_dir = ROOT/'state'
            if args.children:
                now = time.time()
                self.store.ingest(dict(session_id='profile-root',turn_id='t',event='PreToolUse'),now)
                for i in range(args.children):
                    self.store.ingest(dict(session_id='profile-root',agent_id='profile-child-'+str(i),
                                           turn_id='t',event='SubagentStart'),now)
                self._poll_bridge(force=True)

        def _render_current(self):
            frame_count[0] = len(self.animations[args.clip].frames)
            start = time.perf_counter()
            super()._render_current()
            finish = time.perf_counter()
            if self.hwnd:
                samples.append((finish, self.current_key, self.frame_index))
                elapsed.append((finish-start)*1000)
                if finish-samples[0][0] >= args.seconds:
                    memory.update(prepared_cache_bytes=self.frame_renderer.bytes_used if self.frame_renderer else 0,
                                  child_cache_bytes=self.child_sprite_bytes,
                                  dpi_scale=self.dpi_scale, render_scale=self.scale)
                    win.user32.DestroyWindow(self.hwnd)

    hochan_pet.HoChanPet = ProfilePet
    sys.argv = [sys.argv[0], '--status-file', str(directory / 'codex-status.json')]
    if args.asset_dir:
        sys.argv += ['--asset-dir',str(args.asset_dir.resolve())]
    else:
        sys.argv += ['--character',args.character]
    if not args.observe:
        sys.argv.extend(['--preview', args.clip, '--no-codex-observer'])
    hochan_pet.main()
    warm_index = next(i for i,s in enumerate(samples) if s[0]-samples[0][0] >= args.warmup)
    warmed = samples[warm_index:]
    durations = [(b[0]-a[0])*1000 for a, b in zip(warmed, warmed[1:])]
    advances = [(b[2]-a[2]) % frame_count[0] for a,b in zip(warmed,warmed[1:]) if a[1] == b[1] == args.clip]
    result = dict(label=args.label, seconds=args.seconds, size_percent=args.size_percent, character_id=args.character, render_calls=len(warmed),
        render_calls_per_second=round((len(warmed)-1)/(warmed[-1][0]-warmed[0][0]),2),
        render_ms_median=round(statistics.median(elapsed[warm_index:]),3),
        render_ms_p95=round(sorted(elapsed[warm_index:])[int(len(elapsed[warm_index:])*.95)],3),
        interval_ms_median=round(statistics.median(durations),3),
        interval_ms_p95=round(sorted(durations)[int(len(durations)*.95)],3),
        source_frames_skipped=sum(max(0,n-1) for n in advances),
        repeated_frame_renders=sum(n == 0 for n in advances),
        distinct_source_frames_per_second=round(sum(n>0 for n in advances)/(warmed[-1][0]-warmed[0][0]),2),
        source_frame_count=frame_count[0],clip=args.clip,children=args.children,observer=args.observe,
        warmup_seconds=args.warmup,**memory)
    (ROOT / 'build' / ('performance-' + args.label + '.json')).write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
