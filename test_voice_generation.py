"""Voice generation contracts and integration with all Studio creation workflows."""
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import MagicMock, patch
import requests
import voice_generation as voice
import video_studio as studio
from pipeline_common import write_json, read_cache, fingerprint

KEY = 'fixture-elevenlabs-private-key'
CHOICE = {'source':'elevenlabs','voice_id':'my-clone','model_id':'eleven_multilingual_v2','stability':.5,'similarity_boost':.75,'speed':1.0}
SCRIPT = '\u0623\u0647\u0644\u0627 \u0628\u064a\u0643\u0645! Exact English, too.'

def models():
    return [{'model_id':'eleven_multilingual_v2','name':'Multilingual v2','can_do_text_to_speech':True,'maximum_text_length_per_request':10000},
            {'model_id':'eleven_v3','name':'Expressive v3','can_do_text_to_speech':True,'maximum_text_length_per_request':5000},
            {'model_id':'eleven_v4','name':'Expressive v4','can_do_text_to_speech':True,'maximum_text_length_per_request':10000},
            {'model_id':'eleven_v4_turbo','name':'Realtime','can_do_text_to_speech':True},
            {'model_id':'scribe','name':'Transcription','can_do_text_to_speech':False}]

def catalog():
    return {'voices':[{'id':'my-clone','name':'My cloned voice','category':'cloned','fine_tuning':{}},
                      {'id':'pro-clone','name':'My professional voice','category':'professional','fine_tuning':{'eleven_v3':'queued'}}],
            'models':[{'id':m['model_id'],'name':m['name'],'limit':m['maximum_text_length_per_request'], 'serves_pro_voices':True}
                      for m in models() if m.get('maximum_text_length_per_request')]}

