"""Parse an optional AI brief as project data; never interpret it as instructions."""
from __future__ import annotations
import ipaddress
import json
import re
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}


def image_url(value):
    """Validate the form of an optional public image URL without network access."""
    if value is None or value == '':
        return ''
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('Logo URL must be a direct HTTP or HTTPS image link, or null.')
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Logo URL must be a direct HTTP or HTTPS image link.')
    host = parsed.hostname.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.localhost', '.local')):
        raise ValueError('Logo URL must point to a public website.')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if '.' not in host:
            raise ValueError('Logo URL must point to a public website.')
    else:
        if not address.is_global:
            raise ValueError('Logo URL must point to a public website.')
    try:
        parsed.port
    except ValueError:
        raise ValueError('Invalid port in logo URL.') from None
    return value


def gameplay_url(value):
    if not isinstance(value, str):
        raise ValueError('Each game needs a YouTube gameplay_url.')
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in YOUTUBE_HOSTS or parsed.username or parsed.password:
        raise ValueError('Each gameplay_url must link to a YouTube video.')
    parts = parsed.path.strip('/').split('/')
    identifier = parts[0] if parsed.hostname == 'youtu.be' else (
        parse_qs(parsed.query).get('v', [''])[0] if parsed.path == '/watch' else
        parts[1] if len(parts) == 2 and parts[0] in ('shorts', 'embed', 'live') else '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', identifier) or identifier.lower() == 'placeholder':
        raise ValueError('Use a complete YouTube video URL; placeholder links and playlists cannot be imported.')
    return value


def brief_field(row, *keys):
    """Accept equivalent brief formats without silently choosing conflicting data."""
    present = [(key, row[key]) for key in keys if key in row]
    if not present:
        return None
    values = [value.strip() if isinstance(value, str) else value for _, value in present]
    if any(value != values[0] for value in values[1:]):
        raise ValueError(f"Conflicting values for {' / '.join(keys)}. Use one field name or matching values.")
    return present[0][1]


def parse_brief(raw):
    if isinstance(raw, str):
        raw = raw.strip().lstrip('\ufeff')
        if raw.startswith('```'):
            match = re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n```', raw, re.IGNORECASE)
            if not match:
                raise ValueError('Paste one JSON object, or one complete JSON code block.')
            raw = match[1]
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f'Invalid JSON at line {error.lineno}. Paste the AI brief JSON only.') from None
    if not isinstance(raw, dict):
        raise ValueError('The brief must be a JSON object.')
    name = raw.get('project_name')
    script = raw.get('script')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise ValueError('Give the brief a project_name of 1 to 80 characters.')
    if not isinstance(script, str) or not script.strip() or len(script) > 100000:
        raise ValueError('Include a nonempty script containing only the words you will record.')
    rows = raw.get('games')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise ValueError('Include a games list with 1 to 50 entries.')
    games, warnings = [], []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f'Game {index + 1} must be an object.')
        title = brief_field(row, 'name', 'exact_name')
        if not isinstance(title, str) or not title.strip() or len(title) > 150:
            raise ValueError(f'Game {index + 1} needs a name.')
        title = title.strip()
        aliases = row.get('spoken_names', [title])
        if not isinstance(aliases, list) or len(aliases) > 20 or any(not isinstance(a, str) or not a.strip() or len(a) > 150 for a in aliases):
            raise ValueError(f'{title}: spoken_names must be a list of names exactly as spoken in the script.')
        aliases = list(dict.fromkeys([a.strip() for a in aliases])) or [title]
        slug = re.sub(r'[^\w .()-]', '', title).strip(' .')[:65] or 'game'
        try:
            source = gameplay_url(brief_field(row, 'gameplay_url', 'youtube_gameplay_url'))
            logo = image_url(brief_field(row, 'logo_url', 'logo_image_url'))
        except ValueError as error:
            raise ValueError(f'{title}: {error}') from None
        games.append({'folder': f'{index + 1:02d}_{slug}', 'title': title,
                      'spoken_names': aliases, 'url': source, 'logo_url': logo})
        if not logo:
            warnings.append(f'{title}: no logo link; the video can still be built.')
    editor = {'name': name.strip(), 'script': script.strip(), 'mode': 'games',
              'games': games, 'sections': [], 'captions': True}
    return {'editor': editor, 'warnings': warnings}
