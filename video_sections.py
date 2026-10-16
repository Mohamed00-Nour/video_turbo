"""Flexible sections sharing the video builder's background and captions."""
from pathlib import Path
import math
from pipeline_common import normalize_text

LAYOUTS = {'background', 'single', 'split', 'title', 'cyber_breach', 'thermal_meltdown', 'zero_ransom', 'reference_style'}
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.webm'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp'}
BACKGROUND_NAMES = {'gta_background.mp4', 'roblox.mp4', 'fortnite.mp4'}
REFERENCE_VARIANTS = ('hero', 'card', 'collage', 'type', 'device', 'compare', 'metric', 'steps')
REFERENCE_DIRECTION = {
    'scene_tone': ('base', 'contrast', 'accent'),
    'backdrop': ('clean', 'grid', 'orbits', 'spotlight', 'diagonal'),
    'motif': ('none', 'warning', 'connection', 'privacy', 'protection', 'energy', 'share'),
    'media_treatment': ('photo', 'cutout', 'multiply'),
    'text_position': ('top', 'center', 'bottom'),
    'accent_style': ('text', 'block', 'underline'),
    'transition_style': ('cut', 'wipe', 'settle'),
}


def validate_reference_direction(scene):
    for key, choices in REFERENCE_DIRECTION.items():
        if key in scene and scene[key] not in choices: raise ValueError('Unsupported reference ' + key + '.')
    details = scene.get('details', [])
    if not isinstance(details, list) or len(details) > 3 or any(not isinstance(value, str) or len(value) > 50 for value in details):
        raise ValueError('Use up to three short supporting details in a reference scene.')



