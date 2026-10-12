"""Local publishing drafts, protected account connections, and explicit upload jobs."""
from __future__ import annotations
import base64
import copy
import ctypes
import hashlib
import json
import os
import re
import secrets
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from pipeline_common import file_signature, fingerprint, read_cache, write_json
from publishing_clients import youtube_upload, instagram_publish, public_video_url, InstagramProcessingError
from facebook_publishing import facebook_publish, facebook_status, facebook_id, facebook_permalink, facebook_publication_state, FacebookPublishError

OAUTH = ('youtube', 'instagram')
DIRECT = OAUTH + ('facebook_page',)
PLATFORMS = DIRECT + ('facebook', 'tiktok')
HELP = {
    'youtube': 'https://console.cloud.google.com/apis/credentials',
    'instagram': 'https://developers.facebook.com/apps/',
    'facebook_page': 'https://developers.facebook.com/tools/explorer/',
}
SCOPES = {'youtube': 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',
          'instagram': 'instagram_business_basic,instagram_business_content_publish'}


def _protect(payload, decrypt=False):
    """Windows DPAPI binds saved credentials to this Windows user."""
    if os.name != 'nt': return payload
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_uint32), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    source = Blob(len(payload), buffer)
    target = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError('Could not access the locally protected publishing credentials.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(target.data)


class Publisher:
    def __init__(self, data, project_resolver, session=None):
        self.data = Path(data) / 'publishing'
        self.project_resolver = project_resolver
        self.session = session or requests.Session()
        self.lock = threading.RLock()
        self.pending = {}
        self.vault = {'settings': {}, 'accounts': {}}
        vault_file = self.data / 'accounts.json'
        if vault_file.exists():
            try:
                envelope = read_cache(vault_file)
                self.vault = json.loads(_protect(base64.b64decode(envelope['payload']),
                                               decrypt=envelope.get('protection') == 'windows-dpapi'))
            except (OSError, ValueError, KeyError):
                raise ValueError('Publishing credentials could not be opened. Use the Windows user that connected the accounts.') from None
        self.job = read_cache(self.data / 'job.json') or None
        if self.job and self.job.get('status') == 'running':
            self.job.update(status='interrupted', stage='Upload interrupted', finished=time.time(),
                            error='Studio restarted during an upload. Check your account before trying again.')
            self._persist_job()
            self._history_status(self.job)

    @property
    def running(self):
        return bool(self.job and self.job.get('status') == 'running')

    def _idle(self):
        if self.running:
            raise ValueError('Wait for the current publishing upload to finish.')

    def _vault_save(self):
        payload = json.dumps(self.vault, ensure_ascii=False).encode('utf-8')
        write_json(self.data / 'accounts.json', {'protection': 'windows-dpapi' if os.name == 'nt' else 'file-permissions',
                   'payload': base64.b64encode(_protect(payload)).decode('ascii')})
        if os.name != 'nt':
            os.chmod(self.data, 0o700)
            os.chmod(self.data / 'accounts.json', 0o600)

    def _record_path(self, identifier):
        self.project_resolver(identifier)
        return self.data / ('project-' + hashlib.sha256(identifier.encode()).hexdigest() + '.json')

    def _record(self, identifier):
        return read_cache(self._record_path(identifier)) or {'history': []}

    def _save_record(self, identifier, record):
        write_json(self._record_path(identifier), record)

    def _persist_job(self):
        write_json(self.data / 'job.json', self.job)

    def _history_status(self, job):
        record = self._record(job['project'])
        entry = next((row for row in record['history'] if row['id'] == job['id']), None)
        if entry:
            entry.update(status=job['status'], finished=job.get('finished'), url=job.get('url', ''),
                         error=job.get('error', ''), remote_id=job.get('remote_id', ''), warning=job.get('warning', ''),
                         container_id=job.get('container_id', ''), processing_status=job.get('processing_status', ''),
                         publish_attempted=job.get('publish_attempted', False))
            self._save_record(job['project'], record)

    def _video(self, identifier):
        root = Path(self.project_resolver(identifier)).resolve()
        path = (root / 'output/final.mp4').resolve()
        if not path.is_relative_to(root): raise ValueError('The completed video must stay inside its project.')
        ready = path.is_file() and path.stat().st_size > 0
        signature = fingerprint(file_signature(path)) if ready else ''
        return path, {'ready': ready, 'size': path.stat().st_size if ready else 0, 'signature': signature}

    def _default_draft(self, identifier):
        root = Path(self.project_resolver(identifier))
        editor = read_cache(root / 'studio.json')
        script = root / 'script.txt'
        return {'title': str(editor.get('name') or root.name)[:100],
                'description': script.read_text(encoding='utf-8-sig')[:1800] if script.is_file() else '',
                'hashtags': '', 'youtube_privacy': 'private', 'made_for_kids': False,
                'instagram_share_to_feed': True, 'instagram_video_url': '', 'facebook_page_id': ''}

    def _draft(self, identifier, raw):
        if not isinstance(raw, dict): raise ValueError('Publishing settings must be an object.')
        result = self._default_draft(identifier)
        for key, limit in [('title', 100), ('description', 5000), ('hashtags', 1500), ('instagram_video_url', 2048), ('facebook_page_id', 80)]:
            value = raw.get(key, result[key])
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f'{key.replace("_", " ").capitalize()} must be text of at most {limit} characters.')
            result[key] = value.strip()
        if result['facebook_page_id']:
            facebook_id(result['facebook_page_id'])
        result['hashtags'] = ' '.join('#' + tag.strip(',').lstrip('#') for tag in result['hashtags'].split() if tag.strip(',#'))
        if len(result['hashtags']) > 1500: raise ValueError('Hashtags must fit within 1,500 characters.')
        privacy = raw.get('youtube_privacy', 'private')
        if privacy not in ('private', 'unlisted', 'public'): raise ValueError('Choose a valid YouTube visibility.')
        result['youtube_privacy'] = privacy
        for key in ('made_for_kids', 'instagram_share_to_feed'):
            value = raw.get(key, result[key])
            if not isinstance(value, bool): raise ValueError('Use the checkbox for ' + key.replace('_', ' ') + '.')
            result[key] = value
        return result

    def _accounts(self):
        result = {}
        for platform in DIRECT:
            settings = self.vault['settings'].get(platform, {})
            account = self.vault['accounts'].get(platform, {})
            result[platform] = {'configured': bool(settings.get('client_id') and settings.get('client_secret')),
                'connected': bool(account.get('access_token') or account.get('refresh_token')),
                'name': account.get('name', ''), 'client_id': settings.get('client_id', ''),
                'has_secret': bool(settings.get('client_secret')), 'redirect_uri': settings.get('redirect_uri', ''),
                'help_url': HELP[platform], 'page_id': account.get('page_id', '')}
        return result

    def active_job(self):
        with self.lock:
            return copy.deepcopy(self.job)

    def snapshot(self, identifier):
        with self.lock:
            record = self._record(identifier)
            return {'draft': record.get('draft') or self._default_draft(identifier),
                    'accounts': self._accounts(), 'video': self._video(identifier)[1],
                    'history': copy.deepcopy(record.get('history', [])), 'job': copy.deepcopy(self.job)}

    def save_draft(self, identifier, draft):
        with self.lock:
            self._idle()
            draft = self._draft(identifier, draft)
            record = self._record(identifier)
            record['draft'] = draft
            self._save_record(identifier, record)
            return {'ok': True, 'draft': draft}

    def configure(self, platform, settings):
        with self.lock:
            self._idle()
            if platform not in OAUTH: raise ValueError('Facebook Pages connect with a Page access token. Choose YouTube or Instagram for OAuth setup.')
            old = self.vault['settings'].get(platform, {})
            client_id = str(settings.get('client_id', '')).strip()
            client_secret = str(settings.get('client_secret', '')).strip() or old.get('client_secret', '')
            if not client_id or not client_secret: raise ValueError('Enter the app/client ID and secret from your developer account.')
            if len(client_id) > 512 or len(client_secret) > 2048: raise ValueError('App credentials are too long.')
            redirect = str(settings.get('redirect_uri', '')).strip()
            if platform == 'instagram' and redirect:
                parsed = urlparse(redirect)
                if (parsed.scheme != 'https' or not parsed.hostname or parsed.query or parsed.fragment
                        or parsed.username or parsed.password):
                    raise ValueError('Register an HTTPS Instagram redirect URL without query parameters.')
            changed = old.get('client_id') != client_id or old.get('client_secret') != client_secret
            self.vault['settings'][platform] = {'client_id': client_id, 'client_secret': client_secret,
                                              'redirect_uri': redirect, 'api_version': 'v26.0'}
            if changed: self.vault['accounts'].pop(platform, None)
            self.pending = {key: val for key, val in self.pending.items() if val['platform'] != platform}
            self._vault_save()
            return {'ok': True}

    def connect(self, platform, base_url):
        with self.lock:
            self._idle()
            if platform not in OAUTH: raise ValueError('Facebook Pages connect with a Page access token in Account setup.')
            settings = self.vault['settings'].get(platform, {})
            if not settings.get('client_id') or not settings.get('client_secret'):
                raise ValueError('Save the app credentials in Account setup first.')
            if not re.fullmatch(r'http://127\.0\.0\.1:\d+', base_url): raise ValueError('Use the local Studio address.')
            redirect = (base_url + '/api/publishing/callback/youtube') if platform == 'youtube' else settings.get('redirect_uri', '')
            if not redirect: raise ValueError('Instagram needs a registered HTTPS redirect URL, or connect with an app-generated access token.')
            state = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(48)
            self.pending = {key: val for key, val in self.pending.items() if val['expires'] > time.time() and val['platform'] != platform}
            self.pending[state] = {'platform': platform, 'expires': time.time() + 600,
                'redirect': redirect, 'verifier': verifier, 'settings': copy.deepcopy(settings)}
            query = {'client_id': settings['client_id'], 'redirect_uri': redirect,
                     'response_type': 'code', 'scope': SCOPES[platform], 'state': state}
            if platform == 'youtube':
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
                query.update(access_type='offline', prompt='consent', code_challenge=challenge, code_challenge_method='S256')
                endpoint = 'https://accounts.google.com/o/oauth2/v2/auth'
            else:
                query.update(enable_fb_login='false', force_authentication='1')
                endpoint = 'https://www.instagram.com/oauth/authorize'
            return {'authorization_url': endpoint + '?' + urlencode(query), 'redirect_uri': redirect,
                    'manual_callback': platform == 'instagram'}

    def _request(self, method, url, **kwargs):
        try:
            response = self.session.request(method, url, timeout=(15, 45), allow_redirects=False, **kwargs)
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise ValueError('Could not contact the account provider. Check your connection and try again.') from None
        if not 200 <= response.status_code < 300 or not isinstance(payload, dict) or payload.get('error'):
            raise ValueError('The account provider rejected the connection. Check app permissions and reconnect.')
        return payload

    def finish_oauth(self, platform, query):
        with self.lock:
            self._idle()
            redirect_url = query if isinstance(query, str) else ''
            values = parse_qs(urlparse(query).query) if redirect_url else query
            if not isinstance(values, dict): raise ValueError('Paste the full completed OAuth redirect URL.')
            def field(key):
                value = values.get(key, '')
                return value[0] if isinstance(value, list) and len(value) == 1 else value if isinstance(value, str) else ''
            state = field('state')
            pending = self.pending.pop(state, None)
            if not pending or pending['platform'] != platform or pending['expires'] < time.time():
                raise ValueError('This sign-in has expired or does not match. Start account authorization again.')
            if redirect_url:
                actual, expected = urlparse(redirect_url), urlparse(pending['redirect'])
                if (actual.scheme, actual.netloc, actual.path) != (expected.scheme, expected.netloc, expected.path):
                    raise ValueError('Paste the redirect URL registered for this sign-in.')
            if field('error') or not field('code'): raise ValueError('Account authorization was not completed. Start sign-in again.')
            settings = pending['settings']
            data = {'client_id': settings['client_id'], 'client_secret': settings['client_secret'],
                    'grant_type': 'authorization_code', 'redirect_uri': pending['redirect'], 'code': field('code')}
            if platform == 'youtube':
                data['code_verifier'] = pending['verifier']
                token = self._request('POST', 'https://oauth2.googleapis.com/token', data=data)
                if not token.get('access_token'): raise ValueError('YouTube did not return an access token.')
                profile = self._request('GET', 'https://www.googleapis.com/youtube/v3/channels',
                    params={'part': 'snippet', 'mine': 'true'}, headers={'Authorization': 'Bearer ' + token['access_token']})
                rows = profile.get('items', [])
                if not rows: raise ValueError('No YouTube channel was found for this Google account.')
                account = {**token, 'user_id': rows[0]['id'], 'name': rows[0]['snippet']['title'],
                           'expires_at': time.time() + float(token.get('expires_in', 3600))}
            elif platform == 'instagram':
                token = self._request('POST', 'https://api.instagram.com/oauth/access_token', data=data)
                # Some provider responses wrap the token object in a data array.
                if isinstance(token.get('data'), list): token = token['data'][0]
                if not token.get('access_token'): raise ValueError('Instagram did not return an access token.')
                long_token = self._request('GET', 'https://graph.instagram.com/access_token', params={
                    'grant_type': 'ig_exchange_token', 'client_secret': settings['client_secret'], 'access_token': token['access_token']})
                account = self._instagram_identity(long_token['access_token'])
                account['expires_at'] = time.time() + float(long_token.get('expires_in', 5184000))
            else: raise ValueError('Choose YouTube or Instagram.')
            self.vault['accounts'][platform] = account
            self._vault_save()
            return {'ok': True}

    def _instagram_identity(self, token):
        profile = self._request('GET', 'https://graph.instagram.com/v26.0/me',
            params={'fields': 'id,user_id,username', 'access_token': token})
        identifier = profile.get('user_id') or profile.get('id')
        if not identifier or not profile.get('username'): raise ValueError('The token did not identify an Instagram professional account.')
        return {'access_token': token, 'user_id': str(identifier), 'name': '@' + profile['username'], 'api_version': 'v26.0'}

    def _facebook_page_identity(self, token, expected_id=''):
        if expected_id:
            expected_id = facebook_id(expected_id)
        profile = self._request('GET', 'https://graph.facebook.com/v26.0/me',
            headers={'Authorization': 'Bearer ' + token}, params={'fields':'id,name,category'})
        # category belongs to a Page, not a personal-profile /me object.
        if not profile.get('name') or not isinstance(profile.get('category'), str) or not profile['category']:
            raise ValueError('Use a Facebook Page access token, rather than a personal-profile or Instagram token.')
        identifier = facebook_id(profile.get('id'))
        if expected_id and identifier != expected_id:
            raise ValueError('This token belongs to another Facebook Page. Check the Page ID and token.')
        return {'access_token':token, 'page_id':identifier, 'name':str(profile['name']), 'api_version':'v26.0'}

    def connect_token(self, platform, token, page_id=''):
        with self.lock:
            self._idle()
            if platform not in ('instagram', 'facebook_page'):
                raise ValueError('Token connection is available for Instagram and Facebook Pages.')
            if not isinstance(token, str) or not token.strip() or len(token) > 4096:
                raise ValueError('Paste the account access token generated by your Meta app.')
            account = self._instagram_identity(token.strip()) if platform == 'instagram' else self._facebook_page_identity(token.strip(), page_id)
            self.vault['accounts'][platform] = account
            self._vault_save()
            return {'ok': True}

    def disconnect(self, platform):
        with self.lock:
            self._idle()
            if platform not in DIRECT: raise ValueError('Unknown publishing platform.')
            self.vault['accounts'].pop(platform, None)
            self.pending = {key: val for key, val in self.pending.items() if val['platform'] != platform}
            self._vault_save()
            return {'ok': True}

    def _access_account(self, platform):
        account = copy.deepcopy(self.vault['accounts'].get(platform, {}))
        if not account.get('access_token'): raise ValueError('Connect your ' + platform.capitalize() + ' account first.')
        expires = account.get('expires_at', 0)
        if expires and expires < time.time() + 120:
            if platform == 'youtube':
                settings = self.vault['settings'].get(platform, {})
                if not account.get('refresh_token'): raise ValueError('Reconnect YouTube to renew account access.')
                token = self._request('POST', 'https://oauth2.googleapis.com/token', data={
                    'client_id': settings['client_id'], 'client_secret': settings['client_secret'],
                    'grant_type': 'refresh_token', 'refresh_token': account['refresh_token']})
            elif platform == 'facebook_page':
                raise ValueError('Facebook Page access expired. Reconnect it in Account setup.')
            else:
                if expires < time.time(): raise ValueError('Instagram account access expired. Reconnect it in Account setup.')
                token = self._request('GET', 'https://graph.instagram.com/refresh_access_token',
                    params={'grant_type': 'ig_refresh_token', 'access_token': account['access_token']})
            if not token.get('access_token'): raise ValueError('Reconnect your publishing account to renew access.')
            account.update(token)
            account['expires_at'] = time.time() + float(token.get('expires_in', 3600))
            self.vault['accounts'][platform] = account
            self._vault_save()
        return account

    def start(self, identifier, platform, draft, reviewed=False, video_signature=''):
        with self.lock:
            self._idle()
            if platform not in DIRECT: raise ValueError('Use the assisted upload buttons for TikTok and Facebook profiles.')
            if reviewed is not True: raise ValueError('Review the final video and posting settings before publishing.')
            path, video = self._video(identifier)
            if not video['ready']: raise ValueError('Build the video before publishing.')
            if video_signature != video['signature']: raise ValueError('The finished video changed. Reload the publishing screen and review it again.')
            draft = self._draft(identifier, draft)
            if not self._accounts()[platform]['connected']: raise ValueError('Connect your ' + platform.capitalize() + ' account first.')
            caption = '\n\n'.join(x for x in (draft['description'], draft['hashtags']) if x)
            if platform == 'youtube':
                if not draft['title'] or '<' in draft['title'] or '>' in draft['title']: raise ValueError('YouTube needs a title without angle brackets.')
                if len(caption) > 5000: raise ValueError('YouTube description and hashtags must fit within 5,000 characters.')
            elif platform == 'instagram':
                draft['instagram_video_url'] = public_video_url(draft['instagram_video_url'])
                if len(caption) > 2200: raise ValueError('Instagram caption and hashtags must fit within 2,200 characters.')
            destination_id = ''
            destination_name = ''
            if platform == 'facebook_page':
                account = self.vault['accounts'][platform]
                destination_id = facebook_id(account.get('page_id'))
                destination_name = account['name']
                if draft['facebook_page_id'] != destination_id:
                    raise ValueError('The Facebook Page changed. Reload the publishing screen and review the destination again.')
            record = self._record(identifier)
            matching = [row for row in record['history'] if row.get('platform') == platform
                        and row.get('video_signature') == video_signature
                        and (platform != 'facebook_page' or row.get('destination_id') == destination_id)]
            if platform == 'facebook_page' and any(row.get('status') in ('failed', 'interrupted')
                    and row.get('publish_attempted') and not row.get('confirmed_unpublished') for row in matching):
                raise ValueError('A Facebook publish may already have succeeded. Check the existing upload before starting another.')
            if any(row.get('status') in ('complete', 'manual') for row in matching):
                raise ValueError('This video is already recorded as uploaded to ' + platform.capitalize() + '. Check its history before posting again.')
            record['draft'] = draft
            job = {'id': uuid.uuid4().hex, 'project': identifier, 'platform': platform, 'status': 'running',
                'stage': 'Connecting to account', 'progress': 0, 'started': time.time(), 'error': '', 'url': '',
                'destination_id':destination_id, 'destination_name':destination_name}
            record['history'].append({'id': job['id'], 'platform': platform, 'status': 'running', 'url': '',
                'title': draft['title'], 'created': job['started'], 'video_signature': video_signature,
                'visibility': draft['youtube_privacy'] if platform == 'youtube' else 'account', 'method': 'api',
                'destination_id':destination_id, 'destination_name':destination_name})
            self._save_record(identifier, record)
            self.job = job
            self._persist_job()
            threading.Thread(target=self._run, args=(job, path, copy.deepcopy(draft)), daemon=True).start()
            return {'job': copy.deepcopy(job)}

    def _progress(self, job, percent, stage):
        with self.lock:
            job['progress'] = max(job['progress'], min(99, float(percent)))
            job['stage'] = stage
            self._persist_job()

    def _checkpoint(self, job, *, remote_id, publish_attempted):
        with self.lock:
            job.update(remote_id=facebook_id(remote_id, 'video ID'), publish_attempted=publish_attempted is True)
            self._persist_job()
            self._history_status(job)

    def _safe_error(self, error):
        message = str(error) if isinstance(error, ValueError) else 'Upload interrupted. Check your account before retrying.'
        for rows in self.vault.values():
            for row in rows.values():
                for key in ('access_token', 'refresh_token', 'client_secret'):
                    if row.get(key): message = message.replace(row[key], '[redacted]')
        message = re.sub(r'https?://\S+', '[provider URL]', message)
        return message[:600]

    def _run(self, job, path, draft):
        try:
            with self.lock: account = self._access_account(job['platform'])
            progress = lambda n, stage: self._progress(job, n, stage)
            if job['platform'] == 'facebook_page':
                result = facebook_publish(self.session, account, path, draft, progress,
                    checkpoint_callback=lambda **fields:self._checkpoint(job, **fields))
            else:
                adapter = youtube_upload if job['platform'] == 'youtube' else instagram_publish
                result = adapter(self.session, account, path, draft, progress)
            if not isinstance(result, dict) or not result.get('remote_id'):
                raise ValueError('The platform did not confirm the upload. Check your account before trying again.')
            with self.lock:
                job.update(status='complete', stage='Uploaded' if job['platform'] == 'youtube' else 'Published',
                           progress=100, url=result.get('url', ''), remote_id=result['remote_id'],
                           warning=result.get('warning', ''), finished=time.time())
        except Exception as error:
            with self.lock:
                if isinstance(error, FacebookPublishError):
                    job.update(remote_id=error.remote_id, publish_attempted=error.publish_attempted)
                if isinstance(error, InstagramProcessingError):
                    job.update(container_id=error.container_id, processing_status=error.processing_status)
                job.update(status='failed', stage='Upload failed', error=self._safe_error(error), finished=time.time())
        finally:
            with self.lock:
                self._persist_job()
                self._history_status(job)

    def verify_youtube(self, identifier, job_id, url):
        """Confirm an existing video through read-only API calls; never upload it."""
        with self.lock:
            self._idle()
            record = self._record(identifier)
            entry = next((row for row in record['history'] if row['id'] == job_id
                          and row.get('platform') == 'youtube'), None)
            if not entry or entry.get('status') not in ('failed', 'interrupted'):
                raise ValueError('Choose a failed or interrupted YouTube upload to check.')
            path, video = self._video(identifier)
            if not video['ready'] or video['signature'] != entry.get('video_signature'):
                raise ValueError('The project video changed. Check the original upload in YouTube Studio.')
            try:
                parsed = urlparse(url.strip())
                if (parsed.scheme != 'https' or parsed.username or parsed.password
                        or parsed.port not in (None, 443)):
                    raise ValueError()
                host = parsed.hostname
                if host == 'youtu.be':
                    remote_id = parsed.path.strip('/')
                elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
                    remote_id = parse_qs(parsed.query).get('v', [''])[0] if parsed.path == '/watch' else (
                        parsed.path.split('/')[2] if parsed.path.startswith('/shorts/') else '')
                elif host == 'studio.youtube.com' and parsed.path.startswith('/video/'):
                    remote_id = parsed.path.split('/')[2]
                else:
                    raise ValueError()
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', remote_id): raise ValueError()
            except (AttributeError, IndexError, TypeError, ValueError):
                raise ValueError('Paste the existing video link from YouTube Studio.') from None
            account = self._access_account('youtube')
            result = self._request('GET', 'https://www.googleapis.com/youtube/v3/videos',
                params={'part': 'snippet,status,fileDetails,processingDetails', 'id': remote_id},
                headers={'Authorization': 'Bearer ' + account['access_token']})
            rows = result.get('items', [])
            if not rows: raise ValueError('This video was not found. Check its link and connected channel.')
            row = rows[0]
            if row.get('id') != remote_id or not account.get('user_id') or row.get('snippet', {}).get('channelId') != account['user_id']:
                raise ValueError('This video does not belong to the connected YouTube channel.')
            if row['snippet'].get('title') != entry['title']:
                raise ValueError('This video title does not match the upload being checked.')
            status = row.get('status', {}).get('uploadStatus')
            processing = row.get('processingDetails', {}).get('processingStatus')
            if status in ('failed', 'rejected', 'deleted') or processing == 'failed':
                raise ValueError('YouTube reports that this video failed or was rejected. Inspect it in YouTube Studio.')
            file_size = row.get('fileDetails', {}).get('fileSize')
            if file_size is not None and str(file_size) != str(video['size']):
                raise ValueError('The uploaded file size does not match this project video.')
            if status != 'processed' and processing != 'succeeded':
                return {'ok': False, 'message': 'YouTube still reports processing or an incomplete upload. Wait and check again; do not upload a second copy.'}
            if file_size is None:
                raise ValueError('YouTube has not provided the file details needed to verify this upload. Check again later.')
            link = 'https://www.youtube.com/watch?v=' + remote_id
            recovered = {'status': 'complete', 'finished': time.time(), 'url': link, 'remote_id': remote_id,
                         'error': '', 'warning': 'Confirmed by checking the existing YouTube video.', 'verified': True}
            entry.update(recovered)
            self._save_record(identifier, record)
            if self.job and self.job['id'] == job_id:
                self.job.update(recovered, stage='Uploaded', progress=100)
                self._persist_job()
            return {'ok': True, 'url': link, 'message': 'Existing upload verified. History updated without uploading another copy.'}

    def verify_facebook(self, identifier, job_id):
        """Check a known Page upload without sending bytes or publishing again."""
        with self.lock:
            self._idle()
            record = self._record(identifier)
            entry = next((row for row in record['history'] if row['id'] == job_id and row.get('platform') == 'facebook_page'), None)
            if not entry or entry['status'] not in ('failed', 'interrupted') or not entry.get('remote_id'):
                raise ValueError('Choose a failed Facebook Page upload with a recorded video ID.')
            account = self._access_account('facebook_page')
            if account['page_id'] != entry.get('destination_id'):
                raise ValueError('Reconnect the Facebook Page used for this upload before checking it.')
            result = facebook_status(self.session, account, entry['remote_id'], owner=True)
            owner = result.get('from')
            if str(result.get('id')) != entry['remote_id'] or not isinstance(owner, dict) or str(owner.get('id')) != account['page_id']:
                raise ValueError('Facebook did not confirm that this video belongs to the connected Page.')
            state = facebook_publication_state(result)
            if state == 'published':
                recovered = {'status':'complete', 'finished':time.time(), 'url':facebook_permalink(result.get('permalink_url'), entry['remote_id']),
                    'error':'', 'warning':'Confirmed by checking the existing Facebook Reel.', 'verified':True}
                entry.update(recovered)
                self._save_record(identifier, record)
                if self.job and self.job['id'] == job_id:
                    self.job.update(recovered, stage='Published', progress=100)
                    self._persist_job()
                return {'ok':True, 'message':'Existing Facebook Reel verified. No duplicate was uploaded.'}
            if state == 'failed':
                entry['confirmed_unpublished'] = True
                self._save_record(identifier, record)
                return {'ok':False, 'message':'Facebook confirms this upload failed. You can review the video and retry.'}
            return {'ok':False, 'message':'Facebook is still processing this upload. Wait and check again; do not upload another copy.'}

    def mark(self, identifier, platform, url=''):
        with self.lock:
            self._idle()
            if platform not in ('tiktok', 'facebook', 'instagram'): raise ValueError('Choose an assisted upload destination.')
            video = self._video(identifier)[1]
            if not video['ready']: raise ValueError('Build the video before marking it as published.')
            if not isinstance(url, str) or len(url) > 2048: raise ValueError('Enter a valid published post link.')
            url = url.strip()
            hosts = {'tiktok': ('tiktok.com', 'www.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'),
                     'facebook': ('facebook.com', 'www.facebook.com', 'm.facebook.com', 'fb.watch'),
                     'instagram': ('instagram.com', 'www.instagram.com')}
            if url:
                parsed = urlparse(url)
                if parsed.scheme != 'https' or parsed.hostname not in hosts[platform] or parsed.username or parsed.password:
                    raise ValueError('Paste an HTTPS post link from ' + platform.capitalize() + ', or leave it empty.')
            record = self._record(identifier)
            entry = next((row for row in record['history'] if row.get('platform') == platform
                          and row.get('video_signature') == video['signature'] and row['status'] == 'manual'), None)
            if entry:
                entry.update(url=url, finished=time.time())
            else:
                record['history'].append({'id': uuid.uuid4().hex, 'platform': platform, 'status': 'manual',
                    'url': url, 'title': (record.get('draft') or self._default_draft(identifier))['title'],
                    'created': time.time(), 'finished': time.time(), 'video_signature': video['signature'], 'method': 'manual'})
            self._save_record(identifier, record)
            return {'ok': True}
