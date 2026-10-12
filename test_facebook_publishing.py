"""Facebook Page publishing checks: simulated Meta replies and a local HTTP receiver."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests
import facebook_publishing as fb
import publishing as pub
import video_studio as studio
from pipeline_common import write_json, read_cache
from test_publishing import Response, Session

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

    def test_lost_finish_response_retains_remote_id_and_never_repeats_publish(self):
        session = StreamingSession(Response(payload=START), Response(payload={'success': True}), requests.Timeout('lost finish'))
        with self.assertRaises(fb.FacebookPublishError) as error: self.publish(session)
        self.assertTrue(error.exception.publish_attempted)
        self.assertEqual(error.exception.remote_id, VIDEO)
        self.assertEqual(len(session.calls), 3)
        self.assertNotIn(TOKEN, str(error.exception))

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


class PublisherTests(unittest.TestCase):
    def setUp(self):
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
        self.app.session = StreamingSession(Response(payload=START), Response(payload={'success': True}), requests.Timeout('lost'))
        self.start()
        return self.app.job['id']

    def status_reply(self, status, owner=PAGE, video=VIDEO):
        self.app.session = Session(Response(payload={**status, 'id': video, 'from': {'id': owner}}))

    def test_page_token_identifies_page_and_survives_restart_without_exposing_token(self):
        self.app.session = Session(Response(payload={'id': PAGE, 'name': 'Connected Page', 'category': 'Creator'}))
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
        for profile in ({'id': PAGE, 'name': 'Personal profile'}, {'id': '556', 'name': 'Other Page', 'category': 'Creator'}):
            self.app.session = Session(Response(payload=profile))
            with self.assertRaises(ValueError): self.app.connect_token('facebook_page', 'WRONG_TOKEN', PAGE)
            self.assertEqual(self.app.vault['accounts']['facebook_page']['access_token'], TOKEN)

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
        self.app.session = StreamingSession(Response(payload=START), requests.Timeout('lost binary'))
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
                for route, body in (('/api/publishing/token', {'platform': 'facebook_page', 'access_token': TOKEN}),
                                    ('/api/publishing/verify-facebook', {'id': identifier, 'job_id': 'any'})):
                    with self.assertRaises(urllib.error.HTTPError) as error: request(route, body, False)
                    self.assertEqual(error.exception.code, 403)
                app.publisher.session = Session(Response(payload={'id': PAGE, 'name': 'HTTP Page', 'category': 'Creator'}))
                with self.assertRaises(urllib.error.HTTPError):
                    request('/api/publishing/token', {'platform': 'facebook_page', 'access_token': TOKEN, 'page_id': '556'})
                app.publisher.session = Session(Response(payload={'id': PAGE, 'name': 'HTTP Page', 'category': 'Creator'}))
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
