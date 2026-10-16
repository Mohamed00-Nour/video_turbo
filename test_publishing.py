"""Publishing checks use temporary projects and simulated provider responses."""
import json
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from http.server import ThreadingHTTPServer

import requests
import publishing as pub
import publishing_clients as clients
import video_studio as studio
from pipeline_common import write_json


class Response:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code, self.payload, self.headers = status, payload or {}, headers or {}
    def json(self): return self.payload


class Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses: raise AssertionError('Unexpected provider request')
        result = self.responses.pop(0)
        if isinstance(result, Exception): raise result
        return result


class PublishingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        (self.project / 'output').mkdir(parents=True)
        self.video = self.project / 'output/final.mp4'
        self.video.write_bytes(b'video bytes')
        write_json(self.project / 'studio.json', {'name': 'Arabic title \u0645\u062b\u0627\u0644'})
        self.app = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        self.draft = self.app.snapshot('project')['draft']
        self.signature = self.app.snapshot('project')['video']['signature']
        self.app.vault['accounts']['youtube'] = {'access_token': 'PRIVATE_ACCESS_TOKEN', 'name': 'My channel'}
    def configure(self, platform='youtube'):
        self.app.configure(platform, {'client_id': 'my-client', 'client_secret': 'PRIVATE_CLIENT_SECRET',
                                     'redirect_uri': 'https://example.com/callback' if platform == 'instagram' else ''})
    def authorize(self, platform='youtube'):
        self.configure(platform)
        result = self.app.connect(platform, 'http://127.0.0.1:8765')
        state = parse_qs(urlparse(result['authorization_url']).query)['state'][0]
        return result, state
    def wait(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            snapshot = self.app.snapshot('project')
            job = snapshot['job']
            entry = next((row for row in snapshot['history'] if row['id'] == job['id']), None)
            # Restart checks need the durable result, not just the worker's
            # in-memory status before its final history write.
            if job['status'] != 'running' and entry and entry['status'] == job['status']:
                return
            time.sleep(.01)
        self.fail('Publishing worker did not persist its final result')

    def test_draft_and_protected_connection_survive_restart_without_exposing_secrets(self):
        self.configure()
        self.app.vault['accounts']['youtube'] = {'access_token': 'PRIVATE_ACCESS_TOKEN', 'refresh_token': 'PRIVATE_REFRESH_TOKEN', 'name': 'My channel'}
        self.app._vault_save()
        self.app.save_draft('project', {**self.draft, 'hashtags': 'gaming #arabic', 'description': 'New caption'})
        restarted = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        snapshot = restarted.snapshot('project')
        self.assertTrue(snapshot['accounts']['youtube']['connected'])
        self.assertEqual(snapshot['draft']['hashtags'], '#gaming #arabic')
        encoded = json.dumps(snapshot)
        for secret in ('PRIVATE_ACCESS_TOKEN', 'PRIVATE_REFRESH_TOKEN', 'PRIVATE_CLIENT_SECRET'):
            self.assertNotIn(secret, encoded)
            self.assertNotIn(secret, (self.root / 'data/publishing/accounts.json').read_text())
        self.assertEqual(restarted.vault['accounts']['youtube']['refresh_token'], 'PRIVATE_REFRESH_TOKEN')

    def test_platform_overrides_persist_and_inherit_updated_shared_fields(self):
        draft = {**self.draft, 'description': 'Shared caption', 'hashtags': '#shared',
                 'platform_overrides': {'youtube': {'title': 'YouTube title'},
                                        'instagram': {'description': 'Instagram caption', 'hashtags': ''}}}
        self.app.save_draft('project', draft)
        restarted = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        loaded = restarted.snapshot('project')['draft']
        self.assertEqual(loaded['platform_overrides']['instagram']['hashtags'], '')
        self.assertEqual(loaded['platform_overrides']['youtube']['title'], 'YouTube title')
        updated = restarted.save_draft('project', {**loaded, 'description': 'Updated shared', 'hashtags': 'new'})['draft']
        youtube = restarted._platform_draft(updated, 'youtube')
        instagram = restarted._platform_draft(updated, 'instagram')
        self.assertEqual(youtube['title'], 'YouTube title')
        self.assertEqual(youtube['description'], 'Updated shared')
        self.assertEqual(youtube['hashtags'], '#new')
        self.assertEqual(instagram['description'], 'Instagram caption')
        self.assertEqual(instagram['hashtags'], '')
        self.assertEqual(restarted._platform_draft(updated, 'tiktok')['description'], 'Updated shared')
        restored = restarted.save_draft('project', {**updated, 'platform_overrides': {}})['draft']
        self.assertEqual(restarted._platform_draft(restored, 'youtube')['title'], self.draft['title'])

    def test_platform_overrides_reject_invalid_shapes_and_normalize_tags(self):
        invalid = [[], {'unsupported': {}}, {'youtube': []}, {'youtube': {'privacy': 'public'}},
                   {'youtube': {'title': 123}}, {'youtube': {'title': 'x' * 101}},
                   {'instagram': {'description': 'x' * 5001}}, {'tiktok': {'hashtags': 'x' * 1501}}]
        for overrides in invalid:
            with self.subTest(overrides=type(overrides)):
                with self.assertRaises(ValueError):
                    self.app.save_draft('project', {**self.draft, 'platform_overrides': overrides})
        saved = self.app.save_draft('project', {**self.draft,
             'platform_overrides': {'tiktok': {'hashtags': 'gaming ##arabic'}, 'facebook': {}}})['draft']
        self.assertEqual(saved['platform_overrides'], {'tiktok': {'hashtags': '#gaming #arabic'}})

    def test_direct_upload_uses_platform_details_without_replacing_shared_draft(self):
        draft = {**self.draft, 'description': 'Shared description', 'hashtags': '#shared',
                 'platform_overrides': {'youtube': {'title': 'Custom upload title', 'description': 'Custom caption'}}}
        with patch.object(pub, 'youtube_upload', return_value={'remote_id': 'custom-video'}) as adapter:
            self.app.start('project', 'youtube', draft, True, self.signature)
            self.wait()
        sent = adapter.call_args.args[3]
        self.assertEqual(sent['title'], 'Custom upload title')
        self.assertEqual(sent['description'], 'Custom caption')
        self.assertEqual(sent['hashtags'], '#shared')
        self.assertNotIn('platform_overrides', sent)
        saved = self.app.snapshot('project')
        self.assertEqual(saved['draft']['title'], self.draft['title'])
        self.assertEqual(saved['draft']['description'], 'Shared description')
        self.assertEqual(saved['history'][0]['title'], 'Custom upload title')

    def test_instagram_limit_applies_to_resolved_caption(self):
        self.app.vault['accounts']['instagram'] = {'access_token': 'TEST_TOKEN', 'user_id': '123', 'name': '@test'}
        draft = {**self.draft, 'description': 'x' * 3000,
                 'instagram_video_url': 'https://cdn.example.com/video.mp4',
                 'platform_overrides': {'instagram': {'description': 'Short caption'}}}
        with patch.object(pub, 'instagram_publish', return_value={'remote_id': 'reel'}) as adapter:
            self.app.start('project', 'instagram', draft, True, self.signature)
            self.wait()
        self.assertEqual(adapter.call_args.args[3]['description'], 'Short caption')
        with self.assertRaisesRegex(ValueError, '2,200'):
            self.app.start('project', 'instagram',
                           {**draft, 'description': 'Short shared', 'platform_overrides': {'instagram': {'description': 'x' * 2201}}},
                           True, self.signature)

    def test_assisted_history_uses_platform_title(self):
        self.app.save_draft('project', {**self.draft, 'platform_overrides': {'tiktok': {'title': 'TikTok title'}}})
        self.app.mark('project', 'tiktok')
        self.assertEqual(self.app.snapshot('project')['history'][0]['title'], 'TikTok title')
        self.assertFalse(self.app.session.calls)

    def test_youtube_oauth_uses_state_pkce_and_exact_loopback_callback(self):
        result, state = self.authorize()
        query = parse_qs(urlparse(result['authorization_url']).query)
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertEqual(query['redirect_uri'], ['http://127.0.0.1:8765/api/publishing/callback/youtube'])
        self.app.session = Session(Response(payload={'access_token': 'NEW_ACCESS', 'refresh_token': 'NEW_REFRESH', 'expires_in': 3600}),
                                   Response(payload={'items': [{'id': 'my-channel', 'snippet': {'title': 'Selected channel'}}]}))
        self.app.finish_oauth('youtube', {'state': [state], 'code': ['secret-code']})
        self.assertEqual(self.app.snapshot('project')['accounts']['youtube']['name'], 'Selected channel')
        self.assertIn('code_verifier', self.app.session.calls[0][2]['data'])
        with self.assertRaises(ValueError): self.app.finish_oauth('youtube', {'state': state, 'code': 'secret-code'})

    def test_oauth_rejects_absent_expired_and_wrong_provider_state_without_network(self):
        with self.assertRaises(ValueError): self.app.finish_oauth('youtube', {'code': 'code'})
        result, state = self.authorize()
        self.app.pending[state]['expires'] = 0
        with self.assertRaises(ValueError): self.app.finish_oauth('youtube', {'state': state, 'code': 'code'})
        result, state = self.authorize()
        with self.assertRaises(ValueError): self.app.finish_oauth('instagram', {'state': state, 'code': 'code'})
        self.assertFalse(self.app.session.calls)

    def test_manual_oauth_redirect_must_match_registered_uri_and_state_is_consumed(self):
        result, state = self.authorize('instagram')
        self.assertTrue(result['manual_callback'])
        with self.assertRaisesRegex(ValueError, 'redirect URL'):
            self.app.finish_oauth('instagram', 'https://evil.example/callback?state=' + state + '&code=code')
        with self.assertRaises(ValueError):
            self.app.finish_oauth('instagram', result['redirect_uri'] + '?state=' + state + '&code=code')
        self.assertFalse(self.app.session.calls)

    def test_instagram_oauth_exchanges_token_and_identifies_professional_account(self):
        result, state = self.authorize('instagram')
        self.app.session = Session(Response(payload={'access_token': 'SHORT'}),
                                   Response(payload={'access_token': 'LONG', 'expires_in': 5184000}),
                                   Response(payload={'id': '111', 'user_id': '222', 'username': 'mycreator'}))
        self.app.finish_oauth('instagram', result['redirect_uri'] + '?state=' + state + '&code=code')
        self.assertEqual(self.app.snapshot('project')['accounts']['instagram']['name'], '@mycreator')
        self.assertEqual(self.app.vault['accounts']['instagram']['user_id'], '222')
        self.assertNotIn('LONG', json.dumps(self.app.snapshot('project')))

    def test_manual_instagram_token_connection_and_disconnect(self):
        self.app.session = Session(Response(payload={'id': '111', 'user_id': '222', 'username': 'mycreator'}))
        self.app.connect_token('instagram', 'PRIVATE_INSTAGRAM_TOKEN')
        self.assertTrue(self.app.snapshot('project')['accounts']['instagram']['connected'])
        self.assertNotIn('PRIVATE_INSTAGRAM_TOKEN', json.dumps(self.app.snapshot('project')))
        self.app.disconnect('instagram')
        self.assertFalse(self.app.snapshot('project')['accounts']['instagram']['connected'])

    def test_upload_requires_explicit_review_completed_video_and_matching_signature(self):
        for reviewed, signature in [(False, self.signature), ('true', self.signature), (True, 'stale')]:
            with self.assertRaises(ValueError): self.app.start('project', 'youtube', self.draft, reviewed, signature)
        self.video.unlink()
        with self.assertRaises(ValueError): self.app.start('project', 'youtube', self.draft, True, self.signature)
        self.assertIsNone(self.app.job)
        self.assertFalse(self.app.session.calls)

    def test_manual_destinations_cannot_trigger_an_automatic_upload(self):
        for platform in ('tiktok', 'facebook', 'other'):
            with self.assertRaises(ValueError): self.app.start('project', platform, self.draft, True, self.signature)
        self.assertFalse(self.app.session.calls)

    def test_instagram_requires_public_video_and_caption_limit_before_upload(self):
        self.app.vault['accounts']['instagram'] = {'access_token': 'IG', 'user_id': '123', 'name': '@user'}
        for url in ('', 'http://cdn.example.com/video.mp4', 'https://127.0.0.1/video.mp4', 'https://localhost/video.mp4', 'https://cdn.local/video.mp4'):
            with self.assertRaises(ValueError): self.app.start('project', 'instagram', {**self.draft, 'instagram_video_url': url}, True, self.signature)
        with self.assertRaisesRegex(ValueError, '2,200'):
            self.app.start('project', 'instagram', {**self.draft, 'description': 'a'*2201, 'instagram_video_url': 'https://cdn.example.com/video.mp4'}, True, self.signature)
        self.assertFalse(self.app.session.calls)

    def test_instagram_processing_failure_keeps_container_for_read_only_diagnosis(self):
        self.app.vault['accounts']['instagram'] = {'access_token': 'IG', 'user_id': '123', 'name': '@user'}
        self.app.session = Session(Response(payload={'id':'456'}), Response(payload={'status_code':'ERROR'}))
        self.app.start('project', 'instagram', {**self.draft, 'instagram_video_url':'https://cdn.example.com/video.mp4'}, True, self.signature)
        self.wait()
        self.assertEqual(self.app.job['status'], 'failed')
        self.assertEqual(self.app.job['container_id'], '456')
        restarted = pub.Publisher(self.root / 'data', lambda key:self.project, session=Session())
        entry = restarted.snapshot('project')['history'][0]
        self.assertEqual(entry['container_id'], '456')
        self.assertEqual(entry['processing_status'], 'ERROR')
        self.assertFalse(any(call[1].endswith('/media_publish') for call in self.app.session.calls))

    def failed_youtube(self, *, channel='my-channel', title=None, size=None, status='processed', processing='succeeded'):
        self.app.vault['accounts']['youtube']['user_id']='my-channel'
        with patch.object(pub,'youtube_upload',side_effect=ValueError('Upload status unknown')):
            self.app.start('project','youtube',self.draft,True,self.signature)
            self.wait()
        row={'id':'video123','snippet':{'title':self.draft['title'] if title is None else title,'channelId':channel},
             'status':{'uploadStatus':status},'processingDetails':{'processingStatus':processing},
             'fileDetails':{'fileSize':str(self.video.stat().st_size if size is None else size)}}
        self.app.session=Session(Response(payload={'items':[row]}))
        return self.app.job['id']

    def test_existing_processed_upload_is_verified_without_reupload_and_blocks_duplicate(self):
        job_id=self.failed_youtube()
        result=self.app.verify_youtube('project',job_id,'https://www.youtube.com/watch?v=video123')
        self.assertTrue(result['ok'])
        self.assertEqual(self.app.job['status'],'complete')
        self.assertEqual(self.app.snapshot('project')['history'][0]['remote_id'],'video123')
        self.assertEqual([call[0] for call in self.app.session.calls],['GET'])
        with self.assertRaisesRegex(ValueError,'already recorded'):
            self.app.start('project','youtube',self.draft,True,self.signature)

    def test_processing_video_does_not_prematurely_mark_upload_complete(self):
        job_id=self.failed_youtube(status='uploaded',processing='processing')
        result=self.app.verify_youtube('project',job_id,'https://youtu.be/video123')
        self.assertFalse(result['ok'])
        self.assertEqual(self.app.job['status'],'failed')
        self.assertEqual(self.app.snapshot('project')['history'][0]['status'],'failed')

    def test_existing_upload_must_match_channel_title_and_file_size(self):
        for wrong in ({'channel':'other-channel'},{'title':'Another video'},{'size':1234}):
            with self.subTest(wrong=wrong):
                job_id=self.failed_youtube(**wrong)
                with self.assertRaises(ValueError):
                    self.app.verify_youtube('project',job_id,'https://studio.youtube.com/video/video123/edit')
                self.assertEqual(self.app.job['status'],'failed')

    def test_existing_upload_rejects_untrusted_link_without_provider_request(self):
        job_id=self.failed_youtube()
        with self.assertRaisesRegex(ValueError,'existing video link'):
            self.app.verify_youtube('project',job_id,'https://www.youtube.com.evil.example/watch?v=video123')
        self.assertFalse(self.app.session.calls)

    def test_youtube_failed_processing_never_confirms_local_upload(self):
        job_id=self.failed_youtube(status='failed',processing='failed')
        with self.assertRaisesRegex(ValueError,'failed or was rejected'):
            self.app.verify_youtube('project',job_id,'https://youtu.be/video123')
        self.assertEqual(self.app.job['status'],'failed')

    def test_upload_job_completes_with_durable_history_and_blocks_duplicate(self):
        with patch.object(pub, 'youtube_upload', return_value={'remote_id': 'video123', 'url': 'https://www.youtube.com/watch?v=video123'}) as adapter:
            self.app.start('project', 'youtube', self.draft, True, self.signature)
            self.wait()
        snapshot = self.app.snapshot('project')
        self.assertEqual(snapshot['job']['status'], 'complete')
        self.assertEqual(snapshot['history'][0]['status'], 'complete')
        self.assertEqual(adapter.call_args.args[2], self.video.resolve())
        with self.assertRaisesRegex(ValueError, 'already recorded'):
            self.app.start('project', 'youtube', self.draft, True, self.signature)
        restarted = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        self.assertEqual(restarted.snapshot('project')['history'][0]['remote_id'], 'video123')

    def test_failed_upload_does_not_mark_as_published_or_leak_credentials(self):
        with patch.object(pub, 'youtube_upload', side_effect=ValueError('PRIVATE_ACCESS_TOKEN rejected https://provider.example/?token=bad')):
            self.app.start('project', 'youtube', self.draft, True, self.signature)
            self.wait()
        result = self.app.snapshot('project')
        self.assertEqual(result['history'][0]['status'], 'failed')
        self.assertNotIn('PRIVATE_ACCESS_TOKEN', result['job']['error'])
        self.assertNotIn('provider.example', result['job']['error'])
        self.assertFalse(result['job']['url'])

    def connect_multiple(self):
        self.app.vault['accounts']['facebook_page'] = {'access_token': 'PAGE_TOKEN', 'page_id': '123', 'name': 'My Page'}
        self.app.vault['accounts']['instagram'] = {'access_token': 'IG_TOKEN', 'user_id': '456', 'name': '@creator',
            'connection_type': 'facebook', 'page_id': '123'}
        self.draft['facebook_page_id'] = '123'

    def finish_all(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with self.app.lock:
                snapshot = self.app.snapshot('project')
                if not self.app.running and all(entry['status'] != 'running' for entry in snapshot['history']):
                    return snapshot
            time.sleep(.01)
        self.fail('Publishing workers did not finish')

    def test_three_platform_workers_start_together_and_keep_separate_progress(self):
        self.connect_multiple()
        started = {platform: threading.Event() for platform in pub.DIRECT}
        release = threading.Event()
        self.addCleanup(release.set)
        def adapter(platform, percent):
            def upload(session, account, path, draft, progress, **kwargs):
                progress(percent, 'Uploading ' + platform)
                started[platform].set()
                if not release.wait(3): raise ValueError('Test worker timed out')
                return {'remote_id': platform + '-video'}
            return upload
        with patch.object(pub, 'youtube_upload', side_effect=adapter('youtube', 10)), \
                patch.object(pub, 'instagram_local_publish', side_effect=adapter('instagram', 40)), \
                patch.object(pub, 'facebook_publish', side_effect=adapter('facebook_page', 70)):
            result = self.app.start_many('project', list(pub.DIRECT), self.draft, True, self.signature)
            try:
                self.assertEqual(len(result['jobs']), 3)
                self.assertTrue(all(event.wait(2) for event in started.values()))
                snapshot = self.app.snapshot('project')
                self.assertEqual({job['platform']: job['progress'] for job in snapshot['jobs']},
                                 {'youtube': 10, 'instagram': 40, 'facebook_page': 70})
                self.assertEqual(len(snapshot['history']), 3)
                self.assertTrue(self.app.running)
                self.assertEqual(self.app.active_job()['status'], 'running')
                with self.assertRaisesRegex(ValueError, 'already running'):
                    self.app.start('project', 'youtube', self.draft, True, self.signature)
                with self.assertRaises(ValueError): self.app.disconnect('instagram')
            finally: release.set()
            snapshot = self.finish_all()
        self.assertTrue(all(job['status'] == 'complete' for job in snapshot['jobs']))
        self.assertTrue(all(entry['status'] == 'complete' for entry in snapshot['history']))
        self.assertFalse(self.app.running)
        restarted = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        self.assertEqual(len(restarted.snapshot('project')['jobs']), 3)

    def test_can_start_another_platform_while_last_job_completes_and_failure_is_isolated(self):
        self.connect_multiple()
        started = threading.Event(); release = threading.Event(); self.addCleanup(release.set)
        def upload(session, account, path, draft, progress):
            started.set()
            if not release.wait(3): raise ValueError('Test worker timed out')
            return {'remote_id': 'youtube-video'}
        with patch.object(pub, 'youtube_upload', side_effect=upload), \
                patch.object(pub, 'facebook_publish', side_effect=ValueError('Page upload failed')):
            self.app.start('project', 'youtube', self.draft, True, self.signature)
            self.assertTrue(started.wait(2))
            self.app.start('project', 'facebook_page', self.draft, True, self.signature)
            self.wait()
            try:
                self.assertEqual(self.app.job['status'], 'failed')
                self.assertTrue(self.app.running)
                self.assertEqual(self.app.active_job()['platform'], 'youtube')
                with self.assertRaises(ValueError): self.app.save_draft('project', self.draft)
            finally: release.set()
            snapshot = self.finish_all()
        self.assertEqual({job['platform']: job['status'] for job in snapshot['jobs']},
                         {'youtube': 'complete', 'facebook_page': 'failed'})

    def test_batch_validation_is_atomic_and_requires_review(self):
        for platforms, reviewed in [([], True), (['youtube','youtube'], True), (['youtube','tiktok'], True),
                                     (['youtube','instagram'], True), (['youtube'], False), ('youtube', True)]:
            with self.subTest(platforms=platforms, reviewed=reviewed), patch.object(pub.threading, 'Thread') as worker:
                with self.assertRaises(ValueError):
                    self.app.start_many('project', platforms, self.draft, reviewed, self.signature)
                worker.assert_not_called()
                self.assertFalse(self.app.snapshot('project')['history'])
                self.assertIsNone(self.app.job)
        self.connect_multiple()
        invalid = {**self.draft, 'platform_overrides': {'instagram': {'description': 'a' * 2201}}}
        with patch.object(pub.threading, 'Thread') as worker:
            with self.assertRaisesRegex(ValueError, '2,200'):
                self.app.start_many('project', ['youtube', 'instagram'], invalid, True, self.signature)
            worker.assert_not_called()
        self.assertFalse(self.app.snapshot('project')['history'])

    def test_duplicate_is_blocked_until_completed_history_is_durable(self):
        with patch.object(pub.threading, 'Thread'):
            self.app.start('project', 'youtube', self.draft, True, self.signature)
        self.app.job['status'] = 'complete'
        with self.assertRaisesRegex(ValueError, 'already running'):
            self.app.start('project', 'youtube', self.draft, True, self.signature)
        self.assertEqual(len(self.app.snapshot('project')['history']), 1)

    def test_restart_interrupts_all_running_jobs_and_preserves_each_checkpoint(self):
        self.connect_multiple()
        self.app._vault_save()
        with patch.object(pub.threading, 'Thread'):
            self.app.start_many('project', list(pub.DIRECT), self.draft, True, self.signature)
        jobs = {job['platform']: job for job in self.app._jobs()}
        self.app._checkpoint(jobs['facebook_page'], remote_id='789', publish_attempted=True)
        self.app._instagram_checkpoint(jobs['instagram'], container_id='987', publish_attempted=True)
        jobs['youtube'].update(status='complete', progress=100)
        self.app._history_status(jobs['youtube']); self.app._persist_job()
        restarted = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        snapshot = restarted.snapshot('project')
        self.assertEqual({job['platform']: job['status'] for job in snapshot['jobs']},
                         {'youtube': 'complete', 'instagram': 'interrupted', 'facebook_page': 'interrupted'})
        self.assertTrue(all(row['status'] != 'running' for row in snapshot['history']))
        self.assertEqual(restarted._find_job(jobs['instagram']['id'])['container_id'], '987')
        self.assertEqual(restarted._find_job(jobs['facebook_page']['id'])['remote_id'], '789')
        self.assertFalse(restarted.running)
        with self.assertRaisesRegex(ValueError, 'may already have succeeded'):
            restarted.start('project', 'instagram', self.draft, True, self.signature)
        self.assertFalse(restarted.session.calls)

    def test_production_workers_use_separate_http_sessions(self):
        self.connect_multiple()
        self.app.session = requests.Session(); self.app.worker_sessions = True
        self.addCleanup(self.app.session.close)
        sessions = []
        def upload(session, account, path, draft, progress, **kwargs):
            sessions.append(session)
            return {'remote_id': 'video'}
        with patch.object(pub, 'youtube_upload', side_effect=upload), \
                patch.object(pub, 'instagram_local_publish', side_effect=upload), \
                patch.object(pub, 'facebook_publish', side_effect=upload):
            self.app.start_many('project', list(pub.DIRECT), self.draft, True, self.signature)
            self.finish_all()
        self.assertEqual(len({id(session) for session in sessions}), 3)
        self.assertTrue(all(session is not self.app.session for session in sessions))

    def test_unknown_running_job_blocks_account_mutations_and_new_uploads(self):
        self.app.job = {'status': 'running'}
        for operation in (lambda: self.app.start('project', 'youtube', self.draft, True, self.signature),
                          lambda: self.app.disconnect('youtube'), lambda: self.app.save_draft('project', self.draft)):
            with self.assertRaises(ValueError): operation()
        self.assertFalse(self.app.session.calls)

    def test_restart_marks_inflight_job_interrupted_in_history(self):
        job = {'id': 'job', 'project': 'project', 'status': 'running', 'platform': 'youtube', 'started': 0}
        self.app._save_record('project', {'history': [{'id': 'job', 'status': 'running'}]})
        write_json(self.app.data / 'job.json', job)
        restarted = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        self.assertEqual(restarted.snapshot('project')['job']['status'], 'interrupted')
        self.assertEqual(restarted.snapshot('project')['history'][0]['status'], 'interrupted')
        self.assertFalse(restarted.running)
        self.assertFalse(restarted.session.calls)

    def test_manual_history_requires_platform_post_link_and_does_not_publish(self):
        for url in ('javascript:alert(1)', 'https://evil.example/post', 'http://www.facebook.com/reel/1'):
            with self.assertRaises(ValueError): self.app.mark('project', 'facebook', url)
        self.app.mark('project', 'facebook', 'https://www.facebook.com/reel/1')
        self.app.mark('project', 'facebook', 'https://www.facebook.com/reel/2')
        history = self.app.snapshot('project')['history']
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['status'], 'manual')
        self.assertFalse(self.app.session.calls)


class ClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.video = Path(temporary.name) / 'final.mp4'; self.video.write_bytes(b'abcdefghij')
        self.account = {'access_token': 'PRIVATE_ACCESS_TOKEN', 'user_id': '123'}
        self.draft = {'title': 'Title', 'description': 'Caption', 'hashtags': '#gaming', 'youtube_privacy': 'private', 'made_for_kids': False,
                      'instagram_video_url': 'https://cdn.example.com/final.mp4', 'instagram_share_to_feed': True}
        self.location = 'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=opaque'
    def test_youtube_chunks_follow_server_acknowledgements_and_confirm_id(self):
        session = Session(Response(headers={'Location': self.location}), Response(308, headers={'Range': 'bytes=0-3'}),
                          Response(308, headers={'Range': 'bytes=0-7'}), Response(payload={'id': 'video123'}))
        with patch.object(clients, 'YOUTUBE_CHUNK_SIZE', 4):
            result = clients.youtube_upload(session, self.account, self.video, self.draft, None)
        self.assertEqual(result['remote_id'], 'video123')
        self.assertEqual([call[2]['data'] for call in session.calls[1:]], [b'abcd', b'efgh', b'ij'])
        self.assertEqual([call[2]['headers']['Content-Range'] for call in session.calls[1:]], ['bytes 0-3/10', 'bytes 4-7/10', 'bytes 8-9/10'])
        self.assertEqual(session.calls[0][2]['json']['status']['privacyStatus'], 'private')
        self.assertFalse(session.calls[0][2]['json']['status']['selfDeclaredMadeForKids'])

    def test_lost_chunk_response_queries_existing_session_before_continuing(self):
        session = Session(Response(headers={'Location': self.location}), requests.ConnectionError('lost'),
                          Response(308, headers={'Range': 'bytes=0-3'}), Response(payload={'id': 'video123'}))
        with patch.object(clients, 'YOUTUBE_CHUNK_SIZE', 6), patch.object(clients.time, 'sleep'):
            result = clients.youtube_upload(session, self.account, self.video, self.draft, None)
        self.assertEqual(result['remote_id'], 'video123')
        self.assertEqual(session.calls[2][2]['headers']['Content-Range'], 'bytes */10')
        self.assertEqual(session.calls[3][2]['data'], b'efghij')
        self.assertEqual(sum(call[0] == 'POST' for call in session.calls), 1)

    def test_status_query_retries_network_and_transient_server_failures(self):
        session = Session(Response(headers={'Location': self.location}), requests.ConnectionError('lost chunk'),
                          requests.ReadTimeout('secret-token-bearing-url'), Response(503, headers={'Retry-After':'2'}),
                          Response(308, headers={'Range':'bytes=0-3'}), Response(payload={'id':'video123'}))
        with patch.object(clients, 'YOUTUBE_CHUNK_SIZE', 6), patch.object(clients.time, 'sleep'):
            result = clients.youtube_upload(session, self.account, self.video, self.draft, None)
        self.assertEqual(result['remote_id'], 'video123')
        self.assertEqual([call[2]['headers']['Content-Range'] for call in session.calls[2:5]], ['bytes */10']*3)
        self.assertEqual(session.calls[5][2]['data'], b'efghij')
        self.assertEqual(sum(call[0]=='POST' for call in session.calls), 1)

    def test_lost_final_response_is_confirmed_without_resending_video(self):
        session = Session(Response(headers={'Location':self.location}), requests.ReadTimeout('lost final reply'),
                          requests.ConnectionError('status unavailable'), Response(payload={'id':'video123'}))
        with patch.object(clients.time,'sleep'):
            result = clients.youtube_upload(session, self.account, self.video, self.draft, None)
        self.assertEqual(result['remote_id'],'video123')
        self.assertEqual([call[2]['data'] for call in session.calls[1:]], [b'abcdefghij',b'',b''])
        self.assertEqual(sum(call[0]=='POST' for call in session.calls),1)

    def test_status_failure_is_bounded_and_preserves_safe_timeout_reason(self):
        session = Session(Response(headers={'Location':self.location}), requests.ConnectionError('lost'),
                          *[requests.ReadTimeout('PRIVATE_ACCESS_TOKEN https://secret.example/') for _ in range(5)])
        with patch.object(clients.time,'sleep'), self.assertRaisesRegex(ValueError,'after 5 checks') as error:
            clients.youtube_upload(session,self.account,self.video,self.draft,None)
        self.assertIn('timed out',str(error.exception))
        self.assertNotIn('PRIVATE_ACCESS_TOKEN',str(error.exception))
        self.assertNotIn('secret.example',str(error.exception))
        self.assertEqual(sum(call[0]=='POST' for call in session.calls),1)
        self.assertEqual(len(session.calls),7)

    def test_status_permanent_error_is_not_retried(self):
        session=Session(Response(headers={'Location':self.location}), requests.ConnectionError('lost'), Response(403))
        with patch.object(clients.time,'sleep'), self.assertRaisesRegex(ValueError,'HTTP 403'):
            clients.youtube_upload(session,self.account,self.video,self.draft,None)
        self.assertEqual(len(session.calls),3)

    def test_untrusted_youtube_upload_location_never_receives_a_token(self):
        for location in ('https://googleapis.com.evil.example/upload', 'http://www.googleapis.com/upload', 'https://evil.example/upload'):
            session = Session(Response(headers={'Location': location}))
            with self.assertRaisesRegex(ValueError, 'untrusted'):
                clients.youtube_upload(session, self.account, self.video, self.draft, None)
            self.assertEqual(len(session.calls), 1)

    def test_instagram_processes_then_publishes_and_fetches_permalink(self):
        session = Session(Response(payload={'id': '456'}), Response(payload={'status_code': 'IN_PROGRESS'}),
                          Response(payload={'status_code': 'FINISHED'}), Response(payload={'id': '789'}),
                          Response(payload={'permalink': 'https://www.instagram.com/reel/abc/'}))
        with patch.object(clients.time, 'sleep'):
            result = clients.instagram_publish(session, self.account, self.video, self.draft, None)
        self.assertEqual(result['remote_id'], '789')
        self.assertEqual(session.calls[0][2]['data']['share_to_feed'], 'true')
        self.assertEqual(session.calls[0][2]['data']['caption'], 'Caption\n\n#gaming')
        self.assertTrue(session.calls[3][1].endswith('/media_publish'))
        self.assertEqual(session.calls[3][2]['data'], {'creation_id': '456'})
        self.assertFalse(any('PRIVATE_ACCESS_TOKEN' in call[1] for call in session.calls))

    def test_instagram_processing_failure_never_calls_publish(self):
        session = Session(Response(payload={'id': '456'}), Response(payload={'status_code': 'ERROR'}))
        with self.assertRaises(ValueError): clients.instagram_publish(session, self.account, self.video, self.draft, None)
        self.assertFalse(any(call[1].endswith('/media_publish') for call in session.calls))

    def test_instagram_missing_permalink_still_counts_success_and_warns(self):
        session = Session(Response(payload={'id': '456'}), Response(payload={'status_code': 'FINISHED'}),
                          Response(payload={'id': '789'}), Response(403, {'error': {'message': 'PRIVATE_ACCESS_TOKEN'}}))
        result = clients.instagram_publish(session, self.account, self.video, self.draft, None)
        self.assertEqual(result['remote_id'], '789')
        self.assertTrue(result['warning'])
        self.assertFalse(result['url'])


class HttpTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.app = studio.Studio(root/'data', root/'projects')
        self.identifier = self.app.create('Publish HTTP', 'blank')
        path = self.app.project(self.identifier); (path/'output').mkdir()
        (path/'output/final.mp4').write_bytes(b'completed video')
        self.server = ThreadingHTTPServer(('127.0.0.1',0), studio.Handler); self.server.studio = self.app
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
    def request(self, route, data=None, token=True):
        headers = {'X-Studio-Token': self.app.token} if token else {}
        if data is not None:
            data = json.dumps(data).encode(); headers['Content-Type'] = 'application/json'
        with urllib.request.urlopen(urllib.request.Request(self.base+route, data=data, headers=headers)) as response:
            return json.load(response)
    def test_publishing_draft_round_trip_and_manual_history_via_http(self):
        snapshot = self.request('/api/publishing?id='+self.identifier)
        self.assertTrue(snapshot['video']['ready'])
        draft = {**snapshot['draft'], 'description': 'Saved caption'}
        self.request('/api/publishing/save', {'id':self.identifier,'draft':draft})
        self.request('/api/publishing/mark', {'id':self.identifier,'platform':'tiktok','url':'https://www.tiktok.com/@user/video/1'})
        loaded = self.request('/api/publishing?id='+self.identifier)
        self.assertEqual(loaded['draft']['description'], 'Saved caption')
        self.assertEqual(loaded['history'][0]['status'],'manual')
    def test_publishing_mutations_require_studio_token(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/publishing/disconnect', {'platform':'youtube'}, token=False)
        self.assertEqual(error.exception.code,403)
    def test_active_upload_blocks_project_changes_and_new_build(self):
        self.app.publisher.job = {'status':'running'}
        for route, data in [('/api/create',{'name':'another'}),('/api/start',{'id':self.identifier,'action':'build'})]:
            with self.assertRaises(urllib.error.HTTPError) as error: self.request(route,data)
            self.assertEqual(error.exception.code,400)
    def test_batch_endpoint_accepts_other_platforms_during_upload_but_blocks_project_changes(self):
        self.assertIn('parallel-publishing', self.request('/api/health')['features'])
        self.app.publisher.vault['accounts'].update({
            'youtube': {'access_token': 'YT', 'name': 'Channel'},
            'facebook_page': {'access_token': 'PAGE', 'page_id': '123', 'name': 'Page'}})
        snapshot = self.request('/api/publishing?id=' + self.identifier)
        draft = {**snapshot['draft'], 'facebook_page_id': '123'}
        payload = {'id': self.identifier, 'draft': draft, 'reviewed': True, 'video_signature': snapshot['video']['signature']}
        with patch.object(pub.Publisher, '_run'):
            self.request('/api/publishing/start', {**payload, 'platform': 'youtube'})
            result = self.request('/api/publishing/start-many', {**payload, 'platforms': ['facebook_page']})
        self.assertEqual(result['jobs'][0]['platform'], 'facebook_page')
        self.assertEqual(len(self.request('/api/publishing/job')['jobs']), 2)
        for route, body in [('/api/publishing/start-many', {**payload, 'platforms': ['youtube']}),
                            ('/api/create', {'name': 'Another project'}),
                            ('/api/start', {'id': self.identifier, 'action': 'build'})]:
            with self.assertRaises(urllib.error.HTTPError) as error: self.request(route, body)
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/publishing/start-many', {**payload, 'platforms': ['facebook_page']}, token=False)
        self.assertEqual(error.exception.code, 403)

    def test_render_job_blocks_batch_publishing(self):
        self.app.job = {'status': 'running'}
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/publishing/start-many', {'id': self.identifier, 'platforms': ['youtube'], 'draft': {}})
        self.assertEqual(error.exception.code, 400)

    def test_callback_without_state_is_rejected_without_connection(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/publishing/callback/youtube?code=not-real')
        self.assertFalse(self.app.publisher.snapshot(self.identifier)['accounts']['youtube']['connected'])


if __name__ == '__main__': unittest.main()
