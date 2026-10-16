"""Facebook Page publishing checks: simulated Meta replies and a local HTTP receiver."""
import json
import ssl
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
import facebook_publishing as fb
import publishing as pub
import video_studio as studio
from pipeline_common import write_json, read_cache
from test_publishing import Response, Session
from publishing_clients import ProviderNetworkError, request_json, REQUEST_TIMEOUT
from urllib3.exceptions import ProtocolError

PAGE = '555'
VIDEO = '777'
TOKEN = 'PRIVATE_PAGE_TOKEN'
UPLOAD = 'https://rupload.facebook.com/video-upload/v26.0/' + VIDEO
ACCOUNT = {'access_token': TOKEN, 'page_id': PAGE, 'name': 'Fixture Page'}
START = {'video_id': VIDEO, 'upload_url': UPLOAD}
COMPLETE = {'status': {'video_status': 'ready', 'publishing_phase': {'status': 'complete'}}}
PENDING = {'status': {'video_status': 'ready', 'publishing_phase': {'status': 'in_progress'}}}
FAILED = {'status': {'video_status': 'error', 'processing_phase': {'status': 'error'}}}


class StreamingSession(Session):
    def request(self, method, url, **kwargs):
        if url == UPLOAD:
            reader = kwargs['data']
            body = b''.join(reader)
            kwargs = {**kwargs, 'data': body}
        return super().request(method, url, **kwargs)


def replies(*statuses, permalink=True):
    return StreamingSession(Response(payload=START), Response(payload={'success': True}),
        Response(payload={'success': True}), *[Response(payload=status) for status in statuses],
        Response(payload={'permalink_url': 'https://www.facebook.com/reel/' + VIDEO}) if permalink else requests.Timeout('lost'))


class TransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.video = Path(temporary.name) / 'final.mp4'
        self.video.write_bytes(b'abcdefghij')
        self.draft = {'title': 'Title', 'description': 'Caption', 'hashtags': '#gaming', 'facebook_page_id': PAGE}

    def publish(self, session, callback=None, checkpoint=None):
        return fb.facebook_publish(session, ACCOUNT, self.video, self.draft, callback, checkpoint)

    def test_expired_start_token_preserves_codes_without_exposing_provider_text(self):
        session = Session(Response(status=401, payload={'error': {'code': 190, 'error_subcode': 463,
                    'message': TOKEN + ' https://provider.invalid/?access_token=' + TOKEN}}))
        with self.assertRaises(ValueError) as caught:
            self.publish(session)
        self.assertEqual(caught.exception.provider_code, 190)
        self.assertEqual(caught.exception.provider_subcode, 463)
        self.assertIn('expired', str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn('provider.invalid', str(caught.exception))
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][2]['data'], {'upload_phase': 'start'})

    def test_stream_then_finish_once_and_wait_for_confirmed_publishing(self):
        session = replies(PENDING, COMPLETE)
        progress, checkpoints = [], []
        with patch.object(fb.time, 'sleep'):
            result = self.publish(session, lambda n, stage: progress.append(n), lambda **fields: checkpoints.append(fields))
        self.assertEqual(result, {'remote_id': VIDEO, 'url': 'https://www.facebook.com/reel/' + VIDEO})
        self.assertEqual(checkpoints, [{'remote_id': VIDEO, 'publish_attempted': False}, {'remote_id': VIDEO, 'publish_attempted': True}])
        self.assertEqual([call[0] for call in session.calls], ['POST', 'POST', 'POST', 'GET', 'GET', 'GET'])
        upload = session.calls[1][2]
        self.assertEqual(upload['data'], self.video.read_bytes())
        self.assertEqual(upload['headers']['file_size'], '10')
        self.assertEqual(upload['headers']['Content-Length'], '10')
        self.assertEqual(upload['headers']['Authorization'], 'OAuth ' + TOKEN)
        self.assertEqual(upload['timeout'], fb.FACEBOOK_UPLOAD_TIMEOUT)
        self.assertTrue(all(call[2]['timeout'] == REQUEST_TIMEOUT for call in session.calls if call[1] != UPLOAD))
        self.assertEqual(session.calls[2][2]['data'], {'upload_phase': 'finish', 'video_id': VIDEO,
            'video_state': 'PUBLISHED', 'title': 'Title', 'description': 'Caption\n\n#gaming'})
        self.assertTrue(all(call[2]['allow_redirects'] is False for call in session.calls))
        self.assertEqual(progress[-1], 100)
        self.assertEqual(progress, sorted(progress))

    def test_untrusted_upload_locations_never_receive_token_or_video(self):
        for url in ('https://evil.example/upload', UPLOAD + '?redirect=evil', UPLOAD.replace(VIDEO, '778'),
                    UPLOAD.replace('https:', 'http:'), UPLOAD.replace('rupload.', 'rupload.fake.'), None):
            with self.subTest(url=url):
                session = Session(Response(payload={**START, 'upload_url': url}))
                with self.assertRaises(fb.FacebookPublishError) as error: self.publish(session)
                self.assertFalse(error.exception.publish_attempted)
                self.assertEqual(error.exception.remote_id, VIDEO)
                self.assertEqual(len(session.calls), 1)

    def test_failed_binary_upload_never_sends_finish(self):
        for reply in (Response(payload={'success': False}), requests.ConnectionError('lost upload')):
            session = StreamingSession(Response(payload=START), reply)
            with self.assertRaises(fb.FacebookPublishError) as error: self.publish(session)
            self.assertFalse(error.exception.publish_attempted)
            self.assertEqual(len(session.calls), 2)

    def test_wrapped_write_timeout_reports_transfer_timeout_without_publishing(self):
        private = TOKEN + ' https://private.invalid/?access_token=' + TOKEN
        interrupted = requests.ConnectionError(ProtocolError('Connection aborted.', TimeoutError(private)))
        session = StreamingSession(Response(payload=START), interrupted)
        with self.assertRaises(fb.FacebookPublishError) as caught:
            self.publish(session)
        self.assertEqual(caught.exception.network_kind, 'timeout')
        self.assertIn('video transfer timed out', str(caught.exception))
        self.assertIn('No publish was requested', str(caught.exception))
        self.assertFalse(caught.exception.publish_attempted)
        self.assertEqual(caught.exception.remote_id, VIDEO)
        self.assertEqual(len(session.calls), 2)
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn('private.invalid', str(caught.exception))

    def test_connection_reset_remains_distinct_from_transfer_timeout(self):
        session = StreamingSession(Response(payload=START), requests.ConnectionError(TOKEN))
        with self.assertRaises(fb.FacebookPublishError) as caught:
            self.publish(session)
        self.assertEqual(caught.exception.network_kind, 'connection')
        self.assertIn('video transfer was interrupted', str(caught.exception))
        self.assertIn('No publish was requested', str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertEqual(len(session.calls), 2)

    def test_nested_connection_reset_has_safe_reason_and_no_finish(self):
        failure = requests.ConnectionError(ProtocolError(TOKEN, ConnectionResetError(10054, TOKEN)))
        session = StreamingSession(Response(payload=START), failure)
        with self.assertRaises(fb.FacebookPublishError) as caught:
            self.publish(session)
        self.assertEqual(caught.exception.network_reason, 'connection_reset')
        self.assertIn('video transfer was reset', str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertEqual(len(session.calls), 2)
        self.assertFalse(caught.exception.publish_attempted)

    def test_tls_diagnostic_labels_never_expose_arbitrary_provider_text(self):
        for reason, expected in (('DECRYPTION_FAILED_OR_BAD_RECORD_MAC', 'tls_record'), (TOKEN, 'tls')):
            with self.subTest(reason=reason):
                failure = ssl.SSLError(1, TOKEN + ' https://private.invalid/')
                failure.reason = reason
                session = StreamingSession(Response(payload=START), requests.exceptions.SSLError(failure))
                with self.assertRaises(fb.FacebookPublishError) as caught:
                    self.publish(session)
                self.assertEqual(caught.exception.network_reason, expected)
                self.assertNotIn(TOKEN, str(caught.exception))
                self.assertNotIn('private.invalid', str(caught.exception))
                self.assertEqual(len(session.calls), 2)

    def test_curl_streams_file_with_token_only_in_stdin_and_no_redirects(self):
        reply = SimpleNamespace(returncode=0, stdout=b'{"success":true}\n200', stderr=b'')
        with patch.object(fb.subprocess, 'run', return_value=reply) as run:
            result = fb._curl_video_upload('curl.exe', UPLOAD, TOKEN, self.video, self.video.stat().st_size)
        self.assertTrue(result['success'])
        command = run.call_args.args[0]
        configuration = run.call_args.kwargs['input'].decode('utf-8')
        self.assertNotIn(TOKEN, ' '.join(command))
        self.assertIn('Authorization: OAuth ' + TOKEN, configuration)
        self.assertIn('upload-file = ', configuration)
        self.assertEqual(command[1], '--disable')
        self.assertEqual(command[command.index('--proto') + 1], '=https')
        self.assertNotIn('--location', command)
        self.assertEqual(run.call_count, 1)

    def test_curl_preserves_early_http_rejection_without_echoing_token(self):
        reply = SimpleNamespace(returncode=55,
            stdout=json.dumps({'error':{'code':100, 'message':'Fixture rejection ' + TOKEN}}).encode() + b'\n400', stderr=TOKEN.encode())
        with patch.object(fb.subprocess, 'run', return_value=reply):
            with self.assertRaises(ValueError) as caught:
                fb._curl_video_upload('curl.exe', UPLOAD, TOKEN, self.video, self.video.stat().st_size)
        self.assertEqual(caught.exception.provider_code, 100)
        self.assertIn('HTTP 400', str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_curl_configuration_rejects_header_injection_before_launch(self):
        with patch.object(fb.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                fb._curl_video_upload('curl.exe', UPLOAD, TOKEN + '\r\nheader = "bad"', self.video, self.video.stat().st_size)
        run.assert_not_called()

    def test_curl_timeout_never_exposes_stderr(self):
        reply = SimpleNamespace(returncode=28, stdout=b'\n000', stderr=TOKEN.encode())
        with patch.object(fb.subprocess, 'run', return_value=reply):
            with self.assertRaises(ProviderNetworkError) as caught:
                fb._curl_video_upload('curl.exe', UPLOAD, TOKEN, self.video, self.video.stat().st_size)
        self.assertEqual(caught.exception.network_kind, 'timeout')
        self.assertNotIn(TOKEN, str(caught.exception))

    @unittest.skipUnless(fb.os.name == 'nt', 'Windows curl transport')
    def test_windows_curl_upload_finishes_only_once_after_confirmed_transfer(self):
        with requests.Session() as session:
            with (patch.object(session, 'request', side_effect=[Response(payload=START),
                    Response(payload={'success':True}), Response(payload=COMPLETE),
                    Response(payload={'permalink_url':'https://www.facebook.com/reel/' + VIDEO})]) as graph,
                    patch.object(fb.shutil, 'which', return_value='curl.exe'),
                    patch.object(fb.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'{"success":true}\n200', stderr=b'')) as run):
                result = self.publish(session)
        self.assertEqual(result['remote_id'], VIDEO)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(len(graph.call_args_list), 4)
        self.assertEqual(graph.call_args_list[1].kwargs['data']['upload_phase'], 'finish')

    def test_lost_finish_response_retains_remote_id_and_never_repeats_publish(self):
        session = StreamingSession(Response(payload=START), Response(payload={'success': True}), requests.Timeout('lost finish'))
        with self.assertRaises(fb.FacebookPublishError) as error: self.publish(session)
        self.assertTrue(error.exception.publish_attempted)
        self.assertEqual(error.exception.remote_id, VIDEO)
        self.assertEqual(len(session.calls), 3)
        self.assertNotIn(TOKEN, str(error.exception))
        self.assertIn('Check existing upload', str(error.exception))
        self.assertEqual(error.exception.network_kind, 'timeout')

    def test_processing_error_or_malformed_status_never_marks_success(self):
        for status in (FAILED, {'status': []}, {'status': {'publishing_phase': 'complete'}},
                       {'status': {'video_status': 'error', 'publishing_phase': {'status': 'complete'}}}):
            session = replies(status)
            with self.subTest(status=status), self.assertRaises(fb.FacebookPublishError) as error:
                self.publish(session)
            self.assertTrue(error.exception.publish_attempted)
            self.assertEqual(len(session.calls), 4)

    def test_processing_budget_exhaustion_is_unconfirmed_and_never_reposts(self):
        session = replies(PENDING)
        with patch.object(fb, 'FACEBOOK_POLL_TIMEOUT', 1), patch.object(fb.time, 'monotonic', side_effect=[0, .1, 2, 2]), patch.object(fb.time, 'sleep'):
            with self.assertRaisesRegex(fb.FacebookPublishError, 'unconfirmed'): self.publish(session)
        self.assertEqual(len(session.calls), 4)

    def test_permalink_lookup_failure_preserves_confirmed_success(self):
        result = self.publish(replies(COMPLETE, permalink=False))
        self.assertEqual(result['url'], 'https://www.facebook.com/reel/' + VIDEO)
        self.assertEqual(fb.facebook_permalink('https://evil.example/reel', VIDEO), result['url'])

    def test_missing_file_or_changed_page_rejected_before_network(self):
        session = Session()
        self.draft['facebook_page_id'] = '556'
        with self.assertRaisesRegex(ValueError, 'Page changed'): self.publish(session)
        self.video.unlink()
        with self.assertRaises(ValueError): self.publish(session)
        self.assertFalse(session.calls)

    def test_reader_bounds_memory_and_detects_truncated_video(self):
        self.video.write_bytes(b'x' * (2 * 1024 * 1024))
        with self.video.open('rb') as stream:
            reader = fb._VideoReader(stream, self.video.stat().st_size + 1, None)
            self.assertEqual(len(reader.read(100 * 1024 * 1024)), 1024 * 1024)
            self.assertEqual(len(reader.read(100 * 1024 * 1024)), 1024 * 1024)
            with self.assertRaisesRegex(ValueError, 'changed'): reader.read()

    def test_requests_streams_exact_content_length_to_local_receiver(self):
        received = {}
        class Receiver(BaseHTTPRequestHandler):
            def do_POST(self):
                received['length'] = self.headers.get('Content-Length')
                received['transfer'] = self.headers.get('Transfer-Encoding')
                received['body'] = self.rfile.read(int(received['length']))
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Receiver)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with self.video.open('rb') as stream, requests.Session() as session:
                reader = fb._VideoReader(stream, self.video.stat().st_size, None)
                session.post(f'http://127.0.0.1:{server.server_port}/upload', data=reader,
                    headers={'Content-Length': str(len(reader))}, timeout=3).raise_for_status()
            self.assertEqual(received, {'length': '10', 'transfer': None, 'body': b'abcdefghij'})
        finally:
            server.shutdown(); server.server_close(); thread.join(3)


    def test_stalled_local_transfer_needs_write_budget_and_reports_wrapped_timeout(self):
        # Exercise the real requests socket path without a Facebook request.
        self.video.write_bytes(b'x' * (16 * 1024 * 1024))
        received = []
        class Receiver(BaseHTTPRequestHandler):
            def do_POST(self):
                self.connection.settimeout(2)
                time.sleep(.35)
                remaining = int(self.headers['Content-Length'])
                try:
                    while remaining:
                        data = self.rfile.read(min(remaining, 65536))
                        if not data:
                            return
                        remaining -= len(data)
                    received.append(int(self.headers['Content-Length']))
                    self.send_response(200); self.end_headers()
                    self.wfile.write(b'{"success":true}')
                except (OSError, TimeoutError):
                    pass
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Receiver)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = f'http://127.0.0.1:{server.server_port}/upload'
        try:
            with self.video.open('rb') as stream, requests.Session() as session:
                reader = fb._VideoReader(stream, self.video.stat().st_size, None)
                with self.assertRaises(ProviderNetworkError) as caught:
                    request_json(session, 'POST', url, data=reader,
                        headers={'Content-Length':str(len(reader))}, timeout=(.05, 2))
                self.assertEqual(caught.exception.network_kind, 'timeout')
                self.assertIn('timed out', str(caught.exception))
            with self.video.open('rb') as stream, requests.Session() as session:
                reader = fb._VideoReader(stream, self.video.stat().st_size, None)
                result = request_json(session, 'POST', url, data=reader,
                    headers={'Content-Length':str(len(reader))}, timeout=(2, 2))
                self.assertTrue(result['success'])
            self.assertEqual(received, [self.video.stat().st_size])
        finally:
            server.shutdown(); server.server_close(); thread.join(3)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        delay = patch.object(pub, 'META_RETRY_DELAY', 0); delay.start(); self.addCleanup(delay.stop)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'; (self.project / 'output').mkdir(parents=True)
        (self.project / 'output/final.mp4').write_bytes(b'video bytes')
        write_json(self.project / 'studio.json', {'name': 'Fixture project'})
        self.app = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        snapshot = self.app.snapshot('project')
        self.draft = {**snapshot['draft'], 'facebook_page_id': PAGE}
        self.signature = snapshot['video']['signature']
        self.app.vault['accounts']['facebook_page'] = dict(ACCOUNT)
        self.app._vault_save()

    def wait(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            snapshot = self.app.snapshot('project')
            if not self.app.running and snapshot['history'][0]['status'] != 'running': return
            time.sleep(.01)
        self.fail('Worker did not finish')

    def start(self):
        self.app.start('project', 'facebook_page', self.draft, True, self.signature); self.wait()

    def failed_upload(self):
        self.app.session = StreamingSession(Response(payload=START), Response(payload={'success': True}), requests.Timeout('lost'),
            *[requests.ConnectionError('status unavailable') for _ in range(pub.META_RECOVERY_CHECKS)])
        self.start()
        return self.app.job['id']

    def status_reply(self, status, owner=PAGE, video=VIDEO):
        self.app.session = Session(Response(payload={**status, 'id': video, 'from': {'id': owner}}))

    def test_expired_upload_marks_connection_for_reconnect_and_blocks_retry(self):
        self.app.session = Session(Response(status=401, payload={'error': {'code': 190, 'error_subcode': 463, 'message': TOKEN}}))
        self.start()
        snapshot = self.app.snapshot('project')
        self.assertFalse(snapshot['accounts']['facebook_page']['connected'])
        self.assertTrue(snapshot['accounts']['facebook_page']['needs_reconnect'])
        self.assertTrue(snapshot['job']['reconnect_required'])
        self.assertEqual(snapshot['job']['error_subcode'], 463)
        self.assertEqual(snapshot['job']['progress'], 0)
        self.assertNotIn('remote_id', snapshot['job'])
        self.assertNotIn(TOKEN, json.dumps(snapshot))
        self.assertEqual(len(self.app.session.calls), 1)
        with self.assertRaisesRegex(ValueError, 'Connect'):
            self.app.start('project', 'facebook_page', self.draft, True, self.signature)
        restarted = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        self.assertFalse(restarted.snapshot('project')['accounts']['facebook_page']['connected'])
        restarted.session = Session(Response(payload={'id': PAGE, 'name': 'Fixture Page', 'access_token': TOKEN}))
        restarted.connect_token('facebook_page', 'FRESH_PRIVATE_PAGE_TOKEN', PAGE)
        self.assertTrue(restarted.snapshot('project')['accounts']['facebook_page']['connected'])
        self.assertFalse(restarted.snapshot('project')['accounts']['facebook_page']['needs_reconnect'])

    def test_transfer_failure_reason_survives_restart_without_exposing_exception(self):
        failure = requests.ConnectionError(ProtocolError(TOKEN, ConnectionResetError(10054, TOKEN)))
        self.app.session = StreamingSession(*[reply for _ in range(pub.META_UPLOAD_ATTEMPTS) for reply in (Response(payload=START), failure)])
        self.start()
        snapshot = self.app.snapshot('project')
        self.assertEqual(snapshot['job']['network_reason'], 'connection_reset')
        self.assertEqual(snapshot['history'][0]['network_reason'], 'connection_reset')
        self.assertFalse(snapshot['job']['publish_attempted'])
        restarted = pub.Publisher(self.root / 'data', lambda key:self.project, session=Session())
        self.assertEqual(restarted.snapshot('project')['history'][0]['network_reason'], 'connection_reset')
        self.assertNotIn(TOKEN, json.dumps(snapshot))
        self.assertEqual(snapshot['job']['retry_count'], 2)
        self.assertEqual(len(self.app.session.calls), 6)

    def test_meta_upload_error_details_are_actionable_and_redacted_in_history(self):
        message = 'Video was rejected. ' + TOKEN + ' EAATESTSECRETAAAA1234 https://private.invalid/?access_token=' + TOKEN
        self.app.session = StreamingSession(Response(payload=START),
            Response(status=400, payload={'error':{'code':100, 'message':message}}))
        self.start()
        snapshot = self.app.snapshot('project')
        self.assertIn('Video was rejected', snapshot['job']['error'])
        self.assertIn('code 100', snapshot['job']['error'])
        for private in (TOKEN, 'EAATESTSECRETAAAA1234', 'private.invalid'):
            self.assertNotIn(private, json.dumps(snapshot))
        self.assertFalse(snapshot['job']['publish_attempted'])
        self.assertEqual(len(self.app.session.calls), 2)

    def test_page_connection_check_is_read_only_and_expiry_is_actionable(self):
        self.app.session = Session(Response(status=401, payload={'error': {'code': 190, 'error_subcode': 463}}))
        result = self.app.check_account('facebook_page')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error_subcode'], 463)
        self.assertTrue(self.app.snapshot('project')['accounts']['facebook_page']['needs_reconnect'])
        self.assertEqual([call[0] for call in self.app.session.calls], ['GET'])
        self.assertIsNone(self.app.job)
        self.app.session = Session(Response(payload={'id': PAGE, 'name': 'Fixture Page', 'access_token': TOKEN}))
        self.assertTrue(self.app.check_account('facebook_page')['ok'])
        self.assertTrue(self.app.snapshot('project')['accounts']['facebook_page']['connected'])
        self.assertEqual([call[0] for call in self.app.session.calls], ['GET'])
        self.assertEqual(self.app.session.calls[0][2]['params']['fields'], 'id,name,access_token')

    def test_page_connection_network_error_does_not_invalidate_token(self):
        self.app.session = Session(requests.Timeout('private provider details'))
        with self.assertRaises(ValueError):
            self.app.check_account('facebook_page')
        self.assertTrue(self.app.snapshot('project')['accounts']['facebook_page']['connected'])
        self.assertFalse(self.app.snapshot('project')['accounts']['facebook_page']['needs_reconnect'])

    def test_finish_auth_error_preserves_upload_checkpoint_after_reconnecting(self):
        self.app.session = StreamingSession(Response(payload=START), Response(payload={'success': True}),
                   Response(status=401, payload={'error': {'code': 190, 'error_subcode': 463}}))
        self.start()
        self.assertEqual(self.app.job['error_code'], 190)
        self.assertEqual(self.app.job['remote_id'], VIDEO)
        self.assertTrue(self.app.job['publish_attempted'])
        self.app.session = Session(Response(payload={'id': PAGE, 'name': 'Fixture Page', 'access_token': TOKEN}))
        self.app.connect_token('facebook_page', 'FRESH_PRIVATE_PAGE_TOKEN', PAGE)
        self.app.session = Session()
        with self.assertRaisesRegex(ValueError, 'may already have succeeded'):
            self.app.start('project', 'facebook_page', self.draft, True, self.signature)
        self.assertFalse(self.app.session.calls)

    def test_page_token_identifies_page_and_survives_restart_without_exposing_token(self):
        self.app.session = Session(Response(payload={'id': PAGE, 'name': 'Connected Page', 'access_token': TOKEN}))
        self.app.connect_token('facebook_page', 'NEW_PRIVATE_PAGE_TOKEN', PAGE)
        restarted = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        snapshot = restarted.snapshot('project')
        self.assertEqual(snapshot['accounts']['facebook_page']['page_id'], PAGE)
        self.assertEqual(snapshot['accounts']['facebook_page']['name'], 'Connected Page')
        self.assertNotIn('NEW_PRIVATE_PAGE_TOKEN', json.dumps(snapshot))
        self.assertNotIn('NEW_PRIVATE_PAGE_TOKEN', (self.app.data / 'accounts.json').read_text())
        self.app.disconnect('facebook_page')
        self.assertFalse(self.app.snapshot('project')['accounts']['facebook_page']['connected'])

    def test_personal_token_or_wrong_page_cannot_replace_connection(self):
        for profile in ({'id': PAGE, 'name': 'Personal profile'}, {'id': '556', 'name': 'Other Page', 'access_token': TOKEN}):
            self.app.session = Session(Response(payload=profile), Response(payload={'data': []}))
            with self.assertRaises(ValueError): self.app.connect_token('facebook_page', 'WRONG_TOKEN', PAGE)
            self.assertEqual(self.app.vault['accounts']['facebook_page']['access_token'], TOKEN)

    def user_token_reply(self):
        return Response(status=400, payload={'error': {'code': 100,
            'message': 'Tried accessing nonexisting field (access_token)'}})

    def test_user_token_resolves_only_selected_page_and_stores_verified_page_token(self):
        self.app.session = Session(self.user_token_reply(),
            Response(payload={'data': [
                {'id': '556', 'name': 'Other Page', 'access_token': 'OTHER_PAGE_TOKEN'},
                {'id': PAGE, 'name': 'Selected Page', 'access_token': 'RESOLVED_PAGE_TOKEN'}]}),
            Response(payload={'id': PAGE, 'name': 'Selected Page'}))
        self.app.connect_token('facebook_page', 'NEW_USER_TOKEN', PAGE)
        self.assertEqual(self.app.vault['accounts']['facebook_page']['access_token'], 'RESOLVED_PAGE_TOKEN')
        self.assertEqual(self.app.vault['accounts']['facebook_page']['page_id'], PAGE)
        self.assertEqual([call[0] for call in self.app.session.calls], ['GET', 'GET', 'GET'])
        self.assertTrue(self.app.session.calls[1][1].endswith('/me/accounts'))
        self.assertEqual(self.app.session.calls[2][2]['headers']['Authorization'], 'Bearer RESOLVED_PAGE_TOKEN')
        self.assertEqual(self.app.session.calls[2][2]['params']['fields'], 'id,name')
        self.assertTrue(all('category' not in call[2]['params']['fields'] for call in self.app.session.calls))
        self.assertNotIn('RESOLVED_PAGE_TOKEN', json.dumps(self.app.snapshot('project')))
        self.assertNotIn('NEW_USER_TOKEN', (self.app.data / 'accounts.json').read_text())

    def test_direct_page_token_requires_no_category_and_can_infer_page_id(self):
        self.app.session = Session(Response(payload={'id': PAGE, 'name': 'No category Page', 'access_token': 'NEW_PAGE_TOKEN'}))
        self.app.connect_token('facebook_page', 'NEW_PAGE_TOKEN')
        self.assertEqual(self.app.vault['accounts']['facebook_page']['page_id'], PAGE)
        self.assertEqual(len(self.app.session.calls), 1)
        self.assertEqual(self.app.session.calls[0][2]['params']['fields'], 'id,name,access_token')
        self.assertEqual([call[0] for call in self.app.session.calls], ['GET'])

    def test_user_identity_without_page_field_resolves_selected_page(self):
        self.app.session = Session(Response(payload={'id': '123', 'name': 'User'}),
            Response(payload={'data': [{'id': PAGE, 'access_token': 'RESOLVED_PAGE_TOKEN'}]}),
            Response(payload={'id': PAGE, 'name': 'Selected Page'}))
        self.app.connect_token('facebook_page', 'NEW_USER_TOKEN', PAGE)
        self.assertEqual(self.app.vault['accounts']['facebook_page']['access_token'], 'RESOLVED_PAGE_TOKEN')
        self.assertEqual([call[0] for call in self.app.session.calls], ['GET', 'GET', 'GET'])

    def test_empty_or_invalid_page_field_never_proves_page_identity(self):
        for page_token in ('', '   ', None, False, 123):
            with self.subTest(page_token=page_token):
                self.app.session = Session(Response(payload={'id': PAGE, 'name': 'Personal profile', 'access_token': page_token}),
                    Response(payload={'data': []}))
                with self.assertRaises(ValueError):
                    self.app.connect_token('facebook_page', 'NEW_USER_TOKEN', PAGE)
                self.assertEqual(self.app.vault['accounts']['facebook_page']['access_token'], TOKEN)

    def test_missing_page_field_with_user_node_suffix_resolves_page(self):
        self.app.session = Session(Response(status=400, payload={'error': {'code': 100,
                'message': 'Tried accessing nonexisting field (access_token) on node type (User)'}}),
            Response(payload={'data': [{'id': PAGE, 'access_token': 'RESOLVED_PAGE_TOKEN'}]}),
            Response(payload={'id': PAGE, 'name': 'Selected Page'}))
        self.app.connect_token('facebook_page', 'NEW_USER_TOKEN', PAGE)
        self.assertEqual(self.app.vault['accounts']['facebook_page']['access_token'], 'RESOLVED_PAGE_TOKEN')

    def test_user_token_never_selects_another_page_when_expected_page_is_missing(self):
        self.app.session = Session(self.user_token_reply(),
            Response(payload={'data': [{'id': '556', 'name': 'Other Page', 'access_token': 'OTHER_PAGE_TOKEN'}]}))
        with self.assertRaisesRegex(ValueError, 'cannot access the selected Page'):
            self.app.connect_token('facebook_page', 'NEW_USER_TOKEN', PAGE)
        self.assertEqual(self.app.vault['accounts']['facebook_page']['access_token'], TOKEN)
        self.assertEqual(len(self.app.session.calls), 2)

    def test_user_token_with_multiple_pages_requires_explicit_page_id(self):
        self.app.session = Session(self.user_token_reply(), Response(payload={'data': [
            {'id': PAGE, 'access_token': 'ONE_TOKEN'}, {'id': '556', 'access_token': 'TWO_TOKEN'}]}))
        with self.assertRaisesRegex(ValueError, 'Enter the intended Page ID'):
            self.app.connect_token('facebook_page', 'NEW_USER_TOKEN')
        self.assertEqual(self.app.vault['accounts']['facebook_page']['access_token'], TOKEN)
        self.assertEqual(len(self.app.session.calls), 2)

    def test_user_token_candidate_must_identify_the_expected_page(self):
        self.app.session = Session(self.user_token_reply(),
            Response(payload={'data': [{'id': PAGE, 'access_token': 'CANDIDATE_TOKEN'}]}),
            Response(payload={'id': '556', 'name': 'Other Page', 'access_token': TOKEN}))
        with self.assertRaisesRegex(ValueError, 'another Facebook Page'):
            self.app.connect_token('facebook_page', 'NEW_USER_TOKEN', PAGE)
        self.assertEqual(self.app.vault['accounts']['facebook_page']['access_token'], TOKEN)

    def test_connection_code_100_details_are_specific_but_redact_tokens_and_urls(self):
        fresh = 'FRESH_PRIVATE_TOKEN'
        message = 'Unsupported get request. Check Page access. ' + fresh + ' ' + TOKEN + ' https://graph.facebook.com/?access_token=' + fresh
        self.app.session = Session(Response(status=400, payload={'error': {'code': 100, 'message': message}}))
        with self.assertRaises(ValueError) as caught:
            self.app.connect_token('facebook_page', fresh, PAGE)
        detail = str(caught.exception)
        self.assertIn('code 100', detail)
        self.assertIn('Check Page access', detail)
        for secret in (fresh, TOKEN, 'https://graph.facebook.com/'):
            self.assertNotIn(secret, detail)
        self.assertEqual(len(self.app.session.calls), 1)
        self.assertEqual(self.app.vault['accounts']['facebook_page']['access_token'], TOKEN)

    def test_user_token_listing_permission_error_is_actionable_and_credential_safe(self):
        self.app.session = Session(self.user_token_reply(),
            Response(status=400, payload={'error': {'code': 200, 'message': 'Requires pages_show_list permission. NEW_USER_TOKEN'}}))
        with self.assertRaises(ValueError) as caught:
            self.app.connect_token('facebook_page', 'NEW_USER_TOKEN', PAGE)
        self.assertIn('pages_show_list', str(caught.exception))
        self.assertNotIn('NEW_USER_TOKEN', str(caught.exception))
        self.assertEqual(self.app.vault['accounts']['facebook_page']['access_token'], TOKEN)

    def test_page_listing_never_follows_token_bearing_pagination_url(self):
        self.app.session = Session(self.user_token_reply(), Response(payload={
            'data': [], 'paging': {'next': 'https://untrusted.invalid/?access_token=NEW_USER_TOKEN'}}))
        with self.assertRaisesRegex(ValueError, 'first 100'):
            self.app.connect_token('facebook_page', 'NEW_USER_TOKEN', PAGE)
        self.assertEqual(len(self.app.session.calls), 2)

    def test_page_upload_needs_review_file_signature_and_matching_destination(self):
        for reviewed, signature, page in ((False, self.signature, PAGE), (True, 'old', PAGE), (True, self.signature, '556')):
            with self.assertRaises(ValueError): self.app.start('project', 'facebook_page', {**self.draft, 'facebook_page_id': page}, reviewed, signature)
        self.assertIsNone(self.app.job)
        self.assertFalse(self.app.session.calls)

    def test_completed_page_reel_blocks_same_page_but_allows_another_page(self):
        self.app.session = replies(COMPLETE)
        self.start()
        self.assertEqual(self.app.snapshot('project')['history'][0]['destination_name'], 'Fixture Page')
        with self.assertRaisesRegex(ValueError, 'already recorded'): self.start()
        self.app.vault['accounts']['facebook_page']['page_id'] = '556'; self.draft['facebook_page_id'] = '556'
        self.app.session = replies(COMPLETE)
        self.start()
        self.assertEqual(len(self.app.snapshot('project')['history']), 2)

    def test_manual_personal_profile_history_does_not_block_page_publishing(self):
        self.app.mark('project', 'facebook', 'https://www.facebook.com/reel/123')
        self.app.session = replies(COMPLETE); self.start()
        self.assertEqual(self.app.job['status'], 'complete')
        self.assertEqual({row['platform'] for row in self.app.snapshot('project')['history']}, {'facebook', 'facebook_page'})

    def test_ambiguous_publish_is_durable_and_blocks_immediate_duplicate(self):
        self.failed_upload()
        restarted = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        row = restarted.snapshot('project')['history'][0]
        self.assertEqual(row['remote_id'], VIDEO); self.assertTrue(row['publish_attempted'])
        self.assertEqual(row['status'], 'failed')
        with self.assertRaisesRegex(ValueError, 'may already have succeeded'):
            restarted.start('project', 'facebook_page', self.draft, True, self.signature)
        self.assertFalse(restarted.session.calls)

    def test_publish_checkpoint_is_saved_before_finish_and_preserved_on_restart(self):
        with patch.object(pub.threading, 'Thread'):
            self.app.start('project', 'facebook_page', self.draft, True, self.signature)
        self.app._checkpoint(self.app.job, remote_id=VIDEO, publish_attempted=True)
        self.assertTrue(read_cache(self.app.data / 'job.json')['publish_attempted'])
        restarted = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        row = restarted.snapshot('project')['history'][0]
        self.assertEqual(row['status'], 'interrupted'); self.assertEqual(row['remote_id'], VIDEO)
        with self.assertRaisesRegex(ValueError, 'may already have succeeded'):
            restarted.start('project', 'facebook_page', self.draft, True, self.signature)

    def test_verified_publishing_updates_history_using_only_get(self):
        job = self.failed_upload(); self.status_reply(COMPLETE)
        result = self.app.verify_facebook('project', job)
        self.assertTrue(result['ok']); self.assertEqual(self.app.job['status'], 'complete')
        self.assertEqual([call[0] for call in self.app.session.calls], ['GET'])
        with self.assertRaisesRegex(ValueError, 'already recorded'): self.start()

    def test_processing_remains_unconfirmed_and_duplicate_is_blocked(self):
        job = self.failed_upload(); self.status_reply(PENDING)
        self.assertFalse(self.app.verify_facebook('project', job)['ok'])
        self.assertEqual(self.app.job['status'], 'failed')
        with self.assertRaisesRegex(ValueError, 'may already have succeeded'): self.start()

    def test_verified_provider_failure_allows_reviewed_retry(self):
        job = self.failed_upload(); self.status_reply(FAILED)
        self.assertFalse(self.app.verify_facebook('project', job)['ok'])
        self.assertTrue(self.app.snapshot('project')['history'][0]['confirmed_unpublished'])
        self.app.session = replies(COMPLETE); self.start()
        self.assertEqual(self.app.job['status'], 'complete')

    def test_verification_rejects_mismatched_video_or_page_and_malformed_status(self):
        job = self.failed_upload()
        for status, owner, video in ((COMPLETE, '556', VIDEO), (COMPLETE, PAGE, '778'), ({'status': []}, PAGE, VIDEO)):
            self.status_reply(status, owner, video)
            with self.assertRaises(ValueError): self.app.verify_facebook('project', job)
            self.assertEqual(self.app.job['status'], 'failed')
        self.app.vault['accounts']['facebook_page']['page_id'] = '556'; self.app.session = Session()
        with self.assertRaisesRegex(ValueError, 'Reconnect'): self.app.verify_facebook('project', job)
        self.assertFalse(self.app.session.calls)

    def test_failed_upload_without_finish_can_retry_and_expired_page_never_refreshes_instagram(self):
        self.app.session = StreamingSession(*[reply for _ in range(pub.META_UPLOAD_ATTEMPTS) for reply in (Response(payload=START), requests.Timeout('lost binary'))])
        self.start(); self.assertFalse(self.app.job['publish_attempted'])
        self.app.session = replies(COMPLETE); self.start(); self.assertEqual(self.app.job['status'], 'complete')
        self.app.vault['accounts']['facebook_page']['expires_at'] = 1; self.app.session = Session()
        with self.assertRaisesRegex(ValueError, 'expired'): self.app._access_account('facebook_page')
        self.assertFalse(self.app.session.calls)


class HttpTests(unittest.TestCase):
    def test_page_connection_and_recovery_endpoints_require_token_and_do_not_repost(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); app = studio.Studio(root / 'data', root / 'projects')
            identifier = app.create('Facebook HTTP fixture', 'blank')
            project = app.project(identifier); (project / 'output').mkdir(); (project / 'output/final.mp4').write_bytes(b'video')
            server = ThreadingHTTPServer(('127.0.0.1', 0), studio.Handler); server.studio = app
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            def request(route, body, authenticated=True):
                headers = {'Content-Type': 'application/json'}
                if authenticated: headers['X-Studio-Token'] = app.token
                with urllib.request.urlopen(urllib.request.Request(base + route, data=json.dumps(body).encode(), headers=headers)) as reply:
                    return json.load(reply)
            try:
                for route, body in (('/api/publishing/check-account', {'platform': 'facebook_page'}),
                                    ('/api/publishing/token', {'platform': 'facebook_page', 'access_token': TOKEN}),
                                    ('/api/publishing/verify-facebook', {'id': identifier, 'job_id': 'any'})):
                    with self.assertRaises(urllib.error.HTTPError) as error: request(route, body, False)
                    self.assertEqual(error.exception.code, 403)
                app.publisher.session = Session(Response(payload={'id': PAGE, 'name': 'HTTP Page', 'access_token': TOKEN}))
                with self.assertRaises(urllib.error.HTTPError):
                    request('/api/publishing/token', {'platform': 'facebook_page', 'access_token': TOKEN, 'page_id': '556'})
                app.publisher.session = Session(Response(payload={'id': PAGE, 'name': 'HTTP Page', 'access_token': TOKEN}))
                request('/api/publishing/token', {'platform': 'facebook_page', 'access_token': TOKEN, 'page_id': PAGE})
                snapshot = app.publisher.snapshot(identifier)
                app.publisher.session = StreamingSession(Response(payload=START), Response(payload={'success': True}), requests.Timeout('lost'))
                request('/api/publishing/start', {'id': identifier, 'platform': 'facebook_page', 'reviewed': True,
                    'video_signature': snapshot['video']['signature'], 'draft': {**snapshot['draft'], 'facebook_page_id': PAGE}})
                deadline = time.monotonic() + 3
                while app.publisher.running and time.monotonic() < deadline: time.sleep(.01)
                self.assertFalse(app.publisher.running)
                app.publisher.session = Session(Response(payload={**COMPLETE, 'id': VIDEO, 'from': {'id': PAGE}}))
                result = request('/api/publishing/verify-facebook', {'id': identifier, 'job_id': app.publisher.job['id']})
                self.assertTrue(result['ok']); self.assertEqual([call[0] for call in app.publisher.session.calls], ['GET'])
            finally:
                server.shutdown(); server.server_close(); thread.join(3)


if __name__ == '__main__': unittest.main()