def media_path(project, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("Use a relative media path inside the project.")
    path = (Path(project) / relative).resolve()
    if not path.is_relative_to(Path(project).resolve()) or not path.is_file():
        raise ValueError(f'Media file missing or outside the project: {relative}')
    if path.suffix.lower() not in VIDEO_EXTS | IMAGE_EXTS:
        raise ValueError(f'Unsupported section media: {relative}')
    return path


def public_media(relative):
    return 'sections/' + Path(relative).as_posix()


def validate_sections(config, project):
    sections = config.get('sections')
    if not isinstance(sections, list) or not sections:
        raise ValueError('Add at least one section to your video.')
    for section in sections:
        layout = section.get('layout', 'single')
        if layout not in LAYOUTS:
            raise ValueError(f'Unknown section layout: {layout}')
        if layout == 'reference_style':
            if not config.get('reference_style'):
                raise ValueError('Analyze a reference before using reference-style scenes.')
            variant = section.get('variant', 'card')
            if variant not in REFERENCE_VARIANTS:
                raise ValueError('Choose a supported reference scene composition.')
            validate_reference_direction(section)
            if variant in ('hero', 'card', 'collage', 'compare') and not section.get('media'):
                raise ValueError('Add media to the reference scene, or choose expressive typography.')
        for key in ('media', 'secondary_media'):
            if section.get(key):
                media_path(project, section[key])
        if layout in {'single', 'split'} and not section.get('media'):
            raise ValueError(f"Add a clip or screenshot to section: {section.get('title', 'Untitled')}")
        if layout == 'split' and not section.get('secondary_media'):
            raise ValueError('A stacked section needs two media files.')
        if layout == 'title' and not str(section.get('title', '')).strip():
            raise ValueError('A title section needs a title.')
        if section.get('background', 'gta_background.mp4') not in BACKGROUND_NAMES:
            raise ValueError('Choose a background from the background library.')
        for key, lower, upper in [('caption_y', 0, 1), ('offset_seconds', 0, 1e6), ('zoom', 1, 1.5)]:
            value = float(section.get(key, {'caption_y': .76, 'offset_seconds': 0, 'zoom': 1.04}[key]))
            if not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError(f'Invalid {key} in section.')
        if section.get('fit', 'contain') not in {'contain', 'cover'}:
            raise ValueError('Choose contain or cover for media framing.')
        highlight = section.get('highlight')
        if highlight:
            values = [float(highlight[key]) for key in ('x', 'y', 'width', 'height')]
            if not all(math.isfinite(v) and 0 <= v <= 100 for v in values) or values[2] <= 0 or values[3] <= 0 or values[0] + values[2] > 100 or values[1] + values[3] > 100:
                raise ValueError('Highlight must fit inside the media card (percent coordinates).')
    return sections


def section_starts(sections, words, duration, fps=30):
    total = round(duration * fps)
    if not math.isfinite(duration) or total < len(sections):
        raise ValueError('The voiceover must allow at least one frame per section.')
    tokens = [(token, float(w['start'])) for w in words for token in normalize_text(w['word']).split()]
    points = {0: 0, len(sections): total}
    for index, section in enumerate(sections):
        start = section.get('start_seconds')
        phrase = normalize_text(section.get('start_phrase', '')).split()
        if start not in (None, '') and phrase:
            raise ValueError('Choose a start time OR a spoken phrase, not both.')
        if start not in (None, ''):
            value = float(start)
            if not math.isfinite(value) or value < 0:
                raise ValueError('Section start times must be positive finite seconds.')
            frame = round(value * fps)
        elif phrase:
            lower = max(v for k, v in points.items() if k < index) if index else 0
            found = [round(tokens[j][1] * fps) for j in range(len(tokens) - len(phrase) + 1)
                     if [t[0] for t in tokens[j:j + len(phrase)]] == phrase and round(tokens[j][1] * fps) >= lower + (1 if index else 0)]
            if not found:
                raise ValueError(f"Spoken phrase not found in order: {section['start_phrase']}")
            frame = found[0]
        else:
            continue
        if index == 0 and frame != 0:
            raise ValueError('The first section starts at 0; add an intro section before a later start.')
        if frame >= total:
            raise ValueError('A section starts after the voiceover ends.')
        points[index] = frame
    ordered = sorted(points.items())
    if any(b - a < right - left for (left, a), (right, b) in zip(ordered, ordered[1:])):
        raise ValueError('Section start times must follow the section order.')
    starts = [0] * (len(sections) + 1)
    for (left, a), (right, b) in zip(ordered, ordered[1:]):
        for i in range(left, right + 1):
            starts[i] = round(a + (b - a) * (i - left) / (right - left))
    return starts


def reference_detail_frames(section, words, start, duration, fps):
    tokens=[(token,round(float(word['start'])*fps)) for word in words for token in normalize_text(word['word']).split()
            if start <= round(float(word['start'])*fps) < start+duration]
    delays=[]
    for index, detail in enumerate(section.get('details', [])):
        phrase=normalize_text(detail).split()
        matches=[tokens[i][1]-start for i in range(len(tokens)-len(phrase)+1)
                 if phrase and [token[0] for token in tokens[i:i+len(phrase)]]==phrase]
        delays.append(matches[0] if matches else min(round(index*.22*fps),max(0,duration-1)))
    return delays


def make_timeline(config, project, public, words, duration, probe, fps=30):
    sections = validate_sections(config, project)
    starts = section_starts(sections, words, duration, fps)
    padding = float(config.get('end_padding_seconds', 0))
    if not math.isfinite(padding) or padding < 0:
        raise ValueError('End padding must be non-negative.')
    starts[-1] += round(padding * fps)
    lengths = {}
    def frames(relative):
        if relative not in lengths:
            length = probe(Path(public) / relative)
            if not math.isfinite(length) or length <= 0:
                raise ValueError(f'Invalid video: {relative}')
            lengths[relative] = max(1, math.floor(length * fps))
        return lengths[relative]
    blocks = []
    for i, section in enumerate(sections):
        background = section.get('background', 'gta_background.mp4')
        if not (Path(public) / background).is_file():
            background = 'gta_background.mp4'
        reference = section.get('layout') == 'reference_style'
        block = {**section, 'type': 'section', 'startFrame': starts[i],
                 'durationFrames': starts[i + 1] - starts[i], 'bgVideo': background,
                 'bgDurationFrames': 1 if reference else frames(background), 'gtaOffset': 0.8 + i * 3.4,
                 'captionY': float(section.get('caption_y', .76)), 'captions': section.get('captions', True)}
        for key in ('media', 'secondary_media'):
            if section.get(key):
                relative = public_media(section[key])
                video = Path(section[key]).suffix.lower() in VIDEO_EXTS
                block[key] = {'src': relative, 'kind': 'video' if video else 'image',
                              'durationFrames': frames(relative) if video else None}
            else:
                block[key] = None
        if reference:
            block['referenceStyle'] = config.get('reference_style', {})
            block['variant'] = section.get('variant', 'card')
            block['detailFrames'] = reference_detail_frames(section, words, starts[i], starts[i+1]-starts[i], fps)
        blocks.append(block)
    processed = [{'word': w['word'], 'start': w['start'], 'end': w['end'],
                  'startFrame': round(w['start'] * fps),
                  'endFrame': max(round(w['start'] * fps) + 1, round(words[i + 1]['start'] * fps) if i + 1 < len(words) else starts[-1])}
                 for i, w in enumerate(words)]
    return {'fps': fps, 'totalFrames': starts[-1], 'totalDuration': starts[-1] / fps,
            'captionsInGameBlocks': True, 'style': {'bgBlurScale': float(config.get('bg_blur_scale', .6))},
            'blocks': blocks, 'words': processed}