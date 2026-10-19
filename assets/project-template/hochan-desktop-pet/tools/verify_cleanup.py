"""Check production import, resource, state-protocol and naming consistency."""
import ast
import importlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from animation_clock import load_manifest, packing_keys
from asset_storage import frame_files
from character_catalog import discover_characters, load_portraits, validate_pack
from codex_bridge import HEARTBEAT_FILE_NAME, default_status_path
from hochan_pet import HoChanPet


def main():
    retired_name = 'p' + 'ig'
    modules = {p.stem for p in ROOT.glob('*.py')}
    sources = list(ROOT.glob('*.py')) + list((ROOT / 'tools').glob('*.py'))
    for path in sources:
        text = path.read_text(encoding='utf-8-sig')
        assert retired_name not in path.name.lower(), path
        assert retired_name not in text.lower(), path
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in modules:
                imported = importlib.import_module(node.module)
                for name in node.names:
                    assert hasattr(imported, name.name), (path, node.module, name.name)
    for name in sorted(modules):
        importlib.import_module(name)

    hook = ROOT / 'hooks/codex-hochan-hook.ps1'
    hook_text = hook.read_text(encoding='utf-8-sig')
    assert retired_name not in hook_text.lower()
    assert HEARTBEAT_FILE_NAME in hook_text
    assert default_status_path() == ROOT / 'state/codex-status.json'
    assert '-StateDirectory' in (ROOT / 'install-hooks.ps1').read_text(encoding='utf-8-sig')
    assert hook.read_bytes().startswith(b'\xef\xbb\xbf'), 'Windows PowerShell needs UTF-8 BOM for Chinese source'
    assert len([c for c in HoChanPet.__mro__ if '_show_menu' in c.__dict__]) == 1
    assert not hasattr(HoChanPet, '_poll_update')

    referenced = set()
    packs = []
    for character in discover_characters(strict=True).values():
        clips = load_manifest(character.asset_dir)
        validate_pack(clips)
        load_portraits(character)
        config = json.loads(character.skin_path.read_text(encoding='utf-8'))
        manifest_path = character.asset_dir / 'animation-manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        assert character.asset_dir.parent.parent == ROOT / 'assets/characters'
        assert manifest['character_id'] == character.id and manifest['character_name'] == character.name
        assert manifest['animation_prefix'] == config['animation_prefix']
        assert set(clips) == set(config['animations']) | set(config['aliases'])
        for key, spec in config['animations'].items():
            expected_source = ' + '.join(spec['sequence'] if 'sequence' in spec else [spec['animation']])
            assert manifest['animations'][key]['source'] == expected_source, (character.id, key)
        assert packing_keys(clips) == [k for k in config['animations'] if k.startswith('packing_')]
        referenced.add(manifest_path.resolve())
        referenced.update((character.edge_dir / f'{edge}.png').resolve()
                          for edge in ('left', 'right', 'top', 'bottom'))
        for clip in manifest['animations'].values():
            for frame in clip['frames']:
                for relative in frame_files(frame):
                    assert relative.startswith(f"animations/{config['animation_prefix']}_"), (character.id, relative)
                    path = (character.asset_dir / relative).resolve()
                    assert path.is_relative_to(character.asset_dir) and path.is_file(), path
                    referenced.add(path)
        packs.append(dict(character=character.id, keys=len(clips), packing=len(packing_keys(clips))))
    assert {p.name for p in (ROOT / 'assets').iterdir() if p.is_dir()} == {'characters', 'effects'}
    referenced.update(path.resolve() for path in (ROOT / 'assets/effects').glob('*.png'))
    actual = {p.resolve() for p in (ROOT / 'assets').rglob('*') if p.is_file()}
    assert actual == referenced, ('Unreferenced', actual-referenced, 'Missing', referenced-actual)

    # Catch dangling local document links after file and resource renames.
    for doc in [ROOT.parent / 'README.md', *ROOT.glob('*.md'),
                *ROOT.glob('characters/**/*.md'), *ROOT.parent.glob('docs/**/*.md')]:
        for target in re.findall(r'\]\(([^)]+)\)', doc.read_text(encoding='utf-8')):
            if '://' in target or target.startswith('#'):
                continue
            path = target.split('#', 1)[0]
            assert (doc.parent / path).exists(), (doc, target)

    report = dict(status='passed', modules=len(modules), source_files=len(sources),
                  packs=packs, referenced_asset_files=len(referenced),
                  heartbeat=HEARTBEAT_FILE_NAME,
                  checks=['Local imports and retired names', 'Single menu and no updater',
                          'Hook encoding and heartbeat protocol', 'Every production asset referenced',
                          'Character/build mappings and local documentation links'])
    (ROOT / 'build').mkdir(exist_ok=True)
    (ROOT / 'build/cleanup-verification.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
