import copy,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import reference_styles as ref
import video_studio as studio
import video_sections
from pipeline_common import write_json,fingerprint,file_signature


def valid_plan():
    return {'analysis':{'name':'Floating editorial','summary':'Soft depth and moving cards.','background':'#edf2ee','background_end':'#c5d1c9',
            'ink':'#18251e','accent':'#087f51','muted':'#64746a','heading_font':'serif','italic':True,'float_amplitude':15,
            'float_period':120,'shadow_blur':35,'shadow_opacity':.2,'shadow_y':24,'card_radius':30,'entrance':'rise',
            'transition':'blur','caption_style':'phrase','caption_y':.81,'ribbon':True,'observations':[{'time_seconds':.5,'detail':'Floating hero with a soft shadow.'}]},
            'assets':[{'id':'hero','kind':'uploaded','source':'media/hero.png','start_seconds':0,'duration_seconds':1}],
            'scenes':[{'title':'A new story','emphasis':'Your idea','label':'Opening','variant':'hero','media':'hero','secondary_media':'',
                       'start_seconds':0,'fit':'contain','captions':True},
                      {'title':'The next scene','emphasis':'','label':'','variant':'type','media':'','secondary_media':'',
                       'start_seconds':2,'fit':'contain','captions':True}]}

class ReferenceTests(unittest.TestCase):
    def test_plan_preserves_adapted_scene_timing(self):
        plan=valid_plan();self.assertIs(ref.validate_plan(plan,5,{'media/hero.png'}),plan)
        self.assertEqual(plan['scenes'][1]['start_seconds'],2)

    def test_rejects_invalid_sources_timing_and_style(self):
        bad=[]
        for key,value in [('background','url(http://localhost)'),('shadow_opacity',float('nan')),('caption_y',1.1),('entrance','execute')]:
            p=valid_plan();p['analysis'][key]=value;bad.append(p)
        for key,value in [('start_seconds',5),('start_seconds',-1),('media','missing'),('variant','run_shell')]:
            p=valid_plan();p['scenes'][1][key]=value;bad.append(p)
        p=valid_plan();p['assets'][0]['source']='../secret.png';bad.append(p)
        p=valid_plan();p['assets'][0].update(kind='youtube',source='https://localhost/private');bad.append(p)
        p=valid_plan();p['assets'][0].update(kind='image',source='http://127.0.0.1/secret');bad.append(p)
        for plan in bad:
            with self.subTest(plan=plan):
                with self.assertRaises(ValueError):ref.validate_plan(plan,5,{'media/hero.png'})

    def test_directed_graphic_scenes_allow_no_photo_but_validate_direction(self):
        for variant in ('device','metric','steps'):
            plan=valid_plan();scene=plan['scenes'][1]
            scene.update(variant=variant,scene_tone='contrast',backdrop='grid',motif='privacy',details=['Photos','Messages','Accounts'])
            self.assertIs(ref.validate_plan(plan,5,{'media/hero.png'}),plan)
            with tempfile.TemporaryDirectory() as folder:
                config={'sections':[{**scene,'layout':'reference_style','start_seconds':0}], 'reference_style':plan['analysis']}
                self.assertTrue(video_sections.validate_sections(config,folder))
        for key,value in [('scene_tone','url(x)'),('backdrop','execute'),('details',['x'*51]),('details',['1','2','3','4'])]:
            plan=valid_plan();plan['scenes'][1][key]=value
            with self.assertRaises(ValueError):ref.validate_plan(plan,5,{'media/hero.png'})

    def test_supporting_details_reveal_on_spoken_words_inside_the_scene(self):
        scene={'details':['private photos','messages','bank accounts']}
        words=[{'word':'private','start':2.8},{'word':'photos','start':3.1},{'word':'messages','start':3.7},
               {'word':'bank','start':4.3},{'word':'accounts','start':4.5}]
        self.assertEqual(video_sections.reference_detail_frames(scene,words,60,90,30),[24,51,69])

    def test_reference_line_weight_and_contrast_palette_are_bounded(self):
        for key,value in [('ribbon_width',0),('grid_opacity',.9),('contrast_background','white')]:
            plan=valid_plan();plan['analysis'][key]=value
            with self.assertRaises(ValueError):ref.validate_plan(plan,5,{'media/hero.png'})

    def test_asset_facts_distinguish_white_photography_from_a_cutout(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            Image.new('RGB',(40,30),'white').save(root/'photo.png')
            Image.new('RGBA',(40,30),(0,0,0,0)).save(root/'cutout.png')
            result=ref.describe_assets(root,[{'path':name,'kind':'image'} for name in ('photo.png','cutout.png')])
            self.assertTrue(result[0]['white_background']);self.assertFalse(result[0]['transparent'])
            self.assertTrue(result[1]['transparent']);self.assertFalse(result[1]['white_background'])
            self.assertEqual(result[0]['width'],40)

    def test_cli_stream_envelope_and_no_permission_bypass(self):
        with tempfile.TemporaryDirectory() as folder:
            result=type('Result',(),{'returncode':0,'stdout':json.dumps({'event':'result','result':{'status':'SUCCESS','structured_output':valid_plan(),'conversation_id':'test'}}),'stderr':''})()
            with patch.object(ref.subprocess,'run',return_value=result) as run:
                plan,meta=ref.ask_antigravity({'cli_path':'agy.exe','model':ref.DEFAULT_MODEL},folder,'Analyze',ref.SCHEMA)
                self.assertEqual(plan,valid_plan());self.assertEqual(meta['conversation_id'],'test')
                args=run.call_args.args[0]
                self.assertNotIn('--dangerously-skip-permissions',args)
                self.assertEqual(json.loads(run.call_args.kwargs['input'])['message']['content'],'Analyze')

    def test_auth_failure_is_actionable(self):
        result=type('Result',(),{'returncode':1,'stdout':'','stderr':'authentication required'})()
        with patch.object(ref.subprocess,'run',return_value=result):
            with self.assertRaisesRegex(ValueError,'sign-in'):
                ref.ask_antigravity({'cli_path':'agy.exe','model':ref.DEFAULT_MODEL},'.','Check')

    def test_reference_only_timeline_needs_no_gameplay_background(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'media').mkdir();(root/'media/hero.png').write_bytes(b'asset')
            section={**valid_plan()['scenes'][0],'layout':'reference_style','media':'media/hero.png','caption_y':.81}
            config={'sections':[section],'reference_style':valid_plan()['analysis']}
            timeline=video_sections.make_timeline(config,root,root,[{'word':'hello','start':0,'end':.3}],4,
                                                 lambda path:self.fail('A reference scene must not probe a background'))
            self.assertEqual(timeline['totalFrames'],120)
            self.assertEqual(timeline['blocks'][0]['referenceStyle']['accent'],'#087f51')

    def test_manual_reference_scene_requires_analysis_and_media(self):
        with tempfile.TemporaryDirectory() as folder:
            config={'sections':[{'layout':'reference_style','variant':'card'}]}
            with self.assertRaisesRegex(ValueError,'Analyze a reference'):video_sections.validate_sections(config,folder)
            config['reference_style']=valid_plan()['analysis']
            with self.assertRaisesRegex(ValueError,'Add media'):video_sections.validate_sections(config,folder)
            config['sections'][0]['variant']='type'
            self.assertEqual(video_sections.validate_sections(config,folder),config['sections'])

    def test_uploaded_asset_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'media').mkdir();(root/'media/hero.png').write_bytes(b'original')
            result=ref.prepare_assets(root,valid_plan())
            self.assertEqual(result['hero'],'media/hero.png');self.assertEqual((root/'media/hero.png').read_bytes(),b'original')

    def test_new_analysis_enables_motion_without_touching_existing_exports(self):
        import build_video as builder
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'media').mkdir();(root/'output').mkdir()
            (root/'script.txt').write_text('Keep USB and Juice Jacking in English',encoding='utf-8')
            (root/'reference.mp4').write_bytes(b'reference');(root/'voiceover.mp3').write_bytes(b'voice')
            (root/'media/hero.png').write_bytes(b'image')
            (root/'output/final.mp4').write_bytes(b'accepted export')
            write_json(root/'reference_style.json',{'reference_file':'reference.mp4','analysis_provider':'codex'})
            write_json(root/'config.json',{'keep_setting':True})
            with patch.object(builder,'configure_project'),patch.object(builder,'transcribe_voiceover',return_value={}), \
                 patch.object(builder,'apply_script',return_value={'words':[]}),patch.object(ref,'probe',return_value=(5.,None)), \
                 patch.object(ref,'sample_reference',return_value={'sheets':[]}),patch.object(ref,'describe_assets',side_effect=lambda project,items:items), \
                 patch.object(ref,'settings',return_value={'provider':'codex','model':'chosen-model'}), \
                 patch.object(ref,'ask_provider',return_value=(valid_plan(),{})) as ask,patch.object(ref,'log'):
                ref.run_project(root,root/'data')
            config=json.loads((root/'config.json').read_text())
            self.assertEqual(config['reference_style']['renderer_version'],3)
            self.assertEqual(config['sections'][1]['start_seconds'],2)
            self.assertTrue(config['keep_setting'])
            self.assertEqual((root/'output/final.mp4').read_bytes(),b'accepted export')
            self.assertEqual((root/'voiceover.mp3').read_bytes(),b'voice')
            self.assertEqual(ask.call_args.args[0]['model'],'chosen-model')
            self.assertIn('Never translate or transliterate',ask.call_args.args[2])
            self.assertIn('without moving narration or caption timestamps',ask.call_args.args[2])

    def test_failed_asset_preparation_reuses_plan_only_when_inputs_match(self):
        import build_video as builder
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'media').mkdir()
            (root/'script.txt').write_text('Original script',encoding='utf-8')
            (root/'reference.mp4').write_bytes(b'reference');(root/'voiceover.mp3').write_bytes(b'voice')
            (root/'media/hero.png').write_bytes(b'image')
            write_json(root/'reference_style.json',{'status':'awaiting_inputs','reference_file':'reference.mp4','analysis_provider':'codex'})
            with patch.object(builder,'configure_project'),patch.object(builder,'transcribe_voiceover',return_value={}) as transcribe, \
                 patch.object(builder,'apply_script',return_value={'words':[]}),patch.object(ref,'probe',return_value=(5.,None)), \
                 patch.object(ref,'sample_reference',return_value={'sheets':[]}) as sample,patch.object(ref,'describe_assets',side_effect=lambda project,items:items), \
                 patch.object(ref,'settings',return_value={'provider':'codex','model':'chosen-model'}), \
                 patch.object(ref,'ask_provider',side_effect=lambda *args:(valid_plan(),{})) as ask,patch.object(ref,'log'):
                with patch.object(ref,'prepare_assets',side_effect=ValueError('download interrupted')):
                    with self.assertRaisesRegex(ValueError,'download interrupted'):ref.run_project(root,root/'data')
                checkpoint=json.loads((root/'reference_style.json').read_text())
                self.assertEqual(checkpoint['status'],'failed');self.assertTrue(checkpoint['plan_hash'])
                # Retrying the same failed inputs must bypass both AI and alignment.
                ref.run_project(root,root/'data')
                self.assertEqual(ask.call_count,1);self.assertEqual(transcribe.call_count,1);self.assertEqual(sample.call_count,1)
                self.assertEqual(json.loads((root/'reference_style.json').read_text())['status'],'ready')
                # A changed script must invalidate that checkpoint.
                checkpoint['status']='failed';write_json(root/'reference_style.json',checkpoint)
                (root/'script.txt').write_text('Changed script',encoding='utf-8')
                ref.run_project(root,root/'data')
                self.assertEqual(ask.call_count,2)

    def test_plan_checkpoint_invalidates_changed_inputs_but_ignores_download_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'media/reference').mkdir(parents=True)
            reference=root/'reference.mp4';voice=root/'voiceover.mp3'
            reference.write_bytes(b'ref');voice.write_bytes(b'voice')
            signature=lambda **kw:ref.plan_input_signature(root,kw.get('script','Script'),reference,voice,kw.get('state',{}),kw.get('provider','codex'),kw.get('model','model'))
            original=signature()
            for change in [{'script':'Other'},{'provider':'antigravity'},{'model':'other'},{'state':{'instructions':'new'}}]:
                self.assertNotEqual(signature(**change),original)
            (root/'media/reference/download.png').write_bytes(b'cache')
            self.assertEqual(signature(),original)
            (root/'media/upload.png').write_bytes(b'upload')
            self.assertNotEqual(signature(),original)
            voice.write_bytes(b'changed voice');self.assertNotEqual(signature(),original)

    def test_studio_inputs_and_stale_script(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=studio.Studio(root/'data',root/'projects')
            p=app.create_reference('Reference test','hello world');identifier=p['id'];path=Path(p['path'])
            with self.assertRaisesRegex(ValueError,'reference video'):app.start_reference(identifier)
            (path/'reference').mkdir();(path/'reference/source.mp4').write_bytes(b'video');(path/'voiceover.mp3').write_bytes(b'audio')
            state={'status':'ready','reference_file':'reference/source.mp4','script_hash':fingerprint('hello world'),
                   'reference_signature':file_signature(path/'reference/source.mp4'),'voice_signature':file_signature(path/'voiceover.mp3')}
            write_json(path/'reference_style.json',state)
            self.assertFalse(app.reference_state(identifier)['stale'])
            (path/'script.txt').write_text('changed words',encoding='utf-8')
            self.assertTrue(app.reference_state(identifier)['stale'])
            with self.assertRaisesRegex(ValueError,'Analyze the current'):app.start(identifier,'build')

    def test_restart_preserves_reference_checkpoint_without_creating_ai_approval(self):
        for action in ('reference_build','voice_build'):
            with self.subTest(action=action),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);app=studio.Studio(root/'data',root/'projects')
                project=app.create_reference('Reference restart','hello',provider='codex');path=Path(project['path'])
                write_json(path/'reference_style.json',{'status':'preparing_assets','reference_file':'source.mp4','plan_hash':'saved-plan'})
                job={'id':'running-reference','project':project['id'],'action':action,'status':'running'}
                if action=='voice_build':job['next_action']='reference_build'
                write_json(root/'data/ai/job.json',job)
                restarted=studio.Studio(root/'data',root/'projects')
                state=restarted.reference_state(project['id'])
                self.assertEqual(state['status'],'interrupted');self.assertEqual(state['plan_hash'],'saved-plan')
                self.assertFalse((path/'ai_workflow.json').exists())
                self.assertEqual(restarted.workflow(project['id']),{})

    def test_reference_job_is_cancellable_and_uses_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=studio.Studio(root/'data',root/'projects')
            p=app.create_reference('Reference test','hello world');path=Path(p['path']);(path/'source.mp4').write_bytes(b'video');(path/'voiceover.mp3').write_bytes(b'voice')
            write_json(path/'reference_style.json',{'status':'awaiting_inputs','reference_file':'source.mp4'})
            with patch.object(ref,'settings',return_value={'installed':True}),patch.object(studio.threading,'Thread') as thread:
                result=app.start_reference(p['id'],False)
                self.assertEqual(result['job']['action'],'reference_plan');self.assertEqual(thread.call_args.kwargs['target'],app.run)
                app.cancel();self.assertEqual(app.job['status'],'cancelling')

