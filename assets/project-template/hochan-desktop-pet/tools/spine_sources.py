"""Query the actual model instead of relying on another character's exports."""
import subprocess


def query_animations(cli, model):
    result = subprocess.run([str(cli), 'query', str(model), '--animation'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'Spine query failed: {model}\n{result.stdout}\n{result.stderr}')
    animations = {}
    for line in result.stdout.splitlines():
        values = line.split('\t')
        if len(values) == 2:
            try:
                duration = float(values[1])
            except ValueError:
                continue
            animations[values[0]] = dict(animation=values[0], durationSeconds=duration, fps=30)
    if not animations:
        raise ValueError(f'No animations found: {model}')
    return animations


def resolve_model(directory, basename):
    from pathlib import Path
    candidates = [Path(directory) / (basename + suffix) for suffix in ('.skel', '.json')]
    candidates = [path for path in candidates if path.is_file()]
    if len(candidates) != 1:
        raise ValueError(f'Expected exactly one .skel or .json for {basename}: {candidates}')
    model = candidates[0]
    if not model.with_suffix('.atlas').is_file():
        raise FileNotFoundError(model.with_suffix('.atlas'))
    return model
