"""Check this skill's source package without importing or running the desktop pet."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {'.py', '.ps1', '.json', '.yaml', '.md', '.txt', '.cmd'}


def main():
    errors = []
    template = ROOT / 'assets/project-template'
    manifest = json.loads((ROOT / 'assets/template-manifest.json').read_text(encoding='utf-8'))
    actual = {p.relative_to(template).as_posix(): p for p in template.rglob('*') if p.is_file()}
    expected = manifest['files']
    for name in sorted(actual.keys() | expected.keys()):
        if name not in actual or name not in expected:
            errors.append(f'Template file inventory differs: {name}')
        elif hashlib.sha256(actual[name].read_bytes()).hexdigest() != expected[name]['sha256']:
            errors.append(f'Template checksum differs: {name}')
    files = [p for p in ROOT.rglob('*') if p.is_file()]
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if any(part in {'.venv', '__pycache__', 'state', 'build', '.git'} for part in path.relative_to(ROOT).parts):
            errors.append(f'Local state/cache in package: {relative}')
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            source = path.read_text(encoding='utf-8-sig')
            if '\ufffd' in source:
                errors.append(f'Encoding replacement character: {relative}')
            if path.suffix == '.py':
                ast.parse(source, filename=relative)
            elif path.suffix == '.json':
                json.loads(source)
            elif path.suffix == '.md':
                for target in re.findall(r'\]\(([^)]+)\)', source):
                    if '://' in target or target.startswith('#'):
                        continue
                    if not (path.parent / target.split('#', 1)[0]).exists():
                        errors.append(f'Missing local link: {relative} -> {target}')
        except (UnicodeError, ValueError, SyntaxError) as error:
            errors.append(f'{relative}: {error}')
    app = template / 'hochan-desktop-pet'
    identities = set()
    for descriptor in sorted((app / 'characters').glob('*/character.json')):
        try:
            character = json.loads(descriptor.read_text(encoding='utf-8'))
            identity = character['id']
            if descriptor.parent.name != identity:
                errors.append(f'Character directory and id differ: {descriptor.parent.name} -> {identity}')
            if identity in identities:
                errors.append(f'Duplicate character id: {identity}')
            identities.add(identity)
            if character['asset_dir'] != f'assets/characters/{identity}/animation-resources':
                errors.append(f'Character id and asset directory differ: {identity}')
            skin = (descriptor.parent / character['skin']).resolve()
            if not skin.is_relative_to(app.resolve()) or not skin.is_file():
                errors.append(f'Missing or external character recipe: {identity}')
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append(f'Invalid character registration: {descriptor}: {error}')
    for path in [app / 'character_catalog.py', *sorted((app / 'tools').glob('*.py'))]:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                    and target.id == 'DEFAULT_CHARACTER' for target in node.targets)
                    and isinstance(node.value, ast.Constant) and node.value.value not in identities):
                errors.append(f'Unknown default character in {path.name}: {node.value.value}')
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'add_argument' and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value in {'--character', '--template'}):
                for keyword in node.keywords:
                    if (keyword.arg == 'default' and isinstance(keyword.value, ast.Constant)
                            and isinstance(keyword.value.value, str) and keyword.value.value not in identities):
                        errors.append(f'Unknown character/template default in {path.name}: {keyword.value.value}')
    hook = app / 'hooks/codex-hochan-hook.ps1'
    if not hook.read_bytes().startswith(b'\xef\xbb\xbf'):
        errors.append('Hook lost its UTF-8 BOM required by Windows PowerShell 5.1')
    result = dict(status='failed' if errors else 'passed', scope='static package checks only',
                  files=len(files), template_files=len(actual),
                  python_files=sum(p.suffix == '.py' for p in files), errors=errors)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
