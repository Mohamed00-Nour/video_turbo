import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import flow_workflow as flow
import reference_styles as ref
import video_studio as studio
import video_sections
from pipeline_common import fingerprint, file_signature, read_cache, write_json


def plan():
    return {'analysis': {'name': 'Editorial depth', 'summary': 'A calm visual story.',
        'background': '#111111', 'background_end': '#222222', 'ink': '#ffffff',
        'accent': '#ffaa00', 'muted': '#aaaaaa', 'observations': [{'time_seconds': 0, 'detail': 'Soft side lighting.'}]},
        'visual_bible': 'Keep the same red robot, warm light and olive background.',
        'duration_seconds': 6, 'scenes': [
            {'title': 'Opening', 'start_seconds': 0, 'image_prompt': 'The red robot beside a phone.',
             'motion_prompt': 'Slow push in as it turns toward the phone.', 'continuity': 'Same red robot.', 'transition': 'cut'},
            {'title': 'Resolution', 'start_seconds': 3, 'image_prompt': 'The same robot holding the phone.',
             'motion_prompt': 'Slow lateral camera move, one small wave.', 'continuity': 'Same wardrobe and light.', 'transition': 'fade'}]}


def fixture(root, app=None):
    app = app or studio.Studio(root / 'data', root / 'projects')
    project = app.create_reference('Flow test', 'Hello world', provider='codex', workflow='flow')
    path = Path(project['path'])
    (path / 'source.mp4').write_bytes(b'reference')
    (path / 'voiceover.wav').write_bytes(b'voice')
    (path / 'media/flow').mkdir(parents=True)
    for name in ('one.mp4', 'two.mp4'): (path / 'media/flow' / name).write_bytes(b'clip')
    state = read_cache(path / 'reference_style.json')
    storyboard = plan()
    state.update(status='awaiting_clips', reference_file='source.mp4', script_hash=fingerprint('Hello world'),
        reference_signature=file_signature(path / 'source.mp4'), voice_signature=file_signature(path / 'voiceover.wav'),
        analysis=storyboard['analysis'], flow_plan=storyboard, plan_hash=fingerprint(storyboard), flow_clips={})
    write_json(path / 'reference_style.json', state)
    return app, project['id'], path, state


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app, self.identifier, self.path, self.state = fixture(self.root)
        self.probe = patch.object(ref, 'probe', return_value=(8, [{'codec_type': 'video', 'width': 720, 'height': 1280}]))
        self.probe.start(); self.addCleanup(self.probe.stop)

    def assign(self, scene='scene_01', file='media/flow/one.mp4', offset=0):
        return flow.assign_clip(self.path, scene, file, offset, self.state['plan_hash'])

    def test_all_clips_required_and_final_sections_keep_narration_timing(self):
        self.assertEqual(self.assign()['status'], 'awaiting_clips')
        with self.assertRaisesRegex(ValueError, 'Analyze the current'): self.app.start(self.identifier, 'build')
        state = self.assign('scene_02', 'media/flow/two.mp4', 2)
        self.assertEqual(state['status'], 'ready')
        config = read_cache(self.path / 'config.json')
        self.assertEqual([row['start_seconds'] for row in config['sections']], [0, 3])
        self.assertEqual(config['sections'][1]['offset_seconds'], 2)
        flow.validate_build(self.path, state, config)
        self.assertEqual((self.path / 'script.txt').read_text(), 'Hello world')
        self.assertEqual((self.path / 'voiceover.wav').read_bytes(), b'voice')

    def test_display_copy_survives_clip_reimport_and_is_not_baked_into_prompts(self):
        self.state['flow_plan']['scenes'][0]['flow_text'] = {'kicker': 'An open network', 'headline': 'FREE Wi-Fi', 'support': 'A hidden risk'}
        self.state['plan_hash'] = fingerprint(self.state['flow_plan'])
        write_json(self.path / 'reference_style.json', self.state)
        self.assign(); self.assign('scene_02', 'media/flow/two.mp4')
        config = read_cache(self.path / 'config.json')
        self.assertEqual(config['sections'][0]['flow_text']['headline'], 'FREE Wi-Fi')
        config['sections'][0]['flow_text']['headline'] = 'Edited headline'
        write_json(self.path / 'config.json', config)
        self.assign()
        self.assertEqual(read_cache(self.path / 'config.json')['sections'][0]['flow_text']['headline'], 'Edited headline')
        timeline = video_sections.make_timeline(read_cache(self.path / 'config.json'), self.path, self.path, [], 6, lambda path: 8)
        self.assertEqual(timeline['blocks'][0]['flowText']['headline'], 'Edited headline')
        scene = flow.scene_rows(self.state['flow_plan'])[0]
        self.assertNotIn('FREE Wi-Fi', flow.prompt_for(self.state['flow_plan'], scene, 'image'))
        invalid = plan(); invalid['scenes'][0]['flow_text'] = {'kicker': '', 'headline': '', 'support': ''}
        with self.assertRaisesRegex(ValueError, 'display headline'): flow.validate_plan(invalid, 6)

    def test_changed_reference_does_not_inherit_old_finishing_or_headline_overrides(self):
        self.assign(); self.assign('scene_02', 'media/flow/two.mp4')
        config=read_cache(self.path/'config.json')
        config['flow_style']['finishing']={'headlines':True,'headline_font':'serif','depth_motif':'asterisk'}
        config['sections'][0]['flow_text']={'kicker':'','headline':'Old reference copy','support':''}
        write_json(self.path/'config.json',config)
        self.assign()
        self.assertEqual(read_cache(self.path/'config.json')['flow_style']['finishing']['headline_font'],'serif')
        (self.path/'source.mp4').write_bytes(b'a different reference')
        state=read_cache(self.path/'reference_style.json')
        state['reference_signature']=file_signature(self.path/'source.mp4')
        write_json(self.path/'reference_style.json',state)
        self.assign()
        config=read_cache(self.path/'config.json')
        self.assertNotIn('finishing',config['flow_style'])
        self.assertNotIn('flow_text',config['sections'][0])
        timeline=video_sections.make_timeline(config,self.path,self.path,[],6,lambda path:8)
        self.assertEqual(timeline['blocks'][0]['flowFinishing']['depth_motif'],'none')

    def test_new_reference_finishing_reaches_the_timeline(self):
        self.state['flow_plan']['analysis']['finishing']={'headlines':True,'headline_font':'sans','headline_motion':'rise','depth_motif':'orbits','transition':'dissolve','sound':'none'}
        self.state['plan_hash']=fingerprint(self.state['flow_plan'])
        write_json(self.path/'reference_style.json',self.state)
        self.assign(); self.assign('scene_02','media/flow/two.mp4')
        config=read_cache(self.path/'config.json')
        timeline=video_sections.make_timeline(config,self.path,self.path,[],6,lambda path:8)
        style=timeline['blocks'][0]['flowFinishing']
        self.assertEqual((style['headline_font'],style['headline_motion'],style['depth_motif'],style['sound']),('sans','rise','orbits','none'))

    def test_invalid_short_audio_and_stale_imports_preserve_assignments(self):
        for result in [(2, [{'codec_type': 'video'}]), (8, [{'codec_type': 'audio'}])]:
            with patch.object(ref, 'probe', return_value=result), self.assertRaises(ValueError): self.assign()
        self.assign()
        before = (self.path / 'reference_style.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'trim point'): self.assign(offset=6)
        with self.assertRaises(ValueError): flow.assign_clip(self.path, 'scene_99', 'media/flow/one.mp4', plan_hash=self.state['plan_hash'])
        with self.assertRaisesRegex(ValueError, 'storyboard changed'): flow.assign_clip(self.path, 'scene_01', 'media/flow/one.mp4', plan_hash='old')
        with self.assertRaises(ValueError): flow.assign_clip(self.path, 'scene_01', '../outside.mp4', plan_hash=self.state['plan_hash'])
        self.assertEqual(before, (self.path / 'reference_style.json').read_bytes())
        (self.path / 'script.txt').write_text('Changed script')
        with self.assertRaisesRegex(ValueError, 'inputs changed'): self.assign()

    def test_replaced_voice_and_reference_invalidate_the_storyboard(self):
        for filename in ('voiceover.wav', 'source.mp4'):
            old = (self.path / filename).read_bytes()
            (self.path / filename).write_bytes(b'changed input')
            with self.assertRaisesRegex(ValueError, 'inputs changed'): self.assign()
            (self.path / filename).write_bytes(old)
            self.state['voice_signature'] = file_signature(self.path / 'voiceover.wav')
            self.state['reference_signature'] = file_signature(self.path / 'source.mp4')
            write_json(self.path / 'reference_style.json', self.state)

    def test_long_last_scene_nan_and_out_of_order_plan_are_rejected(self):
        for start, duration in [(2, 12), (float('nan'), 6), (0, 6), (7, 6)]:
            value = plan(); value['scenes'][1]['start_seconds'] = start
            with self.assertRaises(ValueError): flow.validate_plan(value, duration)
        value = plan(); value['scenes'][0]['start_seconds'] = 1
        with self.assertRaises(ValueError): flow.validate_plan(value, 6)

    def test_generated_clips_do_not_invalidate_the_analysis_cache(self):
        signature = lambda: ref.plan_input_signature(self.path, 'Hello world', self.path / 'source.mp4',
            self.path / 'voiceover.wav', self.state, 'codex', 'model')
        before = signature(); (self.path / 'media/flow/new-take.mp4').write_bytes(b'new clip')
        self.assertEqual(signature(), before)
        (self.path / 'media/subject.png').write_bytes(b'image')
        self.assertNotEqual(signature(), before)

    def test_build_rejects_reordered_scenes_and_changed_clip_offsets(self):
        self.assign(); state = self.assign('scene_02', 'media/flow/two.mp4')
        config = read_cache(self.path / 'config.json')
        config['sections'].reverse()
        with self.assertRaisesRegex(ValueError, 'order and timing'): flow.validate_build(self.path, state, config)
        config['sections'].reverse(); config['sections'][0]['offset_seconds'] = 7
        with self.assertRaisesRegex(ValueError, 'trim point'): flow.validate_build(self.path, state, config)

    def test_flow_timeline_needs_no_background_and_never_loops_a_short_clip(self):
        self.assign(); self.assign('scene_02', 'media/flow/two.mp4')
        config = read_cache(self.path / 'config.json')
        timeline = video_sections.make_timeline(config, self.path, self.path, [], 6, lambda path: 8)
        self.assertEqual([row['durationFrames'] for row in timeline['blocks']], [90, 90])
        self.assertEqual(timeline['totalFrames'], 180)
        self.assertEqual(timeline['blocks'][0]['flowAccent'], '#ffaa00')
        self.assertTrue(timeline['blocks'][0]['fade_out'])
        self.assertTrue(timeline['blocks'][1]['fade_in'])
        with self.assertRaisesRegex(ValueError, 'shorter than its scene'):
            video_sections.make_timeline(config, self.path, self.path, [], 6, lambda path: 2)

    def test_existing_storyboard_is_reused_without_an_ai_request(self):
        import build_video as builder
        self.state['plan_inputs'] = ref.plan_input_signature(self.path, 'Hello world', self.path / 'source.mp4',
            self.path / 'voiceover.wav', self.state, 'codex', 'model')
        write_json(self.path / 'reference_style.json', self.state)
        with patch.object(builder, 'configure_project'), patch.object(ref, 'settings', return_value={'provider': 'codex', 'model': 'model'}), patch.object(ref, 'ask_provider') as ask:
            flow.run_project(self.path, self.root / 'data')
        ask.assert_not_called()
        self.assertEqual(read_cache(self.path / 'reference_style.json')['status'], 'awaiting_clips')

    def test_flow_start_never_runs_a_build_before_manual_clip_imports(self):
        with patch.object(ref, 'settings', return_value={'provider': 'codex', 'installed': True}), patch.object(studio.threading, 'Thread'):
            result = self.app.start_reference(self.identifier, build=True)
        self.assertEqual(result['job']['action'], 'reference_plan')

    def test_idea_draft_requires_approval_and_does_not_generate_audio(self):
        import build_video as builder
        project = self.app.create_reference('Idea', '', workflow='flow', idea='Explain USB protection in Egyptian Arabic', provider='codex')
        path = Path(project['path']); (path / 'source.mp4').write_bytes(b'reference')
        state = read_cache(path / 'reference_style.json'); state['reference_file'] = 'source.mp4'
        write_json(path / 'reference_style.json', state)
        with patch.object(builder, 'configure_project'), patch.object(ref, 'settings', return_value={'provider':'codex','model':'model'}), \
             patch.object(ref, 'sample_reference', return_value={'sheets':[]}), \
             patch.object(ref, 'ask_provider', return_value=({'script':'Keep USB safe.', 'summary':'A short practical story.'},{})), \
             patch.object(builder, 'transcribe_voiceover') as transcribe:
            ref.run_project(path, self.root / 'data')
        transcribe.assert_not_called()
        self.assertEqual((path / 'script.txt').read_text(), '')
        self.assertFalse((path / 'voiceover.mp3').exists())
        approved = self.app.approve_flow_script(project['id'], 'Keep USB safe. Reviewed.')
        self.assertEqual(approved['editor']['script'], 'Keep USB safe. Reviewed.')
        self.assertEqual(approved['reference_style']['status'], 'awaiting_inputs')

    def test_new_storyboard_uses_recording_then_reuses_imports_on_retry(self):
        import build_video as builder
        connections={'provider':'codex','model':'model'}
        with patch.object(builder,'configure_project'),patch.object(ref,'settings',return_value=connections), \
             patch.object(ref,'sample_reference',return_value={'sheets':[]}), \
             patch.object(builder,'transcribe_voiceover',return_value={}), \
             patch.object(builder,'apply_script',return_value={'words':[{'word':'Hello','start':0,'end':1}]}), \
             patch.object(ref,'ask_provider',return_value=(plan(),{})) as ask:
            flow.run_project(self.path,self.root/'data')
            state=read_cache(self.path/'reference_style.json')
            self.assertEqual(state['status'],'awaiting_clips')
            self.assertEqual(state['flow_plan']['duration_seconds'],8)
            self.assertEqual(state['flow_clips'],{})
            self.assertIn('EXACT supplied narration',ask.call_args.args[2])
            self.assertIn('Never mention local file paths',ask.call_args.args[2])
            self.assertIn('clip-relative seconds starting at zero',ask.call_args.args[2])
            self.state=state
            self.assign()
            flow.run_project(self.path,self.root/'data')
            self.assertEqual(ask.call_count,1)
            self.assertIn('scene_01',read_cache(self.path/'reference_style.json')['flow_clips'])
            self.assertEqual(len(list((self.path/'reference/flow-history').glob('*.json'))),1)

    def test_replacing_take_preserves_caption_and_framing_choices(self):
        self.assign();self.assign('scene_02','media/flow/two.mp4')
        config=read_cache(self.path/'config.json')
        config['sections'][0].update(captions=False,fit='contain',caption_y=.7)
        write_json(self.path/'config.json',config)
        self.assign()
        row=read_cache(self.path/'config.json')['sections'][0]
        self.assertFalse(row['captions']);self.assertEqual(row['fit'],'contain');self.assertEqual(row['caption_y'],.7)

    def test_completed_worker_keeps_flow_awaiting_import_status(self):
        fake=unittest.mock.MagicMock()
        fake.stdout=[];fake.wait.return_value=0
        job={'id':'flow-plan','project':self.identifier,'action':'reference_plan','status':'running',
             'cancel':False,'logs':[]}
        self.app.job=job
        with patch.object(studio.subprocess,'Popen',return_value=fake) as start:
            self.app.run(job,self.path,read_cache(self.path/'config.json'),0)
        self.assertEqual(start.call_count,1)
        self.assertIn('reference_styles.py',start.call_args.args[0][2])
        self.assertEqual(read_cache(self.path/'reference_style.json')['status'],'awaiting_clips')

    def test_cached_user_prompt_is_a_self_contained_still_image_request(self):
        storyboard=plan()
        storyboard['visual_bible']=(
            'FORMAT AND REFERENCES: Compose every shot vertically at 9:16. '
            'Use reference/frames/sheet-01.jpg, reference/frames/sheet-02.jpg and reference/frames/sheet-03.jpg only as aesthetic references. '
            'They are the supplied contact sheets, not footage or props to reproduce. No additional assets are available.\n'
            'WORLD: A sculptural contemporary cafe inside a lavender architectural studio. Two round ivory tables sit on a pale lilac floor.\n'
            'PALETTE: Background #F1E7F8 and violet #8500BD. Soft upper-left light.\n'
            'CAMERA AND MOTION: Each scene is one achievable continuous shot with no internal cuts. '
            'All motion timestamps are absolute recording times. Scene entry transitions are cuts. '
            'Preserve the supplied Arabic/English narration exactly in the edit; do not generate speech in Flow.')
        scene={**flow.scene_rows(storyboard)[0],
            'continuity':'Duration 3.68 seconds; next shot begins at 3.68. Edit-only narration, unchanged: «متفرحش أوي بشبكة الواي فاي المفتوحة». Maintain the customer ivory overshirt and matte violet phone. Narration and captions are added later in Video Turbo.',
            'image_prompt':'The Egyptian customer holds her violet phone at the ivory table. Warm medium-brown skin, dark curls in a low bun. Leave the upper third open.'}
        storyboard['scenes'][0].update({key:scene[key] for key in ('continuity','image_prompt')})
        before=fingerprint(storyboard)
        prompt=flow.prompt_for(storyboard,scene,'image')
        self.assertTrue(prompt.startswith('Create ONE still image'))
        for forbidden in ('reference/','sheet-01','contact sheets','Edit-only','متفرحش','absolute recording','next shot','Duration 3.68'):
            self.assertNotIn(forbidden,prompt)
            self.assertNotIn(forbidden,flow.export_pack({'flow_plan':storyboard}))
        for keep in ('lavender architectural studio','#8500BD','ivory overshirt','matte violet phone','low bun'):
            self.assertIn(keep,prompt)
        self.assertEqual(fingerprint(storyboard),before)

    def test_cached_recording_time_motion_ranges_become_clip_relative(self):
        storyboard=plan()
        scene={**flow.scene_rows(storyboard)[1], 'start_seconds':3.68,'duration_seconds':3.2,
            'motion_prompt':'One continuous shot, 3.68–6.88. Make a slow lateral slide. At 4.20–5.46, the ribbon develops a darker pulse. At 5.46–6.88, five discs disappear behind the phone. At 6.50 seconds, settle the camera.'}
        prompt=flow.prompt_for(storyboard,scene,'motion')
        for cue in ('0–3.2','0.52–1.78','1.78–3.2','At 2.82 seconds'):
            self.assertIn(cue,prompt)
        for cue in ('3.68–6.88','4.20–5.46','5.46–6.88','6.50 seconds'):
            self.assertNotIn(cue,prompt)

    def test_motion_that_already_starts_at_zero_is_not_shifted_twice(self):
        storyboard=plan()
        scene={**flow.scene_rows(storyboard)[1], 'start_seconds':3.68,'duration_seconds':3.2,
               'motion_prompt':'One continuous shot, 0–3.2. At 0.52–1.78, the ribbon pulses.'}
        prompt=flow.prompt_for(storyboard,scene,'motion')
        self.assertIn('0–3.2',prompt);self.assertIn('0.52–1.78',prompt)

    def test_export_omits_windows_paths_and_unavailable_asset_filenames(self):
        storyboard=plan()
        scene={**flow.scene_rows(storyboard)[0],
            'image_prompt':r'Use C:\private\portrait.png as a reference. Use media/customer.jpg as an ingredient. A woman in an ivory shirt holds a violet phone.'}
        prompt=flow.prompt_for(storyboard,scene,'image')
        self.assertNotIn('portrait.png',prompt);self.assertNotIn('media/',prompt)
        self.assertIn('ivory shirt',prompt);self.assertIn('violet phone',prompt)

    def test_pack_has_consistent_image_motion_prompts_and_generation_lengths(self):
        pack = flow.export_pack(self.state)
        self.assertIn('Frames to Video', pack); self.assertIn('vertical 9:16', pack)
        self.assertEqual(pack.count('ONE 4-second vertical 9:16 video.'), 2)
        self.assertIn('No dialogue, narration', pack)


class FlowHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.app, self.identifier, self.path, self.state = fixture(Path(self.temp.name))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), studio.Handler); self.server.studio = self.app
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.probe = patch.object(ref, 'probe', return_value=(8, [{'codec_type': 'video','width':720,'height':1280}]))
        self.probe.start(); self.addCleanup(self.probe.stop)

    def upload(self, scene='scene_01', token=True, plan_hash=None):
        route = '/api/upload?id='+self.identifier+'&role=flow_clip&scene='+scene+'&name=flow.mp4&plan_hash='+(plan_hash or self.state['plan_hash'])
        headers = {'X-Studio-Token':self.app.token} if token else {}
        return urllib.request.urlopen(urllib.request.Request(self.url+route, data=b'video', headers=headers))

    def test_authenticated_clip_upload_and_export(self):
        with self.upload() as response: result=json.load(response)
        self.assertIn('scene_01', result['project']['reference_style']['flow_clips'])
        with self.upload('scene_02') as response: result=json.load(response)
        self.assertEqual(result['project']['reference_style']['status'], 'ready')
        with urllib.request.urlopen(self.url+'/api/reference/flow/pack?id='+self.identifier) as response:
            self.assertIn('Scene image prompt', json.load(response)['text'])

    def test_bad_uploads_and_missing_auth_do_not_replace_clips(self):
        before = (self.path / 'reference_style.json').read_bytes()
        for kwargs in ({'token':False}, {'scene':'scene_99'}, {'plan_hash':'old'}):
            with self.assertRaises(urllib.error.HTTPError): self.upload(**kwargs)
        with patch.object(ref, 'probe', return_value=(1, [{'codec_type':'video'}])):
            with self.assertRaises(urllib.error.HTTPError): self.upload()
        self.assertEqual(before, (self.path / 'reference_style.json').read_bytes())
        self.assertEqual(list((self.path / 'media/flow').glob('scene_*.mp4')), [])
        self.assertEqual(list((self.path / 'media/flow').glob('.upload-*')), [])


if __name__ == '__main__': unittest.main()
