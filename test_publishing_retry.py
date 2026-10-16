"""Retry/recovery checks use simulated Meta responses and never publish live posts."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import publishing as pub
from pipeline_common import write_json
from test_publishing import Response, Session

PAGE, USER, VIDEO, CONTAINER = '555', '123', '777', '888'
TOKEN = 'PRIVATE_RETRY_TOKEN'
COMPLETE = {'status': {'publishing_phase': {'status': 'complete'}}}
PENDING = {'status': {'publishing_phase': {'status': 'in_progress'}}}
FAILED = {'status': {'video_status': 'error'}}


class StreamingSession(Session):
    def request(self, method, url, **kwargs):
        if url.startswith('https://rupload.facebook.com/'):
            kwargs = {**kwargs, 'data': b''.join(kwargs['data'])}
        return super().request(method, url, **kwargs)


def facebook_start(video=VIDEO):
    return Response(payload={'video_id': video,
        'upload_url': 'https://rupload.facebook.com/video-upload/v26.0/' + video})


def facebook_success(video=VIDEO):
    return [facebook_start(video), Response(payload={'success': True}),
        Response(payload={'success': True}), Response(payload=COMPLETE),
        Response(payload={'permalink_url': 'https://www.facebook.com/reel/' + video})]


def owned(state=COMPLETE, owner=PAGE, video=VIDEO):
    return Response(payload={**state, 'id': video, 'from': {'id': owner}})


def instagram_start(container=CONTAINER):
    return Response(payload={'id': container, 'uri': 'https://rupload.facebook.com/ig-api-upload/v26.0/' + container})


def instagram_status(state, container=CONTAINER):
    return Response(payload={'id': container, 'status_code': state})


class RetryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        (self.project / 'output').mkdir(parents=True)
        self.video = self.project / 'output/final.mp4'
        self.video.write_bytes(b'reviewed video')
        write_json(self.project / 'studio.json', {'name': 'Reviewed title'})
        self.app = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        self.app.vault['accounts'] = {
            'facebook_page': {'access_token': TOKEN, 'page_id': PAGE, 'name': 'Fixture Page'},
            'instagram': {'connection_type': 'facebook', 'user_id': USER, 'page_id': PAGE, 'name': '@fixture'}}
        self.app._vault_save()
        snapshot = self.app.snapshot('project')
        self.draft = {**snapshot['draft'], 'facebook_page_id': PAGE}
        self.signature = snapshot['video']['signature']
        delay = patch.object(pub, 'META_RETRY_DELAY', 0)
        delay.start()
        self.addCleanup(delay.stop)

    def publish(self, session, platform='facebook_page'):
        self.app.session = session
        with patch.object(pub.threading, 'Thread'):
            self.app.start('project', platform, self.draft, True, self.signature)
        draft = self.app._platform_draft(self.app._draft('project', self.draft), platform)
        self.app._run(self.app.job, self.video, draft)
        return self.app.snapshot('project')

    def test_transfer_reset_restarts_once_then_publishes_only_new_upload(self):
        session = StreamingSession(facebook_start(), requests.ConnectionError(TOKEN), *facebook_success('778'))
        result = self.publish(session)
        self.assertEqual(result['job']['status'], 'complete')
        self.assertEqual(result['job']['retry_count'], 1)
        finish = [call for call in session.calls if isinstance(call[2].get('data'), dict)
                  and call[2]['data'].get('upload_phase') == 'finish']
        self.assertEqual(len(finish), 1)
        self.assertEqual(finish[0][2]['data']['video_id'], '778')
        self.assertEqual(len(result['history']), 1)
        self.assertEqual(result['history'][0]['retry_count'], 1)

    def test_persistent_transfer_failure_stops_at_three_and_survives_restart(self):
        responses = []
        for video in ('777', '778', '779'):
            responses.extend((facebook_start(video), requests.ConnectionError(TOKEN)))
        session = StreamingSession(*responses)
        result = self.publish(session)
        self.assertEqual(result['job']['status'], 'failed')
        self.assertEqual(result['job']['retry_count'], 2)
        self.assertFalse(result['job']['publish_attempted'])
        self.assertEqual(len(session.calls), 6)
        self.assertNotIn(TOKEN, json.dumps(result))
        restarted = pub.Publisher(self.root / 'data', lambda key: self.project, session=Session())
        self.assertEqual(restarted.snapshot('project')['history'][0]['retry_count'], 2)

    def test_auth_permission_and_tls_certificate_errors_are_not_retried(self):
        for error in (Response(status=401, payload={'error': {'code': 190, 'error_subcode': 463}}),
                      Response(status=403, payload={'error': {'code': 200}}),
                      requests.exceptions.SSLError('certificate verification failed')):
            with self.subTest(error=type(error).__name__):
                self.app.vault['accounts']['facebook_page'].pop('needs_reconnect', None)
                session = StreamingSession(facebook_start(), error)
                result = self.publish(session)
                self.assertEqual(result['job']['status'], 'failed')
                self.assertEqual(len(session.calls), 2)

    def test_changed_file_is_not_uploaded_automatically(self):
        video = self.video
        class ChangedFileSession(StreamingSession):
            def request(self, method, url, **kwargs):
                if url.startswith('https://rupload.facebook.com/'):
                    video.write_bytes(b'a different unreviewed video')
                return super().request(method, url, **kwargs)
        session = ChangedFileSession(facebook_start(), requests.ConnectionError(TOKEN))
        result = self.publish(session)
        self.assertEqual(len(session.calls), 2)
        self.assertIn('changed', result['job']['error'])

    def test_lost_finish_reply_is_confirmed_by_reads_without_second_publish(self):
        session = StreamingSession(facebook_start(), Response(payload={'success': True}),
            requests.Timeout(TOKEN), requests.ConnectionError(TOKEN), owned(PENDING), owned())
        result = self.publish(session)
        self.assertEqual(result['job']['status'], 'complete')
        self.assertTrue(result['job']['verified'])
        self.assertTrue(result['history'][0]['verified'])
        self.assertEqual([call[0] for call in session.calls], ['POST'] * 3 + ['GET'] * 3)
        self.assertEqual(result['job']['remote_id'], VIDEO)
        self.assertNotIn(TOKEN, json.dumps(result))

    def test_unconfirmed_publication_stays_blocked_after_status_retry_limit(self):
        session = StreamingSession(facebook_start(), Response(payload={'success': True}),
            requests.ConnectionError(TOKEN), *[requests.ConnectionError(TOKEN) for _ in range(3)])
        result = self.publish(session)
        self.assertEqual(result['job']['status'], 'failed')
        self.assertTrue(result['job']['publish_attempted'])
        self.assertEqual([call[0] for call in session.calls], ['POST'] * 3 + ['GET'] * 3)
        with self.assertRaisesRegex(ValueError, 'may already have succeeded'):
            self.app.start('project', 'facebook_page', self.draft, True, self.signature)

    def test_wrong_page_status_never_marks_success_or_allows_duplicate(self):
        session = StreamingSession(facebook_start(), Response(payload={'success': True}),
            requests.Timeout(TOKEN), owned(owner='556'))
        result = self.publish(session)
        self.assertEqual(result['job']['status'], 'failed')
        self.assertEqual(len(session.calls), 4)
        with self.assertRaisesRegex(ValueError, 'may already have succeeded'):
            self.app.start('project', 'facebook_page', self.draft, True, self.signature)

    def test_confirmed_remote_failure_allows_new_reviewed_attempt(self):
        result = self.publish(StreamingSession(facebook_start(), Response(payload={'success': True}),
            requests.Timeout(TOKEN), owned(FAILED)))
        self.assertTrue(result['history'][0]['confirmed_unpublished'])
        result = self.publish(StreamingSession(*facebook_success('778')))
        self.assertEqual(result['job']['status'], 'complete')

    def test_manual_status_check_retries_reads_and_never_publishes(self):
        result = self.publish(StreamingSession(facebook_start(), Response(payload={'success': True}),
            requests.Timeout(TOKEN), *[owned(PENDING) for _ in range(3)]))
        self.app.session = Session(requests.Timeout(TOKEN), requests.ConnectionError(TOKEN), owned())
        self.assertTrue(self.app.verify_facebook('project', result['job']['id'])['ok'])
        self.assertEqual([call[0] for call in self.app.session.calls], ['GET'] * 3)

    def test_instagram_transfer_retry_finishes_with_one_publish(self):
        session = StreamingSession(instagram_start(), requests.ConnectionError(TOKEN),
            instagram_start('889'), Response(payload={'success': True}), instagram_status('FINISHED', '889'),
            Response(payload={'id': '999'}), Response(payload={'id': '999', 'permalink': 'https://www.instagram.com/reel/fixture/'}))
        result = self.publish(session, 'instagram')
        self.assertEqual(result['job']['status'], 'complete')
        self.assertEqual(result['job']['retry_count'], 1)
        self.assertEqual(sum(call[1].endswith('/media_publish') for call in session.calls), 1)

    def test_lost_instagram_publish_reply_checks_original_container_only(self):
        session = StreamingSession(instagram_start(), Response(payload={'success': True}),
            instagram_status('FINISHED'), requests.Timeout(TOKEN), instagram_status('PUBLISHED'))
        result = self.publish(session, 'instagram')
        self.assertEqual(result['job']['status'], 'complete')
        self.assertTrue(result['job']['verified'])
        self.assertEqual(result['job']['container_id'], CONTAINER)
        self.assertEqual(result['job']['remote_id'], '')
        self.assertIn('profile', result['job']['warning'])
        self.assertEqual(sum(call[1].endswith('/media_publish') for call in session.calls), 1)
        self.assertEqual(session.calls[-1][0], 'GET')

    def test_lost_start_reply_retries_before_any_publication(self):
        session = StreamingSession(requests.ConnectionError(TOKEN), *facebook_success())
        result = self.publish(session)
        self.assertEqual(result['job']['status'], 'complete')
        self.assertEqual(result['job']['retry_count'], 1)
        self.assertEqual(sum(isinstance(call[2].get('data'), dict)
            and call[2]['data'].get('upload_phase') == 'finish' for call in session.calls), 1)

    def test_retry_backoff_waits_one_then_two_seconds(self):
        responses = [reply for _ in range(3) for reply in (facebook_start(), requests.Timeout(TOKEN))]
        with patch.object(pub, 'META_RETRY_DELAY', 1), patch.object(pub.time, 'sleep') as sleep:
            self.publish(StreamingSession(*responses))
        self.assertEqual([call.args for call in sleep.call_args_list], [(1,), (2,)])

    def test_expired_token_during_recovery_requires_reconnect_without_reposting(self):
        session = StreamingSession(facebook_start(), Response(payload={'success': True}),
            requests.Timeout(TOKEN), Response(status=401, payload={'error': {'code': 190, 'error_subcode': 463}}))
        result = self.publish(session)
        self.assertTrue(result['job']['reconnect_required'])
        self.assertTrue(result['job']['publish_attempted'])
        self.assertFalse(result['accounts']['facebook_page']['connected'])
        self.assertFalse(result['accounts']['instagram']['connected'])
        self.assertEqual([call[0] for call in session.calls], ['POST'] * 3 + ['GET'])

    def test_unconfirmed_instagram_publish_blocks_duplicate_and_status_check_retries(self):
        session = StreamingSession(instagram_start(), Response(payload={'success': True}),
            instagram_status('FINISHED'), requests.Timeout(TOKEN), *[instagram_status('FINISHED') for _ in range(3)])
        result = self.publish(session, 'instagram')
        self.assertEqual(result['job']['status'], 'failed')
        with self.assertRaisesRegex(ValueError, 'may already have succeeded'):
            self.app.start('project', 'instagram', self.draft, True, self.signature)
        self.app.session = Session(requests.Timeout(TOKEN), requests.ConnectionError(TOKEN), instagram_status('PUBLISHED'))
        self.assertTrue(self.app.verify_instagram('project', result['job']['id'])['ok'])
        self.assertEqual([call[0] for call in self.app.session.calls], ['GET'] * 3)


if __name__ == '__main__':
    unittest.main()