class CodexProviderTests(unittest.TestCase):
    def test_legacy_settings_and_provider_preferences_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)
            write_json(data/'reference_styles/settings.json',{'model':'gemini-3.8-flash-high','cli_path':''})
            self.assertEqual(ref.settings(data)['provider'],'antigravity')
            config=ref.configure(data,model='',provider='codex')
            self.assertEqual(config['provider'],'codex')
            self.assertEqual(config['model'],'')
            self.assertEqual(config['providers']['antigravity']['model'],'gemini-3.8-flash-high')
            ref.configure(data,model='gpt-custom',provider='codex')
            config=ref.configure(data,model='gemini-3.8-flash-medium',provider='antigravity')
            self.assertEqual(config['providers']['codex']['model'],'gpt-custom')
            with self.assertRaises(ValueError):ref.configure(data,provider='unsupported')
            with self.assertRaises(ValueError):ref.configure(data,model='--run-something',provider='codex')

    def test_codex_receives_images_context_and_read_only_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'reference').mkdir();(root/'media').mkdir()
            (root/'reference/sheet.jpg').write_bytes(b'image');(root/'media/hero.png').write_bytes(b'image')
            write_json(root/'reference/context.json',{'script':'preserve my words','reference':{'sheets':['reference/sheet.jpg']},
                                                    'available_assets':[{'path':'media/hero.png'}]})
            auth=type('Result',(),{'returncode':0,'stdout':'Logged in using ChatGPT','stderr':''})()
            events=[{'type':'thread.started','thread_id':'codex-thread'},
                    {'type':'item.completed','item':{'type':'agent_message','text':json.dumps(valid_plan())}},
                    {'type':'turn.completed','usage':{'input_tokens':12,'output_tokens':34}}]
            result=type('Result',(),{'returncode':0,'stdout':'\n'.join(json.dumps(x) for x in events),'stderr':''})()
            with patch.object(ref.subprocess,'run',side_effect=[auth,result]) as run:
                plan,meta=ref.ask_codex({'cli_path':'codex.exe','model':''},root,'Analyze',ref.SCHEMA)
            self.assertEqual(plan,valid_plan());self.assertEqual(meta['thread_id'],'codex-thread')
            command=run.call_args.args[0]
            self.assertIn('read-only',command);self.assertIn('--search',command)
            self.assertIn('--output-schema',command);self.assertEqual(command.count('--image'),2)
            self.assertNotIn('--model',command);self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',command)
            self.assertIn('preserve my words',run.call_args.kwargs['input'])
            self.assertEqual(command[-2:],['--','-'])

    def test_api_key_login_is_not_silently_used_or_modified(self):
        auth=type('Result',(),{'returncode':0,'stdout':'Logged in using an API key','stderr':''})()
        with patch.object(ref.subprocess,'run',return_value=auth) as run:
            with self.assertRaisesRegex(ValueError,'Sign in with ChatGPT'):
                ref.ask_codex({'cli_path':'codex.exe','model':''},'.','Check')
            self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[0],['codex.exe','login','status'])

    def test_codex_failures_do_not_accept_partial_answers(self):
        auth=type('Result',(),{'returncode':0,'stdout':'Logged in using ChatGPT','stderr':''})()
        result=type('Result',(),{'returncode':1,'stdout':json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'Partial'}}),'stderr':'limit reached'})()
        with patch.object(ref.subprocess,'run',side_effect=[auth,result]):
            with self.assertRaisesRegex(ValueError,'did not complete'):
                ref.ask_codex({'cli_path':'codex.exe','model':''},'.','Check')

    def test_provider_router_uses_the_selected_connection(self):
        with patch.object(ref,'ask_codex',return_value=('answer',{})) as codex,patch.object(ref,'ask_antigravity') as gemini:
            ref.ask_provider({'provider':'codex'},'.','Analyze')
            codex.assert_called_once();gemini.assert_not_called()

