"""HTTP transports for reviewed YouTube uploads and Instagram Reel publishing.

YouTube protocol:
https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
Instagram protocol:
https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api

Instagram Login uses a public video URL here. Meta's verified local resumable
sample uses Facebook Login; it does not establish support for Instagram Login.
"""

from __future__ import annotations

import ipaddress
import mimetypes
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
import ssl

REQUEST_TIMEOUT = (10, 90)
YOUTUBE_CHUNK_SIZE = 1024 * 1024
YOUTUBE_MAX_RECOVERIES = 5
INSTAGRAM_API_VERSION = "v26.0"
INSTAGRAM_POLL_TIMEOUT = 600
INSTAGRAM_POLL_INTERVAL = 5

_GOOGLE_REASONS = {
    "authError", "forbidden", "insufficientPermissions", "quotaExceeded",
    "dailyLimitExceeded", "rateLimitExceeded", "uploadLimitExceeded",
    "invalidTitle", "invalidDescription", "invalidPrivacySetting",
    "invalidCategoryId", "videoNotFound", "youtubeSignupRequired",
    "accountDelegationForbidden", "accessNotConfigured",
}


def _progress(callback, percent, stage):
    if callback:
        callback(max(0, min(100, int(percent))), stage)


class ProviderNetworkError(ValueError):
    """Safe network failure details without token-bearing exception text."""
    def __init__(self, message, kind, reason=None):
        self.network_kind = kind
        self.network_reason = reason or kind
        super().__init__(message)


def _network_reason(error):
    # Socket failures are often nested in ConnectionError/ProtocolError.
    # Keep only fixed diagnostic labels, never exception messages or URLs.
    pending, seen, reason = [error], set(), 'connection'
    tls_reasons = {
        'UNEXPECTED_EOF_WHILE_READING': 'tls_eof',
        'DECRYPTION_FAILED_OR_BAD_RECORD_MAC': 'tls_record',
        'SSLV3_ALERT_BAD_RECORD_MAC': 'tls_record',
        'CERTIFICATE_VERIFY_FAILED': 'tls_certificate',
    }
    while pending:
        item = pending.pop()
        if not isinstance(item, BaseException) or id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, (requests.Timeout, TimeoutError)):
            return 'timeout'
        code = getattr(item, 'winerror', None) or getattr(item, 'errno', None)
        if code in (104, 10054):
            reason = 'connection_reset'
        elif code in (103, 10053) and reason == 'connection':
            reason = 'connection_aborted'
        elif code in (32, 10058) and reason == 'connection':
            reason = 'broken_pipe'
        if isinstance(item, (requests.exceptions.SSLError, ssl.SSLError)):
            reason = tls_reasons.get(getattr(item, 'reason', None), 'tls')
        pending.extend(arg for arg in item.args if isinstance(arg, BaseException))
        pending.extend((item.__cause__, item.__context__, getattr(item, 'reason', None)))
    return reason


def _request(session, method, url, **kwargs):
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    # Never forward an authorization header to a redirected request.
    kwargs["allow_redirects"] = False
    try:
        return session.request(method, url, **kwargs)
    except requests.Timeout:
        raise ProviderNetworkError("The provider network request timed out.", 'timeout') from None
    except requests.ConnectionError as error:
        reason = _network_reason(error)
        if reason == 'timeout':
            raise ProviderNetworkError("The provider network request timed out.", 'timeout') from None
        raise ProviderNetworkError("The connection to the provider was interrupted.", 'connection', reason) from None
    except requests.RequestException:
        # requests exceptions often contain token-bearing URLs.
        raise ProviderNetworkError("The provider network request failed.", 'request') from None


class ProviderRequestError(ValueError):
    """Credential-safe provider status and numeric codes for recovery."""
    def __init__(self, message, status_code, code=None, subcode=None, provider_message=''):
        self.status_code = status_code
        self.provider_code = code
        self.provider_subcode = subcode
        self.provider_message = provider_message
        super().__init__(message)


