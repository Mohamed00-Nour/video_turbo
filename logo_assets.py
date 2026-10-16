"""Download optional logo links, validating image content and preserving manual assets."""
from __future__ import annotations
import io
import ipaddress
import socket
import tempfile
import urllib.request
import warnings
from pathlib import Path

from ai_brief import image_url
from pipeline_common import file_signature, read_cache, write_json

MAX_LOGO_BYTES = 12 * 1024 * 1024
LOGO_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}


def public_image_url(url):
    url = image_url(url)
    if not url:
        raise ValueError('Missing logo URL.')
    from urllib.parse import urlparse
    parsed = urlparse(url)
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('Logo URL must resolve to a public website.')
    return url


class PublicImageRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        public_image_url(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def fetch_image(url, destination, *, max_pixels=16000000, max_side=None, label='Logo'):
    from PIL import Image, ImageOps
    public_image_url(url)
    opener = urllib.request.build_opener(PublicImageRedirect())
    request = urllib.request.Request(url, headers={'User-Agent': 'VideoTurbo/1.0', 'Accept': 'image/*'})
    with opener.open(request, timeout=25) as response:
        length = response.headers.get('Content-Length')
        if length and int(length) > MAX_LOGO_BYTES:
            raise ValueError(label + ' image exceeds 12 MB.')
        payload = response.read(MAX_LOGO_BYTES + 1)
    if len(payload) > MAX_LOGO_BYTES:
        raise ValueError(label + ' image exceeds 12 MB.')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(payload)) as image:
            if image.width * image.height > max_pixels:
                raise ValueError(f'{label} image is too large; use an image below {max_pixels // 1000000} megapixels.')
            # JPEG draft decoding reduces memory before the full image is loaded.
            if max_side: image.draft('RGB', (max_side, max_side))
            image.load()  # Reject HTML, truncated downloads and invalid images.
            prepared = ImageOps.exif_transpose(image) if max_side else image
            if max_side: prepared.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            prepared.convert('RGBA').save(destination, format='PNG')


def fetch_logo(url, destination):
    fetch_image(url, destination)


def fetch_reference_image(url, destination):
    # Accept normal camera photographs, but bound decoding and renderer memory.
    fetch_image(url, destination, max_pixels=64000000, max_side=2560, label='Reference')


def prepare_logo(url, game_dir, log=print, manual=False):
    """Return whether a usable logo exists; optional failures never stop a video."""
    game_dir = Path(game_dir)
    game_dir.mkdir(parents=True, exist_ok=True)
    destination = game_dir / 'logo.png'
    manifest_path = game_dir / '.logo_manifest.json'
    record = read_cache(manifest_path)
    existing = [p for p in game_dir.iterdir() if p.is_file() and p.suffix.lower() in LOGO_EXTS]
    generated = destination.is_file() and record.get('output') == file_signature(destination)
    if manual or (existing and not generated):
        log('  Keeping the existing manual logo.')
        return bool(existing)
    if generated and record.get('url') == url:
        log('  Logo is cached; skipping download.')
        return True
    try:
        with tempfile.TemporaryDirectory(prefix='.logo-', dir=game_dir) as work:
            pending = Path(work) / 'logo.png'
            fetch_logo(url, pending)
            pending.replace(destination)
        write_json(manifest_path, {'url': url, 'output': file_signature(destination)})
        log('  Logo downloaded from the supplied image link.')
        return True
    except Exception as error:
        log(f'  WARNING: logo download failed ({error}). Upload an image or correct the logo URL; continuing.')
        return bool(existing)
