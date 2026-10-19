"""Discover character packs without hard-coding their names in the UI."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
from asset_storage import frame_files

from PIL import Image

ROOT = Path(__file__).resolve().parent
DEFAULT_CHARACTER = 'ho-chan'
REQUIRED_CLIPS = {'idle', 'left', 'reading', 'working', 'jump', 'question', 'click_feedback',
                  'bow', 'sleep_entry', 'sleep_body', 'wake',
                  'edge_reveal'}


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    model: str
    skin_path: Path
    asset_dir: Path
    order: int = 100
    source_url: str = ''
    copyright: str = ''

    @property
    def edge_dir(self):
        return self.asset_dir.parent / 'edge-tail'

    @property
    def ready(self):
        return (self.asset_dir / 'animation-manifest.json').is_file() and all(
            (self.edge_dir / f'{edge}.png').is_file() for edge in ('left', 'right', 'top', 'bottom'))


def discover_characters(root=ROOT, *, strict=False):
    root = Path(root).resolve()
    result = []
    for path in sorted((root / 'characters').glob('*/character.json')):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            identity = data['id']
            if not isinstance(identity, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', identity):
                raise ValueError(f'Invalid character id: {path}')
            skin = (path.parent / data['skin']).resolve()
            assets = (root / data['asset_dir']).resolve()
            if not skin.is_relative_to(root) or not assets.is_relative_to(root):
                raise ValueError(f'Character paths must stay inside the app: {path}')
            if not skin.is_file() or not isinstance(data['name'], str) or not data['name'].strip():
                raise ValueError(f'Incomplete character descriptor: {path}')
            if not isinstance(data['model'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+', data['model']):
                raise ValueError(f'Invalid model basename: {path}')
            if any(c.id == identity for c in result):
                raise ValueError(f'Duplicate character id: {identity}')
            result.append(Character(identity, data['name'], data['model'], skin, assets, int(data.get('order', 100)),
                                    str(data.get('source_url', '')), str(data.get('copyright', ''))))
        except (OSError, ValueError, KeyError, TypeError):
            if strict:
                raise
            # An unfinished authoring folder must not break installed packs.
            continue
    return {c.id: c for c in sorted(result, key=lambda c: (c.order, c.id))}


def startup_character(settings, requested=None, *, root=ROOT):
    catalog = discover_characters(root)
    if requested:
        character = catalog.get(requested)
        if not character or not character.ready:
            raise ValueError(f'Unknown or unbuilt character: {requested}')
        return character
    identity = settings.get('character_id')
    character = catalog.get(identity) if isinstance(identity, str) else None
    if character and character.ready:
        return character
    default = catalog.get(DEFAULT_CHARACTER)
    if default and default.ready:
        return default
    ready = next((character for character in catalog.values() if character.ready), None)
    if ready is None:
        raise ValueError('No built character pack. Run tools/build_skin.py --character <id> first.')
    return ready


def load_portraits(character):
    result = {}
    for edge in ('left', 'right', 'top', 'bottom'):
        with Image.open(character.edge_dir / f'{edge}.png') as image:
            if image.size != (68, 68):
                raise ValueError(f'Invalid edge portrait: {edge}')
            result[edge] = image.convert('RGBA')
    return result


def validate_pack(clips):
    from animation_clock import packing_keys

    missing = REQUIRED_CLIPS - clips.keys()
    if missing:
        raise ValueError('Missing animation keys: ' + ', '.join(sorted(missing)))
    if not packing_keys(clips):
        raise ValueError('At least one compaction animation is required')
    for clip in clips.values():
        if not len(clip.frames):
            raise ValueError('Empty animation: ' + clip.key)
        for frame in clip.frames.specs:
            files = list(frame_files(frame))
            if not files:
                raise ValueError('Frame has no stored artwork')
            for relative in files:
                if not (clip.source / relative).is_file():
                    raise ValueError('Missing frame: ' + relative)
    if not all('drag_anchor' in frame for frame in clips['left'].frames.specs):
        raise ValueError('The floating animation needs per-frame hand anchors')
    if clips['idle'].frames[0].size != clips['idle'].frames.canvas_size:
        raise ValueError('Character frame and rendering canvas sizes differ')