def _provider_error(response, payload=None):
    """Return useful status/codes without echoing provider text or credentials."""
    suffix = []
    code = subcode = None
    provider_message = ''
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            if isinstance(error.get('message'), str):
                provider_message = error['message'][:2000]
            code = error.get("code")
            if isinstance(code, int) and not isinstance(code, bool):
                suffix.append("code " + str(code))
            else:
                code = None
            subcode = error.get("error_subcode")
            if isinstance(subcode, int) and not isinstance(subcode, bool):
                suffix.append("subcode " + str(subcode))
            else:
                subcode = None
            reasons = error.get("errors", [])
            if isinstance(reasons, list):
                for item in reasons:
                    reason = item.get("reason") if isinstance(item, dict) else None
                    if isinstance(reason, str) and reason in _GOOGLE_REASONS:
                        suffix.append(reason)
                        break
    detail = " (" + ", ".join(suffix) + ")" if suffix else ""
    if code == 190:
        reason = "has expired" if subcode == 463 else "is invalid or has been revoked"
        message = "This account's access token " + reason + detail + ". Reconnect the account with a fresh access token."
    else:
        message = "Provider request failed with HTTP " + str(response.status_code) + detail + "."
    return ProviderRequestError(message, response.status_code, code, subcode, provider_message)


def _response_json(response):
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = None
    if not 200 <= response.status_code < 300:
        raise _provider_error(response, payload)
    if isinstance(payload, dict) and payload.get("error"):
        raise _provider_error(response, payload)
    if not isinstance(payload, dict):
        raise ValueError("The provider returned an invalid response.")
    return payload


def request_json(session, method, url, **kwargs):
    """Perform one bounded request, raising a credential-safe ValueError."""
    return _response_json(_request(session, method, url, **kwargs))


def _token(account):
    token = account.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("This account needs to be connected again.")
    return token


def _boolean(value, label):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise ValueError(label + " must be true or false.")


def _caption(draft):
    description = str(draft.get("description") or "").strip()
    tags = draft.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    formatted = []
    for tag in tags:
        tag = str(tag).strip().strip(",")
        if tag:
            formatted.append("#" + tag.lstrip("#"))
    return "\n\n".join(part for part in (description, " ".join(formatted)) if part)