class ModelCatalogTests(unittest.TestCase):
    def test_codex_discovery_uses_auth_and_pagination_then_cleans_up(self):
        process=MagicMock();process.poll.return_value=None
        responses=[{'id':1,'result':{}},{'id':2,'result':{'account':{'type':'chatgpt'}}},
                   {'id':3,'result':{'data':[{'model':'vision-a'}],'nextCursor':'next'}},
                   {'id':4,'result':{'data':[{'model':'vision-b'}],'nextCursor':None}}]
        process.stdout=io.StringIO('\n'.join(json.dumps(row) for row in responses)+'\n')
        with patch.object(ref.subprocess,'Popen',return_value=process):
            rows=ref.codex_model_rows('codex.exe')
        self.assertEqual([row['model'] for row in rows],['vision-a','vision-b'])
        calls=[json.loads(call.args[0]) for call in process.stdin.write.call_args_list]
        self.assertEqual(calls[0]['method'],'initialize');self.assertEqual(calls[1]['method'],'initialized')
        self.assertEqual(calls[2]['params'],{'refreshToken':False})
        self.assertEqual(calls[-1]['params']['cursor'],'next');process.terminate.assert_called_once()
        process.stdin.close.assert_called_once()

    def test_codex_discovery_requires_chatgpt_login(self):
        process=MagicMock();process.poll.return_value=None
        process.stdout=io.StringIO(json.dumps({'id':1,'result':{}})+'\n'+json.dumps({'id':2,'result':{'account':None}})+'\n')
        with patch.object(ref.subprocess,'Popen',return_value=process):
            with self.assertRaisesRegex(ValueError,'Sign in with ChatGPT'):ref.codex_model_rows('codex.exe')
        process.terminate.assert_called_once()

    def test_codex_filters_hidden_and_text_only_models_without_hardcoding(self):
        rows=[{'model':'future-vision','displayName':'Future Vision','isDefault':True,'inputModalities':['text','image']},
              {'model':'text-only','inputModalities':['text']},{'model':'no-input','inputModalities':[]},{'model':'hidden','hidden':True},
              {'model':'legacy-vision'}]
        config={'providers':{'codex':{'installed':True,'cli_path':'codex.exe'}}}
        with patch.object(ref,'settings',return_value=config),patch.object(ref,'codex_model_rows',return_value=rows):
            result=ref.available_models('.', 'codex')
        self.assertEqual([r['id'] for r in result['models']],['future-vision','legacy-vision'])
        self.assertEqual(result['models'][0]['name'],'Future Vision');self.assertTrue(result['models'][0]['is_default'])

    def test_antigravity_only_lists_gemini_and_deduplicates(self):
        config={'providers':{'antigravity':{'installed':True,'cli_path':'agy.exe'}}}
        result=type('Result',(),{'returncode':0,'stdout':'Fetching models...\ngemini-next-high\tGemini Next High\nclaude-other\tOther model\ngemini-next-low  Gemini Next Low\ngemini-next-high\tGemini Next High','stderr':''})()
        with patch.object(ref,'settings',return_value=config),patch.object(ref.subprocess,'run',return_value=result) as run:
            models=ref.available_models('.', 'antigravity')['models']
        self.assertEqual([r['id'] for r in models],['gemini-next-high','gemini-next-low'])
        self.assertEqual(run.call_args.args[0],['agy.exe','models'])

    def test_discovery_errors_are_actionable(self):
        with self.assertRaises(ValueError):ref.available_models('.','unknown')
        config={'providers':{'codex':{'installed':False,'cli_path':''}}}
        with patch.object(ref,'settings',return_value=config):
            with self.assertRaisesRegex(ValueError,'not found'):ref.available_models('.','codex')
        config['providers']['codex'].update(installed=True,cli_path='codex.exe')
        with patch.object(ref,'settings',return_value=config),patch.object(ref,'codex_model_rows',return_value=[]):
            with self.assertRaisesRegex(ValueError,'No compatible models'):ref.available_models('.','codex')
        with patch.object(ref,'settings',return_value=config),patch.object(ref,'codex_model_rows',side_effect=OSError('private details')):
            with self.assertRaisesRegex(ValueError,'could not be started'):ref.available_models('.','codex')

