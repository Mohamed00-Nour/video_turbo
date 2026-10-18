"""Reference-specific finishing; an unanalysed reference gets no decorative preset."""
import math
import os
from pathlib import Path

FINISH_DEFAULTS = {
    'headlines': False, 'headline_font': 'sans', 'headline_motion': 'fade',
    'headline_position': 'top', 'headline_color': 'accent', 'show_grid': False,
    'overlay': False, 'depth_motif': 'none', 'depth_opacity': .3, 'depth_blur': 16,
    'transition': 'cut', 'transition_seconds': .3, 'sound': 'none', 'caption_style': 'panel',
}
FINISH_CHOICES = {
    'headline_font': ('serif', 'sans', 'mono'),
    'headline_motion': ('blur_slide', 'rise', 'scale', 'fade', 'none'),
    'headline_position': ('top', 'center'), 'headline_color': ('accent', 'ink'),
    'depth_motif': ('asterisk', 'arrows', 'orbits', 'none'),
    'transition': ('blur', 'dissolve', 'slide', 'cut'), 'sound': ('subtle', 'none'),
    'caption_style': ('panel', 'plain'),
}


def finishing_style(value=None):
    if value is not None and not isinstance(value, dict):
        raise ValueError('Flow finishing must be a reference style object.')
    style = {**FINISH_DEFAULTS, **(value or {})}
    for key, choices in FINISH_CHOICES.items():
        if style[key] not in choices: raise ValueError('Unsupported Flow finishing ' + key + '.')
    for key in ('headlines', 'show_grid', 'overlay'):
        if not isinstance(style[key], bool): raise ValueError('Invalid Flow finishing ' + key + '.')
    for key, low, high in [('depth_opacity', 0, .7), ('depth_blur', 0, 50), ('transition_seconds', .05, .8)]:
        value = style[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Invalid Flow finishing ' + key + '.')
    return style


def display_font_source(engine):
    """Use a local/installed Bodoni face, with the bundled Amiri face as fallback."""
    engine = Path(engine)
    candidates = [engine / 'fonts/Bodoni-Italic.ttf',
                  Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/BOD_I.TTF',
                  engine / 'studio/ui-fonts/Amiri-Bold.ttf']
    return next(path for path in candidates if path.is_file())