def _google_upload_url(value):
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        valid = (
            parsed.scheme == "https"
            and (host == "googleapis.com" or host.endswith(".googleapis.com"))
            and parsed.port in (None, 443)
            and not parsed.username and not parsed.password
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("YouTube returned an untrusted upload location.")
    return value


def _youtube_offset(response, total, previous, maximum):
    value = response.headers.get("Range", "")
    if not value:
        offset = 0
    else:
        match = re.fullmatch(r"(?:bytes=)?0-(\d+)", value.strip())
        if not match:
            raise ValueError("YouTube returned an invalid upload acknowledgement.")
        offset = int(match.group(1)) + 1
    if offset < previous or offset > maximum or offset > total:
        raise ValueError("YouTube returned an inconsistent upload acknowledgement.")
    return offset


def _youtube_result(response):
    payload = _response_json(response)
    video_id = payload.get("id")
    if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", video_id):
        raise ValueError(
            "YouTube accepted the upload but did not return its video ID. "
            "Check your channel before trying another upload."
        )
    return {"remote_id": video_id, "url": "https://www.youtube.com/watch?v=" + video_id}


def _youtube_status(session, upload_url, headers, total):
    """Retry status queries without resending bytes or creating another session."""
    detail = "The network request failed."
    for attempt in range(YOUTUBE_MAX_RECOVERIES):
        delay = min(2 ** attempt, 8)
        try:
            response = _request(
                session, "PUT", upload_url, headers={
                    **headers, "Content-Length": "0", "Content-Range": "bytes */" + str(total),
                }, data=b"",
            )
        except ValueError as error:
            detail = str(error)
        else:
            if response.status_code not in (429, 500, 502, 503, 504):
                return response
            detail = "YouTube returned HTTP " + str(response.status_code) + "."
            retry_after = response.headers.get("Retry-After", "")
            if str(retry_after).isdigit():
                delay = min(30, max(delay, int(retry_after)))
        if attempt + 1 < YOUTUBE_MAX_RECOVERIES:
            time.sleep(delay)
    raise ValueError(
        "YouTube upload status could not be confirmed after " + str(YOUTUBE_MAX_RECOVERIES)
        + " checks. " + detail + " Check your channel before trying another upload."
    )


def youtube_upload(session, account, path, draft, progress_callback):
    """Upload in one resumable session; recovery never starts a second upload."""
    token = _token(account)
    video_path = Path(path)
    if not video_path.is_file():
        raise ValueError("The exported video is no longer available.")
    total = video_path.stat().st_size
    if not total:
        raise ValueError("The exported video is empty.")
    privacy = draft.get("youtube_privacy", "private")
    if privacy not in ("private", "unlisted", "public"):
        raise ValueError("Select a valid YouTube visibility.")
    title = str(draft.get("title") or "").strip()
    if not title:
        raise ValueError("Enter a title before uploading to YouTube.")
    mime = mimetypes.guess_type(str(video_path))[0] or "application/octet-stream"
    if not mime.startswith("video/"):
        mime = "application/octet-stream"
    auth = {"Authorization": "Bearer " + token}
    metadata = {
        "snippet": {"title": title, "description": _caption(draft), "categoryId": "22"},
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": _boolean(draft.get("made_for_kids", False), "Made for kids"),
        },
    }
    _progress(progress_callback, 0, "Starting YouTube upload")
    initial = _request(
        session, "POST", "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            **auth, "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(total), "X-Upload-Content-Type": mime,
        }, json=metadata,
    )
    if not 200 <= initial.status_code < 300:
        _response_json(initial)
    upload_url = _google_upload_url(initial.headers.get("Location"))
    _progress(progress_callback, 5, "Uploading video to YouTube")

    offset = 0
    recoveries = 0
    no_progress = 0
    completion_checks = 0
    with video_path.open("rb") as source:
        while True:
            if offset == total:
                # All bytes were acknowledged, but completion must return an ID.
                completion_checks += 1
                if completion_checks > 3:
                    raise ValueError(
                        "YouTube has received the video, but completion could not be confirmed. "
                        "Check your channel before trying another upload."
                    )
                time.sleep(completion_checks)
                response = _youtube_status(session, upload_url, auth, total)
                maximum = total
            else:
                source.seek(offset)
                chunk = source.read(min(YOUTUBE_CHUNK_SIZE, total - offset))
                if not chunk:
                    raise ValueError("The exported video changed during upload.")
                end = offset + len(chunk) - 1
                maximum = end + 1
                response = None
                try:
                    response = _request(
                        session, "PUT", upload_url,
                        headers={
                            **auth, "Content-Type": mime, "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {offset}-{end}/{total}",
                        }, data=chunk,
                    )
                except ValueError:
                    pass
                if response is None or response.status_code in (500, 502, 503, 504):
                    recoveries += 1
                    if recoveries > YOUTUBE_MAX_RECOVERIES:
                        raise ValueError(
                            "YouTube upload status could not be confirmed. "
                            "Check your channel before trying another upload."
                        )
                    time.sleep(min(2 ** (recoveries - 1), 8))
                    _progress(progress_callback, 5 + 90 * offset / total,
                              "Connection interrupted; checking YouTube upload status")
                    response = _youtube_status(session, upload_url, auth, total)

            if 200 <= response.status_code < 300:
                result = _youtube_result(response)
                _progress(progress_callback, 100, "YouTube upload completed")
                return result
            if response.status_code != 308:
                _response_json(response)
            next_offset = _youtube_offset(response, total, offset, maximum)
            no_progress = no_progress + 1 if next_offset == offset else 0
            if no_progress > 3:
                raise ValueError(
                    "YouTube is not acknowledging upload progress. "
                    "Check your channel before trying another upload."
                )
            if next_offset > offset:
                recoveries = 0
            offset = next_offset
            _progress(progress_callback, 5 + 90 * offset / total, "Uploading video to YouTube")