class CreationProviderTests(unittest.TestCase):
    def test_creation_saves_the_chosen_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=studio.Studio(root/'data',root/'projects')
            project=app.create_reference('Codex choice','hello world',provider='codex')
            self.assertEqual(project['reference_style']['analysis_provider'],'codex')
            with self.assertRaises(ValueError):app.create_reference('Invalid provider','hello',provider='unknown')

    def test_start_uses_project_choice_and_checks_the_right_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);app=studio.Studio(root/'data',root/'projects')
            project=app.create_reference('Codex choice','hello',provider='codex');path=Path(project['path'])
            (path/'source.mp4').write_bytes(b'video');(path/'voiceover.mp3').write_bytes(b'audio')
            state=app.reference_state(project['id']);state['reference_file']='source.mp4';write_json(path/'reference_style.json',state)
            connections={'provider':'antigravity','installed':True,'providers':{'codex':{'installed':False},'antigravity':{'installed':True}}}
            with patch.object(ref,'settings',return_value=connections),patch.object(studio.threading,'Thread'):
                with self.assertRaisesRegex(ValueError,'selected local AI'):app.start_reference(project['id'])
                connections['providers']['codex']['installed']=True
                result=app.start_reference(project['id'],False)
                self.assertIn('Codex / ChatGPT',result['job']['stage'])
                self.assertEqual(app.reference_state(project['id'])['analysis_provider'],'codex')

