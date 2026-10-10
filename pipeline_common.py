"""Shared timing and cache utilities for asset preparation and rendering."""
from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from pathlib import Path


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def file_signature(path: Path) -> dict:
    stat = path.stat()
    return {'path': str(path.resolve()), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def read_cache(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.pending-', suffix='.json', delete=False) as target:
        pending = Path(target.name)
        try:
            json.dump(value, target, ensure_ascii=False, indent=2)
        except BaseException:
            target.close()
            pending.unlink(missing_ok=True)
            raise
    try:
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def voiceover_path(project: Path) -> Path:
    for stem in ('voiceover', 'voice over'):
        for ext in ('.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg'):
            path = project / (stem + ext)
            if path.is_file():
                return path
    raise FileNotFoundError(f'No voiceover found in {project}. Use voiceover.mp3 or voiceover.wav.')


def normalize_text(text: str) -> str:
    text = re.sub(r'[\u0610-\u061a\u064b-\u065f\u0670\u0640]', '', text.lower())
    text = text.translate(str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ة': 'ه', 'ى': 'ي'}))
    return re.sub(r'[^\w]+', ' ', text).strip()


def plan_game_timing(games: list[dict], words: list[dict], duration: float,
                     config: dict | None = None, fps: int = 30) -> dict:
    """Use ordered spoken aliases as anchors; interpolate missing game starts."""
    config = config or {}
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Voiceover duration must be positive and finite.')
    total = max(1, round(duration * fps))
    n = len(games)
    if total < n + 2:
        raise ValueError('Voiceover is too short to show all games and an ending.')
    padding = float(config.get('end_padding_seconds', 0))
    if not math.isfinite(padding) or padding < 0:
        raise ValueError('end_padding_seconds must be non-negative.')
    tokens = []
    for word in words:
        for token in normalize_text(word['word']).split():
            tokens.append((token, float(word['start'])))
    anchors = {}
    last_index, last_frame = -1, 0
    for i, game in enumerate(games):
        aliases = game.get('spoken_names') or [game.get('title', game.get('game_name', game['folder']))]
        candidates = []
        for alias in aliases:
            parts = normalize_text(alias).split()
            if not parts:
                continue
            for j in range(len(tokens) - len(parts) + 1):
                if [t[0] for t in tokens[j:j + len(parts)]] == parts:
                    frame = round(tokens[j][1] * fps)
                    lower = last_frame + (i - last_index) if last_index >= 0 else 1
                    if lower <= frame <= total - (n - i) - 1:
                        candidates.append(frame)
                        break
        if candidates:
            frame = min(candidates)
            anchors[i] = frame
            last_index, last_frame = i, frame
    hook_default = min(float(config.get('hook_seconds', 3.5)), duration * .2)
    cta_default = min(float(config.get('cta_seconds', 5)), duration * .2)
    if not math.isfinite(hook_default) or hook_default < 0 or not math.isfinite(cta_default) or cta_default < 0:
        raise ValueError('Hook and CTA durations must be non-negative.')
    hook = anchors.get(0, max(1, round(hook_default * fps)))
    if anchors and 0 not in anchors:
        hook = min(hook, min(frame - index for index, frame in anchors.items()))
    hook = min(max(1, hook), total - n - 1)
    cta = max(hook + n, total - max(1, round(cta_default * fps)))
    if anchors:
        index = max(anchors)
        # Reserve space for remaining games if the last mention is near the end.
        cta = max(cta, anchors[index] + n - index)
    cta = min(cta, total - 1)
    points = {0: hook, **anchors, n: cta}
    starts = [0] * (n + 1)
    for (left, a), (right, b) in zip(sorted(points.items()), sorted(points.items())[1:]):
        for i in range(left, right + 1):
            starts[i] = round(a + (b - a) * (i - left) / (right - left))
    if n == 0:
        starts = [hook]
        cta = hook
    ranges = [(starts[i], starts[i + 1]) for i in range(n)]
    if any(end <= start for start, end in ranges):
        raise ValueError('Game timing does not leave at least one frame per game.')
    return {'fps': fps, 'hookFrames': hook, 'gameRanges': ranges,
            'ctaStartFrame': cta, 'totalFrames': total + round(padding * fps)}