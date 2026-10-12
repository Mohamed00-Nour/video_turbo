"""Local browser UI for Video Turbo. Run: python video_studio.py"""
from __future__ import annotations
import argparse
import copy
import json
import mimetypes
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from pipeline_common import read_cache, write_json, voiceover_path
import video_sections as sections
from ai_brief import parse_brief, image_url
from publishing import Publisher

ENGINE = Path(__file__).resolve().parent
WEB = ENGINE / 'studio'
DATA = ENGINE / 'output'
PROJECTS = ENGINE / 'projects'
UPLOAD_EXTS = sections.VIDEO_EXTS | sections.IMAGE_EXTS | {'.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg'}


class Studio:
    def __init__(self, data=DATA, projects=PROJECTS):
        self.data, self.projects = Path(data), Path(projects)
        self.registry = read_cache(self.data / 'studio_registry.json')
        self.presets = read_cache(self.data / 'studio_presets.json')
        self.lock = threading.RLock()
        self.job = None
        self.process = None
        self.token = secrets.token_urlsafe(32)
        self.publisher = Publisher(self.data, self.project)

    def persist(self):
        write_json(self.data / 'studio_registry.json', self.registry)

    def project(self, identifier):
        if identifier not in self.registry:
            raise ValueError('Project not found.')
        return Path(self.registry[identifier]['path']).resolve()

    def idle(self):
        if self.publisher.running:
            raise ValueError('Wait for the publishing upload to finish before changing the video project.')
        if self.job and self.job['status'] in ('running', 'cancelling'):
            raise ValueError('Wait for the current job or cancel it before making changes.')

    def register(self, path):
        path = Path(path).resolve()
        for key, value in self.registry.items():
            if value['path'] == str(path):
                return key
        identifier = uuid.uuid4().hex
        self.registry[identifier] = {'path': str(path), 'name': path.name}
        self.persist()
        return identifier

    def create(self, name, preset='blank'):
        self.idle()
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Give the project a name.')
        slug = re.sub(r'[^\w -]', '', name).strip(' .')[:70] or 'video'
        path = self.projects / f'{slug}-{uuid.uuid4().hex[:6]}'
        if preset == 'games':
            editor = {'name': name, 'mode': 'games', 'script': '', 'games': [], 'sections': [], 'captions': True}
        else:
            defaults = {
                'blank': [{'title': 'Opening', 'layout': 'background', 'caption_y': .46}],
                'showcase': [{'title': 'Opening', 'layout': 'background', 'caption_y': .46},
                             {'title': 'Main content', 'layout': 'single'}, {'title': 'Closing', 'layout': 'background'}],
                'comparison': [{'title': 'Opening', 'layout': 'background', 'caption_y': .46},
                               {'title': 'Comparison', 'layout': 'split'}, {'title': 'Closing', 'layout': 'title'}],
            }
            selected = defaults.get(preset) or self.presets.get(preset)
            if selected is None:
                raise ValueError('Unknown layout preset.')
            editor = {'name': name, 'mode': 'sections', 'script': '', 'games': [],
                      'sections': copy.deepcopy(selected), 'captions': True}
        path.mkdir(parents=True, exist_ok=False)
        write_json(path / 'studio.json', editor)
        return self.register(path)

    def import_brief(self, raw):
        self.idle()
        parsed = parse_brief(raw)
        editor = parsed['editor']
        identifier = self.create(editor['name'], 'games')
        result = self.save(identifier, editor)
        config_path = self.project(identifier) / 'config.json'
        config = read_cache(config_path)
        config['brief_sources'] = True
        write_json(config_path, config)
        return result

    def list_projects(self):
        # Discover existing video folders without modifying their contents.
        for path in ENGINE.parent.iterdir():
            if path.is_dir() and (path / 'script.txt').is_file() and ((path / 'games').is_dir() or (path / 'studio.json').is_file()):
                self.register(path)
        return [{'id': key, 'name': value['name'], 'path': value['path']} for key, value in self.registry.items() if Path(value['path']).is_dir()]

    def media(self, path):
        files = []
        for directory in ('media', 'games'):
            for item in (path / directory).rglob('*'):
                if item.is_file() and item.suffix.lower() in sections.VIDEO_EXTS | sections.IMAGE_EXTS and item.resolve().is_relative_to(path.resolve()) and not item.name.startswith('raw_gameplay'):
                    files.append({'path': item.relative_to(path).as_posix(), 'name': item.name,
                                  'kind': 'video' if item.suffix.lower() in sections.VIDEO_EXTS else 'image'})
        return files

    def load(self, identifier):
        path = self.project(identifier)
        editor = read_cache(path / 'studio.json')
        config = read_cache(path / 'config.json')
        if not editor:
            sources = {}
            if (path / 'games.txt').exists():
                for line in (path / 'games.txt').read_text('utf-8-sig').splitlines():
                    if '|' in line and not line.lstrip().startswith('#'):
                        folder, url = line.split('|', 1)
                        sources[folder.strip()] = url.strip()
            games = config.get('games') or [{'folder': p.name, 'title': re.sub(r'^\d+[_ -]*', '', p.name)} for p in sorted((path / 'games').glob('*')) if p.is_dir()]
            editor = {'name': path.name, 'mode': 'sections' if 'sections' in config else 'games',
                      'sections': config.get('sections', []), 'games': [{**g, 'url': sources.get(g['folder'], '')} for g in games],
                      'captions': config.get('captions_in_game_blocks', True)}
        editor['script'] = (path / 'script.txt').read_text('utf-8-sig') if (path / 'script.txt').exists() else editor.get('script', '')
        try:
            voice = voiceover_path(path).name
        except FileNotFoundError:
            voice = ''
        return {'id': identifier, 'path': str(path), 'editor': editor, 'media': self.media(path),
                'voiceover': voice, 'music': (path / 'music.mp3').is_file(),
                'background': (path / 'gta_background.mp4').is_file(),
                'final': (path / 'output/final.mp4').is_file(), 'preview': (path / 'output/studio_preview.png').is_file()}

    def save(self, identifier, editor):
        self.idle()
        path = self.project(identifier)
        if not isinstance(editor, dict) or editor.get('mode') not in ('sections', 'games'):
            raise ValueError('Invalid project settings.')
        if not isinstance(editor.get('script', ''), str):
            raise ValueError('Script must be text.')
        config = read_cache(path / 'config.json')
        config['captions_in_game_blocks'] = bool(editor.get('captions', True))
        if editor['mode'] == 'sections':
            draft = editor.get('sections', [])
            if not isinstance(draft, list) or not draft:
                raise ValueError('Add a section first.')
            # A draft may have empty media slots; check referenced files now,
            # while full readiness is validated before preview/build.
            for section in draft:
                if section.get('layout', 'single') not in sections.LAYOUTS:
                    raise ValueError('Invalid section layout.')
                for field in ('media', 'secondary_media'):
                    if section.get(field):
                        sections.media_path(path, section[field])
            config['sections'] = draft
            config.pop('games', None)
        else:
            games = editor.get('games', [])
            if not isinstance(games, list) or not games:
                raise ValueError('Add at least one game.')
            seen = set()
            for i, game in enumerate(games):
                folder = (game.get('folder') or f'{i + 1:02d}_game').strip(' .')
                if not re.fullmatch(r'[\w .()-]+', folder) or folder in ('.', '..'):
                    raise ValueError('Use a unique, simple folder name for each game.')
                if folder.casefold() in seen:
                    raise ValueError('Use a unique folder name for each game.')
                seen.add(folder.casefold())
                game['folder'] = folder
                if game.get('url') and (urlparse(game['url']).scheme not in ('http', 'https') or urlparse(game['url']).hostname not in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be')):
                    raise ValueError('Game download sources must be YouTube URLs.')
                game['logo_url'] = image_url(game.get('logo_url'))
                for field in ('top', 'bottom', 'logo'):
                    if game.get(field):
                        source = sections.media_path(path, game[field])
                        if field != 'logo' and source.suffix.lower() != '.mp4':
                            raise ValueError('Use MP4 files for game clips.')
                        if field == 'logo' and source.suffix.lower() not in sections.IMAGE_EXTS:
                            raise ValueError('Choose an image for the game logo.')
            for game in games:
                target = path / 'games' / game['folder']
                if not target.resolve().is_relative_to(path):
                    raise ValueError('Game folder points outside the project.')
                target.mkdir(parents=True, exist_ok=True)
                for field in ('top', 'bottom', 'logo'):
                    if game.get(field):
                        source = sections.media_path(path, game[field])
                        dest = target / (field + source.suffix.lower())
                        if source.resolve() != dest.resolve():
                            shutil.copy2(source, dest)
            config.pop('sections', None)
            config['games'] = []
            for game in games:
                spec = {key: game.get(key, []) if key == 'spoken_names' else game.get(key, '')
                        for key in ('folder', 'title', 'spoken_names', 'logo_url')}
                spec['manual_logo'] = bool(game.get('logo'))
                spec['logo_file'] = ('logo' + Path(game['logo']).suffix.lower()) if game.get('logo') else ''
                config['games'].append(spec)
            (path / 'games.txt').write_text('\n'.join(f"{g['folder']} | {g['url']}" for g in games if g.get('url')), encoding='utf-8')
        write_json(path / 'config.json', config)
        write_json(path / 'studio.json', editor)
        (path / 'script.txt').write_text(editor.get('script', ''), encoding='utf-8')
        self.registry[identifier]['name'] = editor.get('name') or path.name
        self.persist()
        return self.load(identifier)

    def start(self, identifier, action, at=0):
        with self.lock:
            self.idle()
            if action not in ('build', 'preview'):
                raise ValueError('Choose build or preview.')
            path = self.project(identifier)
            voiceover_path(path)
            config = read_cache(path / 'config.json')
            if 'sections' in config:
                sections.validate_sections(config, path)
            elif not config.get('games') and not (path / 'games').is_dir():
                raise ValueError('Save your sections or game list first.')
            at = float(at)
            if not math.isfinite(at) or at < 0:
                raise ValueError('Choose a valid preview time.')
            job = {'id': uuid.uuid4().hex, 'project': identifier, 'action': action, 'status': 'running',
                   'stage': 'Starting', 'progress': 0, 'logs': [], 'started': time.time(), 'cancel': False}
            self.job = job
            threading.Thread(target=self.run, args=(job, path, config, float(at)), daemon=True).start()
            return copy.deepcopy(job)

    def run(self, job, path, config, at):
        commands = []
        if 'sections' not in config and (path / 'games.txt').is_file() and (path / 'games.txt').read_text('utf-8').strip():
            commands.append([sys.executable, '-u', str(ENGINE / 'prepare_assets.py'), '--project', str(path)])
        command = [sys.executable, '-u', str(ENGINE / 'build_video.py'), '--project', str(path), '--no-preview']
        if job['action'] == 'preview':
            command += ['--preview-only', '--preview-at', str(at)]
        commands.append(command)
        try:
            for command in commands:
                with self.lock:
                    if job['cancel']:
                        break
                    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'}
                    self.process = subprocess.Popen(command, cwd=ENGINE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                    text=True, encoding='utf-8', errors='replace', env=env,
                                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    process = self.process
                for line in process.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    with self.lock:
                        job['logs'].append(line)
                        job['logs'] = job['logs'][-600:]
                        if 'Transcribing' in line: job['stage'] = 'Transcribing voiceover'
                        if 'Aligning' in line: job['stage'] = 'Aligning captions'
                        if '[PREPARE]' in line: job['stage'] = 'Preparing footage'
                        if 'Bundling' in line: job['stage'] = 'Preparing renderer'
                        for word, lower, span in [('Rendered', 10, 75), ('Encoded', 85, 12)]:
                            match = re.search(rf'{word}\s+(\d+)/(\d+)', line)
                            if match:
                                job['stage'] = 'Rendering frames' if word == 'Rendered' else 'Encoding video'
                                job['progress'] = lower + span * int(match[1]) / max(1, int(match[2]))
                        if 'Audio' in line or 'muxing' in line: job['stage'] = 'Finishing audio'
                code = process.wait()
                with self.lock:
                    self.process = None
                    if job['cancel']:
                        break
                if code != 0:
                    raise RuntimeError('Build step failed. See the job log for details.')
            with self.lock:
                job['status'] = 'cancelled' if job['cancel'] else 'complete'
                job['stage'] = 'Cancelled' if job['cancel'] else 'Ready'
                job['progress'] = 0 if job['cancel'] else 100
        except Exception as error:
            with self.lock:
                job['status'] = 'cancelled' if job['cancel'] else 'failed'
                job['error'] = str(error)
                job['stage'] = job['status'].capitalize()
        finally:
            with self.lock:
                self.process = None
                job['finished'] = time.time()

    def cancel(self):
        with self.lock:
            if not self.job or self.job['status'] != 'running':
                raise ValueError('No running job to cancel.')
            self.job['cancel'] = True
            self.job['status'] = 'cancelling'
            process = self.process
            if process and process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, check=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    process.terminate()
            return {'ok': True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    @property
    def studio(self): return self.server.studio

    def json_response(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def send_file(self, path):
        if not path.is_file():
            raise ValueError('File not found.')
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        request = self.headers.get('Range')
        if request:
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', request)
            if not match or int(match[1]) >= size:
                self.send_response(416); self.send_header('Content-Range', f'bytes */{size}'); self.end_headers(); return
            start = int(match[1]); end = min(end, int(match[2]) if match[2] else end); status = 206
            if end < start: raise ValueError('Invalid byte range.')
        self.send_response(status)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(max(0, end - start + 1)))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-store')
        if status == 206: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as source:
            source.seek(start); remaining = end - start + 1
            while remaining > 0:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk: break
                self.wfile.write(chunk); remaining -= len(chunk)

    def do_GET(self):
        try:
            parsed = urlparse(self.path); query = parse_qs(parsed.query)
            host = self.headers.get('Host', '')
            if host not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                self.json_response({'error': 'Use the localhost address.'}, 403); return
            if parsed.path == '/api/health':
                self.json_response({'app': 'video-turbo-studio', 'engine': str(ENGINE)})
            elif parsed.path == '/api/state':
                with self.studio.lock:
                    self.json_response({'token': self.studio.token, 'projects': self.studio.list_projects(),
                                        'presets': list(self.studio.presets), 'job': self.studio.job,
                                        'publishing_job': self.studio.publisher.active_job()})
            elif parsed.path == '/api/project':
                with self.studio.lock: self.json_response(self.studio.load(query['id'][0]))
            elif parsed.path == '/api/job':
                with self.studio.lock: self.json_response(self.studio.job)
            elif parsed.path == '/api/publishing':
                self.json_response(self.studio.publisher.snapshot(query['id'][0]))
            elif parsed.path == '/api/publishing/job':
                self.json_response(self.studio.publisher.active_job())
            elif parsed.path == '/api/publishing/callback/youtube':
                self.studio.publisher.finish_oauth('youtube', query)
                payload = b'<!doctype html><meta charset="utf-8"><title>YouTube connected</title><p>YouTube is connected. Return to your Video Turbo Studio tab. You can close this tab.</p>'
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.end_headers()
                self.wfile.write(payload)
            elif parsed.path == '/media':
                project = self.studio.project(query['id'][0])
                relative = query['file'][0]
                path = (project / relative).resolve()
                if not path.is_relative_to(project) or path.suffix.lower() not in UPLOAD_EXTS:
                    raise ValueError('Invalid media path.')
                self.send_file(path)
            elif parsed.path == '/caption-font.css':
                self.send_file(ENGINE / 'code/src/font.css')
            elif parsed.path.startswith('/library/'):
                name = unquote(parsed.path.split('/')[-1])
                aliases = {'gta_background.mp4': ['gta_background.mp4'], 'roblox.mp4': ['roblox.mp4', 'Roblox 1.mp4'], 'fortnite.mp4': ['fortnite.mp4', 'Fortnight.mp4']}
                if name not in aliases: raise ValueError('Unknown background.')
                source = next((ENGINE / alias for alias in aliases[name] if (ENGINE / alias).is_file()), None)
                if source is None: raise ValueError('Background not installed.')
                self.send_file(source)
            else:
                name = parsed.path.lstrip('/') or 'index.html'
                path = (WEB / name).resolve()
                if not path.is_relative_to(WEB.resolve()) or path.suffix not in ('.html', '.css', '.js'):
                    raise ValueError('Page not found.')
                self.send_file(path)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except (ValueError, KeyError, OSError) as error:
            self.json_response({'error': str(error)}, 400)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            expected = f'http://127.0.0.1:{self.server.server_port}'
            origin = self.headers.get('Origin')
            if self.headers.get('X-Studio-Token') != self.studio.token or (origin and origin not in (expected, f'http://localhost:{self.server.server_port}')):
                self.json_response({'error': 'Reload the studio page.'}, 403); return
            length = int(self.headers.get('Content-Length', '0'))
            query = parse_qs(parsed.query)
            if parsed.path == '/api/upload':
                with self.studio.lock:
                    self.studio.idle()
                    project = self.studio.project(query['id'][0])
                    name = Path(query['name'][0]).name; ext = Path(name).suffix.lower()
                    role = query.get('role', ['media'])[0]
                    if ext not in UPLOAD_EXTS or not 0 < length <= 4 * 1024**3:
                        raise ValueError('Use a supported media file, up to 4 GB.')
                    if role == 'voice':
                        if ext not in {'.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg'}: raise ValueError('Choose an audio file for the voiceover.')
                        target = project / ('voiceover' + ext)
                    elif role in ('music', 'background'):
                        if ext != ('.mp3' if role == 'music' else '.mp4'): raise ValueError('Use MP3 for music and MP4 for backgrounds.')
                        target = project / ('music.mp3' if role == 'music' else 'gta_background.mp4')
                    elif role == 'media':
                        if ext not in sections.VIDEO_EXTS | sections.IMAGE_EXTS: raise ValueError('Choose a clip or screenshot.')
                        target = project / 'media' / (uuid.uuid4().hex[:12] + '-' + re.sub(r'[^\w .()-]', '', Path(name).stem)[:60] + ext)
                    else: raise ValueError('Unknown upload type.')
                    if not target.resolve().is_relative_to(project): raise ValueError('Upload target points outside the project.')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    pending = target.with_name('.upload-' + uuid.uuid4().hex)
                    try:
                        with pending.open('wb') as out:
                            remaining = length
                            while remaining:
                                data = self.rfile.read(min(1024 * 1024, remaining))
                                if not data: raise ValueError('Upload was interrupted.')
                                out.write(data); remaining -= len(data)
                        pending.replace(target)
                        if role == 'voice':
                            for suffix in ('.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg'):
                                old = project / ('voiceover' + suffix)
                                if old != target: old.unlink(missing_ok=True)
                    finally: pending.unlink(missing_ok=True)
                    self.json_response({'path': target.relative_to(project).as_posix(), 'project': self.studio.load(query['id'][0])})
                return
            if length > 2 * 1024**2: raise ValueError('Request too large.')
            data = json.loads(self.rfile.read(length))
            with self.studio.lock:
                if parsed.path == '/api/create':
                    identifier = self.studio.create(data['name'], data.get('preset', 'blank')); result = self.studio.load(identifier)
                elif parsed.path == '/api/brief/validate': result = parse_brief(data['brief'])
                elif parsed.path == '/api/brief/import': result = self.studio.import_brief(data['brief'])
                elif parsed.path == '/api/import':
                    self.studio.idle(); path = Path(data['path']).resolve()
                    if not path.is_dir() or not (path / 'script.txt').is_file(): raise ValueError('Choose an existing video folder containing script.txt.')
                    result = self.studio.load(self.studio.register(path))
                elif parsed.path == '/api/save': result = self.studio.save(data['id'], data['editor'])
                elif parsed.path == '/api/start': result = self.studio.start(data['id'], data['action'], data.get('at', 0))
                elif parsed.path == '/api/cancel': result = self.studio.cancel()
                elif parsed.path == '/api/publishing/save':
                    self.studio.idle(); result = self.studio.publisher.save_draft(data['id'], data['draft'])
                elif parsed.path == '/api/publishing/settings':
                    self.studio.idle(); result = self.studio.publisher.configure(data['platform'], data)
                elif parsed.path == '/api/publishing/connect':
                    self.studio.idle(); result = self.studio.publisher.connect(data['platform'], expected)
                elif parsed.path == '/api/publishing/oauth/finish':
                    self.studio.idle(); result = self.studio.publisher.finish_oauth(data['platform'], data['redirect_url'])
                elif parsed.path == '/api/publishing/token':
                    self.studio.idle(); result = self.studio.publisher.connect_token(data['platform'], data['access_token'], data.get('page_id', ''))
                elif parsed.path == '/api/publishing/disconnect':
                    self.studio.idle(); result = self.studio.publisher.disconnect(data['platform'])
                elif parsed.path == '/api/publishing/start':
                    self.studio.idle()
                    result = self.studio.publisher.start(data['id'], data['platform'], data['draft'],
                              data.get('reviewed', False), data.get('video_signature', ''))
                elif parsed.path == '/api/publishing/verify-youtube':
                    self.studio.idle(); result = self.studio.publisher.verify_youtube(data['id'], data['job_id'], data['url'])
                elif parsed.path == '/api/publishing/verify-facebook':
                    self.studio.idle(); result = self.studio.publisher.verify_facebook(data['id'], data['job_id'])
                elif parsed.path == '/api/publishing/mark':
                    self.studio.idle(); result = self.studio.publisher.mark(data['id'], data['platform'], data.get('url', ''))
                elif parsed.path == '/api/preset':
                    self.studio.idle()
                    if not str(data['name']).strip(): raise ValueError('Name the preset.')
                    if data['name'] in ('blank', 'games', 'showcase', 'comparison'): raise ValueError('Choose another preset name.')
                    draft = copy.deepcopy(data['sections'])
                    if not isinstance(draft, list) or not draft: raise ValueError('Add sections to the preset.')
                    for section in draft:
                        for key in ('media', 'secondary_media', 'start_seconds', 'start_phrase'): section.pop(key, None)
                    self.studio.presets[data['name']] = draft
                    write_json(self.studio.data / 'studio_presets.json', self.studio.presets)
                    result = {'ok': True}
                else: raise ValueError('Unknown action.')
            self.json_response(result)
        except (ValueError, KeyError, OSError, TypeError) as error:
            self.json_response({'error': str(error)}, 400)


class StudioServer(ThreadingHTTPServer):
    def server_bind(self):
        # Windows HTTPServer otherwise permits two listeners to share this port,
        # which can route UI requests to a stale backend with a different token.
        if os.name == 'nt':
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def running_studio(url):
    """Identify this studio without changing its projects or interrupting a job."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + '/api/health', timeout=2) as response:
            data = json.loads(response.read(8192))
        return (isinstance(data, dict) and data.get('app') == 'video-turbo-studio'
                and isinstance(data.get('engine'), str) and Path(data['engine']).resolve() == ENGINE)
    except (OSError, ValueError, TypeError):
        return False


def main():
    parser = argparse.ArgumentParser(description='Start the local Video Turbo studio.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    try:
        server = StudioServer(('127.0.0.1', args.port), Handler)
    except OSError as error:
        if running_studio(url):
            print(f'Video Turbo Studio is already running: {url}', flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        print(f'Cannot start the studio on port {args.port}: {error}. Use the already running studio, or choose another --port.', file=sys.stderr)
        return 1
    server.studio = Studio()
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Video Turbo Studio: {url}', flush=True)
    if not args.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        if server.studio.job and server.studio.job['status'] == 'running': server.studio.cancel()
        server.server_close()


if __name__ == '__main__': sys.exit(main())