class WorkerTests(unittest.TestCase):
    def test_worker_uses_recording_and_writes_editable_data(self):
        import build_video
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'media').mkdir()
            from PIL import Image
            Image.new('RGBA',(20,20),(255,255,255,255)).save(root/'media/hero.png')
            (root/'reference.mp4').write_bytes(b'video');(root/'voiceover.mp3').write_bytes(b'audio')
            (root/'script.txt').write_text('hello world',encoding='utf-8')
            write_json(root/'reference_style.json',{'reference_file':'reference.mp4','instructions':'Use soft depth','analysis_provider':'codex'})
            write_json(root/'config.json',{'sections':[{'layout':'title','title':'Waiting'}]})
            write_json(root/'studio.json',{'name':'Example','mode':'sections','script':'hello world'})
            words={'words':[{'word':'hello','start':0,'end':.5}]}
            with patch.object(ref,'probe',return_value=(5,[])),patch.object(ref,'sample_reference',return_value={'sheets':['sheet.jpg']}), \
                 patch.object(build_video,'configure_project'),patch.object(build_video,'transcribe_voiceover',return_value=words), \
                 patch.object(build_video,'apply_script',return_value=words),patch.object(ref,'settings',return_value={'provider':'antigravity','model':ref.DEFAULT_MODEL,'providers':{'codex':{'model':'gpt-chosen','cli_path':'codex.exe'}}}), \
                 patch.object(ref,'ask_codex',return_value=(valid_plan(),{'thread_id':'verified'})) as ask:
                ref.run_project(root,root/'data')
            config=json.loads((root/'config.json').read_text(encoding='utf-8'))
            state=json.loads((root/'reference_style.json').read_text(encoding='utf-8'))
            self.assertEqual(config['sections'][0]['media'],'media/hero.png')
            self.assertEqual(config['sections'][0]['layout'],'reference_style')
            self.assertEqual(config['sections'][1]['start_seconds'],2)
            self.assertEqual((root/'script.txt').read_text(encoding='utf-8'),'hello world')
            self.assertEqual(state['status'],'ready');self.assertEqual(state['provider'],'codex')
            self.assertEqual(state['model'],'gpt-chosen')
            self.assertEqual(state['metadata']['thread_id'],'verified')
            self.assertIn('VIEW EVERY contact sheet',ask.call_args.args[2])

    def test_bad_plan_does_not_replace_existing_scenes(self):
        import build_video
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'media').mkdir();(root/'reference.mp4').write_bytes(b'video');(root/'voiceover.mp3').write_bytes(b'audio')
            (root/'script.txt').write_text('hello',encoding='utf-8')
            original={'sections':[{'layout':'title','title':'Keep this scene'}]}
            write_json(root/'config.json',original);write_json(root/'reference_style.json',{'reference_file':'reference.mp4'})
            plan=valid_plan();plan['scenes'][0]['start_seconds']=1
            words={'words':[]}
            with patch.object(ref,'probe',return_value=(5,[])),patch.object(ref,'sample_reference',return_value={'sheets':[]}), \
                 patch.object(build_video,'configure_project'),patch.object(build_video,'transcribe_voiceover',return_value=words), \
                 patch.object(build_video,'apply_script',return_value=words),patch.object(ref,'settings',return_value={'model':ref.DEFAULT_MODEL}), \
                 patch.object(ref,'ask_antigravity',return_value=(plan,{})):
                with self.assertRaises(ValueError):ref.run_project(root,root/'data')
            self.assertEqual(json.loads((root/'config.json').read_text(encoding='utf-8')),original)
            self.assertEqual(json.loads((root/'reference_style.json').read_text(encoding='utf-8'))['status'],'failed')

if __name__=='__main__':unittest.main()
