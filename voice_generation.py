"""ElevenLabs voiceovers for every Studio workflow; no credentials reach the browser."""
from __future__ import annotations
import argparse
import base64
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import requests
from pipeline_common import read_cache, write_json, fingerprint, file_signature, voiceover_path
from publishing import _protect

API = 'https://api.elevenlabs.io'
DEFAULTS = {'source': 'upload', 'voice_id': '', 'model_id': '', 'stability': .5, 'similarity_boost': .75, 'speed': 1.0}


def options(value):
    if not isinstance(value, dict): raise ValueError('Choose your voiceover settings.')
    result = {key: value.get(key, default) for key, default in DEFAULTS.items()}
    if result['source'] not in ('upload', 'elevenlabs'): raise ValueError('Choose Upload or ElevenLabs for your voiceover.')
    for key in ('voice_id', 'model_id'):
        if not isinstance(result[key], str) or (result[key] and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', result[key])):
            raise ValueError('Choose a valid ElevenLabs voice and model.')
    for key, low, high in [('stability', 0, 1), ('similarity_boost', 0, 1), ('speed', .7, 1.2)]:
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Choose a valid voice ' + key.replace('_', ' ') + '.')
    if result['model_id'] == 'eleven_v3' and result['stability'] not in (0, .5, 1):
        raise ValueError('Eleven v3 stability must be 0 (Creative), 0.5 (Natural), or 1 (Robust).')
    if result['model_id'] in ('eleven_v3', 'eleven_v4'): result['speed'] = 1.0
    return result


def project_state(project):
    saved = read_cache(Path(project) / 'voiceover.json')
    result = {**DEFAULTS, **saved}
    generated = result.get('generated', {})
    if generated:
        script = (Path(project) / 'script.txt').read_text('utf-8-sig').strip()
        try: current = file_signature(voiceover_path(Path(project))) == generated.get('file_signature')
        except FileNotFoundError: current = False
        result['stale'] = current and generated.get('fingerprint') != fingerprint({'text': script, **options(result)})
        result['generated_current'] = current
    return result


class ElevenLabs:
    def __init__(self, data, session=None):
        self.path = Path(data) / 'voice' / 'elevenlabs.json'
        self.catalog_path = self.path.with_name('catalog.json')
        self.session = session or requests.Session()
        self.settings = {}
        if self.path.is_file():
            try:
                saved = read_cache(self.path)
                self.settings = json.loads(_protect(base64.b64decode(saved['payload']), decrypt=saved.get('protection') == 'windows-dpapi'))
            except (OSError, ValueError, KeyError):
                raise ValueError('ElevenLabs credentials could not be opened. Use the Windows account that saved them.') from None

    def snapshot(self):
        return {'configured': bool(self.settings.get('api_key')), 'defaults': options(self.settings.get('defaults', {}))}

    def configure(self, api_key='', defaults=None):
        if not isinstance(api_key, str): raise ValueError('Enter an ElevenLabs API key.')
        key = api_key.strip() or self.settings.get('api_key', '')
        if not key or len(key) > 4096 or any(c.isspace() for c in key):
            raise ValueError('Enter an ElevenLabs API key. Blank keeps a saved key.')
        saved = {'api_key': key, 'defaults': options(defaults if defaults is not None else self.settings.get('defaults', {}))}
        payload = base64.b64encode(_protect(json.dumps(saved).encode('utf-8'))).decode('ascii')
        write_json(self.path, {'protection': 'windows-dpapi' if os.name == 'nt' else 'file-permissions', 'payload': payload})
        if os.name != 'nt': os.chmod(self.path.parent, 0o700); os.chmod(self.path, 0o600)
        if key != self.settings.get('api_key'): self.catalog_path.unlink(missing_ok=True)
        self.settings = saved
        return self.snapshot()

    def request(self, method, route, **kwargs):
        key = self.settings.get('api_key')
        if not key: raise ValueError('Connect ElevenLabs in Voice settings first.')
        try:
            response = self.session.request(method, API + route, headers={'xi-api-key': key},
                                            timeout=(15, 120), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise ValueError('ElevenLabs could not be reached. Check your connection; your existing audio is safe.') from None
        if not 200 <= response.status_code < 300:
            status = response.status_code
            response.close()
            reason = ('Check your API key and its Text to Speech, Voices and Models permissions.' if status in (401, 403) else
                      'Check your ElevenLabs subscription, remaining credits and API-key limit.' if status in (402, 429) else
                      'Check the selected voice, model and script length; a cloned voice may still need verification or training.' if status in (400, 404, 422) else
                      'ElevenLabs is unavailable. Retry later.')
            raise ValueError(f'ElevenLabs request failed ({status}). ' + reason)
        return response

    def get(self, route, **kwargs):
        response = self.request('GET', route, **kwargs)
        try: return response.json()
        except ValueError: raise ValueError('ElevenLabs returned an unreadable response. Refresh the connection.') from None
        finally: response.close()

    def catalog(self, refresh=False):
        if not self.settings.get('api_key'): raise ValueError('Save your ElevenLabs API key first.')
        cached = read_cache(self.catalog_path)
        if not refresh and time.time() - cached.get('updated', 0) < 60: return cached
        voices, seen, token = [], set(), None
        for _ in range(100):
            params = {'page_size': 100, 'include_total_count': False}
            if token: params['next_page_token'] = token
            data = self.get('/v2/voices', params=params)
            if not isinstance(data, dict) or not isinstance(data.get('voices'), list): raise ValueError('ElevenLabs returned an invalid voice list.')
            for voice in data['voices']:
                identifier = voice.get('voice_id')
                if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier) or identifier in seen: continue
                seen.add(identifier)
                voices.append({'id': identifier, 'name': voice.get('name') or identifier, 'category': voice.get('category', ''),
                               'fine_tuning': (voice.get('fine_tuning') or {}).get('state', {})})
            if not data.get('has_more'): break
            next_token = data.get('next_page_token')
            if not next_token or next_token == token: raise ValueError('ElevenLabs voice pagination failed. Refresh to retry.')
            token = next_token
        else: raise ValueError('Too many ElevenLabs voices to load. Use a workspace with fewer saved voices.')
        rows = self.get('/v1/models')
        if not isinstance(rows, list): raise ValueError('ElevenLabs returned an invalid model list.')
        models = []
        for row in rows:
            identifier = row.get('model_id', '')
            # Realtime-only models need a WebSocket, not the narration API.
            if not row.get('can_do_text_to_speech') or identifier.endswith(('_conversational', '_v4_turbo')): continue
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier): continue
            limit = row.get('maximum_text_length_per_request')
            limit = limit if isinstance(limit, int) and limit > 0 else 5000
            models.append({'id': identifier, 'name': row.get('name') or identifier, 'limit': limit,
                           'languages': row.get('languages', []), 'serves_pro_voices': row.get('serves_pro_voices', True)})
        if not voices or not models: raise ValueError('No usable voices or narration models were returned. Finish setting up your voice in ElevenLabs, then refresh.')
        result = {'voices': sorted(voices, key=lambda v: (v['category'] not in ('cloned', 'professional'), v['name'].casefold())),
                  'models': models, 'updated': time.time()}
        write_json(self.catalog_path, result)
        return result

    def selection(self, settings, text):
        settings = options(settings)
        if settings['source'] != 'elevenlabs': raise ValueError('Choose ElevenLabs as your voiceover source.')
        catalog = self.catalog()
        voice = next((v for v in catalog['voices'] if v['id'] == settings['voice_id']), None)
        model = next((m for m in catalog['models'] if m['id'] == settings['model_id']), None)
        if not voice or not model: raise ValueError('The selected voice or model is unavailable. Refresh ElevenLabs voices and models.')
        if not text or len(text) > model['limit']:
            raise ValueError(f"This model accepts up to {model['limit']:,} characters per voiceover. Shorten the script or choose another model.")
        if voice['category'] == 'professional' and (not model['serves_pro_voices'] or voice['fine_tuning'].get(model['id']) not in (None, 'fine_tuned')):
            raise ValueError('Your Professional Voice Clone is not ready for this model. Finish its training in ElevenLabs or choose another model.')
        return voice, model

    def generate(self, project, force=False):
        project = Path(project)
        settings = project_state(project)
        text = (project / 'script.txt').read_text('utf-8-sig').strip()
        selected = options(settings)
        digest = fingerprint({'text': text, **selected})
        generated = settings.get('generated', {})
        if not force and generated.get('fingerprint') == digest and settings.get('generated_current'):
            print('[VOICE] Reusing saved ElevenLabs voiceover; no new speech request.', flush=True)
            return generated
        voice, model = self.selection(selected, text)
        print(f'[VOICE] Generating voiceover with {voice["name"]} / {model["name"]} ({len(text):,} characters)', flush=True)
        route = '/v1/text-to-speech/' + voice['id']
        delivery = {k: selected[k] for k in ('stability', 'similarity_boost')}
        if model['id'] not in ('eleven_v3', 'eleven_v4'): delivery['speed'] = selected['speed']
        body = {'model_id': model['id'], 'text': text, 'voice_settings': delivery}
        response = self.request('POST', route, params={'output_format': 'mp3_44100_128'}, json=body, stream=True)
        directory = project / 'voiceover-history'
        directory.mkdir(exist_ok=True)
        pending = directory / ('pending-' + uuid.uuid4().hex + '.mp3')
        # No automatic HTTP retries: a retry could incur a second charge.
        try:
            try:
                with pending.open('wb') as output:
                    size = 0
                    for chunk in response.iter_content(64 * 1024):
                        if not chunk: continue
                        size += len(chunk)
                        if size > 100 * 1024**2: raise ValueError('ElevenLabs audio exceeded the 100 MB voiceover limit.')
                        output.write(chunk)
                if not size: raise ValueError('ElevenLabs returned empty audio. Your existing voiceover is safe.')
            except requests.RequestException:
                raise ValueError('The ElevenLabs audio download was interrupted. Your existing voiceover is safe; check usage before retrying.') from None
            duration = probe_audio(pending)
            archive = directory / (uuid.uuid4().hex + '.mp3')
            pending.replace(archive)
            target = project / 'voiceover.mp3'
            if target.exists(): shutil.copy2(target, directory / ('previous-' + uuid.uuid4().hex + '.mp3'))
            # Replace only after the downloaded audio has been checked.
            replacement = project / ('.voiceover-' + uuid.uuid4().hex + '.mp3')
            try:
                shutil.copyfile(archive, replacement)
                replacement.replace(target)
            finally: replacement.unlink(missing_ok=True)
            generated = {'fingerprint': digest, 'file_signature': file_signature(target), 'voice_name': voice['name'],
                         'model_name': model['name'], 'characters': len(text), 'duration': duration, 'created': time.time(),
                         'archive': archive.relative_to(project).as_posix()}
            write_json(project / 'voiceover.json', {**selected, 'generated': generated})
            print('[VOICE] Voiceover saved. Captions and scenes will follow this audio.', flush=True)
            return generated
        finally:
            response.close()
            pending.unlink(missing_ok=True)


def probe_audio(path):
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', str(path)],
                                capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        value = json.loads(result.stdout)
        duration = float(value.get('format', {}).get('duration', 0))
        if result.returncode or not math.isfinite(duration) or duration <= 0 or not any(s.get('codec_type') == 'audio' for s in value.get('streams', [])):
            raise ValueError()
        return duration
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise ValueError('ElevenLabs did not return playable audio. Your existing voiceover is safe; check usage before retrying.') from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try: ElevenLabs(args.data).generate(args.project, args.force)
    except (ValueError, OSError) as error:
        print('[VOICE] ' + str(error), flush=True)
        return 1
    return 0


if __name__ == '__main__': sys.exit(main())
