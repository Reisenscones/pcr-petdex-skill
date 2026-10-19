"""Scaffold a character descriptor and calibrated-animation configuration."""
import argparse
import copy
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from character_catalog import discover_characters
from spine_sources import query_animations, resolve_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--id', required=True, help='Stable ASCII id, e.g. kyouka-gothic')
    parser.add_argument('--name', required=True, help='Display name in the character menu')
    parser.add_argument('--model', required=True, help='Basename of one .skel or .json with matching .atlas in source/spine')
    parser.add_argument('--template', default='ho-chan')
    parser.add_argument('--source-url', required=True)
    parser.add_argument('--copyright', required=True)
    args = parser.parse_args()
    if not args.name.strip():
        parser.error('Display name cannot be empty')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', args.id) or not re.fullmatch(r'[A-Za-z0-9_-]+', args.model):
        parser.error('Invalid character id or model basename')
    directory = ROOT / 'characters' / args.id
    if directory.exists():
        parser.error('Character directory already exists; edit its configuration instead')
    catalog = discover_characters(strict=True)
    if args.template not in catalog:
        parser.error('Unknown template character')
    model = resolve_model(ROOT.parent / 'source/spine', args.model)
    known = query_animations(ROOT.parent / '.tools/SpineViewer-v0.16.34/SpineViewerCLI.exe', model)
    skin = copy.deepcopy(json.loads(catalog[args.template].skin_path.read_text(encoding='utf-8')))
    skin['name'] = args.name
    skin['animation_prefix'] = args.id
    for key, spec in skin['animations'].items():
        names = spec.get('sequence', [spec.get('animation')])
        mapped = []
        for name in names:
            if name not in known:
                suffix = name.partition('_')[2]
                candidates = [value for value in known if value.endswith('_' + suffix)]
                if len(candidates) != 1:
                    parser.error(f'Map {key} manually: no unique replacement for {name}')
                name = candidates[0]
            mapped.append(name)
        if 'sequence' in spec:
            spec['sequence'] = mapped
        else:
            spec['animation'] = mapped[0]
        spec['duration_seconds'] = sum(known[name]['durationSeconds'] for name in mapped)
    descriptor = dict(id=args.id, name=args.name, model=args.model, skin='skin.json',
                      asset_dir=f'assets/characters/{args.id}/animation-resources', order=len(catalog),
                      source_url=args.source_url, copyright=args.copyright)
    directory.mkdir(parents=True)
    (directory / 'skin.json').write_text(json.dumps(skin, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (directory / 'character.json').write_text(json.dumps(descriptor, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Registered {args.id}: {args.name}')
    print(f'Build with: python tools/build_skin.py --character {args.id}')


if __name__ == '__main__':
    main()