class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.project=self.root/'project';self.project.mkdir()
        (self.project/'script.txt').write_text(SCRIPT,encoding='utf-8')
        write_json(self.project/'voiceover.json',CHOICE)
        self.session=MagicMock();self.api=voice.ElevenLabs(self.root/'data',self.session)
        self.api.configure(KEY,CHOICE)

    def response(self,status=200,data=None,audio=None):
        result=MagicMock(status_code=status,headers={'Content-Type':'audio/mpeg'})
        result.json.return_value=data
        result.iter_content.return_value=[audio] if audio is not None else [b'fixture-audio']
        self.session.request.return_value=result
        return result

    def test_key_is_protected_and_never_in_snapshot_or_project(self):
        snapshot=self.api.snapshot();self.assertTrue(snapshot['configured'])
        self.assertNotIn(KEY,json.dumps(snapshot))
        self.assertNotIn(KEY,self.api.path.read_text())
        self.assertNotIn(KEY,(self.project/'voiceover.json').read_text())
        self.assertEqual(voice.ElevenLabs(self.root/'data').snapshot(),snapshot)
        self.api.configure(defaults={**CHOICE,'speed':1.1})
        self.assertEqual(self.api.settings['api_key'],KEY)

    def test_bad_options_and_key_are_rejected(self):
        for extra in [{'speed':float('nan')},{'speed':True},{'speed':1.3},{'stability':-1},{'voice_id':'../bad'},{'source':'other'}]:
            with self.assertRaises(ValueError):voice.options({**CHOICE,**extra})
        with self.assertRaises(ValueError):self.api.configure('has a space')

    def test_catalog_paginates_deduplicates_and_returns_only_narration_models(self):
        first={'voices':[{'voice_id':'default','name':'Default','category':'premade'}],'has_more':True,'next_page_token':'next'}
        second={'voices':[{'voice_id':'my-clone','name':'My clone','category':'cloned'}, {'voice_id':'default','name':'Default'}],'has_more':False}
        self.session.request.side_effect=[MagicMock(status_code=200,json=lambda:first),MagicMock(status_code=200,json=lambda:second),MagicMock(status_code=200,json=models)]
        result=self.api.catalog(True)
        self.assertEqual([v['id'] for v in result['voices']],['my-clone','default'])
        self.assertEqual([m['id'] for m in result['models']],['eleven_multilingual_v2','eleven_v3','eleven_v4'])
        self.assertEqual(result['models'][2]['limit'],10000)
        self.assertEqual(self.session.request.call_args_list[1].kwargs['params']['next_page_token'],'next')
        self.assertEqual(self.api.catalog(),result);self.assertEqual(self.session.request.call_count,3)
        self.api.configure('another-fixture-key');self.assertFalse(self.api.catalog_path.exists())

    def test_broken_pagination_does_not_publish_partial_catalog(self):
        self.response(data={'voices':[],'has_more':True,'next_page_token':None})
        with self.assertRaisesRegex(ValueError,'pagination'):self.api.catalog(True)
        self.assertFalse(self.api.catalog_path.exists())

    def test_model_limit_and_unready_professional_clone_block_paid_request(self):
        with patch.object(self.api,'catalog',return_value=catalog()):
            for choice,text in [({**CHOICE,'voice_id':'missing'},SCRIPT),({**CHOICE,'model_id':'missing'},SCRIPT),
                                (CHOICE,'x'*10001),({**CHOICE,'voice_id':'pro-clone','model_id':'eleven_v3'},SCRIPT)]:
                with self.assertRaises(ValueError):self.api.selection(choice,text)
        self.session.request.assert_not_called()

    def test_exact_script_generation_cache_regeneration_and_changed_script(self):
        self.response()
        with patch.object(self.api,'catalog',return_value=catalog()),patch.object(voice,'probe_audio',return_value=3.2):
            generated=self.api.generate(self.project)
            args=self.session.request.call_args
            self.assertEqual(args.args[:2],('POST',voice.API+'/v1/text-to-speech/my-clone'))
            self.assertEqual(args.kwargs['json']['text'],SCRIPT)
            self.assertEqual(args.kwargs['params']['output_format'],'mp3_44100_128')
            self.assertFalse(args.kwargs['allow_redirects'])
            self.assertEqual(self.api.generate(self.project),generated)
            self.assertEqual(self.session.request.call_count,1)
            self.api.generate(self.project,force=True);self.assertEqual(self.session.request.call_count,2)
            (self.project/'script.txt').write_text(SCRIPT+' More.',encoding='utf-8')
            self.assertTrue(voice.project_state(self.project)['stale'])
            self.api.generate(self.project);self.assertEqual(self.session.request.call_count,3)
        self.assertFalse(voice.project_state(self.project)['stale'])
        self.assertEqual(len(list((self.project/'voiceover-history').glob('previous-*.mp3'))),2)

    def test_v4_uses_speech_api_without_unsupported_speed(self):
        write_json(self.project/'voiceover.json',{**CHOICE,'model_id':'eleven_v4'})
        self.response()
        with patch.object(self.api,'catalog',return_value=catalog()),patch.object(voice,'probe_audio',return_value=1): self.api.generate(self.project)
        args=self.session.request.call_args
        self.assertEqual(args.args[1],voice.API+'/v1/text-to-speech/my-clone')
        self.assertEqual(args.kwargs['json'],{'model_id':'eleven_v4','text':SCRIPT,'voice_settings':{'stability':.5,'similarity_boost':.75}})

    def test_failed_or_invalid_audio_preserves_existing_voiceover_and_metadata(self):
        target=self.project/'voiceover.mp3';target.write_bytes(b'original')
        for bad in ('http','empty','decode','interrupted'):
            with self.subTest(bad=bad):
                self.response(status=401 if bad=='http' else 200,audio=b'' if bad=='empty' else b'audio')
                if bad=='interrupted':self.session.request.return_value.iter_content.side_effect=requests.ConnectionError(KEY)
                with patch.object(self.api,'catalog',return_value=catalog()),patch.object(voice,'probe_audio',side_effect=ValueError('Unplayable audio')):
                    with self.assertRaises(ValueError) as error:self.api.generate(self.project)
                self.assertNotIn(KEY,str(error.exception));self.assertEqual(target.read_bytes(),b'original')
                self.assertNotIn('generated',read_cache(self.project/'voiceover.json'))
                self.assertFalse(list((self.project/'voiceover-history').glob('pending-*')) if (self.project/'voiceover-history').exists() else [])

    def test_transport_failure_has_no_secret_in_error_and_no_automatic_retry(self):
        self.session.request.side_effect=requests.ConnectionError(KEY)
        with self.assertRaises(ValueError) as error:self.api.request('GET','/v1/models')
        self.assertNotIn(KEY,str(error.exception));self.assertEqual(self.session.request.call_count,1)

    def test_real_audio_probe_accepts_mp3_and_rejects_invalid_payload(self):
        good=self.project/'sample.mp3'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.3','-y',str(good)],check=True,capture_output=True)
        self.assertGreater(voice.probe_audio(good),.2)
        good.write_bytes(b'not audio')
        with self.assertRaisesRegex(ValueError,'playable audio'):voice.probe_audio(good)


class StudioVoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.app=studio.Studio(root/'data',root/'projects')
        self.app.voice.configure(KEY,CHOICE)
        self.identifier=self.app.create('Voice check');self.path=self.app.project(self.identifier)
        editor=self.app.load(self.identifier)['editor'];editor['script']=SCRIPT
        self.app.save(self.identifier,editor);self.app.save_voice(self.identifier,CHOICE)

    def fake_process(self,command,**kwargs):
        process=MagicMock();process.stdout=iter(['[VOICE] Generating fixture audio\n'] if 'voice_generation.py' in command[2] else [])
        process.wait.return_value=0;process.poll.return_value=0
        return process

    def run_job(self,job):
        self.app.job=job
        with patch.object(studio.subprocess,'Popen',side_effect=self.fake_process) as calls:
            self.app.run(job,self.path,read_cache(self.path/'config.json'),0)
        return [Path(call.args[0][2]).name for call in calls.call_args_list]

    def test_shared_voice_only_job_preserves_existing_final_and_workflow_state(self):
        (self.path/'output').mkdir();(self.path/'output/final.mp4').write_bytes(b'old final')
        write_json(self.path/'ai_workflow.json',{'source':'import','status':'awaiting_assets','auto_build':True})
        with patch.object(studio.threading,'Thread'):
            job=self.app.start_voice(self.identifier)['job']
        self.assertEqual(self.run_job(job),['voice_generation.py'])
        self.assertEqual(self.app.workflow(self.identifier)['status'],'awaiting_assets')
        self.assertEqual((self.path/'output/final.mp4').read_bytes(),b'old final')
        self.assertEqual(read_cache(self.app.data/'ai/job.json')['status'],'complete')

    def test_manual_build_routes_through_voice_before_render_when_no_recording(self):
        with patch.object(studio.threading,'Thread'):
            job=self.app.start(self.identifier,'build')
        self.assertEqual(self.run_job(job),['voice_generation.py','build_video.py'])
        self.assertEqual(job['status'],'complete')

    def test_imported_brief_generates_voice_then_prepares_assets_and_builds(self):
        brief={'project_name':'Import','script':SCRIPT,'games':[{'exact_name':'OpenTTD','spoken_names':['OpenTTD'],'youtube_gameplay_url':'https://youtu.be/ESlyTiZwsDk','logo_image_url':None}]}
        project=self.app.import_brief(brief);self.identifier=project['id'];self.path=self.app.project(self.identifier)
        self.app.save_voice(self.identifier,CHOICE)
        with patch.object(studio.threading,'Thread'):job=self.app.start_voice(self.identifier,build=True)['job']
        self.assertEqual(self.run_job(job),['voice_generation.py','prepare_assets.py','build_video.py'])
        self.assertEqual(self.app.workflow(self.identifier)['status'],'complete')

    def test_ai_and_series_scripts_need_approval_before_spending_voice_credits(self):
        for series in ('','pc-games'):
            write_json(self.path/'ai_workflow.json',{'provider':'gemini','status':'awaiting_review','series_id':series,'outline':{'script':SCRIPT}})
            with patch.object(studio.threading,'Thread') as thread:
                with self.assertRaisesRegex(ValueError,'approve'):self.app.start_voice(self.identifier)
                thread.assert_not_called()

    def test_reference_without_recorded_voice_generates_before_analysis_and_render(self):
        (self.path/'reference').mkdir();(self.path/'reference/source.mp4').write_bytes(b'reference')
        write_json(self.path/'reference_style.json',{'status':'awaiting_inputs','analysis_provider':'codex','reference_file':'reference/source.mp4'})
        connections={'provider':'codex','providers':{'codex':{'installed':True}}}
        with patch.object(studio.threading,'Thread'),patch.object(studio.reference_styles,'settings',return_value=connections):
            job=self.app.start_reference(self.identifier)['job']
        self.assertEqual(self.run_job(job),['voice_generation.py','reference_styles.py','build_video.py'])
        self.assertEqual(self.app.reference_state(self.identifier)['status'],'complete')

    def test_reference_plan_only_does_not_render_video_or_mark_complete(self):
        (self.path/'source.mp4').write_bytes(b'reference')
        write_json(self.path/'reference_style.json',{'status':'awaiting_inputs','analysis_provider':'codex','reference_file':'source.mp4'})
        with patch.object(studio.threading,'Thread'),patch.object(studio.reference_styles,'settings',return_value={'provider':'codex','providers':{'codex':{'installed':True}}}):
            job=self.app.start_reference(self.identifier,False)['job']
        self.assertEqual(self.run_job(job),['voice_generation.py','reference_styles.py'])
        self.assertEqual(self.app.reference_state(self.identifier)['status'],'ready')

    def test_asset_completion_can_auto_generate_selected_voice_without_upload(self):
        write_json(self.path/'ai_workflow.json',{'source':'import','status':'assets_ready','auto_build':True,'approved_script_hash':fingerprint(SCRIPT),'prepared_inputs_hash':self.app.asset_inputs_hash(self.app.load(self.identifier)['editor'])})
        with patch.object(self.app,'start') as start:self.app.maybe_auto_build(self.identifier)
        start.assert_called_once_with(self.identifier,'build')

    def test_unconfigured_voice_or_missing_selection_waits_without_starting_paid_job(self):
        self.app.voice.settings={}
        with patch.object(studio.threading,'Thread') as thread:
            with self.assertRaisesRegex(ValueError,'Connect ElevenLabs'):self.app.start_voice(self.identifier)
            thread.assert_not_called()

    def test_cancel_before_process_starts_never_sends_request_or_renders(self):
        with patch.object(studio.threading,'Thread'):job=self.app.start_voice(self.identifier,True)['job']
        job['cancel']=True
        self.assertEqual(self.run_job(job),[]);self.assertEqual(job['status'],'cancelled')

    def test_voice_failure_stops_chain_and_preserves_script(self):
        with patch.object(studio.threading,'Thread'):job=self.app.start_voice(self.identifier,True)['job']
        process=MagicMock();process.stdout=iter(['[VOICE] ElevenLabs quota exhausted\n']);process.wait.return_value=1
        with patch.object(studio.subprocess,'Popen',return_value=process) as start:self.app.run(job,self.path,read_cache(self.path/'config.json'),0)
        self.assertEqual(start.call_count,1);self.assertEqual(job['status'],'failed')
        self.assertEqual((self.path/'script.txt').read_text('utf-8'),SCRIPT)


