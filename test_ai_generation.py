import copy
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch
import requests
from ai_generation import AIGenerator, validate_outline
from pipeline_common import read_cache, write_json, fingerprint
import video_studio as studio


def outline():
    return {'project_name':'Test games','script':'Try OpenTTD.','games':[{'exact_name':'OpenTTD','spoken_names':['OpenTTD']}]}


def brief(script='Try OpenTTD.'):
    return {'project_name':'Test games','script':script,'games':[{'exact_name':'OpenTTD','spoken_names':['OpenTTD'],
        'youtube_gameplay_url':'https://youtu.be/ESlyTiZwsDk','logo_image_url':None}]}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.session=MagicMock();self.ai=AIGenerator(Path(self.temp.name),self.session)

    def response(self,provider,value,**extra):
        if provider=='gemini': data={'status':'completed','steps':[{'type':'thought','text':'ignore'}, {'type':'model_output','content':[{'type':'text','text':json.dumps(value)}]}]}
        elif provider=='openai': data={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}]}
        else: data={'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(value)}]}
        data.update(extra);self.session.post.return_value=MagicMock(status_code=200,json=lambda:data)

    def test_all_provider_script_requests_use_schema_and_no_asset_search(self):
        for provider in ('gemini','openai','claude'):
            with self.subTest(provider=provider):
                self.ai.configure(provider,api_key='fixture-private-key');self.response(provider,outline())
                self.assertEqual(self.ai.script(provider,self.ai.account(provider),{'idea':'free games'}),outline())
                _,options=self.session.post.call_args
                self.assertNotIn('tools',options['json']);self.assertFalse(options['allow_redirects'])
                self.assertTrue(any(key in options['json'] for key in ('response_format','text','output_config')))
                self.assertNotIn('fixture-private-key',json.dumps(options['json']))

    def test_saved_keys_are_not_exposed_and_blank_preserves_existing_key(self):
        self.ai.configure('gemini',api_key='fixture-secret')
        self.ai.configure('gemini',model='gemini-3.8-flash',api_key='')
        self.assertNotIn('fixture-secret',json.dumps(self.ai.snapshot()))
        self.assertTrue(self.ai.snapshot()['providers']['gemini']['configured'])
        self.assertEqual(AIGenerator(self.ai.path.parents[1]).account('gemini')['api_key'],'fixture-secret')
        if studio.os.name=='nt': self.assertNotIn('fixture-secret',self.ai.path.read_text())

    def test_invalid_setup_is_rejected(self):
        for args in [('other','','key'),('gemini','https://evil.example/model','key'),('gemini','','key with spaces'),('gemini','','')]:
            with self.subTest(args=args),self.assertRaises(ValueError):self.ai.configure(*args)

    def test_provider_failure_does_not_echo_secret_or_provider_body(self):
        self.ai.configure('gemini',api_key='fixture-secret')
        for status in (400,401,403,429,500):
            self.session.post.return_value=MagicMock(status_code=status,json=lambda:{'error':'fixture-secret sensitive provider response'})
            with self.subTest(status=status),self.assertRaises(ValueError) as error:self.ai.script('gemini',self.ai.account('gemini'),{})
            self.assertIn(str(status),str(error.exception));self.assertNotIn('fixture-secret',str(error.exception))

    def test_transport_errors_do_not_leak_request_headers(self):
        self.ai.configure('gemini',api_key='fixture-secret')
        self.session.post.side_effect=requests.Timeout('fixture-secret')
        with self.assertRaisesRegex(ValueError,'timed out') as error:self.ai.script('gemini',self.ai.account('gemini'),{})
        self.assertNotIn('fixture-secret',str(error.exception))

    def test_incomplete_provider_response_is_not_used(self):
        for provider in ('gemini','openai','claude'):
            self.ai.configure(provider,api_key='fixture-key')
            self.response(provider,outline(),**({'status':'in_progress'} if provider!='claude' else {'stop_reason':'max_tokens'}))
            with self.assertRaisesRegex(ValueError,'did not finish'):self.ai.script(provider,self.ai.account(provider),{})

    def test_asset_brief_preserves_approved_script_and_uses_search(self):
        for provider in ('gemini','openai','claude'):
            self.ai.configure(provider,api_key='fixture-key');self.response(provider,brief('Reviewed OpenTTD script.'))
            value,parsed=self.ai.brief(provider,self.ai.account(provider),outline(),'Reviewed OpenTTD script.')
            self.assertEqual(parsed['editor']['script'],'Reviewed OpenTTD script.')
            self.assertIn('tools',self.session.post.call_args.kwargs['json'])
            self.response(provider,brief('Changed by AI.'))
            with self.assertRaisesRegex(ValueError,'changed the approved script'):self.ai.brief(provider,self.ai.account(provider),outline(),'Reviewed OpenTTD script.')

    def test_script_validation_rejects_missing_or_invalid_games(self):
        for change in ({'script':''},{'games':[]},{'games':[{'exact_name':'x','spoken_names':['']}]}):
            data=outline();data.update(change)
            with self.assertRaises(ValueError):validate_outline(data)

    def test_all_providers_receive_series_memory_and_platform_without_remote_chat_state(self):
        series={'platform':'mobile','instructions':'Explain touch controls.','reference_script':'Example structure.',
                'covered_games':['Mindustry'],'recent_episodes':[{'name':'First episode','idea':'Offline games','games':['Mindustry']}]}
        for provider in ('gemini','openai','claude'):
            with self.subTest(provider=provider):
                self.ai.configure(provider,api_key='fixture-key');self.response(provider,outline())
                self.ai.script(provider,self.ai.account(provider),{'idea':'Create one more episode','language':'English','series':series})
                body=self.session.post.call_args.kwargs['json']
                prompt=body['messages'][0]['content'] if provider=='claude' else body['input']
                self.assertIn(json.dumps(series),prompt)
                self.assertIn('avoid repeating games',prompt)
                self.assertNotIn('previous_response_id',body)
                self.response(provider,brief())
                self.ai.brief(provider,self.ai.account(provider),outline(),'Try OpenTTD.',series=series)
                body=self.session.post.call_args.kwargs['json']
                prompt=body['messages'][0]['content'] if provider=='claude' else body['input']
                self.assertIn('"game_platform": "mobile"',prompt)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.app=studio.Studio(self.root/'data',self.root/'projects')
        self.app.ai.configure('gemini',api_key='fixture-key')
        self.app.ai.script=MagicMock(return_value=outline())
        from ai_brief import parse_brief
        self.app.ai.brief=MagicMock(side_effect=lambda provider,account,selection,script,series=None:(brief(script),parse_brief(brief(script))))
        self.thread=patch('video_studio.threading.Thread').start();self.addCleanup(patch.stopall)
        self.process=MagicMock();self.process.stdout=[];self.process.wait.return_value=0
        self.spawn=patch('video_studio.subprocess.Popen',return_value=self.process).start()

    def script_project(self,series_id=''):
        result=self.app.create_ai('My video','gemini','Free PC games','Egyptian Arabic',series_id)
        job=self.app.job;self.app.run_ai(job,self.app.ai.account('gemini'))
        return result['project']['id']

    def prepare(self,identifier,script='Try OpenTTD.'):
        result=self.app.approve_ai(identifier,script,True);job=self.app.job
        self.app.run_ai(job,self.app.ai.account('gemini'))
        return job

    def test_script_is_saved_before_any_asset_request_or_download(self):
        identifier=self.script_project()
        project=self.app.load(identifier)
        self.assertEqual(project['editor']['script'],'Try OpenTTD.')
        self.assertEqual(project['ai_workflow']['status'],'awaiting_review')
        self.app.ai.brief.assert_not_called();self.spawn.assert_not_called()
        self.assertFalse((self.app.project(identifier)/'ai_brief.json').exists())
        self.assertEqual(self.app.ai.script.call_args.args[2],{'idea':'Free PC games','language':'Egyptian Arabic'})
        self.assertNotIn('duration',self.app.workflow(identifier))

    def test_approval_is_required_and_duplicate_approval_is_blocked(self):
        identifier=self.script_project()
        with self.assertRaisesRegex(ValueError,'approve'):self.app.approve_ai(identifier,'Try OpenTTD.',False)
        self.app.approve_ai(identifier,'Reviewed OpenTTD.',True)
        with self.assertRaises(ValueError):self.app.approve_ai(identifier,'Reviewed OpenTTD.',True)
        self.app.ai.brief.assert_not_called()

    def test_next_episode_inherits_only_the_selected_series_approved_script_and_games(self):
        pc=self.app.series.save('','PC games','pc','Hook, three games, closing.','Egyptian Arabic')['series'][-1]['id']
        mobile=self.app.series.save('','Mobile games','mobile','Explain touch controls.','English')['series'][-1]['id']
        identifier=self.script_project(pc)
        self.assertEqual(self.app.series.context(pc)['approved_episode_count'],0)
        self.prepare(identifier,'Reviewed PC episode.')
        self.assertEqual(self.app.ai.brief.call_args.kwargs['series']['platform'],'pc')
        second=self.script_project(mobile)
        context=self.app.ai.script.call_args.args[2]['series']
        self.assertEqual(context['instructions'],'Explain touch controls.')
        self.assertEqual(context['covered_games'],[])
        self.assertEqual(context['reference_script'],'')
        self.script_project(pc)
        context=self.app.ai.script.call_args.args[2]['series']
        self.assertEqual(context['reference_script'],'Reviewed PC episode.')
        self.assertEqual(context['covered_games'],['OpenTTD'])
        self.assertNotEqual(self.app.workflow(second)['series_id'],pc)

    def test_series_edits_apply_to_new_episodes_and_retries_keep_original_context(self):
        series=self.app.series.save('','PC games','pc','Original structure.','English')['series'][-1]['id']
        identifier=self.script_project(series)
        self.app.series.save(series,'PC games','pc','New structure.','English','New reference.')
        workflow=self.app.workflow(identifier);workflow['status']='interrupted'
        write_json(self.app.project(identifier)/'ai_workflow.json',workflow)
        self.app.retry_ai(identifier);self.app.run_ai(self.app.job,self.app.ai.account('gemini'))
        self.assertEqual(self.app.ai.script.call_args.args[2]['series']['instructions'],'Original structure.')
        self.script_project(series)
        self.assertEqual(self.app.ai.script.call_args.args[2]['series']['instructions'],'New structure.')

    def test_unknown_series_does_not_create_a_project(self):
        with self.assertRaisesRegex(ValueError,'Series not found'):
            self.app.create_ai('x','gemini','Another episode','English','unknown')
        self.assertEqual(self.app.registry,{})

    def test_standalone_episode_does_not_read_or_update_series_memory(self):
        series=self.app.series.save('','PC games','pc','Saved structure.','English')['series'][-1]['id']
        identifier=self.script_project(series);self.prepare(identifier,'Series reference script.')
        before=self.app.series.snapshot()
        standalone=self.script_project()
        self.assertNotIn('series',self.app.ai.script.call_args.args[2])
        self.assertNotIn('series_id',self.app.workflow(standalone))
        self.prepare(standalone,'Standalone script.')
        self.assertEqual(self.app.series.snapshot(),before)
        self.assertEqual(self.app.ai.brief.call_args.kwargs,{})

    def test_assets_prepare_without_voiceover_then_wait_for_recording(self):
        identifier=self.script_project();self.prepare(identifier,'Reviewed OpenTTD.')
        self.assertEqual(self.app.workflow(identifier)['status'],'assets_ready')
        self.assertEqual(self.app.load(identifier)['editor']['script'],'Reviewed OpenTTD.')
        self.assertEqual(self.spawn.call_count,1)
        self.assertIn('--without-voiceover',self.spawn.call_args.args[0])
        self.assertIn('prepare_assets.py',self.spawn.call_args.args[0][2])
        self.assertEqual(read_cache(self.app.project(identifier)/'ai_brief.json')['script'],'Reviewed OpenTTD.')
        self.assertTrue(read_cache(self.app.project(identifier)/'config.json')['brief_sources'])

    def test_recording_ready_before_assets_starts_one_auto_build_and_keeps_checkpoint(self):
        identifier=self.script_project();(self.app.project(identifier)/'voiceover.wav').write_bytes(b'fixture audio')
        self.prepare(identifier)
        self.assertEqual(self.app.job['action'],'build')
        self.assertEqual(self.app.workflow(identifier)['status'],'rendering')
        self.assertEqual(read_cache(self.app.data/'ai/job.json')['id'],self.app.job['id'])
        before=self.thread.call_count;self.app.maybe_auto_build(identifier)
        self.assertEqual(self.thread.call_count,before)
        self.app.run(self.app.job,self.app.project(identifier),read_cache(self.app.project(identifier)/'config.json'),0)
        self.assertEqual(self.app.workflow(identifier)['status'],'complete')

    def test_recording_added_after_assets_starts_auto_build_once(self):
        identifier=self.script_project();self.prepare(identifier)
        (self.app.project(identifier)/'voiceover.wav').write_bytes(b'fixture')
        self.app.maybe_auto_build(identifier);job=self.app.job
        self.assertEqual(job['action'],'build')
        self.app.maybe_auto_build(identifier);self.assertIs(self.app.job,job)

    def test_script_edit_clears_approval_and_prevents_automatic_build(self):
        identifier=self.script_project();self.prepare(identifier)
        editor=self.app.load(identifier)['editor'];editor['script']='New spoken script.'
        self.app.save(identifier,editor)
        (self.app.project(identifier)/'voiceover.wav').write_bytes(b'fixture')
        self.app.maybe_auto_build(identifier)
        self.assertEqual(self.app.job['action'],'ai_prepare')
        self.assertEqual(self.app.workflow(identifier)['status'],'awaiting_review')
        with self.assertRaisesRegex(ValueError,'Approve'):self.app.start(identifier,'build')

    def test_exported_brief_keeps_the_user_project_name(self):
        identifier=self.script_project();self.prepare(identifier)
        self.assertEqual(read_cache(self.app.project(identifier)/'ai_brief.json')['project_name'],'My video')

    def test_build_failure_records_the_project_step_for_retry(self):
        identifier=self.script_project();self.prepare(identifier)
        (self.app.project(identifier)/'voiceover.wav').write_bytes(b'fixture')
        self.app.maybe_auto_build(identifier);job=self.app.job
        self.process.wait.return_value=1
        self.app.run(job,self.app.project(identifier),read_cache(self.app.project(identifier)/'config.json'),0)
        self.assertEqual(self.app.workflow(identifier)['failed_step'],'build')
        self.assertEqual(self.app.workflow(identifier)['status'],'failed')

    def test_invalid_project_name_does_not_start_generation(self):
        with self.assertRaisesRegex(ValueError,'1 to 80'):self.app.create_ai('x'*81,'gemini','games','English')
        self.app.ai.script.assert_not_called();self.assertEqual(self.app.registry,{})

    def test_provider_failure_preserves_script_and_retry_requires_no_new_project(self):
        identifier=self.script_project();self.app.ai.brief.side_effect=ValueError('Gemini request failed (HTTP 429). Check quota.')
        self.prepare(identifier)
        self.assertEqual(self.app.workflow(identifier)['status'],'failed')
        self.assertEqual(self.app.load(identifier)['editor']['script'],'Try OpenTTD.')
        self.spawn.assert_not_called()
        self.app.retry_ai(identifier);self.assertEqual(len(self.app.registry),1)
        self.assertEqual(self.app.job['action'],'ai_prepare')

    def test_cancellation_prevents_asset_request_and_auto_build(self):
        identifier=self.script_project();self.app.approve_ai(identifier,'Try OpenTTD.',True)
        self.app.job['cancel']=True;job=self.app.job
        self.app.run_ai(job,self.app.ai.account('gemini'))
        self.assertEqual(self.app.workflow(identifier)['status'],'cancelled')
        self.app.ai.brief.assert_not_called();self.spawn.assert_not_called()

    def test_restart_marks_ai_job_interrupted_and_keeps_script(self):
        identifier=self.script_project();self.app.approve_ai(identifier,'Try OpenTTD.',True)
        restarted=studio.Studio(self.app.data,self.app.projects)
        self.assertEqual(restarted.job['status'],'interrupted')
        self.assertEqual(restarted.load(identifier)['editor']['script'],'Try OpenTTD.')
        self.assertEqual(restarted.workflow(identifier)['status'],'interrupted')

    def test_bad_request_or_missing_key_does_not_create_project(self):
        for idea,language in [('', 'English'), ('x'*10001, 'English'), ('x', ''), ('x', 'y'*101)]:
            with self.assertRaises(ValueError):self.app.create_ai('x','gemini',idea,language)
        self.assertEqual(self.app.registry,{})
        with self.assertRaisesRegex(ValueError,'API key'):self.app.create_ai('x','openai','x','English')
        self.assertEqual(self.app.registry,{})


class ImportedAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.app=studio.Studio(root/'data',root/'projects')
        self.app.ai.account=MagicMock(side_effect=AssertionError('Imported briefs must not need an API key'))
        self.thread=patch('video_studio.threading.Thread').start();self.addCleanup(patch.stopall)
        self.process=MagicMock();self.process.stdout=[];self.process.wait.return_value=0
        self.spawn=patch('video_studio.subprocess.Popen',return_value=self.process).start()
        self.identifier=self.app.import_brief(brief())['id']
        self.path=self.app.project(self.identifier)

    def prepare(self):
        result=self.app.prepare_imported_assets(self.identifier)
        self.app.run(self.app.job,self.path,read_cache(self.path/'config.json'),0)
        return result

    def test_import_exposes_prepare_without_starting_jobs_or_requiring_api_key(self):
        project=self.app.load(self.identifier)
        self.assertEqual(project['ai_workflow']['source'],'import')
        self.assertEqual(project['ai_workflow']['status'],'awaiting_assets')
        self.assertEqual(project['editor']['script'],brief()['script'])
        self.assertEqual(len(project['editor']['games']),1)
        self.assertIsNone(self.app.job);self.spawn.assert_not_called();self.app.ai.account.assert_not_called()

    def test_existing_import_without_workflow_can_prepare_before_first_video(self):
        (self.path/'ai_workflow.json').unlink()
        self.assertEqual(self.app.load(self.identifier)['ai_workflow']['status'],'awaiting_assets')
        self.prepare()
        self.assertEqual(self.app.workflow(self.identifier)['status'],'assets_ready')
        self.assertEqual(self.spawn.call_count,1)
        self.assertIn('--without-voiceover',self.spawn.call_args.args[0])
        self.assertIn('prepare_assets.py',self.spawn.call_args.args[0][2])
        self.app.ai.account.assert_not_called()

    def test_voiceover_ready_before_assets_finishes_starts_exactly_one_build(self):
        self.app.prepare_imported_assets(self.identifier);preparation=self.app.job
        (self.path/'voiceover.wav').write_bytes(b'fixture audio')
        self.app.maybe_auto_build(self.identifier)
        self.assertIs(self.app.job,preparation)
        self.app.run(preparation,self.path,read_cache(self.path/'config.json'),0)
        build=self.app.job
        self.assertEqual(build['action'],'build')
        self.app.maybe_auto_build(self.identifier);self.assertIs(self.app.job,build)
        self.assertEqual(self.app.workflow(self.identifier)['status'],'rendering')
        self.app.run(build,self.path,read_cache(self.path/'config.json'),0)
        self.assertEqual(self.app.workflow(self.identifier)['status'],'complete')
        self.assertIn('build_video.py',self.spawn.call_args.args[0][2])

    def test_voiceover_ready_after_assets_starts_exactly_one_build(self):
        self.prepare();self.assertEqual(self.app.workflow(self.identifier)['status'],'assets_ready')
        (self.path/'voiceover.mp3').write_bytes(b'fixture audio')
        self.app.maybe_auto_build(self.identifier);build=self.app.job
        self.assertEqual(build['action'],'build')
        self.app.maybe_auto_build(self.identifier);self.assertIs(self.app.job,build)

    def test_manual_build_still_works_without_separate_preparation(self):
        (self.path/'voiceover.wav').write_bytes(b'fixture audio')
        job=self.app.start(self.identifier,'build')
        self.app.run(self.app.job,self.path,read_cache(self.path/'config.json'),0)
        self.assertEqual(job['action'],'build')
        self.assertEqual(self.spawn.call_count,2)
        self.assertNotIn('--without-voiceover',self.spawn.call_args_list[0].args[0])
        self.assertEqual(self.app.workflow(self.identifier)['status'],'complete')

    def test_script_and_game_source_edits_require_fresh_preparation_for_auto_build(self):
        for change in ('script','game'):
            with self.subTest(change=change):
                self.prepare();editor=self.app.load(self.identifier)['editor']
                if change=='script':editor['script']='A changed OpenTTD script.'
                else:editor['games'][0]['url']='https://youtu.be/abcdefghijk'
                self.app.save(self.identifier,editor)
                (self.path/'voiceover.wav').write_bytes(b'fixture audio')
                self.app.maybe_auto_build(self.identifier)
                self.assertEqual(self.app.job['action'],'ai_prepare')
                self.assertEqual(self.app.workflow(self.identifier)['status'],'awaiting_assets')
                (self.path/'voiceover.wav').unlink()

    def test_failure_retry_uses_imported_sources_without_api_key(self):
        self.process.wait.return_value=1;self.prepare()
        self.assertEqual(self.app.workflow(self.identifier)['status'],'failed')
        self.app.retry_ai(self.identifier)
        self.assertEqual(self.app.job['action'],'ai_prepare')
        self.process.wait.return_value=0
        self.app.run(self.app.job,self.path,read_cache(self.path/'config.json'),0)
        self.assertEqual(self.app.workflow(self.identifier)['status'],'assets_ready')
        self.app.ai.account.assert_not_called()

    def test_duplicate_prepare_is_blocked_and_cancel_does_not_build(self):
        self.app.prepare_imported_assets(self.identifier);job=self.app.job
        with self.assertRaises(ValueError):self.app.prepare_imported_assets(self.identifier)
        job['cancel']=True;(self.path/'voiceover.wav').write_bytes(b'fixture audio')
        self.app.run(job,self.path,read_cache(self.path/'config.json'),0)
        self.assertEqual(self.app.workflow(self.identifier)['status'],'cancelled')
        self.spawn.assert_not_called();self.assertIs(self.app.job,job)

    def test_restart_keeps_imported_preparation_recoverable(self):
        self.app.prepare_imported_assets(self.identifier)
        restarted=studio.Studio(self.app.data,self.app.projects)
        self.assertEqual(restarted.workflow(self.identifier)['status'],'interrupted')
        restarted.retry_ai(self.identifier)
        self.assertEqual(restarted.job['action'],'ai_prepare')

    def test_non_imported_project_cannot_start_imported_preparation(self):
        identifier=self.app.create('Manual project','games')
        with self.assertRaisesRegex(ValueError,'Import an AI brief'):self.app.prepare_imported_assets(identifier)


class WorkflowHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.app=studio.Studio(root/'data',root/'projects')
        self.identifier=self.app.create('fixture')
        self.server=studio.StudioServer(('127.0.0.1',0),studio.Handler);self.server.studio=self.app
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    def post(self,path,value,token=True):
        headers={'Content-Type':'application/json'}
        if token:headers['X-Studio-Token']=self.app.token
        return urllib.request.urlopen(urllib.request.Request(self.url+path,data=json.dumps(value).encode(),headers=headers))

    def test_settings_create_approve_and_retry_require_csrf_token(self):
        for path in ('settings','series','create','approve','retry'):
            with self.subTest(path=path),self.assertRaises(urllib.error.HTTPError) as error:self.post('/api/ai/'+path,{},False)
            self.assertEqual(error.exception.code,403)

    def test_settings_do_not_return_api_key(self):
        with self.post('/api/ai/settings',{'provider':'gemini','api_key':'fixture-secret'}) as response:value=json.load(response)
        self.assertTrue(value['providers']['gemini']['configured']);self.assertNotIn('fixture-secret',json.dumps(value))
        with urllib.request.urlopen(self.url+'/api/ai/settings') as response:self.assertNotIn('fixture-secret',response.read().decode())

    def test_create_script_without_target_duration_and_retry_legacy_project(self):
        self.app.ai.configure('gemini',api_key='fixture-key')
        self.app.ai.script=MagicMock(return_value=outline())
        with patch.object(self.app,'run_ai'):
            with self.post('/api/ai/create',{'name':'My video','provider':'gemini','idea':'Free PC games','language':'English'}) as response:
                result=json.load(response)
        identifier=result['project']['id']
        workflow=self.app.workflow(identifier)
        self.assertNotIn('duration',workflow)
        workflow.update(status='interrupted',duration=60)
        write_json(self.app.project(identifier)/'ai_workflow.json',workflow)
        self.app.job['status']='interrupted'
        with patch.object(self.app,'run_ai'):
            self.app.retry_ai(identifier)
        self.app.run_ai(self.app.job,self.app.ai.account('gemini'))
        self.assertEqual(self.app.workflow(identifier)['status'],'awaiting_review')
        self.assertEqual(self.app.ai.script.call_args.args[2],{'idea':'Free PC games','language':'English'})

    def test_series_save_edit_list_and_select_use_saved_default_language(self):
        self.app.ai.configure('gemini',api_key='fixture-secret')
        with self.post('/api/ai/series',{'name':'Mobile games','platform':'mobile','instructions':'Explain touch controls.','language':'English'}) as response:
            saved=json.load(response)['series'][0]
        with self.post('/api/ai/series',{**saved,'instructions':'Explain offline play.'}) as response:
            value=json.load(response)
        self.assertEqual(len(value['series']),1)
        with urllib.request.urlopen(self.url+'/api/ai/series') as response:
            value=json.load(response)
        self.assertEqual(value['series'][0]['instructions'],'Explain offline play.')
        self.assertNotIn('fixture-secret',json.dumps(value))
        with patch.object(self.app,'run_ai'):
            with self.post('/api/ai/create',{'name':'Next episode','provider':'gemini','idea':'Create one more episode','series_id':saved['id']}) as response:
                result=json.load(response)
        workflow=result['project']['ai_workflow']
        self.assertEqual(workflow['language'],'English')
        self.assertEqual(workflow['series_context']['platform'],'mobile')

    def test_voiceover_upload_allowed_during_asset_preparation_only_for_that_project(self):
        other=self.app.create('other');self.app.job={'id':'prep','project':self.identifier,'action':'ai_prepare','status':'running'}
        request=urllib.request.Request(self.url+f'/api/upload?id={self.identifier}&name=recording.wav&role=voice',data=b'audio',headers={'X-Studio-Token':self.app.token})
        with urllib.request.urlopen(request) as response:self.assertEqual(json.load(response)['project']['voiceover'],'voiceover.wav')
        for identifier,role in ((other,'voice'),(self.identifier,'media')):
            request=urllib.request.Request(self.url+f'/api/upload?id={identifier}&name=clip.mp4&role={role}',data=b'file',headers={'X-Studio-Token':self.app.token})
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(request)

    def test_imported_prepare_route_and_voiceover_upload_start_build_without_provider(self):
        with self.post('/api/brief/import',{'brief':brief()}) as response:project=json.load(response)
        identifier=project['id']
        with self.assertRaises(urllib.error.HTTPError) as error:self.post('/api/brief/prepare',{'id':identifier},False)
        self.assertEqual(error.exception.code,403)
        with patch.object(self.app,'run'):
            with self.post('/api/brief/prepare',{'id':identifier}) as response:result=json.load(response)
        self.assertEqual(result['job']['action'],'ai_prepare')
        self.assertEqual(result['project']['ai_workflow']['status'],'preparing_assets')
        request=urllib.request.Request(self.url+f'/api/upload?id={identifier}&name=recording.wav&role=voice',data=b'audio',headers={'X-Studio-Token':self.app.token})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(json.load(response)['project']['voiceover'],'voiceover.wav')
        self.assertEqual(self.app.job['action'],'ai_prepare')
        process=MagicMock();process.stdout=[];process.wait.return_value=0
        with patch('video_studio.subprocess.Popen',return_value=process),patch.object(self.app,'run') as runner:
            # Complete the real preparation pipeline while mocking only the future render thread.
            studio.Studio.run(self.app,self.app.job,self.app.project(identifier),read_cache(self.app.project(identifier)/'config.json'),0)
        self.assertEqual(self.app.job['action'],'build')
        self.assertEqual(self.app.workflow(identifier)['status'],'rendering')
        self.assertNotIn('provider',self.app.workflow(identifier))

    def test_voiceover_does_not_modify_files_during_build(self):
        self.app.job={'id':'build','project':self.identifier,'action':'build','status':'running'}
        request=urllib.request.Request(self.url+f'/api/upload?id={self.identifier}&name=recording.wav&role=voice',data=b'audio',headers={'X-Studio-Token':self.app.token})
        with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(request)
        self.assertFalse((self.app.project(self.identifier)/'voiceover.wav').exists())


if __name__=='__main__':unittest.main()