def public_video_url(value):
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        valid = (
            parsed.scheme == "https" and bool(host)
            and parsed.port in (None, 443)
            and not parsed.username and not parsed.password and not parsed.fragment
            and host != "localhost" and "." in host
            and not host.endswith((".localhost", ".local", ".test", ".invalid", ".example"))
        )
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None:
            valid = valid and address.is_global
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError(
            "Instagram needs a public HTTPS URL for this exported video. "
            "A file on your computer or a localhost URL cannot be fetched by Instagram."
        )
    return value


def _instagram_id(value, label):
    value = str(value or "")
    if not re.fullmatch(r"\d{1,80}", value):
        raise ValueError("Instagram returned an invalid " + label + ".")
    return value


def _instagram_permalink(value):
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme == "https" and host in ("instagram.com", "www.instagram.com")
            and parsed.port in (None, 443)
            and not parsed.username and not parsed.password and not parsed.fragment
        ):
            return value
    except ValueError:
        pass
    return ""


class InstagramProcessingError(ValueError):
    """Keep the failed container ID available for read-only troubleshooting."""
    def __init__(self, container_id, status):
        self.container_id = container_id
        self.processing_status = status
        super().__init__("Instagram could not process this video. Check its format and public video URL.")


def instagram_publish(session, account, path, draft, progress_callback):
    """Publish an Instagram Login Reel from a reviewed, public video URL."""
    token = _token(account)
    video_url = public_video_url(draft.get("instagram_video_url") or "")
    user_id = _instagram_id(account.get("user_id"), "account ID")
    version = str(account.get("api_version") or INSTAGRAM_API_VERSION)
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise ValueError("Select a valid Instagram API version.")
    api = "https://graph.instagram.com/" + version
    headers = {"Authorization": "Bearer " + token}
    _progress(progress_callback, 0, "Sending video to Instagram")
    created = request_json(
        session, "POST", api + "/" + user_id + "/media", headers=headers,
        data={
            "media_type": "REELS", "video_url": video_url, "caption": _caption(draft),
            "share_to_feed": str(_boolean(
                draft.get("instagram_share_to_feed", True), "Instagram feed sharing"
            )).lower(),
        },
    )
    container_id = _instagram_id(created.get("id"), "media container ID")
    _progress(progress_callback, 15, "Instagram is processing the video")
    deadline = time.monotonic() + INSTAGRAM_POLL_TIMEOUT
    while time.monotonic() < deadline:
        status = request_json(
            session, "GET", api + "/" + container_id,
            headers=headers, params={"fields": "status_code"},
        ).get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise InstagramProcessingError(container_id, status)
        if status == "PUBLISHED":
            raise ValueError(
                "Instagram reports that this container is already published. "
                "Check your profile before trying another publish."
            )
        if status != "IN_PROGRESS":
            raise ValueError("Instagram returned an unexpected processing status.")
        elapsed = INSTAGRAM_POLL_TIMEOUT - max(0, deadline - time.monotonic())
        _progress(progress_callback, 15 + min(65, elapsed / 8), "Instagram is processing the video")
        time.sleep(min(INSTAGRAM_POLL_INTERVAL, max(0, deadline - time.monotonic())))
    else:
        raise ValueError("Instagram processing took too long. The Reel has not been submitted for publishing.")

    _progress(progress_callback, 85, "Publishing Instagram Reel")
    try:
        published = request_json(
            session, "POST", api + "/" + user_id + "/media_publish",
            headers=headers, data={"creation_id": container_id},
        )
        media_id = _instagram_id(published.get("id"), "published media ID")
    except ValueError:
        # This request may have completed remotely even when the response is lost.
        raise ValueError(
            "Instagram publishing could not be confirmed. "
            "Check your profile before trying another publish."
        ) from None

    result = {"remote_id": media_id, "url": ""}
    try:
        media = request_json(
            session, "GET", api + "/" + media_id,
            headers=headers, params={"fields": "permalink"},
        )
        result["url"] = _instagram_permalink(media.get("permalink"))
    except ValueError:
        pass
    if not result["url"]:
        # The publish already succeeded; missing link lookup must not cause a retry.
        result["warning"] = "Reel published. Its link could not be retrieved; check your Instagram profile."
    _progress(progress_callback, 100, "Instagram Reel published")
    return result