class VoiceHTTPTests(unittest.TestCase):
    # Keep HTTP cases separate from inherited pipeline cases.
    def setUp(self):
        StudioVoiceTests.setUp(self)
        self.server=studio.StudioServer(('127.0.0.1',0),studio.Handler);self.server.studio=self.app
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
        self.addCleanup(self.stop)
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def stop(self):self.server.shutdown();self.server.server_close();self.worker.join(timeout=3)

    def request(self,path,data=None,token=True):
        headers={'X-Studio-Token':self.app.token} if token else {}
        body=None if data is None else json.dumps(data).encode('utf-8')
        return urllib.request.urlopen(urllib.request.Request(self.base+path,data=body,headers=headers),timeout=5)

    def test_settings_and_catalog_never_return_api_key(self):
        with self.request('/api/voice/settings') as response:self.assertNotIn(KEY,response.read().decode())
        with patch.object(self.app.voice,'catalog',return_value=catalog()):
            with self.request('/api/voice/catalog?refresh=1') as response:self.assertEqual(len(json.load(response)['voices']),2)
        # Authentication is checked before reading a body. An empty unauthorized
        # POST avoids a Windows TCP reset from closing a socket with unread data.
        request=urllib.request.Request(self.base+'/api/voice/settings',data=b'',method='POST')
        with self.assertRaises(urllib.error.HTTPError) as rejected:urllib.request.urlopen(request,timeout=5)
        self.assertEqual(rejected.exception.code,403)

    def test_creation_endpoints_preserve_elevenlabs_option_without_requiring_subscription_yet(self):
        for endpoint,payload in [('/api/create',{'name':'Manual','preset':'blank'}),
                                 ('/api/reference/create',{'name':'Reference','script':SCRIPT,'provider':'codex'}),
                                 ('/api/brief/import',{'brief':{'project_name':'Brief','script':SCRIPT,'games':[{'exact_name':'OpenTTD','spoken_names':['OpenTTD'],'youtube_gameplay_url':'https://youtu.be/ESlyTiZwsDk'}]}})]:
            with self.subTest(endpoint=endpoint),self.request(endpoint,{**payload,'voice_source':'elevenlabs'}) as response:
                project=json.load(response);self.assertEqual(project['voice_settings']['source'],'elevenlabs');self.assertEqual(project['voice_settings']['voice_id'],'my-clone')
                self.assertNotIn(KEY,json.dumps(project))
        self.app.ai.configure('gemini',api_key='fixture-gemini-key')
        with patch.object(self.app,'run_ai'):
            with self.request('/api/ai/create',{'name':'AI episode','provider':'gemini','idea':'A game','language':'Arabic','voice_source':'elevenlabs'}) as response:
                self.assertEqual(json.load(response)['project']['voice_settings']['source'],'elevenlabs')


if __name__=='__main__':unittest.main()
