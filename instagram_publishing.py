"""Local Instagram Reel uploads through the connected Facebook Page.

Protocol: https://github.com/fbsamples/reels_publishing_apis/tree/main/insta_reels_publishing_api_sample
"""
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from publishing_clients import (_caption, _progress, _token, _boolean, _instagram_id,
    _instagram_permalink, request_json, INSTAGRAM_API_VERSION, INSTAGRAM_POLL_TIMEOUT, INSTAGRAM_POLL_INTERVAL)
from facebook_publishing import _video_upload


def instagram_api(account):
    if account.get('connection_type') != 'facebook':
        raise ValueError('Connect Instagram through your Facebook Page for local video uploads.')
    version = str(account.get('api_version') or INSTAGRAM_API_VERSION)
    if not re.fullmatch(r'v\d+\.\d+', version):
        raise ValueError('Select a valid Instagram API version.')
    return 'https://graph.facebook.com/' + version


def _upload_uri(value, container_id):
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'https' and parsed.hostname == 'rupload.facebook.com'
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment
                 and re.fullmatch(r'/ig-api-upload/(?:v\d+\.\d+/)?' + re.escape(container_id), parsed.path))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError('Instagram returned an untrusted upload location.')
    return value


def instagram_container_status(session, account, container_id):
    identifier = _instagram_id(container_id, 'media container ID')
    result = request_json(session, 'GET', instagram_api(account) + '/' + identifier,
        headers={'Authorization':'Bearer ' + _token(account)}, params={'fields':'id,status_code'})
    if _instagram_id(result.get('id'), 'media container ID') != identifier:
        raise ValueError('Instagram returned a different media container. Do not retry publishing.')
    status = result.get('status_code')
    if status not in ('IN_PROGRESS', 'FINISHED', 'PUBLISHED', 'ERROR', 'EXPIRED'):
        raise ValueError('Instagram returned an unexpected processing status.')
    return status


class InstagramPublishError(ValueError):
    def __init__(self, message, container_id, publish_attempted, processing_status='', provider_error=None):
        self.container_id = container_id
        self.publish_attempted = publish_attempted
        self.processing_status = processing_status
        self.provider_code = getattr(provider_error, 'provider_code', None)
        self.provider_subcode = getattr(provider_error, 'provider_subcode', None)
        self.provider_message = getattr(provider_error, 'provider_message', '')
        self.network_kind = getattr(provider_error, 'network_kind', None)
        self.network_reason = getattr(provider_error, 'network_reason', None)
        super().__init__(message)


def instagram_local_publish(session, account, path, draft, progress_callback, checkpoint_callback=None):
    video = Path(path)
    if not video.is_file() or not video.stat().st_size:
        raise ValueError('The exported video is no longer available or is empty.')
    total = video.stat().st_size
    api = instagram_api(account)
    token = _token(account)
    identifier = _instagram_id(account.get('user_id'), 'account ID')
    headers = {'Authorization':'Bearer ' + token}
    _progress(progress_callback, 0, 'Starting Instagram video upload')
    created = request_json(session, 'POST', api + '/' + identifier + '/media', headers=headers,
        data={'media_type':'REELS', 'upload_type':'resumable', 'caption':_caption(draft),
              'share_to_feed':str(_boolean(draft.get('instagram_share_to_feed', True), 'Instagram feed sharing')).lower()})
    container_id = _instagram_id(created.get('id'), 'media container ID')
    publish_attempted, status, phase = False, '', 'transfer'
    try:
        if checkpoint_callback:
            checkpoint_callback(container_id=container_id, publish_attempted=False)
        uri = _upload_uri(created.get('uri'), container_id)
        uploaded = _video_upload(session, uri, token, video, total, progress_callback, destination='Instagram')
        if uploaded.get('success') is not True:
            raise ValueError('Instagram did not confirm receiving the video. No publish was requested.')
        phase = 'processing'
        deadline = time.monotonic() + INSTAGRAM_POLL_TIMEOUT
        while time.monotonic() < deadline:
            status = instagram_container_status(session, account, container_id)
            if status == 'FINISHED':
                break
            if status in ('ERROR', 'EXPIRED'):
                raise ValueError('Instagram could not process this video. Check the existing upload before retrying.')
            if status == 'PUBLISHED':
                raise ValueError('Instagram reports this container is already published. Check the existing upload before retrying.')
            _progress(progress_callback, 75, 'Instagram is processing the video')
            time.sleep(min(INSTAGRAM_POLL_INTERVAL, max(0, deadline - time.monotonic())))
        else:
            raise ValueError('Instagram processing is still unconfirmed. No publish was requested. Check the existing upload.')
        phase = 'publish'
        publish_attempted = True
        if checkpoint_callback:
            checkpoint_callback(container_id=container_id, publish_attempted=True)
        _progress(progress_callback, 85, 'Publishing Instagram Reel')
        published = request_json(session, 'POST', api + '/' + identifier + '/media_publish',
            headers=headers, data={'creation_id':container_id})
        media_id = _instagram_id(published.get('id'), 'published media ID')
    except ValueError as error:
        message = str(error)
        if publish_attempted:
            message = 'Instagram publishing could not be confirmed. Use Check existing upload before trying again.'
        elif getattr(error, 'network_kind', None):
            problem = 'timed out' if error.network_kind == 'timeout' else 'was interrupted'
            message = ('The Instagram video transfer ' if phase == 'transfer' else 'The Instagram processing check ') + problem + '. No publish was requested. Check the existing upload.'
        raise InstagramPublishError(message, container_id, publish_attempted, status, error) from None
    result = {'remote_id':media_id, 'url':''}
    try:
        media = request_json(session, 'GET', api + '/' + media_id, headers=headers, params={'fields':'id,permalink'})
        if _instagram_id(media.get('id'), 'published media ID') == media_id:
            result['url'] = _instagram_permalink(media.get('permalink'))
    except ValueError:
        pass
    if not result['url']:
        result['warning'] = 'Reel published. Its link could not be retrieved; check your Instagram profile.'
    _progress(progress_callback, 100, 'Instagram Reel published')
    return result
