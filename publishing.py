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
from publishing_clients import youtube_upload, instagram_publish, public_video_url, InstagramProcessingError, ProviderRequestError, request_json
from facebook_publishing import facebook_publish, facebook_status, facebook_id, facebook_permalink, facebook_publication_state, FacebookPublishError
from instagram_publishing import instagram_local_publish, instagram_container_status, InstagramPublishError
from publishing_clients import _instagram_id

OAUTH = ('youtube', 'instagram')
DIRECT = OAUTH + ('facebook_page',)
PLATFORMS = DIRECT + ('facebook', 'tiktok')
POST_FIELDS = {'title': 100, 'description': 5000, 'hashtags': 1500}
HELP = {
    'youtube': 'https://console.cloud.google.com/apis/credentials',
    'instagram': 'https://developers.facebook.com/apps/',
    'facebook_page': 'https://developers.facebook.com/tools/explorer/',
}
SCOPES = {'youtube': 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly',
          'instagram': 'instagram_business_basic,instagram_business_content_publish'}
META_UPLOAD_ATTEMPTS = 3
META_RECOVERY_CHECKS = 3
META_RETRY_DELAY = 1


def _retryable_network(error):
    return (getattr(error, 'network_kind', None) in ('timeout', 'connection')
            and getattr(error, 'network_reason', None) not in ('tls', 'tls_certificate'))


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
        self.worker_sessions = session is None
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
        saved = read_cache(self.data / 'job.json') or None
        self.jobs = {}
        if saved and 'jobs' in saved:
            self.jobs = {job.get('platform', ''): job for job in saved['jobs']}
            self.job = {key: value for key, value in saved.items() if key != 'jobs'} or None
            if self.job:
                self.job = self.jobs.get(self.job.get('platform'), self.job)
        else:
            self.job = saved
        for job in self._jobs():
            if job.get('status') == 'running':
                job.update(status='interrupted', stage='Upload interrupted', finished=time.time(),
                           error='Studio restarted during an upload. Check your account before trying again.')
                self._history_status(job)
        if saved:
            self._persist_job()

    def _jobs(self):
        jobs = dict(self.jobs)
        if self.job:
            jobs[self.job.get('platform', '')] = self.job
        return list(jobs.values())

    def _find_job(self, job_id):
        return next((job for job in self._jobs() if job.get('id') == job_id), None)

    @property
    def running(self):
        with self.lock:
            return any(job.get('status') == 'running' for job in self._jobs())

    def _idle(self, platform=None):
        if any(job.get('status') == 'running' and
               (platform is None or not job.get('platform') or job['platform'] == platform)
               for job in self._jobs()):
            raise ValueError('Wait for the current publishing upload to finish.' if platform is None
                             else 'An upload to this platform is already running.')

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
        write_json(self.data / 'job.json', {**(self.job or {}), 'jobs': self._jobs()})

    def _history_status(self, job):
        record = self._record(job['project'])
        entry = next((row for row in record['history'] if row['id'] == job['id']), None)
        if entry:
            entry.update(status=job['status'], finished=job.get('finished'), url=job.get('url', ''),
                         error=job.get('error', ''), remote_id=job.get('remote_id', ''), warning=job.get('warning', ''),
                         container_id=job.get('container_id', ''), processing_status=job.get('processing_status', ''),
                         network_reason=job.get('network_reason', ''),
                         retry_count=job.get('retry_count', 0), verified=job.get('verified', False),
                         confirmed_unpublished=job.get('confirmed_unpublished', False),
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
                'instagram_share_to_feed': True, 'instagram_video_url': '', 'facebook_page_id': '',
                'platform_overrides': {}}

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
        overrides = raw.get('platform_overrides', {})
        if not isinstance(overrides, dict) or any(platform not in PLATFORMS for platform in overrides):
            raise ValueError('Use a supported destination for platform posting details.')
        for platform, fields in overrides.items():
            if not isinstance(fields, dict) or any(key not in POST_FIELDS for key in fields):
                raise ValueError('Platform overrides may contain only title, description and hashtags.')
            normalized = {}
            for key, value in fields.items():
                if not isinstance(value, str) or len(value) > POST_FIELDS[key]:
                    raise ValueError(f'{platform} {key} must be text of at most {POST_FIELDS[key]} characters.')
                value = value.strip()
                if key == 'hashtags':
                    value = ' '.join('#' + tag.strip(',').lstrip('#') for tag in value.split() if tag.strip(',#'))
                    if len(value) > POST_FIELDS[key]:
                        raise ValueError('Platform hashtags must fit within 1,500 characters.')
                normalized[key] = value
            if normalized:
                result['platform_overrides'][platform] = normalized
        return result

    @staticmethod
    def _platform_draft(draft, platform):
        result = dict(draft)
        overrides = result.pop('platform_overrides', {})
        result.update(overrides.get(platform, {}))
        return result

    def _accounts(self):
        result = {}
        for platform in DIRECT:
            settings = self.vault['settings'].get(platform, {})
            account = self.vault['accounts'].get(platform, {})
            linked = platform == 'instagram' and account.get('connection_type') == 'facebook'
            page = self.vault['accounts'].get('facebook_page', {}) if linked else {}
            unavailable = linked and (not page.get('access_token') or page.get('needs_reconnect') or page.get('page_id') != account.get('page_id'))
            result[platform] = {'configured': bool(settings.get('client_id') and settings.get('client_secret')),
                'connected': bool(page.get('access_token') if linked else account.get('access_token') or account.get('refresh_token')) and not account.get('needs_reconnect', False) and not unavailable,
                'needs_reconnect': bool(account.get('needs_reconnect') or unavailable),
                'connection_type': account.get('connection_type', 'instagram_login' if platform == 'instagram' else ''),
                'upload_mode': 'local' if linked else 'url' if platform == 'instagram' else 'local',
                'user_id': account.get('user_id', ''), 'source_page_name': account.get('source_page_name', ''),
                'name': account.get('name', ''), 'client_id': settings.get('client_id', ''),
                'has_secret': bool(settings.get('client_secret')), 'redirect_uri': settings.get('redirect_uri', ''),
                'help_url': HELP[platform], 'page_id': account.get('page_id', '')}
        return result

    def active_job(self):
        with self.lock:
            jobs = self._jobs()
            job = next((job for job in jobs if job.get('status') == 'running'), self.job)
            return {**copy.deepcopy(job), 'jobs': copy.deepcopy(jobs)} if job else None

    def snapshot(self, identifier):
        with self.lock:
            record = self._record(identifier)
            return {'draft': record.get('draft') or self._default_draft(identifier),
                    'accounts': self._accounts(), 'video': self._video(identifier)[1],
                    'history': copy.deepcopy(record.get('history', [])), 'job': copy.deepcopy(self.job),
                    'jobs': copy.deepcopy(self._jobs())}

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

    def _facebook_connection_error(self, error, *tokens):
        # Meta's field/access errors explain code 100. Redact all known secrets
        # before using those details in UI text; never include provider URLs.
        detail = error.provider_message
        for token in tokens:
            if token:
                detail = detail.replace(token, '[redacted]')
        detail = re.sub(r'(?:EAA|IGAA)[A-Za-z0-9_-]{8,}', '[redacted]', detail)
        detail = self._safe_error(ValueError(detail))
        if detail:
            return 'Facebook Page connection failed (code ' + str(error.provider_code) + '): ' + detail
        return str(error)

    def _facebook_page_identity(self, token, expected_id='', resolve_user=True):
        if expected_id:
            expected_id = facebook_id(expected_id)
        # A Page's access_token field establishes Page identity. Tokens obtained
        # from /me/accounts already have Page provenance; only verify their ID.
        fields = 'id,name,access_token' if resolve_user else 'id,name'
        try:
            profile = request_json(self.session, 'GET', 'https://graph.facebook.com/v26.0/me',
                headers={'Authorization': 'Bearer ' + token}, params={'fields': fields})
        except ProviderRequestError as error:
            missing_page_field = (error.provider_code == 100 and re.search(
                r'nonexisting field\s*\(access_token\)', error.provider_message, re.IGNORECASE))
            if resolve_user and missing_page_field:
                return self._facebook_page_from_user_token(token, expected_id)
            if error.provider_code == 100:
                raise ValueError(self._facebook_connection_error(error, token)) from None
            raise
        if not profile.get('name'):
            raise ValueError('The token did not identify a Facebook Page.')
        identifier = facebook_id(profile.get('id'))
        if resolve_user and (not isinstance(profile.get('access_token'), str) or not profile['access_token'].strip()):
            return self._facebook_page_from_user_token(token, expected_id)
        if expected_id and identifier != expected_id:
            raise ValueError('This token belongs to another Facebook Page. Check the Page ID and token.')
        return {'access_token':token, 'page_id':identifier, 'name':str(profile['name']), 'api_version':'v26.0'}

    def _facebook_page_from_user_token(self, token, expected_id):
        # Match the chosen Page explicitly; never select a different Page.
        try:
            result = request_json(self.session, 'GET', 'https://graph.facebook.com/v26.0/me/accounts',
                headers={'Authorization':'Bearer ' + token},
                params={'fields':'id,name,access_token,tasks', 'limit':100})
        except ProviderRequestError as error:
            if error.provider_code in (100, 10, 200):
                raise ValueError(self._facebook_connection_error(error, token)) from None
            raise
        pages = result.get('data')
        if not isinstance(pages, list):
            raise ValueError('Facebook did not return the Pages managed by this token.')
        matches = [page for page in pages if isinstance(page, dict)
                   and (not expected_id or str(page.get('id')) == expected_id)]
        if not matches and result.get('paging', {}).get('next'):
            raise ValueError('The selected Page was not in the first 100 results. Select its Page access token in Graph API Explorer and paste that token.')
        if not matches:
            raise ValueError('This User token cannot access the selected Page. Authorize that Page in Meta, include pages_show_list and pages_read_engagement, and generate a new token.')
        if len(matches) != 1:
            raise ValueError('This User token manages multiple Pages. Enter the intended Page ID in Account setup before connecting.')
        page = matches[0]
        page_token = page.get('access_token')
        if not isinstance(page_token, str) or not page_token:
            raise ValueError('Facebook did not return a Page access token for the selected Page. Reauthorize the Page with publishing permissions.')
        return self._facebook_page_identity(page_token, facebook_id(page.get('id')), resolve_user=False)

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

    def connect_instagram_page(self):
        """Resolve and verify the linked professional account using GETs only."""
        with self.lock:
            self._idle()
            page = self._access_account('facebook_page')
            token = page['access_token']
            try:
                profile = request_json(self.session, 'GET', 'https://graph.facebook.com/v26.0/' + page['page_id'],
                    headers={'Authorization':'Bearer ' + token},
                    params={'fields':'id,instagram_business_account{id,username}'})
                if str(profile.get('id')) != page['page_id']:
                    raise ValueError('Facebook returned a different Page. Reconnect the intended Page before connecting Instagram.')
                linked = profile.get('instagram_business_account')
                if not isinstance(linked, dict) or not linked.get('id') or not linked.get('username'):
                    raise ValueError('Meta did not return a linked Instagram professional account. Link Instagram in your Facebook Page settings under Linked accounts, and reconnect the Page with instagram_basic, instagram_content_publish and pages_read_engagement permissions.')
                identifier = _instagram_id(linked['id'], 'linked account ID')
                limit = request_json(self.session, 'GET', 'https://graph.facebook.com/v26.0/' + identifier + '/content_publishing_limit',
                    headers={'Authorization':'Bearer ' + token}, params={'fields':'config,quota_usage'})
                if not isinstance(limit.get('data'), list) or not any(isinstance(row, dict) and isinstance(row.get('quota_usage'), int) and not isinstance(row['quota_usage'], bool) for row in limit['data']):
                    raise ValueError('Instagram publishing access could not be verified. Authorize instagram_content_publish for the linked account in your Meta app.')
            except ProviderRequestError as error:
                if error.provider_code == 190:
                    self.vault['accounts']['facebook_page']['needs_reconnect'] = True
                    self._vault_save()
                    raise
                if error.provider_code in (10, 100, 200):
                    detail = self._facebook_connection_error(error, token).replace('Facebook Page connection failed', 'Instagram local upload setup failed', 1)
                    raise ValueError(detail + ' Add instagram_basic and instagram_content_publish in Meta, authorize the linked account, and reconnect the Facebook Page with a fresh token.') from None
                raise
            account = {'connection_type':'facebook', 'user_id':identifier, 'name':'@' + str(linked['username']),
                'page_id':page['page_id'], 'source_page_name':page['name'], 'api_version':'v26.0'}
            self.vault['accounts']['instagram'] = account
            self._vault_save()
            return {'ok':True, 'message':'Connected ' + account['name'] + ' for local MP4 uploads. No public video link is needed.'}

    def check_account(self, platform):
        """Check the saved Page identity without uploading or publishing."""
        with self.lock:
            self._idle()
            if platform != 'facebook_page':
                raise ValueError('Choose the Facebook Page connection to check.')
            account = self.vault['accounts'].get(platform, {})
            if not account.get('access_token'):
                raise ValueError('Connect your Facebook Page first.')
            try:
                identity = self._facebook_page_identity(account['access_token'], account.get('page_id', ''))
            except ProviderRequestError as error:
                if error.provider_code != 190:
                    raise
                account['needs_reconnect'] = True
                self._vault_save()
                return {'ok': False, 'needs_reconnect': True, 'error_code': error.provider_code,
                        'error_subcode': error.provider_subcode,
                        'message': 'Your Facebook Page access token has expired or is invalid. Reconnect the Page in Account setup with a fresh Page access token.'}
            self.vault['accounts'][platform] = {**account, **identity, 'needs_reconnect': False}
            self._vault_save()
            return {'ok': True, 'message': 'Facebook Page connection verified: ' + identity['name'] + '.'}

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
        if platform == 'instagram' and account.get('connection_type') == 'facebook':
            page = self._access_account('facebook_page')
            if page.get('page_id') != account.get('page_id'):
                raise ValueError('The Facebook Page changed. Reconnect Instagram from the intended Page before publishing.')
            return {**account, 'access_token':page['access_token']}
        if not account.get('access_token'): raise ValueError('Connect your ' + platform.capitalize() + ' account first.')
        if platform == 'facebook_page' and account.get('needs_reconnect'):
            raise ValueError('Reconnect your Facebook Page with a fresh Page access token in Account setup.')
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
        result = self.start_many(identifier, [platform], draft, reviewed, video_signature)
        return {'job': result['jobs'][0]}

    def start_many(self, identifier, platforms, draft, reviewed=False, video_signature=''):
        with self.lock:
            if (not isinstance(platforms, list) or not platforms or
                    any(not isinstance(platform, str) or platform not in DIRECT for platform in platforms)):
                raise ValueError('Choose YouTube, Instagram or Facebook Page for direct publishing.')
            if len(platforms) != len(set(platforms)):
                raise ValueError('Select each publishing platform only once.')
            prepared = [self._prepare_start(identifier, platform, draft, reviewed, video_signature)
                        for platform in platforms]
            record = self._record(identifier)
            record['draft'] = prepared[0][4]
            record['history'].extend(item[3] for item in prepared)
            self._save_record(identifier, record)
            for job, path, post, entry, normalized in prepared:
                self.jobs[job['platform']] = job
                self.job = job
            self._persist_job()
            result = {'jobs': copy.deepcopy([item[0] for item in prepared])}
            for job, path, post, entry, normalized in prepared:
                threading.Thread(target=self._run, args=(job, path, copy.deepcopy(post)), daemon=True).start()
            return result

    def _prepare_start(self, identifier, platform, draft, reviewed, video_signature):
        self._idle(platform)
        if platform not in DIRECT: raise ValueError('Use the assisted upload buttons for TikTok and Facebook profiles.')
        if reviewed is not True: raise ValueError('Review the final video and posting settings before publishing.')
        path, video = self._video(identifier)
        if not video['ready']: raise ValueError('Build the video before publishing.')
        if video_signature != video['signature']: raise ValueError('The finished video changed. Reload the publishing screen and review it again.')
        draft = self._draft(identifier, draft)
        if not self._accounts()[platform]['connected']: raise ValueError('Connect your ' + platform.capitalize() + ' account first.')
        post = self._platform_draft(draft, platform)
        caption = '\n\n'.join(x for x in (post['description'], post['hashtags']) if x)
        if platform == 'youtube':
            if not post['title'] or '<' in post['title'] or '>' in post['title']: raise ValueError('YouTube needs a title without angle brackets.')
            if len(caption) > 5000: raise ValueError('YouTube description and hashtags must fit within 5,000 characters.')
        elif platform == 'instagram':
            if self.vault['accounts'][platform].get('connection_type') != 'facebook':
                post['instagram_video_url'] = public_video_url(draft['instagram_video_url'])
            if len(caption) > 2200: raise ValueError('Instagram caption and hashtags must fit within 2,200 characters.')
        destination_id = ''
        destination_name = ''
        if platform == 'facebook_page':
            account = self.vault['accounts'][platform]
            destination_id = facebook_id(account.get('page_id'))
            destination_name = account['name']
            if draft['facebook_page_id'] != destination_id:
                raise ValueError('The Facebook Page changed. Reload the publishing screen and review the destination again.')
        if platform == 'instagram':
            account = self.vault['accounts'][platform]
            destination_id = _instagram_id(account.get('user_id'), 'account ID')
            destination_name = account['name']
        record = self._record(identifier)
        matching = [row for row in record['history'] if row.get('platform') == platform
                    and row.get('video_signature') == video_signature
                    and (platform != 'facebook_page' or row.get('destination_id') == destination_id)
                    and (platform != 'instagram' or not row.get('destination_id') or row.get('destination_id') == destination_id)]
        if any(row.get('status') == 'running' for row in matching):
            raise ValueError('An upload to this platform is already running.')
        if platform == 'facebook_page' and any(row.get('status') in ('failed', 'interrupted')
                and row.get('publish_attempted') and not row.get('confirmed_unpublished') for row in matching):
            raise ValueError('A Facebook publish may already have succeeded. Check the existing upload before starting another.')
        if platform == 'instagram' and any(row.get('status') in ('failed', 'interrupted')
                and (row.get('publish_attempted') or row.get('processing_status') == 'PUBLISHED')
                and not row.get('confirmed_unpublished') for row in matching):
            raise ValueError('An Instagram publish may already have succeeded. Check the existing upload before starting another.')
        if any(row.get('status') in ('complete', 'manual') for row in matching):
            raise ValueError('This video is already recorded as uploaded to ' + platform.capitalize() + '. Check its history before posting again.')
        job = {'id': uuid.uuid4().hex, 'project': identifier, 'platform': platform, 'status': 'running',
            'video_signature': video_signature,
            'stage': 'Connecting to account', 'progress': 0, 'started': time.time(), 'error': '', 'url': '',
            'destination_id':destination_id, 'destination_name':destination_name,
            'instagram_connection_type':self.vault['accounts'][platform].get('connection_type', 'instagram_login') if platform == 'instagram' else ''}
        entry = {'id': job['id'], 'platform': platform, 'status': 'running', 'url': '',
            'title': post['title'], 'created': job['started'], 'video_signature': video_signature,
            'visibility': draft['youtube_privacy'] if platform == 'youtube' else 'account', 'method': 'api',
            'destination_id':destination_id, 'destination_name':destination_name,
            'instagram_connection_type':job['instagram_connection_type']}
        return job, path, post, entry, draft

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

    def _instagram_checkpoint(self, job, *, container_id, publish_attempted):
        with self.lock:
            job.update(container_id=_instagram_id(container_id, 'media container ID'), publish_attempted=publish_attempted is True)
            self._persist_job()
            self._history_status(job)

    def _safe_error(self, error):
        message = str(error) if isinstance(error, ValueError) else 'Upload interrupted. Check your account before retrying.'
        for rows in self.vault.values():
            for row in rows.values():
                for key in ('access_token', 'refresh_token', 'client_secret'):
                    if row.get(key): message = message.replace(row[key], '[redacted]')
        message = re.sub(r'(?:EAA|IGAA)[A-Za-z0-9_-]{8,}', '[redacted]', message)
        message = re.sub(r'https?://\S+', '[provider URL]', message)
        return message[:600]

    def _read_meta_status(self, operation):
        for attempt in range(META_UPLOAD_ATTEMPTS):
            try:
                return operation()
            except ValueError as error:
                if not _retryable_network(error) or attempt + 1 == META_UPLOAD_ATTEMPTS:
                    raise
                time.sleep(META_RETRY_DELAY * 2 ** attempt)

    def _recover_meta_publication(self, job, session, account, error):
        """Resolve a lost publish reply using reads of the saved upload only."""
        for attempt in range(META_RECOVERY_CHECKS):
            self._progress(job, job['progress'], 'Connection interrupted. Checking existing upload ('
                           + str(attempt + 1) + ' of ' + str(META_RECOVERY_CHECKS) + ')')
            if attempt:
                time.sleep(META_RETRY_DELAY * 2 ** (attempt - 1))
            try:
                if job['platform'] == 'facebook_page':
                    remote_id = job.get('remote_id') or getattr(error, 'remote_id', '')
                    result = facebook_status(session, account, remote_id, owner=True)
                    owner = result.get('from')
                    if (str(result.get('id')) != remote_id or not isinstance(owner, dict)
                            or str(owner.get('id')) != account['page_id']):
                        return None
                    state = facebook_publication_state(result)
                    if state == 'published':
                        return {'remote_id': remote_id, 'url': facebook_permalink(result.get('permalink_url'), remote_id),
                                'verified': True, 'warning': 'Connection recovered. Meta confirmed the existing Reel is published.'}
                    failed = state == 'failed'
                else:
                    container_id = job.get('container_id') or getattr(error, 'container_id', '')
                    state = instagram_container_status(session, account, container_id)
                    job['processing_status'] = state
                    if state == 'PUBLISHED':
                        return {'verified': True, 'warning': 'Connection recovered. Instagram confirmed publication; check your profile for the Reel link.'}
                    failed = state in ('ERROR', 'EXPIRED')
                if failed:
                    job['confirmed_unpublished'] = True
                    return None
            except ValueError as check_error:
                if getattr(check_error, 'provider_code', None) == 190:
                    raise
                if not _retryable_network(check_error):
                    return None
        return None

    def _publish_meta(self, job, session, account, path, draft):
        facebook = job['platform'] == 'facebook_page'
        adapter = facebook_publish if facebook else instagram_local_publish
        checkpoint = self._checkpoint if facebook else self._instagram_checkpoint
        for attempt in range(META_UPLOAD_ATTEMPTS):
            if attempt:
                self._progress(job, job['progress'], 'Connection interrupted. Retrying upload ('
                               + str(attempt + 1) + ' of ' + str(META_UPLOAD_ATTEMPTS) + ')')
                time.sleep(META_RETRY_DELAY * 2 ** (attempt - 1))
                with self.lock:
                    _, video = self._video(job['project'])
                    if not video['ready'] or video['signature'] != job['video_signature']:
                        raise ValueError('The finished video changed. Review it again before retrying the upload.')
                    job.update(progress=0, retry_count=attempt)
            prefix = 'Retry ' + str(attempt) + ' of ' + str(META_UPLOAD_ATTEMPTS - 1) + ': ' if attempt else ''
            try:
                return adapter(session, account, path, draft,
                    lambda percent, stage: self._progress(job, percent, prefix + stage),
                    checkpoint_callback=lambda **fields: checkpoint(job, **fields))
            except ValueError as error:
                if not _retryable_network(error):
                    raise
                if getattr(error, 'publish_attempted', job.get('publish_attempted', False)):
                    recovered = self._recover_meta_publication(job, session, account, error)
                    if recovered:
                        return recovered
                    raise
                if attempt + 1 == META_UPLOAD_ATTEMPTS:
                    raise

    def _run(self, job, path, draft):
        own_session = self.worker_sessions and isinstance(self.session, requests.sessions.Session)
        session = requests.Session() if own_session else self.session
        try:
            with self.lock: account = self._access_account(job['platform'])
            progress = lambda n, stage: self._progress(job, n, stage)
            local_meta = job['platform'] == 'facebook_page' or job['platform'] == 'instagram' and account.get('connection_type') == 'facebook'
            if local_meta:
                result = self._publish_meta(job, session, account, path, draft)
            else:
                adapter = youtube_upload if job['platform'] == 'youtube' else instagram_publish
                result = adapter(session, account, path, draft, progress)
            if not isinstance(result, dict) or not (result.get('remote_id') or local_meta and job['platform'] == 'instagram' and result.get('verified') is True):
                raise ValueError('The platform did not confirm the upload. Check your account before trying again.')
            with self.lock:
                job.update(status='complete', stage='Uploaded' if job['platform'] == 'youtube' else 'Published',
                           progress=100, url=result.get('url', ''), remote_id=result.get('remote_id', ''),
                           verified=result.get('verified', False),
                           warning=result.get('warning', ''), finished=time.time())
        except Exception as error:
            with self.lock:
                if isinstance(error, FacebookPublishError):
                    job.update(remote_id=error.remote_id, publish_attempted=error.publish_attempted)
                if isinstance(error, InstagramProcessingError):
                    job.update(container_id=error.container_id, processing_status=error.processing_status)
                if isinstance(error, InstagramPublishError):
                    job.update(container_id=error.container_id, processing_status=error.processing_status, publish_attempted=error.publish_attempted)
                if getattr(error, 'network_reason', None):
                    job['network_reason'] = error.network_reason
                page_token = job['platform'] == 'facebook_page' or job['platform'] == 'instagram' and self.vault['accounts'].get('instagram', {}).get('connection_type') == 'facebook'
                reconnect = page_token and getattr(error, 'provider_code', None) == 190
                if reconnect:
                    account = self.vault['accounts'].get('facebook_page', {})
                    account['needs_reconnect'] = True
                    self._vault_save()
                    job.update(reconnect_required=True, error_code=190,
                               error_subcode=getattr(error, 'provider_subcode', None))
                job.update(status='failed', stage='Reconnect Facebook Page' if reconnect else 'Upload failed',
                           error=self._safe_error(ValueError(str(error) + ' ' + error.provider_message)
                               if isinstance(error, (FacebookPublishError, InstagramPublishError)) and error.provider_message else error),
                           finished=time.time())
        finally:
            with self.lock:
                self._persist_job()
                self._history_status(job)

            if own_session:
                session.close()

    def verify_instagram(self, identifier, job_id):
        """Read a saved local-upload container; never publish or upload again."""
        with self.lock:
            self._idle()
            record = self._record(identifier)
            entry = next((row for row in record['history'] if row['id'] == job_id and row.get('platform') == 'instagram'), None)
            if not entry or not entry.get('container_id') or entry.get('instagram_connection_type') != 'facebook':
                raise ValueError('Choose an existing local Instagram upload from this project.')
            account = self._access_account('instagram')
            if account.get('connection_type') != 'facebook' or account.get('user_id') != entry.get('destination_id'):
                raise ValueError('Reconnect the Instagram account used for this upload before checking it.')
            status = self._read_meta_status(lambda: instagram_container_status(self.session, account, entry['container_id']))
            entry['processing_status'] = status
            entry['checked_at'] = time.time()
            if status == 'PUBLISHED':
                entry.update(status='complete', error='', finished=time.time(),
                    warning='Instagram confirmed publication. Check your profile for the Reel link.')
                message = 'Instagram confirmed that this Reel is published. No new publish request was sent.'
            elif status in ('ERROR', 'EXPIRED'):
                entry['confirmed_unpublished'] = True
                message = 'Instagram reports this upload as ' + status.lower() + '. It is safe to review the video and start a new upload.'
            else:
                message = 'Instagram has processed this upload; publication is still unconfirmed. Check again before retrying.' if status == 'FINISHED' else 'Instagram is still uploading or processing this video. Check again shortly.'
            self._save_record(identifier, record)
            job = self._find_job(job_id)
            if job:
                job.update(processing_status=status)
                if status == 'PUBLISHED':
                    job.update(status='complete', stage='Published', progress=100, error='', finished=entry['finished'], warning=entry['warning'])
                elif status in ('ERROR', 'EXPIRED'):
                    job['confirmed_unpublished'] = True
                self._persist_job()
            return {'ok':True, 'message':message}

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
            job = self._find_job(job_id)
            if job:
                job.update(recovered, stage='Uploaded', progress=100)
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
            result = self._read_meta_status(lambda: facebook_status(self.session, account, entry['remote_id'], owner=True))
            owner = result.get('from')
            if str(result.get('id')) != entry['remote_id'] or not isinstance(owner, dict) or str(owner.get('id')) != account['page_id']:
                raise ValueError('Facebook did not confirm that this video belongs to the connected Page.')
            state = facebook_publication_state(result)
            if state == 'published':
                recovered = {'status':'complete', 'finished':time.time(), 'url':facebook_permalink(result.get('permalink_url'), entry['remote_id']),
                    'error':'', 'warning':'Confirmed by checking the existing Facebook Reel.', 'verified':True}
                entry.update(recovered)
                self._save_record(identifier, record)
                job = self._find_job(job_id)
                if job:
                    job.update(recovered, stage='Published', progress=100)
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
                    'url': url, 'title': self._platform_draft(record.get('draft') or self._default_draft(identifier), platform)['title'],
                    'created': time.time(), 'finished': time.time(), 'video_signature': video['signature'], 'method': 'manual'})
            self._save_record(identifier, record)
            return {'ok': True}
