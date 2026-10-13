"""Facebook Page Reel transport: local MP4 upload followed by confirmed publishing.

Protocol: https://github.com/fbsamples/reels_publishing_apis/tree/main/fb_reels_publishing_api_sample
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
from types import SimpleNamespace

import requests
import re
import time
from urllib.parse import urlsplit

from publishing_clients import _caption, _progress, _token, request_json, _response_json, ProviderNetworkError

FACEBOOK_API_VERSION = 'v26.0'
FACEBOOK_POLL_TIMEOUT = 600
FACEBOOK_POLL_INTERVAL = 5
# urllib3 uses the connect timeout on the socket while sending the request body.
# A video needs a larger write budget than the default 10-second API timeout.
FACEBOOK_UPLOAD_TIMEOUT = (120, 600)


def facebook_id(value, label='Page ID'):
    value = str(value or '')
    if not re.fullmatch(r'\d{1,80}', value):
        raise ValueError('Enter a valid numeric Facebook ' + label + '.')
    return value


def facebook_api(account):
    version = str(account.get('api_version') or FACEBOOK_API_VERSION)
    if not re.fullmatch(r'v\d+\.\d+', version):
        raise ValueError('Select a valid Facebook API version.')
    return 'https://graph.facebook.com/' + version


def facebook_permalink(value, video_id):
    if isinstance(value, str):
        try:
            parsed = urlsplit(value)
            if (parsed.scheme == 'https' and parsed.hostname in ('facebook.com', 'www.facebook.com', 'm.facebook.com')
                    and parsed.port in (None, 443) and not parsed.username and not parsed.password and not parsed.fragment):
                return value
        except ValueError:
            pass
    return 'https://www.facebook.com/reel/' + facebook_id(video_id, 'video ID')


def _upload_url(value, video_id):
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'https' and parsed.hostname == 'rupload.facebook.com'
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment
                 and re.fullmatch(r'/video-upload/v\d+\.\d+/' + re.escape(video_id), parsed.path))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError('Facebook returned an untrusted upload location.')
    return value


class FacebookPublishError(ValueError):
    def __init__(self, message, remote_id, publish_attempted, provider_error=None):
        self.remote_id = remote_id
        self.publish_attempted = publish_attempted
        self.provider_code = getattr(provider_error, 'provider_code', None)
        self.provider_subcode = getattr(provider_error, 'provider_subcode', None)
        self.provider_message = getattr(provider_error, 'provider_message', '')
        self.network_kind = getattr(provider_error, 'network_kind', None)
        self.network_reason = getattr(provider_error, 'network_reason', None)
        super().__init__(message)


class _VideoReader:
    """Stream the file without buffering the complete MP4 in memory."""
    def __init__(self, file, size, callback, destination='Facebook Page'):
        self.file, self.size, self.callback = file, size, callback
        self.destination = destination

    def __len__(self):
        return self.size

    def tell(self):
        return self.file.tell()

    def seek(self, *args):
        return self.file.seek(*args)

    def read(self, amount=-1):
        remaining = self.size - self.tell()
        if not remaining:
            return b''
        amount = min(remaining, 1024 * 1024, amount if amount >= 0 else 65536)
        data = self.file.read(amount)
        if not data and amount:
            raise ValueError('The exported video changed during upload.')
        _progress(self.callback, 5 + 60 * self.tell() / self.size, 'Uploading video to ' + self.destination)
        return data

    def __iter__(self):
        while True:
            data = self.read(65536)
            if not data:
                return
            yield data



def _curl_quote(value):
    value = str(value)
    if any(character in value for character in ('\r', '\n', '\0')):
        raise ValueError('The Facebook upload configuration contains an invalid value.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _curl_video_upload(executable, upload_url, token, video, total, destination='Facebook'):
    # Keep the token out of process arguments and files. curl reads this config
    # from stdin, streams the MP4, and receives early HTTP errors while sending.
    config = '\n'.join([
        'request = "POST"',
        'url = ' + _curl_quote(upload_url),
        'upload-file = ' + _curl_quote(video.resolve().as_posix()),
        'header = ' + _curl_quote('Authorization: OAuth ' + token),
        'header = "offset: 0"',
        'header = ' + _curl_quote('file_size: ' + str(total)),
        'header = ' + _curl_quote('Content-Length: ' + str(total)),
        'header = "Content-Type: application/octet-stream"',
        'write-out = "\\n%{http_code}"',
    ]) + '\n'
    command = [executable, '--disable', '--silent', '--show-error', '--globoff', '--proto', '=https',
        '--connect-timeout', str(FACEBOOK_UPLOAD_TIMEOUT[0]), '--max-time', str(FACEBOOK_UPLOAD_TIMEOUT[1]),
        '--speed-time', str(FACEBOOK_UPLOAD_TIMEOUT[0]), '--speed-limit', '1', '--config', '-']
    try:
        result = subprocess.run(command, input=config.encode('utf-8'), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=FACEBOOK_UPLOAD_TIMEOUT[1] + 15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except subprocess.TimeoutExpired:
        raise ProviderNetworkError('The ' + destination + ' video transfer timed out.', 'timeout') from None
    except OSError:
        raise ProviderNetworkError('The ' + destination + ' video transfer could not start.', 'request') from None
    text = result.stdout.decode('utf-8', errors='replace').rstrip('\r\n')
    body, separator, status = text.rpartition('\n')
    if separator and re.fullmatch(r'[1-5]\d{2}', status):
        # An HTTP rejection may arrive before the complete body is sent.
        if result.returncode == 0 or int(status) >= 400:
            return _response_json(SimpleNamespace(status_code=int(status), json=lambda: json.loads(body)))
    if result.returncode:
        reason = {28:'timeout', 35:'tls', 51:'tls_certificate', 60:'tls_certificate',
                  55:'curl_send', 56:'curl_receive'}.get(result.returncode, 'connection')
        kind = 'timeout' if reason == 'timeout' else 'connection'
        raise ProviderNetworkError('The ' + destination + ' video transfer failed.', kind, reason)
    raise ValueError(destination + ' returned an invalid upload response.')


def _video_upload(session, upload_url, token, video, total, progress_callback, *, destination='Facebook Page'):
    executable = shutil.which('curl.exe') if os.name == 'nt' and isinstance(session, requests.Session) else None
    if executable:
        _progress(progress_callback, 5, 'Uploading video to ' + destination + ' (' + str(round(total / (1024 * 1024), 1)) + ' MB)')
        result = _curl_video_upload(executable, upload_url, token, video, total, destination)
        if result.get('success') is True:
            _progress(progress_callback, 65, destination + ' received the video')
        return result
    with video.open('rb') as file:
        return request_json(session, 'POST', upload_url, headers={
            'Authorization':'OAuth ' + token, 'offset':'0', 'file_size':str(total),
            'Content-Length':str(total), 'Content-Type':'application/octet-stream',
        }, data=_VideoReader(file, total, progress_callback, destination), timeout=FACEBOOK_UPLOAD_TIMEOUT)


def facebook_status(session, account, video_id, *, owner=False):
    fields = 'id,status,from,permalink_url' if owner else 'status'
    return request_json(session, 'GET', facebook_api(account) + '/' + facebook_id(video_id, 'video ID'),
        headers={'Authorization':'Bearer ' + _token(account)}, params={'fields':fields})



def facebook_publication_state(result):
    """A ready video is not published until its publishing phase is complete."""
    status = result.get('status')
    if not isinstance(status, dict):
        raise ValueError('Facebook returned an invalid video status. Check the existing Reel before retrying.')
    phases = []
    for key in ('uploading_phase', 'processing_phase', 'publishing_phase'):
        phase = status.get(key, {})
        if not isinstance(phase, dict):
            raise ValueError('Facebook returned an invalid video status. Check the existing Reel before retrying.')
        phases.append(phase)
    if status.get('video_status') == 'error' or any(phase.get('status') == 'error' for phase in phases):
        return 'failed'
    return 'published' if phases[-1].get('status') == 'complete' else 'processing'


def facebook_publish(session, account, path, draft, progress_callback, checkpoint_callback=None):
    """One upload session and one finish request; confirm the publishing phase."""
    video = Path(path)
    if not video.is_file() or not video.stat().st_size:
        raise ValueError('The exported video is no longer available or is empty.')
    total = video.stat().st_size
    page_id = facebook_id(account.get('page_id'))
    if draft.get('facebook_page_id') != page_id:
        raise ValueError('The Facebook Page changed. Reload and review the destination again.')
    token = _token(account)
    api = facebook_api(account)
    headers = {'Authorization':'Bearer ' + token}
    endpoint = api + '/' + page_id + '/video_reels'
    _progress(progress_callback, 0, 'Starting Facebook Page upload')
    created = request_json(session, 'POST', endpoint, headers=headers, data={'upload_phase':'start'})
    video_id = facebook_id(created.get('video_id'), 'video ID')
    publish_attempted = False
    try:
        if checkpoint_callback:
            checkpoint_callback(remote_id=video_id, publish_attempted=False)
        upload_url = _upload_url(created.get('upload_url'), video_id)
        uploaded = _video_upload(session, upload_url, token, video, total, progress_callback)
        if uploaded.get('success') is not True:
            raise ValueError('Facebook did not confirm receiving the video. No publish was requested.')
        _progress(progress_callback, 70, 'Publishing Reel to Facebook Page')
        # Persist before the only publish request, so a restart cannot cause a duplicate.
        publish_attempted = True
        if checkpoint_callback:
            checkpoint_callback(remote_id=video_id, publish_attempted=True)
        published = request_json(session, 'POST', endpoint, headers=headers, data={
            'upload_phase':'finish', 'video_id':video_id, 'video_state':'PUBLISHED',
            'title':str(draft.get('title') or ''), 'description':_caption(draft),
        })
        if published.get('success') is not True:
            raise ValueError('Facebook publishing could not be confirmed. Check the existing Reel before retrying.')
        deadline = time.monotonic() + FACEBOOK_POLL_TIMEOUT
        while time.monotonic() < deadline:
            result = facebook_status(session, account, video_id)
            state = facebook_publication_state(result)
            if state == 'failed':
                raise ValueError('Facebook could not process or publish this Reel. Check the existing upload before retrying.')
            if state == 'published':
                break
            _progress(progress_callback, 85, 'Facebook is processing the Reel')
            time.sleep(min(FACEBOOK_POLL_INTERVAL, max(0, deadline - time.monotonic())))
        else:
            raise ValueError('Facebook publishing is still unconfirmed. Check the existing Reel before retrying.')
    except ValueError as error:
        message = str(error)
        kind = getattr(error, 'network_kind', None)
        if kind:
            reason = getattr(error, 'network_reason', None)
            problem = 'timed out' if kind == 'timeout' else 'was reset' if reason == 'connection_reset' else 'was interrupted'
            if publish_attempted:
                message = 'Facebook publishing could not be confirmed because the connection ' + problem + '. Use Check existing upload before trying again.'
            else:
                message = 'The Facebook video transfer ' + problem + '. No publish was requested. Check your connection and retry the upload.'
        raise FacebookPublishError(message, video_id, publish_attempted, provider_error=error) from None
    link = facebook_permalink('', video_id)
    try:
        result = request_json(session, 'GET', api + '/' + video_id, headers=headers, params={'fields':'permalink_url'})
        link = facebook_permalink(result.get('permalink_url'), video_id)
    except ValueError:
        pass
    _progress(progress_callback, 100, 'Facebook Page Reel published')
    return {'remote_id':video_id, 'url':link}
