"""Instagram local upload checks using simulated Meta replies, never live posts."""
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests
import instagram_publishing as ig
import publishing as pub
import video_studio as studio
from pipeline_common import write_json
from test_publishing import Response, Session

PAGE = '555'
USER = '123'
CONTAINER = '456'
MEDIA = '789'
TOKEN = 'PRIVATE_FACEBOOK_PAGE_TOKEN'
URI = 'https://rupload.facebook.com/ig-api-upload/v26.0/' + CONTAINER
ACCOUNT = {'connection_type':'facebook', 'user_id':USER, 'name':'@creator', 'page_id':PAGE, 'api_version':'v26.0'}
CREATE = {'id':CONTAINER, 'uri':URI}
LINKED = {'id':PAGE, 'instagram_business_account':{'id':USER, 'username':'creator'}}
LIMIT = {'data':[{'quota_usage':0, 'config':{'quota_total':50}}]}


def status(value):
    return Response(payload={'id':CONTAINER, 'status_code':value})


class StreamingSession(Session):
    def request(self, method, url, **kwargs):
        if url == URI:
            kwargs = {**kwargs, 'data':b''.join(kwargs['data'])}
        return super().request(method, url, **kwargs)


def success(*statuses):
    return StreamingSession(Response(payload=CREATE), Response(payload={'success':True}),
        *[status(value) for value in statuses or ('FINISHED',)], Response(payload={'id':MEDIA}),
        Response(payload={'id':MEDIA, 'permalink':'https://www.instagram.com/reel/fixture/'}))


class TransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.video = Path(temporary.name) / 'final.mp4'; self.video.write_bytes(b'video bytes')
        self.account = {**ACCOUNT, 'access_token':TOKEN}
        self.draft = {'description':'Caption', 'hashtags':'#gaming', 'instagram_share_to_feed':True}

    def publish(self, session, checkpoint=None):
        with patch.object(ig.time, 'sleep'):
            return ig.instagram_local_publish(session, self.account, self.video, self.draft, None, checkpoint)

    def test_local_video_uploads_without_url_and_publishes_only_after_ready(self):
        session = success('IN_PROGRESS', 'FINISHED'); checkpoints = []
        result = self.publish(session, lambda **fields:checkpoints.append(fields))
        self.assertEqual(result['remote_id'], MEDIA)
        self.assertEqual(result['url'], 'https://www.instagram.com/reel/fixture/')
        self.assertEqual(session.calls[0][2]['data'], {'media_type':'REELS', 'upload_type':'resumable',
            'caption':'Caption\n\n#gaming', 'share_to_feed':'true'})
        self.assertEqual(session.calls[1][2]['data'], self.video.read_bytes())
        self.assertEqual(session.calls[1][2]['headers']['Authorization'], 'OAuth ' + TOKEN)
        self.assertEqual(session.calls[1][2]['headers']['file_size'], str(self.video.stat().st_size))
        self.assertEqual([call[0] for call in session.calls], ['POST','POST','GET','GET','POST','GET'])
        self.assertEqual(checkpoints, [{'container_id':CONTAINER, 'publish_attempted':False},
            {'container_id':CONTAINER, 'publish_attempted':True}])
        self.assertTrue(all(call[2]['allow_redirects'] is False for call in session.calls))
        self.assertFalse(any(TOKEN in call[1] for call in session.calls))

    def test_untrusted_upload_uris_never_receive_token_or_video(self):
        for uri in ('https://untrusted.invalid/ig-api-upload/v26.0/' + CONTAINER,
                'http://rupload.facebook.com/ig-api-upload/v26.0/' + CONTAINER,
                URI + '?next=bad', URI + '#fragment', URI.replace(CONTAINER, '999'),
                URI.replace('rupload.facebook.com','user@rupload.facebook.com')):
            with self.subTest(uri=uri):
                session = Session(Response(payload={'id':CONTAINER, 'uri':uri}))
                with self.assertRaises(ig.InstagramPublishError) as caught: self.publish(session)
                self.assertEqual(caught.exception.container_id, CONTAINER)
                self.assertFalse(caught.exception.publish_attempted)
                self.assertEqual(len(session.calls), 1)
        self.assertEqual(ig._upload_uri('https://rupload.facebook.com/ig-api-upload/' + CONTAINER, CONTAINER),
            'https://rupload.facebook.com/ig-api-upload/' + CONTAINER)

    def test_binary_failure_keeps_container_and_never_publishes(self):
        for response in (Response(payload={'success':False}), requests.Timeout(TOKEN)):
            session = StreamingSession(Response(payload=CREATE), response)
            with self.assertRaises(ig.InstagramPublishError) as caught: self.publish(session)
            self.assertEqual(caught.exception.container_id, CONTAINER)
            self.assertFalse(caught.exception.publish_attempted)
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertEqual(len(session.calls), 2)

    def test_processing_errors_and_already_published_containers_never_publish(self):
        for value in ('ERROR','EXPIRED','PUBLISHED'):
            with self.subTest(status=value):
                session = StreamingSession(Response(payload=CREATE), Response(payload={'success':True}), status(value))
                with self.assertRaises(ig.InstagramPublishError) as caught: self.publish(session)
                self.assertEqual(caught.exception.processing_status, value)
                self.assertFalse(caught.exception.publish_attempted)
                self.assertEqual(len(session.calls), 3)

    def test_lost_publish_reply_keeps_checkpoint_and_sends_one_publish(self):
        session = StreamingSession(Response(payload=CREATE), Response(payload={'success':True}),
            status('FINISHED'), requests.ConnectionError(TOKEN))
        checkpoints = []
        with self.assertRaises(ig.InstagramPublishError) as caught:
            self.publish(session, lambda **fields:checkpoints.append(fields))
        self.assertTrue(caught.exception.publish_attempted)
        self.assertTrue(checkpoints[-1]['publish_attempted'])
        self.assertIn('Check existing upload', str(caught.exception))
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertEqual(sum(call[1].endswith('/media_publish') for call in session.calls), 1)

    def test_unexpected_status_and_foreign_container_do_not_leak_or_publish(self):
        for payload in ({'id':CONTAINER, 'status_code':TOKEN}, {'id':'999','status_code':'FINISHED'}):
            session = StreamingSession(Response(payload=CREATE), Response(payload={'success':True}), Response(payload=payload))
            with self.assertRaises(ig.InstagramPublishError) as caught: self.publish(session)
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertEqual(len(session.calls), 3)

    def test_processing_timeout_does_not_publish(self):
        session = StreamingSession(Response(payload=CREATE), Response(payload={'success':True}), status('IN_PROGRESS'))
        with patch.object(ig, 'INSTAGRAM_POLL_TIMEOUT', 1), patch.object(ig.time, 'monotonic', side_effect=[0,.1,2,2]):
            with self.assertRaisesRegex(ig.InstagramPublishError, 'No publish'): self.publish(session)
        self.assertEqual(len(session.calls), 3)

    def test_permalink_failure_preserves_confirmed_success(self):
        session = StreamingSession(Response(payload=CREATE), Response(payload={'success':True}), status('FINISHED'),
            Response(payload={'id':MEDIA}), requests.Timeout(TOKEN))
        result = self.publish(session)
        self.assertEqual(result['remote_id'], MEDIA)
        self.assertTrue(result['warning'])
        self.assertFalse(result['url'])
        self.assertEqual(sum(call[1].endswith('/media_publish') for call in session.calls), 1)

    @unittest.skipUnless(os.name == 'nt', 'Windows curl transport')
    def test_windows_curl_upload_uses_instagram_labels_and_publishes_once(self):
        from types import SimpleNamespace
        import facebook_publishing as fb
        progress = []
        with requests.Session() as session:
            with (patch.object(session,'request',side_effect=[Response(payload=CREATE),status('FINISHED'),
                    Response(payload={'id':MEDIA}),Response(payload={'id':MEDIA,'permalink':'https://www.instagram.com/reel/fixture/'})]) as graph,
                    patch.object(fb.shutil,'which',return_value='curl.exe'),
                    patch.object(fb.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'{"success":true}\n200',stderr=b'')) as run):
                result=ig.instagram_local_publish(session,self.account,self.video,self.draft,lambda value,stage:progress.append(stage))
        self.assertEqual(result['remote_id'],MEDIA)
        self.assertEqual(run.call_count,1)
        self.assertEqual(sum(call.args[1].endswith('/media_publish') for call in graph.call_args_list),1)
        self.assertIn(URI,run.call_args.kwargs['input'].decode())
        self.assertTrue(all('Facebook Page' not in stage for stage in progress))

    def test_legacy_credentials_or_missing_file_fail_before_network(self):
        session = Session(); self.account.pop('connection_type')
        with self.assertRaises(ValueError): self.publish(session)
        self.account['connection_type'] = 'facebook'; self.video.unlink()
        with self.assertRaises(ValueError): self.publish(session)
        self.assertFalse(session.calls)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        delay = patch.object(pub, 'META_RETRY_DELAY', 0); delay.start(); self.addCleanup(delay.stop)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.project = self.root / 'project'
        (self.project / 'output').mkdir(parents=True); (self.project / 'output/final.mp4').write_bytes(b'video bytes')
        write_json(self.project / 'studio.json', {'name':'Fixture'})
        self.app = pub.Publisher(self.root / 'data', lambda key:self.project, session=Session())
        self.app.vault['accounts']['facebook_page'] = {'access_token':TOKEN, 'page_id':PAGE, 'name':'Fixture Page'}
        self.app.vault['accounts']['instagram'] = {'access_token':'PRIVATE_LEGACY_TOKEN', 'user_id':USER, 'name':'@legacy'}
        self.app._vault_save()
        snapshot = self.app.snapshot('project'); self.draft = snapshot['draft']; self.signature = snapshot['video']['signature']

    def connect(self):
        self.app.session = Session(Response(payload=LINKED), Response(payload=LIMIT))
        self.app.connect_instagram_page()

    def wait(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            snapshot = self.app.snapshot('project'); job = snapshot['job']
            entry = next(row for row in snapshot['history'] if row['id'] == job['id'])
            if job['status'] != 'running' and entry['status'] == job['status']: return
            time.sleep(.01)
        self.fail('Worker did not persist its result')

    def start(self):
        self.app.start('project','instagram',self.draft,True,self.signature); self.wait()

    def ambiguous(self):
        self.connect()
        self.app.session = StreamingSession(Response(payload=CREATE), Response(payload={'success':True}),
            status('FINISHED'), requests.ConnectionError(TOKEN),
            *[requests.ConnectionError('status unavailable') for _ in range(pub.META_RECOVERY_CHECKS)])
        self.start()
        return self.app.job['id']

    def test_connection_is_read_only_uses_page_reference_and_survives_restart(self):
        self.connect()
        self.assertEqual([call[0] for call in self.app.session.calls], ['GET','GET'])
        self.assertNotIn('access_token', self.app.vault['accounts']['instagram'])
        restarted = pub.Publisher(self.root / 'data', lambda key:self.project, session=Session())
        snapshot = restarted.snapshot('project')
        self.assertEqual(snapshot['accounts']['instagram']['upload_mode'],'local')
        self.assertTrue(snapshot['accounts']['instagram']['connected'])
        self.assertEqual(snapshot['accounts']['instagram']['name'],'@creator')
        self.assertNotIn(TOKEN,json.dumps(snapshot))
        self.app.vault['accounts']['facebook_page']['access_token'] = 'ROTATED_PAGE_TOKEN'
        self.assertEqual(self.app._access_account('instagram')['access_token'],'ROTATED_PAGE_TOKEN')
        self.app.vault['accounts']['facebook_page']['page_id'] = '556'
        self.assertFalse(self.app.snapshot('project')['accounts']['instagram']['connected'])
        with self.assertRaises(ValueError): self.app._access_account('instagram')

    def test_missing_link_permission_error_or_invalid_page_preserves_old_connection(self):
        for responses in ((Response(payload={'id':PAGE}),),
                (Response(payload={'id':'556','instagram_business_account':LINKED['instagram_business_account']}),),
                (Response(payload=LINKED), Response(status=400,payload={'error':{'code':200,'message':'Need instagram_content_publish ' + TOKEN}}))):
            with self.subTest(responses=responses):
                self.app.session = Session(*responses)
                with self.assertRaises(ValueError) as caught: self.app.connect_instagram_page()
                self.assertNotIn(TOKEN,str(caught.exception))
                self.assertEqual(self.app.vault['accounts']['instagram']['name'],'@legacy')
                self.assertTrue(all(call[0]=='GET' for call in self.app.session.calls))

    def test_expired_page_during_connection_preserves_valid_legacy_instagram(self):
        self.app.session=Session(Response(status=401,payload={'error':{'code':190,'error_subcode':463,'message':TOKEN}}))
        with self.assertRaises(ValueError) as caught: self.app.connect_instagram_page()
        self.assertTrue(self.app.vault['accounts']['facebook_page']['needs_reconnect'])
        self.assertEqual(self.app.vault['accounts']['instagram']['name'],'@legacy')
        self.assertTrue(self.app.snapshot('project')['accounts']['instagram']['connected'])
        self.assertNotIn(TOKEN,str(caught.exception))
        self.assertEqual([call[0] for call in self.app.session.calls],['GET'])

    def test_invalid_publishing_eligibility_does_not_replace_connection(self):
        for payload in ({'data':[]},{'data':[{}]},{'data':[{'quota_usage':True}]},{'data':'invalid'}):
            self.app.session=Session(Response(payload=LINKED),Response(payload=payload))
            with self.assertRaises(ValueError): self.app.connect_instagram_page()
            self.assertEqual(self.app.vault['accounts']['instagram']['name'],'@legacy')

    def test_local_start_needs_review_signature_and_caption_limit_but_no_url(self):
        self.connect(); self.app.session = Session()
        for reviewed, signature in ((False,self.signature),(True,'changed')):
            with self.assertRaises(ValueError): self.app.start('project','instagram',self.draft,reviewed,signature)
        with self.assertRaisesRegex(ValueError,'2,200'):
            self.app.start('project','instagram',{**self.draft,'description':'x'*2201},True,self.signature)
        self.assertFalse(self.app.session.calls)
        self.app.session = success(); self.start()
        self.assertEqual(self.app.job['status'],'complete')
        self.assertEqual(self.app.job['destination_name'],'@creator')
        self.assertEqual(self.app.job['destination_id'],USER)
        with self.assertRaisesRegex(ValueError,'already recorded'): self.start()

    def test_expired_page_token_never_uses_instagram_login_refresh(self):
        self.connect()
        self.app.vault['accounts']['facebook_page']['expires_at'] = 1
        self.app.session = Session()
        with self.assertRaisesRegex(ValueError,'expired'): self.app._access_account('instagram')
        self.assertFalse(self.app.session.calls)

    def test_ambiguous_publish_survives_restart_and_blocks_duplicate(self):
        self.ambiguous()
        restarted = pub.Publisher(self.root / 'data', lambda key:self.project, session=Session())
        entry = restarted.snapshot('project')['history'][0]
        self.assertEqual(entry['container_id'],CONTAINER)
        self.assertTrue(entry['publish_attempted'])
        with self.assertRaisesRegex(ValueError,'may already have succeeded'):
            restarted.start('project','instagram',self.draft,True,self.signature)
        self.assertFalse(restarted.session.calls)

    def test_published_container_is_verified_without_new_publish(self):
        job_id = self.ambiguous(); self.app.session = Session(status('PUBLISHED'))
        self.app.verify_instagram('project',job_id)
        self.assertEqual([call[0] for call in self.app.session.calls],['GET'])
        self.assertEqual(self.app.snapshot('project')['history'][0]['status'],'complete')
        self.assertEqual(self.app.job['status'],'complete')
        with self.assertRaisesRegex(ValueError,'already recorded'): self.start()

    def test_ready_container_remains_unconfirmed_and_error_allows_reviewed_retry(self):
        job_id = self.ambiguous(); self.app.session = Session(status('FINISHED'))
        self.app.verify_instagram('project',job_id)
        with self.assertRaisesRegex(ValueError,'may already have succeeded'): self.start()
        self.app.session = Session(status('ERROR')); self.app.verify_instagram('project',job_id)
        self.assertTrue(self.app.snapshot('project')['history'][0]['confirmed_unpublished'])
        self.app.session = success(); self.start()
        self.assertEqual(self.app.job['status'],'complete')

    def test_checking_old_upload_with_other_instagram_account_makes_no_request(self):
        job_id = self.ambiguous(); self.app.vault['accounts']['instagram']['user_id'] = '124'
        self.app.session = Session()
        with self.assertRaises(ValueError): self.app.verify_instagram('project',job_id)
        self.assertFalse(self.app.session.calls)

    def test_auth_error_invalidates_shared_page_and_details_are_redacted(self):
        self.connect()
        self.app.session = Session(Response(status=401,payload={'error':{'code':190,'error_subcode':463,'message':TOKEN}}))
        self.start(); snapshot = self.app.snapshot('project')
        self.assertFalse(snapshot['accounts']['facebook_page']['connected'])
        self.assertFalse(snapshot['accounts']['instagram']['connected'])
        self.assertTrue(snapshot['job']['reconnect_required'])
        self.assertNotIn(TOKEN,json.dumps(snapshot))


class HttpTests(unittest.TestCase):
    def test_connection_and_recovery_routes_require_csrf_and_make_only_gets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); app = studio.Studio(root/'data',root/'projects')
            app.publisher.vault['accounts']['facebook_page'] = {'access_token':TOKEN,'page_id':PAGE,'name':'Fixture Page'}
            server = ThreadingHTTPServer(('127.0.0.1',0),studio.Handler); server.studio = app
            thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            url = f'http://127.0.0.1:{server.server_port}'
            def request(route, authenticated):
                headers = {'Content-Type':'application/json'}
                if authenticated: headers['X-Studio-Token'] = app.token
                with urllib.request.urlopen(urllib.request.Request(url+route,data=b'{}',headers=headers)) as response:
                    return json.load(response)
            try:
                for route in ('/api/publishing/instagram-page','/api/publishing/verify-instagram'):
                    with self.assertRaises(urllib.error.HTTPError) as caught: request(route,False)
                    self.assertEqual(caught.exception.code,403)
                app.publisher.session = Session(Response(payload=LINKED),Response(payload=LIMIT))
                self.assertTrue(request('/api/publishing/instagram-page',True)['ok'])
                self.assertEqual([call[0] for call in app.publisher.session.calls],['GET','GET'])
            finally:
                server.shutdown(); server.server_close(); thread.join(3)


if __name__ == '__main__': unittest.main()
