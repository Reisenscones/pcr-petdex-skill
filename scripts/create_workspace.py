"""Copy the bundled source template and user-supplied Spine material into a new folder.

Uses only Python's standard library. Does not install software or start a pet.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil


SKILL = Path(__file__).resolve().parents[1]
ALLOWED = {'.skel', '.json', '.atlas', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tga'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--materials', type=Path, required=True,
                        help='Directory with skeletons, same-basename atlases and all referenced textures')
    args = parser.parse_args()
    destination, materials = args.destination.resolve(), args.materials.resolve()
    if destination.exists():
        parser.error('Destination already exists; choose a new directory. Nothing was overwritten.')
    if not materials.is_dir():
        parser.error('Material directory does not exist')
    if destination.is_relative_to(materials) or destination.is_relative_to(SKILL):
        parser.error('Destination must be outside the materials and installed skill directories')
    if not (SKILL / 'assets/project-template/hochan-desktop-pet/hochan_pet.py').is_file():
        parser.error('Skill package is incomplete: missing bundled runtime template')
    files = [p for p in materials.rglob('*') if p.is_file() and p.suffix.lower() in ALLOWED
             and not any(part.startswith('.') for part in p.relative_to(materials).parts)]
    if any(p.is_symlink() or not p.resolve().is_relative_to(materials) for p in files):
        parser.error('Materials must contain regular files inside the material directory')
    models = [p for p in files if p.suffix.lower() in {'.skel', '.json'}
              and p.with_suffix('.atlas').is_file()]
    if not models:
        parser.error('No .skel or .json with a same-basename .atlas was found')
    shutil.copytree(SKILL / 'assets/project-template', destination)
    source = destination / 'source/spine'
    for path in files:
        target = source / path.relative_to(materials)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    (destination / 'source/reference-frames').mkdir(parents=True, exist_ok=True)
    (destination / 'hochan-desktop-pet/preview').mkdir(exist_ok=True)
    print(json.dumps(dict(workspace=str(destination), material_files=len(files),
                          models=[str(p.relative_to(materials)) for p in models],
                          next='Prepare tools, inspect model animations, then build the selected character.'),
                     ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
