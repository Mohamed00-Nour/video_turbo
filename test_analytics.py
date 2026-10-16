"""Analytics tests use temporary storage and read-only simulated provider GETs."""
import copy
import json
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
import analytics as stats
import video_studio as studio


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
    def json(self): return self.payload


class Session:
    def __init__(self, handler, calls): self.handler, self.calls = handler, calls
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.handler(url, kwargs['params'])


class Publisher:
    def __init__(self):
        self.lock = threading.RLock()
        self.records = {'project': {'history': []}}
        self.accounts = {
            'youtube': {'access_token': 'PRIVATE_YT', 'channel_id': 'channel'},
            'instagram': {'access_token': 'PRIVATE_META', 'user_id': '222', 'connection_type': 'facebook'},
            'facebook_page': {'access_token': 'PRIVATE_META', 'page_id': '333'}}
    def _record(self, identifier): return self.records[identifier]
    def _access_account(self, platform):
        result = self.accounts[platform]
        if isinstance(result, Exception): raise result
        return copy.deepcopy(result)


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.publisher = Publisher()
        self.now, self.calls = [1800000000], []
        self.handler = self.success
        self.app = stats.Analytics(self.root, self.publisher, lambda: [{'id': 'project', 'name': 'Example'}],
            session_factory=lambda: Session(self.handler, self.calls), clock=lambda: self.now[0])
        self.addCleanup(self.app.close)
    def post(self, platform='youtube', remote='video_1', version='render1', **extra):
        entry = {'id': 'entry'+str(len(self.publisher.records['project']['history'])), 'platform': platform,
                 'status': 'complete', 'remote_id': remote, 'video_signature': version, 'title': 'Example video',
                 'created': self.now[0]-86400, 'destination_id': {'youtube': '', 'instagram': '222', 'facebook_page': '333'}[platform],
                 'destination_name': 'My account', **extra}
        self.publisher.records['project']['history'].append(entry)
        return entry
    def success(self, url, params):
        if 'googleapis' in url:
            return Response({'items': [{'id': key, 'statistics': {'viewCount': '123'}} for key in params['id'].split(',')]})
        if '/insights' in url:
            return Response({'data': [{'name': 'views', 'values': [{'value': 45}]}]})
        return Response({'id': url.rsplit('/', 1)[-1], 'from': {'id': '333'}, 'views': 0})
    def rows(self): return self.app.snapshot()['videos'][0]['posts']
    def wait(self):
        deadline = time.monotonic()+3
        while self.app.job['status'] == 'running' and time.monotonic() < deadline: time.sleep(.01)
        self.assertNotEqual(self.app.job['status'], 'running')
    def test_three_platforms_use_only_gets_and_preserve_zero(self):
        self.post(); self.post('instagram', '777'); self.post('facebook_page', '888')
        self.app._run()
        rows = self.rows()
        self.assertEqual([row['views'] for row in rows], [123, 45, 0])
        self.assertEqual(self.app.job['successful'], 3)
        self.assertTrue(all(row['status'] == 'ready' for row in rows))
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(all(call[1]['headers']['Authorization'].startswith('Bearer ') for call in self.calls))
        self.assertNotIn('PRIVATE_', json.dumps(self.app.snapshot()))
        self.assertNotIn('PRIVATE_', self.app.path.read_bytes().decode('latin1'))
    def test_catalog_deduplicates_uploads_and_separates_render_versions(self):
        self.post(); self.post(); self.post(remote='another', version='render2')
        self.post(remote='failed', status='failed'); self.post('instagram', '999', status='running')
        self.post('instagram', '', status='manual')
        self.assertEqual(len(self.app.catalog()), 3)
        self.assertEqual(len(self.app.snapshot()['videos']), 2)
        self.app._run()
        rows = [post for video in self.app.snapshot()['videos'] for post in video['posts']]
        self.assertEqual(next(row for row in rows if not row['remote_id'])['status'], 'unavailable')
        self.assertEqual(self.app.job['completed'], 3)
    def test_youtube_batches_fifty_ids(self):
        for index in range(101): self.post(remote='video_'+str(index))
        self.app._run()
        self.assertEqual([len(call[1]['params']['id'].split(',')) for call in self.calls], [50,50,1])
        self.assertEqual(self.app.job['successful'], 101)
    def test_saved_counts_survive_failed_refresh_and_restart(self):
        self.post(); self.app._run(); self.now[0] += 900
        self.handler = lambda *args: Response({'error': {'code': 190, 'message': 'PRIVATE_META'}}, 401)
        self.app._run()
        row = self.rows()[0]
        self.assertEqual((row['views'], row['status']), (123, 'reconnect'))
        self.assertEqual(row['updated'], self.now[0]-900)
        self.assertEqual(len(self.app.history(row['video'])['series'][0]['points']), 1)
        restarted = stats.Analytics(self.root, self.publisher, self.app.project_list, clock=lambda: self.now[0])
        self.assertEqual(restarted.snapshot()['videos'][0]['posts'][0]['views'], 123)
        self.assertNotIn('PRIVATE_', json.dumps(restarted.snapshot()))
    def test_provider_errors_have_actionable_safe_statuses(self):
        cases = [(401, {}, 'reconnect'), (400, {'error': {'code':190}}, 'reconnect'),
                 (403, {'error': {'errors':[{'reason':'insufficientPermissions'}]}}, 'permission'),
                 (429, {}, 'rate_limited'), (403, {'error': {'errors':[{'reason':'quotaExceeded'}]}}, 'rate_limited'),
                 (500, {'error': {'message': 'PRIVATE_TOKEN', 'errors': None}}, 'unavailable'),
                 (200, [], 'unavailable')]
        for status, payload, expected in cases:
            with self.subTest(status=status, expected=expected):
                session=Session(lambda *args: Response(payload,status), [])
                with self.assertRaises(stats.AnalyticsError) as error:
                    stats.get_json(session, 'https://graph.facebook.com/id', 'PRIVATE_TOKEN', {}, 'instagram')
                self.assertEqual(error.exception.status, expected)
                self.assertNotIn('PRIVATE_', str(error.exception))
    def test_network_failure_retains_count_without_leaking_exception(self):
        self.post(); self.app._run(); self.now[0] += 900
        def broken(*args): raise requests.ConnectionError('PRIVATE_TOKEN')
        self.handler = broken; self.app._run()
        self.assertEqual(self.rows()[0]['views'],123)
        self.assertEqual(self.rows()[0]['status'],'unavailable')
        self.assertNotIn('PRIVATE_',json.dumps(self.app.snapshot()))
    def test_instagram_login_supports_total_value_insights(self):
        self.post('instagram','777')
        self.publisher.accounts['instagram']['connection_type']='instagram'
        self.handler=lambda *args: Response({'data':[{'name':'views','total_value':{'value':92}}]})
        self.app._run()
        self.assertEqual(self.rows()[0]['views'],92)
        self.assertIn('graph.instagram.com',self.calls[0][0])
    def test_facebook_rejects_other_page_ownership(self):
        self.post('facebook_page','888')
        self.handler=lambda *args: Response({'id':'888','from':{'id':'other'},'views':234})
        self.app._run()
        self.assertIsNone(self.rows()[0]['views'])
        self.assertEqual(self.rows()[0]['status'],'unavailable')
    def test_old_destination_requires_original_account_without_provider_call(self):
        self.post('instagram','777',destination_id='other')
        self.app._run()
        self.assertEqual(self.rows()[0]['status'],'reconnect')
        self.assertFalse(self.calls)
    def test_malformed_payload_does_not_fabricate_zero(self):
        for platform,payload in [('youtube',{'items':[{'id':'777','statistics':None}]}),
                                 ('instagram',{'data':None}), ('facebook_page',{'id':'777','from':None,'views':9})]:
            with self.subTest(platform=platform):
                self.publisher.records['project']['history']=[]
                self.post(platform,'777')
                self.handler=lambda *args: Response(payload)
                self.app._run()
                self.assertIsNone(self.rows()[0]['views'])
                self.assertEqual(self.rows()[0]['status'],'unavailable')
                self.assertEqual(self.app.job['completed'],1)
    def test_invalid_counts_and_unsafe_ids_never_become_data(self):
        for value in [None,True,-1,'1.5','nan',9007199254740992]:
            with self.subTest(value=value), self.assertRaises(stats.AnalyticsError): stats.count(value)
        self.post(remote='../../other')
        self.app._run()
        self.assertFalse(self.calls)
        self.assertIsNone(self.rows()[0]['views'])
    def test_platform_reads_run_concurrently(self):
        self.post();self.post('instagram','777');self.post('facebook_page','888')
        barrier=threading.Barrier(3)
        def together(url,params):
            barrier.wait(timeout=2)
            return self.success(url,params)
        self.handler=together;self.app._run()
        self.assertEqual(self.app.job['successful'],3)
    def test_one_failed_platform_does_not_block_other_counts(self):
        self.post();self.post('instagram','777');self.post('facebook_page','888')
        self.publisher.accounts['instagram']=ValueError('PRIVATE_TOKEN')
        self.app._run()
        self.assertEqual([row['status'] for row in self.rows()],['ready','reconnect','ready'])
    def test_unexpected_failure_keeps_already_completed_batches(self):
        for index in range(51): self.post(remote='video_'+str(index))
        def second_fails(url,params):
            if params['id']=='video_50': raise RuntimeError('PRIVATE_TOKEN')
            return self.success(url,params)
        self.handler=second_fails;self.app._run()
        self.assertEqual(self.app.job['completed'],51)
        self.assertEqual(self.app.job['successful'],50)
        self.assertEqual(sum(row['status']=='ready' for row in self.rows()),50)
    def test_refresh_runs_once_and_cooldown_survives_restart(self):
        self.post();gate=threading.Event()
        self.addCleanup(gate.set)
        original=self.app._run
        def wait_then_run(): gate.wait(timeout=2);original()
        with patch.object(self.app,'_run',wait_then_run):
            self.assertTrue(self.app.refresh()['started'])
            self.assertFalse(self.app.refresh()['started'])
            gate.set();self.wait()
        self.assertFalse(self.app.refresh()['started'])
        restarted=stats.Analytics(self.root,self.publisher,self.app.project_list,clock=lambda:self.now[0])
        self.assertFalse(restarted.refresh()['started'])
        self.now[0]+=61
        self.assertTrue(self.app.refresh()['started']);self.wait()
    def test_history_has_baseline_real_growth_and_bounded_points(self):
        self.post();post=self.app.catalog()[0]
        finish=self.now[0]
        for index,age in enumerate([31,8,6,2,0]):
            self.now[0]=finish-age*86400
            self.app._save(post,{'status':'ready','views':10+index*20,'metric':'viewCount'})
        self.now[0]=finish
        history=self.app.history(post['video'],7)['series'][0]
        self.assertEqual([point['views'] for point in history['points']],[30,50,70,90])
        self.assertEqual(history['change'],60)
        self.assertEqual(self.app.history(post['video'],30)['series'][0]['change'],80)
        for index in range(600):
            self.now[0]=finish+index*900
            self.app._save(post,{'status':'ready','views':index,'metric':'viewCount'})
        history=self.app.history(post['video'],7)['series'][0]
        self.assertLessEqual(len(history['points']),240)
        self.assertEqual(history['points'][-1]['views'],599)
        self.app._save(post,{'status':'ready','views':1000,'metric':'changed'})
        self.assertEqual(len(self.app.history(post['video'])['series'][0]['points']),1)
    def test_history_rejects_unknown_video_and_unsupported_range(self):
        self.post()
        with self.assertRaises(ValueError): self.app.history('unknown')
        with self.assertRaises(ValueError): self.app.history(self.app.catalog()[0]['video'],1)
    def test_auto_refresh_stops_with_studio(self):
        called=threading.Event()
        with patch.object(self.app,'refresh',side_effect=lambda:called.set()):
            self.app.start_auto();self.assertTrue(called.wait(1))
            self.app.close();self.app.scheduler.join(timeout=1)
        self.assertFalse(self.app.scheduler.is_alive())


class AnalyticsHttpTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        self.app=studio.Studio(root/'data',root/'projects');self.addCleanup(self.app.analytics.close)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),studio.Handler);self.server.studio=self.app
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def request(self,path,data=None,token=True,origin=None):
        headers={'X-Studio-Token':self.app.token} if token else {}
        if origin:headers['Origin']=origin
        if data is not None:
            headers['Content-Type']='application/json';data=json.dumps(data).encode()
        with urllib.request.urlopen(urllib.request.Request(self.base+path,data=data,headers=headers)) as response:
            return json.load(response)
    def test_refresh_requires_token_and_same_origin(self):
        for kwargs in [{'token':False},{'origin':'https://example.com'}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(urllib.error.HTTPError) as error:
                self.request('/api/analytics/refresh',{},**kwargs)
            self.assertEqual(error.exception.code,403)
    def test_analytics_read_and_refresh_available_during_build_and_upload(self):
        self.app.job={'status':'running'};self.app.publisher.job={'status':'running'}
        self.assertIn('analytics',self.request('/api/health')['features'])
        self.assertEqual(self.request('/api/analytics')['videos'],[])
        with patch.object(self.app.analytics,'refresh',return_value={'started':True}) as refresh:
            self.assertTrue(self.request('/api/analytics/refresh',{})['started'])
            refresh.assert_called_once()
    def test_history_invalid_query_is_a_controlled_error(self):
        for query in ['', '?video=missing&days=7','?video=missing&days=word']:
            with self.subTest(query=query),self.assertRaises(urllib.error.HTTPError) as error:
                self.request('/api/analytics/history'+query)
            self.assertEqual(error.exception.code,400)


if __name__=='__main__':unittest.main()
