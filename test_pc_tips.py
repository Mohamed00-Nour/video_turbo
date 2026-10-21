"""Offline tests: no provider calls, desktop input, or paid generation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from PIL import Image

import pc_tips as pc
import pc_tips_ai as local_ai
import reference_styles
import pc_tips_runner as runner
import pc_tips_walkthrough as walkthrough
import video_sections
import video_studio
from pipeline_common import read_cache, write_json, fingerprint


def plan():
    return {'topic': 'Clipboard history', 'topic_key': 'windows-clipboard-history-win-v', 'benefit': 'Find copied text', 'os': 'Windows 10', 'compatibility': 'windows10_only',
        'requirements': ['Use a test desktop'],
        'steps': [{'os': 'Windows 10', 'title': 'Open', 'narration': 'على ويندوز عشرة، افتح سجل النسخ من الاختصار ده', 'goal': 'Open clipboard history', 'verification': 'Clipboard panel is visible'},
                  {'os': 'Windows 10', 'title': 'Use', 'narration': 'اختار النص اللي انت محتاجه دلوقتي', 'goal': 'Select a sample entry', 'verification': 'Sample text is pasted'}],
        'closing': 'وبكده هتوصل للي نسخته بسهولة.', 'sources': [{'title': 'Microsoft support', 'url': 'https://support.microsoft.com/windows'}],
        'post_caption': 'حيلة بسيطة للكمبيوتر'}


def problem_plan():
    value = plan()
    value['problem'] = {'title':'النص القديم ضاع', 'os':value['os'],
        'narration':'بتنسخ حاجة تانية وتضيع منك أول حاجة؟ بص المشكلة دي.',
        'goal':'Show a second copied sample replacing the first pasted value before opening history.',
        'verification':'Only the second sample is pasted.',
        'capture_instructions':['انسخ نص تجريبي، وبعده انسخ نص تاني.', 'اعمل Paste عشان تبين إن النص الأول اتبدل.']}
    for step in value['steps']:
        step['capture_instructions'] = [step['goal'], 'اثبت ثانيتين على النتيجة.']
    return value


class PcTipsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.studio = video_studio.Studio(self.data, self.root / 'projects')
        self.identifier = self.studio.create('PC episode')
        self.project = self.studio.project(self.identifier)

    def seed(self, status='preparing', automatic=False):
        value = {'project': self.identifier, 'part': 1, 'idea': 'A useful shortcut', 'theme': pc.theme(1),
                 'script_model': pc.SCRIPT_MODEL, 'ai_connection': 'chatgpt-sign-in', 'auto_produce': True,
                 'recording_mode': 'automatic' if automatic else 'upload', 'status': status, 'plan': plan(), 'error': ''}
        script = pc.narration(1, value['plan'])
        editor = self.studio.load(self.identifier)['editor']; editor['script'] = script
        self.studio.save(self.identifier, editor)
        value['script_hash'] = fingerprint(script)
        pc.save_state(self.project, value)
        return value

    def asset(self, name, data=b'fixture'):
        target = self.project / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        return target

    def intro(self, project, data, saved):
        self.asset('media/pc-tips/intro.png')
        pc.save_state(project, saved, intro='media/pc-tips/intro.png')

    def test_numbering_survives_restarts_and_rotates_every_theme(self):
        for index in range(1, 8):
            self.assertEqual(pc.reserve(self.data, 'project-' + str(index), 'topic'), index)
        self.assertEqual(pc.next_part(self.data), 8)
        self.assertEqual(len({pc.theme(i)['id'] for i in range(1, 6)}), 5)
        self.assertEqual(pc.theme(6)['id'], pc.theme(1)['id'])

    def test_creation_selects_pc_models_and_voice_before_starting_worker(self):
        with patch('pc_tips_ai.require_connection'), patch('video_studio.threading.Thread') as thread:
            result = self.studio.create_pc_tips('Episode one', 'Help me find files', 'upload', False, 'elevenlabs')
        saved = result['project']['pc_tips']
        self.assertEqual(saved['part'], 1)
        self.assertEqual(saved['script_model'], pc.SCRIPT_MODEL)
        self.assertEqual(saved['ai_connection'], 'google-first-subscriptions')
        self.assertNotIn('image_model', saved)
        self.assertEqual(saved['status'], 'writing_script')
        self.assertEqual(result['job']['action'], 'pc_draft')
        self.assertEqual(result['project']['voice_settings']['source'], 'elevenlabs')
        thread.return_value.start.assert_called_once()

    def test_invalid_creation_does_not_reserve_part_or_create_project(self):
        count = len(self.studio.registry)
        for args in [(None, 'idea'), ('name', None), ('name', 'idea', 'bad'), ('name', 'idea', 'upload', 'yes')]:
            with self.assertRaises(ValueError): self.studio.create_pc_tips(*args)
        for invalid in ('not-a-type', [], None):
            with self.assertRaises(ValueError): self.studio.create_pc_tips(category=invalid)
        self.assertEqual(pc.next_part(self.data), 1)
        self.assertEqual(len(self.studio.registry), count)

    def test_plan_validation_rejects_missing_sources_bad_links_and_bad_steps(self):
        self.assertEqual(pc.validate_plan(plan()), plan())
        for field, value in [('sources', []), ('steps', []), ('requirements', 'none'),
                             ('sources', [{'title': 'bad', 'url': 'javascript:alert(1)'}]),
                             ('sources', [{'title': 'bad', 'url': 'https://secret@example.com'}])]:
            invalid = plan(); invalid[field] = value
            with self.assertRaises(ValueError): pc.validate_plan(invalid)

    def test_draft_uses_research_and_pc_contract_without_game_instructions(self):
        self.seed()
        with patch('pc_tips_ai.ask', return_value=problem_plan()) as ask:
            pc.draft(self.project, self.data)
            args, kwargs = ask.call_args
        self.assertIn(pc.SYSTEM, args[2])
        self.assertIn('Research official sources using web search', args[2])
        self.assertEqual(args[3], pc.PLAN_SCHEMA)
        self.assertEqual(kwargs['model'], pc.SCRIPT_MODEL)
        self.assertIn('PC Tips and Tricks، الجزء 1.', (self.project / 'script.txt').read_text('utf-8'))
        self.assertEqual(pc.state(self.project)['status'], 'preparing')

    def test_uploaded_recording_path_waits_without_generating_voice_or_running_desktop(self):
        self.seed()
        with patch('pc_tips.generate_intro', side_effect=self.intro), patch('pc_tips.ElevenLabs') as voice, patch('pc_tips_runner.record') as record:
            pc.prepare(self.project, self.data)
        self.assertEqual(pc.state(self.project)['status'], 'awaiting_recording')
        voice.assert_not_called(); record.assert_not_called()

    def test_automatic_recording_waits_for_explicit_dedicated_session_configuration(self):
        self.seed(automatic=True)
        with patch('pc_tips.generate_intro', side_effect=self.intro), patch('pc_tips_runner.record') as record:
            pc.prepare(self.project, self.data)
        self.assertEqual(pc.state(self.project)['status'], 'awaiting_runner')
        record.assert_not_called()

    def test_recording_then_uploaded_voice_resumes_without_regenerating_recordings(self):
        saved = self.seed(); self.asset('media/demo.mp4')
        pc.save_state(self.project, saved, recordings=[{'file': 'media/demo.mp4'}])
        info = {'duration': 10, 'width': 1280, 'height': 720}
        with patch('pc_tips.generate_intro', side_effect=self.intro), patch('pc_tips.video_info', return_value=info), patch('pc_tips_runner.record') as record:
            pc.prepare(self.project, self.data)
            self.assertEqual(pc.state(self.project)['status'], 'awaiting_voice')
            self.asset('voiceover.wav')
            pc.prepare(self.project, self.data)
            record.assert_not_called()
        self.assertEqual(pc.state(self.project)['status'], 'ready')
        config = read_cache(self.project / 'config.json')
        self.assertEqual([row['layout'] for row in config['sections']], ['pc_intro', 'pc_demo'])
        self.assertNotIn('games', config)
        self.assertEqual(config['sections'][0]['part'], 1)

    def test_per_step_recordings_follow_narration_phrases_without_game_background(self):
        saved = self.seed()
        saved.update(intro='media/intro.png', recordings=[{'file': 'media/one.mp4'}, {'file': 'media/two.mp4'}])
        for name in ['media/intro.png', 'media/one.mp4', 'media/two.mp4']: self.asset(name)
        with patch('pc_tips.video_info', return_value={'duration': 2, 'width': 1280, 'height': 720}): pc.apply_sections(self.project, saved)
        config = read_cache(self.project / 'config.json')
        words = [{'word': word, 'start': i / 2, 'end': i / 2 + .3}
                 for i, word in enumerate(pc.narration(1, plan()).split())]
        timeline = video_sections.make_timeline(config, self.project, self.project, words, 20, lambda p: 2)
        self.assertEqual(len(timeline['blocks']), 3)
        self.assertTrue(all(block['bgDurationFrames'] == 1 for block in timeline['blocks']))
        self.assertEqual(timeline['totalFrames'], 600)

    def test_script_edit_invalidates_export_and_updates_step_cues(self):
        saved = self.seed(status='complete')
        self.asset('output/final.mp4')
        self.assertTrue(self.studio.load(self.identifier)['final'])
        editor = self.studio.load(self.identifier)['editor']
        editor['script'] = editor['script'].replace('افتح سجل النسخ', 'افتح قائمة النسخ')
        self.studio.save(self.identifier, editor)
        current = pc.state(self.project)
        self.assertEqual(current['status'], 'awaiting_voice')
        self.assertIn('افتح قائمة النسخ', current['plan']['steps'][0]['narration'])
        self.assertFalse(self.studio.load(self.identifier)['final'])

    def test_script_structure_error_keeps_previous_script_and_state(self):
        self.seed(); before = (self.project / 'script.txt').read_bytes()
        editor = self.studio.load(self.identifier)['editor']; editor['script'] = 'arbitrary replacement'
        with self.assertRaisesRegex(ValueError, 'one narration line'): self.studio.save(self.identifier, editor)
        self.assertEqual((self.project / 'script.txt').read_bytes(), before)

    def test_changed_voice_is_not_presented_as_current_final(self):
        saved = self.seed(status='complete'); self.asset('voiceover.wav'); self.asset('output/final.mp4')
        pc.save_state(self.project, saved, voice_signature=pc.voice_signature(self.project))
        self.assertTrue(self.studio.load(self.identifier)['final'])
        self.asset('voiceover.wav', b'new narration')
        self.assertFalse(self.studio.load(self.identifier)['final'])

    def test_intro_cache_reuses_success_and_does_not_replace_on_failed_generation(self):
        saved = self.seed()
        def generated(data, project, prompt, target, **kwargs):
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (256, 384), '#223344').save(target, 'PNG')
        with patch('pc_tips_ai.generate_image', side_effect=generated) as generate:
            target = pc.generate_intro(self.project, self.data, saved)
            before = target.read_bytes()
            pc.generate_intro(self.project, self.data, saved)
            self.assertEqual(generate.call_count, 1)
            saved['part'] = 2
            generate.side_effect = ValueError('Included usage limit')
            with self.assertRaisesRegex(ValueError, 'usage limit'): pc.generate_intro(self.project, self.data, saved)
            self.assertEqual(target.read_bytes(), before)

    def test_pc_jobs_use_one_dedicated_worker_and_no_game_asset_downloader(self):
        self.seed()
        job = {'id': 'job', 'project': self.identifier, 'action': 'pc_produce', 'status': 'running', 'logs': [], 'cancel': False}
        self.studio.job = job
        process = Mock(); process.stdout = []; process.wait.return_value = 0
        with patch('video_studio.subprocess.Popen', return_value=process) as popen:
            self.studio.run(job, self.project, {}, 0)
        command = popen.call_args.args[0]
        self.assertIn('pc_tips.py', str(command))
        self.assertNotIn('prepare_assets.py', str(command))
        self.assertEqual(popen.call_count, 1)

    def test_restart_marks_pc_job_interrupted_in_its_own_state(self):
        self.seed(status='recording')
        write_json(self.data / 'ai/job.json', {'project': self.identifier, 'action': 'pc_produce', 'status': 'running'})
        restarted = video_studio.Studio(self.data, self.root / 'projects')
        self.assertEqual(restarted.load(self.identifier)['pc_tips']['status'], 'interrupted')
        self.assertFalse((self.project / 'ai_workflow.json').exists())


class ClosingTests(unittest.TestCase):
    setUp = PcTipsTests.setUp
    seed = PcTipsTests.seed

    def test_empty_missing_and_whitespace_closing_end_on_the_last_step(self):
        for closing in ('', '  \n\t ', None):
            value=problem_plan();value['closing']=closing
            current=pc.validate_plan(value,require_problem=True)
            self.assertEqual(current['closing'],'')
            script=pc.narration(4,current)
            self.assertTrue(script.endswith(current['steps'][-1]['narration']))
            self.assertEqual(len(script.splitlines()),len(pc.tutorial_shots(current))+1)
        value=problem_plan();value.pop('closing')
        self.assertEqual(pc.validate_plan(value)['closing'],'')

    def test_closing_limit_still_rejects_overlong_or_nontext_values(self):
        value=problem_plan();value['closing']='x'*500
        self.assertEqual(len(pc.validate_plan(value)['closing']),500)
        for closing in ('x'*501, [], 12):
            value['closing']=closing
            with self.assertRaisesRegex(ValueError,'closing'):pc.validate_plan(value)

    def test_editing_a_script_without_closing_keeps_every_solution_line(self):
        saved=self.seed();value=problem_plan();value['closing']=''
        script=pc.narration(1,value);pc.save_state(self.project,saved,plan=value,script_hash=fingerprint(script))
        edited=script.replace(value['steps'][0]['narration'],'افتح الخطوة الأولى دلوقتي.')
        pc.sync_script(self.project,saved,edited)
        current=pc.state(self.project)
        self.assertEqual(current['plan']['steps'][-1]['narration'],value['steps'][-1]['narration'])
        self.assertEqual(current['plan']['closing'],'')
        pc.sync_script(self.project,current,edited+'\nوبكده خلصنا.')
        current=pc.state(self.project)
        self.assertEqual(current['plan']['closing'],'وبكده خلصنا.')
        pc.sync_script(self.project,current,edited)
        self.assertEqual(pc.state(self.project)['plan']['closing'],'')

    def test_automatic_draft_with_no_closing_continues_without_extra_model_call(self):
        self.seed();value=problem_plan();value['closing']=''
        with patch('pc_tips_ai.ask',return_value=value) as ask:pc.draft(self.project,self.data)
        ask.assert_called_once()
        saved=pc.state(self.project)
        self.assertEqual(saved['status'],'preparing');self.assertEqual(saved['part'],1)
        self.assertEqual(saved['plan']['closing'],'')
        self.assertTrue((self.project/'script.txt').read_text('utf-8').endswith(value['steps'][-1]['narration']))

    def test_overlong_closing_is_repaired_without_changing_the_chosen_tip(self):
        self.seed();value=problem_plan();value['closing']='x'*501
        with patch('pc_tips_ai.ask',side_effect=[value,{'closing':''}]) as ask:pc.draft(self.project,self.data)
        self.assertEqual(ask.call_count,2)
        self.assertIn('Shorten only',ask.call_args.args[2])
        saved=pc.state(self.project)
        self.assertEqual(saved['plan']['topic_key'],value['topic_key'])
        self.assertEqual(saved['plan']['steps'],value['steps'])
        self.assertEqual(saved['part'],1)
        self.assertEqual(saved['status'],'preparing')
        self.assertEqual(saved['plan']['closing'],'')
        self.assertTrue((self.project/'reference/pc-tips-draft.json').exists())


class WindowsVersionTests(unittest.TestCase):
    setUp = PcTipsTests.setUp
    seed = PcTipsTests.seed
    asset = PcTipsTests.asset

    def different_paths(self):
        value = plan()
        value['steps'][0].update(narration='على ويندوز عشرة، افتح Ease of Access وبعدها Display.',
                                 goal='Open Settings > Ease of Access > Display.')
        value['steps'][1].update(narration='اقفل Show animations in Windows لو شغالة.',
                                 goal='Turn off Show animations in Windows if enabled.')
        return value

    def test_windows10_is_announced_once_and_validation_is_idempotent(self):
        value = pc.validate_plan(self.different_paths())
        self.assertEqual(pc.narration(2, value).count('على ويندوز عشرة،'), 1)
        self.assertEqual(pc.validate_plan(value), value)
        self.assertEqual(pc.PLAN_SCHEMA['properties']['os']['enum'], ['Windows 10'])
        self.assertEqual(pc.PLAN_SCHEMA['properties']['compatibility']['enum'], ['windows10_only'])

    def test_mixed_and_windows11_plans_are_rejected(self):
        import copy
        for version, mode in [('Windows 11','windows11_only'),('Windows 10 & 11','same_steps'),
                              ('Windows 10 & 11','different_steps'),('Windows 10','same_steps')]:
            value = plan(); value.update(os=version, compatibility=mode)
            with self.assertRaises(ValueError): pc.validate_plan(value)
        for field in ('os', 'narration', 'goal', 'verification'):
            value = plan(); value['steps'][0][field] = 'Windows 11'
            with self.assertRaises(ValueError): pc.validate_plan(value)
        value = problem_plan(); value['problem']['os'] = 'Windows 11'
        with self.assertRaises(ValueError): pc.validate_plan(value)
        value = plan(); value['requirements'] = ['Windows 11 only']
        with self.assertRaises(ValueError): pc.validate_plan(value)

    def test_tutorial_shots_use_windows10_for_real_and_animated_footage(self):
        saved = self.seed()
        saved.update(plan=pc.validate_plan(self.different_paths()), intro='media/intro.png',
                     recordings=[{'file':'media/one.mp4'}, {'file':'media/two.mp4'}])
        for name in ('media/intro.png','media/one.mp4','media/two.mp4'): self.asset(name)
        for source in ('recorded','illustrated'):
            saved['visual_source'] = source
            with patch('pc_tips.video_info',return_value={'duration':3,'width':1280,'height':720}):
                pc.apply_sections(self.project, saved)
            rows = read_cache(self.project / 'config.json')['sections'][1:]
            self.assertTrue(all(row['label'].startswith('Windows 10') for row in rows))

    def test_legacy_conversion_keeps_part_and_topic_and_detaches_old_footage(self):
        saved = self.seed(status='complete'); old = plan()
        old.update(os='Windows 10 & 11',compatibility='same_steps')
        for row in old['steps']: row['os']='Windows 10 & 11'
        self.asset('media/old.mp4'); self.asset('voiceover.wav')
        pc.save_state(self.project,saved,plan=old,recordings=[{'file':'media/old.mp4'}])
        self.assertTrue(pc.state(self.project)['windows_stale'])
        with patch('pc_tips_ai.ask',return_value=problem_plan()) as ask:
            pc.convert_to_windows10(self.project,self.data)
        current=pc.state(self.project)
        self.assertFalse(current['windows_stale']); self.assertEqual(current['part'],saved['part'])
        self.assertEqual(current['plan']['topic_key'],old['topic_key'])
        self.assertEqual(current['recordings'],[]); self.assertTrue(current['needs_voice_upload'])
        self.assertTrue((self.project/'media/old.mp4').exists())
        self.assertEqual(read_cache(self.project/'reference/pre-windows10-plan.json'),old)
        with patch('pc_tips_ai.ask') as ask: pc.convert_to_windows10(self.project,self.data)
        ask.assert_not_called()

    def test_legacy_episode_without_topic_key_can_be_researched_for_windows10(self):
        saved=self.seed(); saved['plan'].pop('topic_key');saved['plan']['os']='Windows 11'
        for step in saved['plan']['steps']:step.pop('os')
        pc.save_state(self.project,saved)
        with patch('pc_tips_ai.ask',return_value=problem_plan()): pc.convert_to_windows10(self.project,self.data)
        self.assertEqual(pc.state(self.project)['plan']['topic_key'],plan()['topic_key'])

    def test_rejected_conversion_preserves_existing_episode(self):
        saved = self.seed(); saved['plan']['os']='Windows 11'; pc.save_state(self.project,saved)
        script=(self.project/'script.txt').read_text('utf-8')
        with patch('pc_tips_ai.ask',return_value=saved['plan']):
            with self.assertRaises(ValueError): pc.convert_to_windows10(self.project,self.data)
        self.assertEqual(pc.state(self.project)['plan'],saved['plan'])
        self.assertEqual((self.project/'script.txt').read_text('utf-8'),script)

    def test_recording_refuses_windows11_before_desktop_input(self):
        from types import SimpleNamespace
        with patch('pc_tips.settings',return_value={'runner_enabled':True}), patch('pc_tips_runner.os.name','nt'), \
             patch('pc_tips_runner.sys.getwindowsversion',return_value=SimpleNamespace(major=10,build=22631),create=True), \
             patch('pc_tips_runner.Desktop') as desktop:
            with self.assertRaisesRegex(ValueError,'Windows 10'): runner.record(self.project,self.data,self.seed())
        desktop.assert_not_called()



class AutomaticIdeaTests(unittest.TestCase):
    setUp = PcTipsTests.setUp
    asset = PcTipsTests.asset
    seed = PcTipsTests.seed
    intro = PcTipsTests.intro

    def automatic(self):
        saved = self.seed(automatic=True)
        saved.update(category='shortcuts', idea='', idea_source='automatic')
        saved.pop('plan', None)
        pc.save_state(self.project, saved)
        return saved

    def test_chooses_idea_from_type_and_saves_it_to_history(self):
        saved = self.automatic()
        pc.reserve(self.data, self.identifier, '', 'shortcuts')
        with patch('pc_tips_ai.ask', return_value=problem_plan()) as ask:
            pc.draft(self.project, self.data)
        prompt = ask.call_args.args[2]
        self.assertIn('Shortcuts & easier use', prompt)
        self.assertIn('Choose one specific', prompt)
        self.assertEqual(pc.state(self.project)['idea'], plan()['topic'])
        episode = read_cache(self.data / 'pc_tips/series.json')['episodes'][0]
        self.assertEqual(episode['topic_key'], plan()['topic_key'])
        self.assertEqual(episode['category'], 'shortcuts')
        self.assertEqual(pc.state(self.project)['status'], 'preparing')

    def test_duplicate_technique_is_rechosen_even_with_different_title(self):
        self.automatic()
        write_json(self.data / 'pc_tips/series.json', {'episodes':[{'project':'previous', 'topic':'Old title',
                   'topic_key':plan()['topic_key'], 'idea':'', 'category':'shortcuts'}]})
        fresh = problem_plan(); fresh.update(topic='Switch between windows', topic_key='windows-switch-apps-alt-tab')
        with patch('pc_tips_ai.ask', side_effect=[problem_plan(), fresh]) as ask:
            pc.draft(self.project, self.data)
        self.assertEqual(ask.call_count, 2)
        self.assertIn('rejected_duplicate', ask.call_args.args[2])
        self.assertEqual(pc.state(self.project)['plan']['topic_key'], fresh['topic_key'])

    def test_repeated_duplicate_stops_without_saving_reused_plan(self):
        self.automatic()
        write_json(self.data / 'pc_tips/series.json', {'episodes':[{'project':'previous', 'topic':plan()['topic'],
                   'topic_key':plan()['topic_key'], 'idea':''}]})
        with patch('pc_tips_ai.ask', return_value=problem_plan()) as ask:
            with self.assertRaisesRegex(ValueError, 'repeated a previous tip'): pc.draft(self.project, self.data)
        self.assertEqual(ask.call_count, 2)
        self.assertNotIn('plan', pc.state(self.project))

    def test_production_preferences_are_saved_and_reused(self):
        pc.configure(self.data, {'voice_source':'upload', 'recording_mode':'upload', 'auto_produce':False})
        with patch('pc_tips_ai.require_connection'), patch('video_studio.threading.Thread'):
            result = self.studio.create_pc_tips(category='apps')
        saved = result['project']['pc_tips']
        self.assertEqual(saved['category'], 'apps')
        self.assertFalse(saved['auto_produce']); self.assertEqual(saved['recording_mode'], 'upload')
        self.assertEqual(result['project']['voice_settings']['source'], 'upload')

    def test_automatic_creation_proceeds_to_render_without_idea_or_review_handoff(self):
        pc.configure(self.data, {'runner_enabled':True, 'recording_mode':'automatic'})
        with patch('pc_tips_ai.require_connection'), patch('video_studio.threading.Thread'):
            created = self.studio.create_pc_tips(category='organization')
        self.project = self.studio.project(created['project']['id'])
        self.asset('media/demo.mp4')
        def generate_voice(project):
            self.asset('voiceover.wav')
        with patch('pc_tips_ai.ask', return_value=problem_plan()), patch('pc_tips.generate_intro', side_effect=self.intro), patch('pc_tips.video_info', return_value={'duration':10,'width':1280,'height':720}), patch('pc_tips_runner.record', return_value=[{'file':'media/demo.mp4'}]) as record, patch('pc_tips.ElevenLabs') as voice, patch('pc_tips.build') as build, patch('sys.argv', ['pc_tips.py','--project',str(self.project),'--data',str(self.data),'--draft']):
            voice.return_value.snapshot.return_value = {'configured':True, 'defaults':{'voice_id':'default-voice','model_id':'default-model'}}
            voice.return_value.generate.side_effect = generate_voice
            self.assertEqual(pc.main(), 0)
        record.assert_called_once(); voice.return_value.generate.assert_called_once()
        build.assert_called_once()
        self.assertEqual(pc.state(self.project)['status'], 'ready')
        self.assertEqual(read_cache(self.project / 'voiceover.json')['voice_id'], 'default-voice')

    def test_missing_voice_setup_keeps_assets_and_waits_for_saved_default(self):
        saved = self.seed()
        self.asset('media/demo.mp4'); pc.save_state(self.project, saved, recordings=[{'file':'media/demo.mp4'}])
        write_json(self.project / 'voiceover.json', {'source':'elevenlabs'})
        with patch('pc_tips.generate_intro', side_effect=self.intro), patch('pc_tips.video_info', return_value={'duration':10,'width':1280,'height':720}), patch('pc_tips.ElevenLabs') as voice:
            voice.return_value.snapshot.return_value = {'configured':False,'defaults':{}}
            pc.prepare(self.project, self.data)
            self.assertEqual(pc.state(self.project)['status'], 'awaiting_voice_setup')
            voice.return_value.generate.assert_not_called()
            voice.return_value.snapshot.return_value = {'configured':True,'defaults':{'voice_id':'my-voice','model_id':'speech-model'}}
            voice.return_value.generate.side_effect = lambda project: self.asset('voiceover.wav')
            pc.prepare(self.project, self.data)
        self.assertEqual(pc.state(self.project)['status'], 'ready')



def storyboard():
    return {'steps': [{'scenes': [{'options':[], 'before':'', 'surface':'clipboard', 'title': 'Clipboard', 'path': ['Windows', 'Clipboard'],
        'rows': [{'label': 'Sample text', 'value': ''}], 'focus': 0, 'action': 'shortcut',
        'keys': ['Win', 'V'], 'note': 'افتح سجل النسخ'}]} for _ in plan()['steps']]}


def window_storyboard():
    import copy
    windows = [{'app':'notepad','placement':'floating','text':'125 + 75'},
               {'app':'calculator','placement':'floating','text':'0'}]
    def scene(action, focus, active, keys=(), assist=False, before=''):
        return {'surface':'windows','title':'Notepad and Calculator','path':['Desktop'],
                'rows':[], 'focus':focus,'action':action,'keys':list(keys),'note':'\u0631\u062a\u0628 \u0627\u0644\u0634\u0628\u0627\u0643\u064a\u0646.',
                'before':before,'options':[], 'windows':copy.deepcopy(windows),
                'active_window':active,'snap_assist':assist}
    problem = [scene('activate_window',1,0),scene('activate_window',0,1)]
    left = [scene('snap_left',0,0,['Win','Left'],True)]
    windows[0]['placement']='left'
    right = [scene('activate_window',1,0),scene('snap_right',1,1,['Win','Right'])]
    windows[1]['placement']='right';windows[1]['text']='200'
    right.append(scene('calculate',1,1,before='125 + 75'))
    right.append(scene('result',1,1))
    return {'steps':[{'scenes':problem},{'scenes':left},{'scenes':right}]}


def transparency_plan():
    value=problem_plan()
    value.update(topic='Remove acrylic transparency',topic_key=walkthrough.PERFORMANCE_TOPIC,
                 benefit='Remove GPU-intensive acrylic; demonstrate the visual change only.')
    return value


def transparency_storyboard():
    def scene(surface,transparency,action,rows,path,keys=()):
        return {'surface':surface,'title':path[-1],'path':path,'rows':rows,'focus':0,'action':action,
                'keys':list(keys),'note':'Show the actual visual effect.','transparency':transparency,
                'before':'','options':[],'windows':[],'active_window':0,'snap_assist':False}
    apps=[{'label':'Notepad','value':''},{'label':'Settings','value':''}]
    opening=scene('start','on','shortcut',apps,['Start'],['Ctrl','Esc'])
    toggle=scene('settings','on','toggle_off',[{'label':'Transparency effects','value':'Off'}],
                 ['Settings','Personalization','Colors'])
    ending=scene('start','off','shortcut',apps,['Start'],['Ctrl','Esc'])
    return {'steps':[{'scenes':[opening]},{'scenes':[toggle]},{'scenes':[ending]}]}


class WalkthroughTests(unittest.TestCase):
    setUp = PcTipsTests.setUp
    seed = PcTipsTests.seed
    asset = PcTipsTests.asset
    intro = PcTipsTests.intro

    def test_transparency_effect_changes_through_the_documented_toggle(self):
        value=walkthrough.validate(transparency_storyboard(),transparency_plan())
        self.assertEqual([step['scenes'][0]['transparency'] for step in value['steps']],['on','on','off'])

    def test_transparency_requires_a_real_toggle_and_repeated_start_action(self):
        import copy
        for fault in ('missing_state','fake_change','wrong_path','wrong_before','different_apps','different_action'):
            value=copy.deepcopy(transparency_storyboard())
            if fault=='missing_state':value['steps'][2]['scenes'][0].pop('transparency')
            elif fault=='fake_change':value['steps'][1]['scenes'][0]['action']='result'
            elif fault=='wrong_path':value['steps'][1]['scenes'][0]['path']=['Settings','System','Display']
            elif fault=='wrong_before':value['steps'][1]['scenes'][0]['transparency']='off'
            elif fault=='different_apps':value['steps'][2]['scenes'][0]['rows']=[{'label':'Mail','value':''}]
            else:value['steps'][2]['scenes'][0]['action']='result'
            with self.subTest(fault=fault),self.assertRaises(ValueError):
                walkthrough.validate(value,transparency_plan())

    def test_transparency_quality_review_samples_the_repeated_final_action(self):
        saved=self.seed();saved.update(plan=transparency_plan(),visual_source='illustrated')
        self.asset('output/final.mp4')
        write_json(self.project/'output/timeline.json',{'fps':30,'blocks':[
            {'layout':'pc_demo','startFrame':60,'durationFrames':120},
            {'layout':'pc_demo','startFrame':360,'durationFrames':120}]})
        def extract(command,**kwargs):
            Path(command[-1]).write_bytes(b'image');return Mock(returncode=0)
        with patch('pc_tips.subprocess.run',side_effect=extract) as run, \
             patch('pc_tips_ai.ask',return_value={'passed':True,'issues':[]}) as ask:
            pc.quality_check(self.project,self.data,saved,{'duration':20})
        times=[float(call.args[0][call.args[0].index('-ss')+1]) for call in run.call_args_list]
        self.assertIn(5,times);self.assertIn(15,times)
        self.assertIn('final background must be opaque',ask.call_args.args[2])

    def test_animated_mode_needs_no_desktop_session_and_reaches_ready(self):
        saved = self.seed()
        pc.save_state(self.project, saved, recording_mode='illustrated')
        self.asset('voiceover.wav')
        def animate(project, data, current):
            rows = [{'file': 'media/step-1.mp4'}, {'file': 'media/step-2.mp4'}]
            for row in rows: self.asset(row['file'])
            pc.save_state(project, current, recordings=rows, visual_source='illustrated')
        with patch('pc_tips.generate_intro', side_effect=self.intro), patch('pc_tips_walkthrough.generate', side_effect=animate), patch('pc_tips_runner.record') as record, patch('pc_tips.video_info', return_value={'duration':8,'width':1024,'height':960}):
            pc.prepare(self.project, self.data)
        record.assert_not_called()
        saved = pc.state(self.project)
        self.assertEqual(saved['status'], 'ready')
        rows = read_cache(self.project / 'config.json')['sections'][1:]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all('شرح توضيحي' in row['label'] for row in rows))

    def test_switching_modes_keeps_script_voice_and_part_but_detaches_old_footage(self):
        saved = self.seed(status='complete'); self.asset('voiceover.wav')
        saved.update(recordings=[{'file':'media/real.mp4'}], quality_check={'passed':True}, visual_source='recorded')
        pc.save_state(self.project, saved)
        with patch('pc_tips_ai.require_connection'), patch('video_studio.threading.Thread'):
            result = self.studio.start_pc_tips(self.identifier, 'illustrated')
        current = result['project']['pc_tips']
        self.assertEqual(current['part'], 1); self.assertEqual(current['script_hash'], saved['script_hash'])
        self.assertEqual(current['recording_mode'], 'illustrated'); self.assertEqual(current['recordings'], [])
        self.assertEqual(current['quality_check'], {})
        self.assertTrue((self.project/'voiceover.wav').exists())
        pc.change_mode(current, 'upload')
        self.assertEqual(current['recording_mode'], 'upload')
        with self.assertRaises(ValueError): pc.change_mode(current, 'unknown')

    def test_saved_animated_preference_is_available_to_new_episodes(self):
        pc.configure(self.data, {'recording_mode':'illustrated'})
        with patch('pc_tips_ai.require_connection'), patch('video_studio.threading.Thread'):
            created = self.studio.create_pc_tips(category='apps')
        self.assertEqual(created['project']['pc_tips']['recording_mode'], 'illustrated')

    def test_storyboard_requires_all_steps_and_bounded_valid_interactions(self):
        self.assertEqual(walkthrough.validate(storyboard(), plan()), storyboard())
        import copy
        invalid = storyboard(); invalid['steps'].pop()
        with self.assertRaises(ValueError): walkthrough.validate(invalid, plan())
        for field, value in [('focus',8), ('focus',True), ('action','shell'), ('keys',[]), ('path',[]),
                             ('rows',[]), ('surface','windows11'), ('note','x'*101)]:
            invalid = copy.deepcopy(storyboard())
            invalid['steps'][0]['scenes'][0][field] = value
            with self.assertRaises(ValueError): walkthrough.validate(invalid, plan())

    def test_missing_problem_reports_expected_count_and_role(self):
        with self.assertRaisesRegex(ValueError, r'expected 3 steps \(problem, solution, solution\), received 2'):
            walkthrough.validate(storyboard(), problem_plan())

    def test_window_storyboard_covers_overlap_snapping_and_verified_calculation(self):
        value=window_storyboard()
        self.assertEqual(walkthrough.validate(value,problem_plan()),value)
        import copy
        mutations = [
            (0,0,'windows',[{'app':'browser','placement':'floating','text':'0'}]),
            (1,0,'keys',['Win','Right']),
            (1,0,'active_window',True),
            (1,0,'active_window',1),
            (2,2,'before','125 + 76'),
            (2,2,'before','125; print(75)'),
            (2,2,'snap_assist',True),
            (2,2,'focus',0),
        ]
        for step,scene,field,replacement in mutations:
            with self.subTest(field=field,replacement=replacement):
                invalid=copy.deepcopy(value);invalid['steps'][step]['scenes'][scene][field]=replacement
                with self.assertRaises(ValueError):walkthrough.validate(invalid,problem_plan())
        invalid=copy.deepcopy(value)
        invalid['steps'][2]['scenes'][0]['windows'][0]['placement']='floating'
        with self.assertRaisesRegex(ValueError,'Preserve window placements'):
            walkthrough.validate(invalid,problem_plan())

    def test_generation_contract_counts_problem_and_all_solution_shots(self):
        saved=self.seed();saved['plan']=problem_plan()
        process=Mock();process.stdout=iter([]);process.wait.return_value=0
        def candidate(data,project,prompt,schema,**kwargs):
            self.assertIn('Return exactly 3 entries',prompt)
            self.assertEqual(schema['properties']['steps']['minItems'],3)
            self.assertEqual(schema['properties']['steps']['maxItems'],3)
            self.assertEqual(kwargs['repair_attempts'],1)
            payload=json.loads(prompt.split('required_shots order. ')[1])
            self.assertEqual([shot['role'] for shot in payload['required_shots']],['problem','solution','solution'])
            self.assertIn('snapping left/right',kwargs['quality_prompt'])
            return window_storyboard()
        with patch('pc_tips_ai.ask',side_effect=candidate),patch('pc_tips_walkthrough.subprocess.Popen',return_value=process),patch('pc_tips.video_info'):
            walkthrough.generate(self.project,self.data,saved)
        manifest=read_cache(self.project/'media/pc-tips/walkthrough.json')
        self.assertEqual([step['phase'] for step in manifest['steps']],['problem','solution','solution'])

    def test_dropdown_uses_actual_before_and_after_options(self):
        value=storyboard(); scene=value['steps'][0]['scenes'][0]
        scene.update(surface='settings',title='Mouse',path=['Settings','Devices','Mouse'],
                     action='choose',before='Right',options=['Left','Right'],keys=[],
                     rows=[{'label':'Select your primary button','value':'Left'}])
        self.assertEqual(walkthrough.validate(value,plan()),value)
        for before,options in [('', ['Left','Right']),('Right',['Left']),('Left',['Left','Right']),('Right',['Left','Left'])]:
            scene.update(before=before,options=options)
            with self.assertRaises(ValueError): walkthrough.validate(value,plan())

    def test_storyboard_and_local_clips_are_reused_without_new_model_request(self):
        saved = self.seed()
        process = Mock(); process.stdout = iter([]); process.wait.return_value=0
        with patch('pc_tips_ai.ask', return_value=storyboard()) as ask, patch('pc_tips_walkthrough.subprocess.Popen', return_value=process) as render, patch('pc_tips.video_info', return_value={'duration':8}):
            walkthrough.generate(self.project, self.data, saved)
            process.stdout = iter([])
            walkthrough.generate(self.project, self.data, saved)
        ask.assert_called_once()
        self.assertEqual(render.call_count,2)
        manifest=read_cache(self.project/'media/pc-tips/walkthrough.json')
        self.assertEqual(len(manifest['steps']),len(plan()['steps']))
        self.assertEqual(manifest['steps'][0]['os'], 'Windows 10')
        self.assertEqual(pc.state(self.project)['visual_source'], 'illustrated')
        self.assertEqual(pc.state(self.project)['recording_report'], [])

    def test_resuming_animation_replaces_stale_clip_references(self):
        saved=self.seed();self.asset('voiceover.wav');self.asset('media/old.mp4');self.asset('media/new.mp4')
        pc.save_state(self.project,saved,recording_mode='illustrated',visual_source='illustrated',recordings=[{'file':'media/old.mp4'}])
        def refresh(project,data,current):
            pc.save_state(project,current,recordings=[{'file':'media/new.mp4'}],visual_source='illustrated')
        with patch('pc_tips.generate_intro',side_effect=self.intro),patch('pc_tips_walkthrough.generate',side_effect=refresh),patch('pc_tips.video_info',return_value={'duration':8}):
            pc.prepare(self.project,self.data)
        rows=read_cache(self.project/'config.json')['sections']
        self.assertEqual(rows[1]['media'],'media/new.mp4')
        self.assertEqual(pc.state(self.project)['status'],'ready')

    def test_quality_review_uses_illustration_contract(self):
        saved = self.seed(); saved['visual_source']='illustrated'; self.asset('output/final.mp4')
        def extract(command, **kwargs):
            Path(command[-1]).write_bytes(b'image')
            return Mock(returncode=0)
        with patch('pc_tips.subprocess.run',side_effect=extract), patch('pc_tips_ai.ask',return_value={'passed':True,'issues':[]}) as ask:
            pc.quality_check(self.project,self.data,saved,{'duration':30})
        prompt=ask.call_args.args[2]
        self.assertIn('not a live desktop recording',prompt)
        self.assertIn('illustration label must be visible',prompt)


class ProblemFirstTests(unittest.TestCase):
    setUp = PcTipsTests.setUp
    seed = PcTipsTests.seed
    asset = PcTipsTests.asset
    intro = PcTipsTests.intro

    def test_new_plan_requires_problem_and_concrete_capture_actions(self):
        value=pc.validate_plan(problem_plan(),require_problem=True)
        self.assertEqual(value['problem']['title'],problem_plan()['problem']['title'])
        for field in ('problem','capture_instructions'):
            invalid=problem_plan()
            if field=='problem': invalid.pop(field)
            else: invalid['steps'][0].pop(field)
            with self.assertRaises(ValueError): pc.validate_plan(invalid,require_problem=True)

    def test_problem_narration_precedes_solution_and_can_be_edited(self):
        saved=self.seed(); value=problem_plan()
        script=pc.narration(1,value)
        self.assertEqual(script.splitlines()[1],value['problem']['narration'])
        self.assertEqual(script.splitlines()[2],value['steps'][0]['narration'])
        pc.save_state(self.project,saved,plan=value,script_hash=fingerprint(script))
        changed=script.replace(value['problem']['narration'],'المشكلة دي بتحصل معاك؟')
        pc.sync_script(self.project,saved,changed)
        self.assertEqual(pc.state(self.project)['plan']['problem']['narration'],'المشكلة دي بتحصل معاك؟')

    def test_clips_and_whole_upload_start_on_the_problem_cue(self):
        saved=self.seed()
        saved.update(plan=problem_plan(),intro='media/intro.png',visual_source='illustrated')
        for name in ('media/intro.png','media/problem.mp4','media/body1.mp4','media/body2.mp4'):self.asset(name)
        saved['recordings']=[{'file':'media/'+name+'.mp4'} for name in ('problem','body1','body2')]
        with patch('pc_tips.video_info',return_value={'duration':4}):
            pc.apply_sections(self.project,saved)
            rows=read_cache(self.project/'config.json')['sections']
            self.assertEqual(len(rows),4)
            self.assertEqual(rows[1]['media'],'media/problem.mp4')
            self.assertEqual(rows[1]['start_phrase'],' '.join(saved['plan']['problem']['narration'].split()[:4]))
            self.assertEqual(rows[2]['title'],saved['plan']['steps'][0]['title'])
            saved['recordings']=saved['recordings'][:1]
            pc.apply_sections(self.project,saved)
            rows=read_cache(self.project/'config.json')['sections']
            self.assertEqual(rows[1]['start_phrase'],' '.join(saved['plan']['problem']['narration'].split()[:4]))

    def test_checklist_has_problem_first_and_windows_specific_actions(self):
        value=problem_plan()
        value['steps']=WindowsVersionTests.different_paths(self)['steps']
        for step in value['steps']:step['capture_instructions']=[step['goal']]
        rows=pc.recording_guide(value)
        self.assertEqual(rows[0]['role'],'problem')
        self.assertEqual([r['os'] for r in rows[1:]],['Windows 10','Windows 10'])
        self.assertTrue(all(r['actions'] and r['result'] for r in rows))

    def test_upgrading_preserves_body_and_keeps_old_files_but_requests_new_uploaded_voice(self):
        saved=self.seed(status='complete');self.asset('voiceover.wav');self.asset('media/old.mp4')
        saved['recordings']=[{'file':'media/old.mp4'}];pc.save_state(self.project,saved)
        response={'problem':problem_plan()['problem'],'steps':[{'capture_instructions':[step['goal']]} for step in plan()['steps']]}
        with patch('pc_tips_ai.ask',return_value=response):
            pc.add_problem_opening(self.project,self.data)
        current=pc.state(self.project)
        self.assertEqual(current['part'],saved['part'])
        self.assertEqual(current['plan']['steps'][0]['narration'],saved['plan']['steps'][0]['narration'])
        self.assertEqual(current['recordings'],[])
        self.assertTrue(current['needs_voice_upload'])
        self.assertTrue((self.project/'media/old.mp4').exists())
        self.assertEqual((self.project/'reference/pre-problem-script.txt').read_text('utf-8'),pc.narration(1,plan()))
        self.assertIn(current['plan']['problem']['narration'],(self.project/'script.txt').read_text('utf-8'))
        with patch('pc_tips_ai.ask') as ask: pc.add_problem_opening(self.project,self.data)
        ask.assert_not_called()

    def test_incomplete_upgrade_leaves_old_script_and_plan_untouched(self):
        self.seed()
        original=(self.project/'script.txt').read_text('utf-8')
        with patch('pc_tips_ai.ask',return_value={'problem':problem_plan()['problem'],'steps':[]}):
            with self.assertRaises(ValueError):pc.add_problem_opening(self.project,self.data)
        self.assertEqual((self.project/'script.txt').read_text('utf-8'),original)
        self.assertNotIn('problem',pc.state(self.project)['plan'])

    def test_updated_uploaded_narration_waits_instead_of_using_old_audio(self):
        saved=self.seed();self.asset('voiceover.wav');self.asset('media/whole.mp4')
        pc.save_state(self.project,saved,plan=problem_plan(),recordings=[{'file':'media/whole.mp4'}],needs_voice_upload=True)
        with patch('pc_tips.generate_intro',side_effect=self.intro),patch('pc_tips.video_info',return_value={'duration':20}):
            pc.prepare(self.project,self.data)
        self.assertEqual(pc.state(self.project)['status'],'awaiting_voice')
        self.assertTrue(pc.state(self.project)['needs_voice_upload'])

    def test_animation_shots_include_problem_phase_and_shorter_opening(self):
        saved=self.seed();saved['plan']=problem_plan()
        scenes=storyboard();scenes['steps'].insert(0,scenes['steps'][0])
        process=Mock();process.stdout=iter([]);process.wait.return_value=0
        with patch('pc_tips_ai.ask',return_value=scenes),patch('pc_tips_walkthrough.subprocess.Popen',return_value=process),patch('pc_tips.video_info',return_value={'duration':4}):
            walkthrough.generate(self.project,self.data,saved)
        manifest=read_cache(self.project/'media/pc-tips/walkthrough.json')
        self.assertEqual(manifest['steps'][0]['phase'],'problem')
        self.assertTrue(90<=manifest['steps'][0]['frames']<=150)
        self.assertEqual(manifest['steps'][1]['phase'],'solution')


class ActionTests(unittest.TestCase):
    def test_invalid_actions_never_reach_desktop(self):
        bad = [[{'type': 'shell', 'command': 'bad'}], [{'type': 'click', 'x': -1, 'y': 5}],
               [{'type': 'click', 'x': 50, 'y': 100}], [{'type': 'keypress', 'keys': ['made-up-key']}],
               [{'type': 'scroll', 'x': 1, 'y': 1, 'scroll_y': 100000}], [{'type': 'type', 'text': 'x' * 1001}]]
        for actions in bad:
            with self.assertRaises(ValueError): runner.validate_actions(actions, 100, 100)

    def test_supported_actions_use_bounded_screen_coordinates(self):
        actions = [{'type': 'keypress', 'keys': ['META', 'V']}, {'type': 'click', 'x': 40, 'y': 50, 'button': 'left'}]
        self.assertEqual(runner.validate_actions(actions, 100, 100), actions)
        self.assertEqual(runner.key_code('WIN'), 0x5B)


class PcHttpTests(unittest.TestCase):
    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        PcTipsTests.setUp(self)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), video_studio.Handler)
        self.server.studio = self.studio
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    seed = PcTipsTests.seed
    asset = PcTipsTests.asset

    def request(self, route, value=None, token=True, raw=None):
        import urllib.request
        headers = {'X-Studio-Token': self.studio.token} if token else {}
        payload = raw if raw is not None else json.dumps(value).encode('utf-8') if value is not None else None
        request = urllib.request.Request(self.url + route, data=payload, headers=headers)
        with urllib.request.urlopen(request) as response: return json.load(response)

    def test_settings_are_readable_without_exposing_credentials(self):
        value = self.request('/api/pc-tips/settings')
        self.assertEqual(value['next_part'], 1)
        self.assertEqual(value['script_model'], pc.SCRIPT_MODEL)
        self.assertFalse(value['runner_enabled'])
        self.assertEqual(value['voice_source'], 'elevenlabs')
        self.assertIn('illustrated',value['recording_modes'])
        self.assertTrue(value['auto_produce'])
        self.assertEqual({row['id'] for row in value['categories']}, set(pc.CATEGORIES))
        self.assertNotIn('api_key', value)

    def test_category_only_request_names_episode_and_starts_automatic_production(self):
        with patch('pc_tips_ai.require_connection'), patch.object(self.studio, 'run'):
            result = self.request('/api/pc-tips/create', {'category': 'performance'})
        episode = result['project']['pc_tips']
        self.assertEqual(episode['category'], 'performance')
        self.assertEqual(episode['idea_source'], 'automatic')
        self.assertEqual(episode['idea'], '')
        self.assertTrue(episode['auto_produce'])
        self.assertEqual(episode['recording_mode'], 'illustrated')
        self.assertEqual(result['project']['voice_settings']['source'], 'elevenlabs')
        self.assertIn('Part 01', result['project']['editor']['name'])

    def test_http_creation_requires_studio_token_and_preserves_voice_choice(self):
        import urllib.error
        payload = {'name': 'Episode', 'idea': 'Windows shortcuts', 'voice_source': 'elevenlabs', 'auto_produce': False}
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            self.request('/api/pc-tips/create', payload, token=False)
        self.assertEqual(rejected.exception.code, 403)
        self.assertEqual(pc.next_part(self.data), 1)
        with patch('pc_tips_ai.require_connection'), patch.object(self.studio, 'run'):
            result = self.request('/api/pc-tips/create', payload)
        self.assertEqual(result['project']['pc_tips']['part'], 1)
        self.assertEqual(result['project']['voice_settings']['source'], 'elevenlabs')

    def test_recording_upload_validates_before_replacing_and_keeps_review_mode(self):
        import urllib.error
        saved=self.seed(status='awaiting_review'); pc.save_state(self.project,saved,visual_source='illustrated')
        route = '/api/upload?id=' + self.identifier + '&role=pc_demo&name=screen.mp4'
        with patch('pc_tips.video_info', return_value={'duration': 10, 'width': 1280, 'height': 720}):
            result = self.request(route, raw=b'video-fixture')
        self.assertEqual(result['project']['pc_tips']['status'], 'awaiting_review')
        self.assertEqual(result['project']['pc_tips']['visual_source'],'recorded')
        previous = pc.state(self.project)['recordings']
        with patch('pc_tips.video_info', side_effect=ValueError('Use a playable screen recording')):
            with self.assertRaises(urllib.error.HTTPError): self.request(route, raw=b'invalid')
        self.assertEqual(pc.state(self.project)['recordings'], previous)
        self.assertFalse(list((self.project / 'media/pc-tips').glob('.upload-*')))

    def test_recording_replacement_invalidates_completed_video_before_resume(self):
        self.seed(status='complete'); self.asset('output/final.mp4')
        with patch('pc_tips.video_info', return_value={'duration': 10, 'width': 1280, 'height': 720}), patch.object(self.studio, 'maybe_auto_build') as resume:
            result = self.request('/api/upload?id=' + self.identifier + '&role=pc_demo&name=screen.mp4', raw=b'replacement')
        self.assertFalse(result['project']['final'])
        self.assertEqual(result['project']['pc_tips']['status'], 'awaiting_recording')
        resume.assert_called_once_with(self.identifier)

    def test_voice_upload_can_arrive_while_pc_assets_are_preparing(self):
        saved=self.seed(status='recording');pc.save_state(self.project,saved,needs_voice_upload=True)
        self.studio.job = {'id': 'worker', 'action': 'pc_produce', 'status': 'running', 'project': self.identifier}
        result = self.request('/api/upload?id=' + self.identifier + '&role=voice&name=recording.wav', raw=b'audio')
        self.assertEqual(result['project']['voiceover'], 'voiceover.wav')
        self.assertEqual(result['project']['pc_tips']['status'], 'recording')
        self.assertFalse(result['project']['pc_tips']['needs_voice_upload'])


class PackageTests(unittest.TestCase):
    setUp = PcTipsTests.setUp
    seed = PcTipsTests.seed
    asset = PcTipsTests.asset

    def test_subtitle_export_uses_real_timing_and_excludes_intro(self):
        write_json(self.project / 'output/timeline.json', {'fps': 30, 'blocks': [
            {'startFrame': 0, 'durationFrames': 60, 'captions': False},
            {'startFrame': 60, 'durationFrames': 60, 'captions': True}],
            'words': [{'word': 'intro', 'startFrame': 0, 'endFrame': 30},
                      {'word': 'افتح', 'startFrame': 60, 'endFrame': 75},
                      {'word': 'القائمة', 'startFrame': 75, 'endFrame': 90},
                      {'word': 'واختار', 'startFrame': 90, 'endFrame': 100},
                      {'word': 'النص', 'startFrame': 100, 'endFrame': 110},
                      {'word': 'دلوقتي', 'startFrame': 110, 'endFrame': 120}]})
        pc.export_captions(self.project)
        value = (self.project / 'output/captions.srt').read_text('utf-8')
        self.assertIn('00:00:02,000 --> 00:00:03,667', value)
        self.assertIn('افتح القائمة', value)
        self.assertNotIn('intro', value)
        self.assertNotIn('\\n', value)

    def test_scene_and_media_changes_make_a_completed_export_stale(self):
        saved = self.seed(status='complete')
        self.asset('media/demo.mp4'); self.asset('output/final.mp4')
        saved['recordings'] = [{'file': 'media/demo.mp4'}]
        pc.save_state(self.project, saved, render_signature=pc.render_signature(self.project, saved))
        self.assertTrue(self.studio.load(self.identifier)['final'])
        self.asset('media/demo.mp4', b'changed video')
        self.assertTrue(pc.state(self.project)['render_stale'])
        self.assertFalse(self.studio.load(self.identifier)['final'])

    def test_failed_visual_review_blocks_completed_package(self):
        saved = self.seed(status='ready')
        self.asset('output/final.mp4')
        def subprocess_result(command, **kwargs):
            if '-frames:v' in command: Path(command[-1]).write_bytes(b'jpeg')
            return Mock(returncode=0)
        with patch('pc_tips.prepare'), patch('pc_tips.subprocess.run', side_effect=subprocess_result), patch('pc_tips.video_info', return_value={'duration': 20, 'width': 1080, 'height': 1920}), patch('pc_tips_ai.ask', return_value={'passed': False, 'issues': ['Unreadable captions']}) as ask, patch('sys.argv', ['pc_tips.py', '--project', str(self.project), '--data', str(self.data)]):
            self.assertEqual(pc.main(), 1)
        self.assertEqual(pc.state(self.project)['status'], 'failed')
        self.assertFalse(pc.state(self.project)['quality_check']['passed'])
        self.assertFalse(self.studio.load(self.identifier)['final'])


class SubscriptionTests(unittest.TestCase):
    setUp = PcTipsTests.setUp
    asset = PcTipsTests.asset
    seed = PcTipsTests.seed

    def test_launcher_rejects_backend_that_still_uses_paid_pc_apis(self):
        health = {'app':'video-turbo-studio', 'engine':str(video_studio.ENGINE), 'features':['pc-tips']}
        response = Mock(); response.read.side_effect = lambda *args: json.dumps(health).encode()
        context = Mock(); context.__enter__ = Mock(return_value=response); context.__exit__ = Mock(return_value=False)
        with patch('video_studio.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = context
            self.assertFalse(video_studio.running_studio('http://127.0.0.1:8765', require_pc=True))
            health['features'].append('pc-chatgpt-sign-in')
            self.assertFalse(video_studio.running_studio('http://127.0.0.1:8765', require_pc=True))
            health['features'].append('pc-auto-ideas')
            self.assertFalse(video_studio.running_studio('http://127.0.0.1:8765', require_pc=True))
            health['features'].append('pc-visual-modes')
            self.assertFalse(video_studio.running_studio('http://127.0.0.1:8765', require_pc=True))
            health['features'].append('pc-problem-first')
            self.assertFalse(video_studio.running_studio('http://127.0.0.1:8765', require_pc=True))
            health['features'].append('pc-google-first')
            self.assertTrue(video_studio.running_studio('http://127.0.0.1:8765', require_pc=True))

    def test_settings_do_not_store_or_accept_an_api_key(self):
        with self.assertRaisesRegex(ValueError, 'Do not enter an API key'):
            pc.configure(self.data, {'api_key': 'must-not-be-stored'})
        value = pc.configure(self.data, {'script_model': pc.SCRIPT_MODEL, 'runner_enabled': False})
        self.assertEqual(value['provider'], 'google-first')
        self.assertEqual(value['provider_order'], ['antigravity', 'codex'])
        saved = read_cache(self.data / 'pc_tips/settings.json')
        self.assertNotIn('api_key', saved); self.assertNotIn('image_model', saved)

    def test_api_login_is_refused_without_logout_or_project_creation(self):
        config = {'provider': 'codex', 'cli_path': 'codex.exe', 'model': pc.SCRIPT_MODEL, 'subscription_only': True}
        with patch('pc_tips_ai.connections', return_value=[config]), patch('reference_styles.subprocess.run', return_value=Mock(returncode=0, stdout='Logged in using an API key', stderr='')) as run:
            with self.assertRaisesRegex(ValueError, 'existing login has not been changed'):
                self.studio.create_pc_tips('Episode', 'Windows shortcut')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ['codex.exe', 'login', 'status'])
        self.assertEqual(pc.next_part(self.data), 1)

    def test_subscription_command_ignores_api_environment_and_custom_providers(self):
        import os
        config = {'cli_path': 'codex.exe', 'model': pc.SCRIPT_MODEL, 'subscription_only': True}
        events = '\n'.join(json.dumps(item) for item in [
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"passed":true}'}},
            {'type': 'turn.completed'}])
        responses = [Mock(returncode=0, stdout='Logged in using ChatGPT', stderr=''), Mock(returncode=0, stdout=events, stderr='')]
        image = self.asset('media/screen.png')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'never-forward', 'OPENAI_BASE_URL': 'https://custom.invalid'}), patch('reference_styles.subprocess.run', side_effect=responses) as run:
            result, _ = reference_styles.ask_codex(config, self.project, 'Check screenshot', {'type': 'object'}, images=[image], use_context=False)
        self.assertTrue(result['passed'])
        command = run.call_args.args[0]
        self.assertIn('--ignore-user-config', command)
        self.assertIn('model_provider="openai"', command)
        self.assertIn('--image', command)
        self.assertIn('read-only', command)
        for call in run.call_args_list:
            self.assertNotIn('OPENAI_API_KEY', call.kwargs['env'])
            self.assertNotIn('OPENAI_BASE_URL', call.kwargs['env'])

    def test_native_image_is_validated_and_copied_without_paid_fallback(self):
        source = self.project / 'generated.png'; Image.new('RGB', (256, 384), 'navy').save(source)
        target = self.project / 'media/pc-tips/intro.png'
        with patch('pc_tips_ai.ask', return_value={'image_file': str(source), 'error': ''}) as ask:
            local_ai.generate_image(self.data, self.project, 'PC setup', target)
        self.assertTrue(target.is_file()); self.assertTrue(ask.call_args.kwargs['native_images'])
        before = target.read_bytes()
        outside = self.root / 'unrelated.png'; source.replace(outside)
        for response in [{'image_file': str(outside), 'error': ''}, {'image_file': '', 'error': 'Native tool unavailable'}]:
            with patch('pc_tips_ai.ask', return_value=response):
                with self.assertRaises(ValueError): local_ai.generate_image(self.data, self.project, 'PC setup', target)
            self.assertEqual(target.read_bytes(), before)

    def test_recorder_uses_screenshot_attachment_and_stops_on_blocked_or_invalid_decisions(self):
        saved = self.seed(); screenshot = self.asset('media/screen.png')
        with patch('pc_tips_ai.ask', return_value={'status': 'actions', 'reason': '', 'actions': [{'type': 'wait'}]}) as ask:
            result = runner.response(self.data, self.project, saved, {'goal': 'Open clipboard'}, screenshot)
        self.assertEqual(result['actions'], [{'type': 'wait'}])
        self.assertEqual(ask.call_args.kwargs['images'], [screenshot])
        with patch('pc_tips_ai.ask', return_value={'status': 'done', 'actions': [{'type': 'wait'}]}):
            with self.assertRaisesRegex(ValueError, 'stopped recording'): runner.response(self.data, self.project, saved, {}, screenshot)


class GoogleRoutingTests(unittest.TestCase):
    setUp = PcTipsTests.setUp

    def routes(self):
        return [{'provider': 'antigravity', 'cli_path': 'agy.exe', 'model': pc.GOOGLE_MODEL, 'subscription_only': True},
                {'provider': 'codex', 'cli_path': 'codex.exe', 'model': pc.SCRIPT_MODEL, 'subscription_only': True}]

    def test_google_is_first_and_accepted_result_avoids_chatgpt(self):
        with patch('pc_tips_ai.connections', return_value=self.routes()), patch('pc_tips_ai.ask_antigravity', return_value=({'valid': True}, {})) as google, patch('pc_tips_ai.ask_codex') as chat:
            value = local_ai.ask(self.data, self.project, 'Create', {'type': 'object'}, model=pc.SCRIPT_MODEL, stage='Script')
        self.assertTrue(value['valid']); chat.assert_not_called()
        self.assertEqual(google.call_args.args[0]['model'], pc.GOOGLE_MODEL)
        rows = read_cache(self.project / 'reference/pc-ai-routing.json')['attempts']
        self.assertEqual([x['status'] for x in rows], ['trying', 'accepted'])

    def test_google_failure_falls_back_to_the_chatgpt_model(self):
        with patch('pc_tips_ai.connections', return_value=self.routes()), patch('pc_tips_ai.ask_antigravity', side_effect=ValueError('Google quota reached')), patch('pc_tips_ai.ask_codex', return_value=({'valid': True}, {})) as chat:
            self.assertTrue(local_ai.ask(self.data, self.project, 'Create', {'type': 'object'})['valid'])
        self.assertEqual(chat.call_args.args[0]['model'], pc.SCRIPT_MODEL)
        self.assertTrue(chat.call_args.args[0]['subscription_only'])
        rows = read_cache(self.project / 'reference/pc-ai-routing.json')['attempts']
        self.assertEqual([x['status'] for x in rows], ['trying', 'rejected', 'trying', 'accepted'])
        self.assertIn('quota', rows[1]['reason'])

    def test_bad_candidate_falls_back_even_when_google_request_succeeds(self):
        def valid(value):
            if value.get('path') != 'Correct Windows 10 path': raise ValueError('Wrong Windows path')
        with patch('pc_tips_ai.connections', return_value=self.routes()), patch('pc_tips_ai.ask_antigravity', return_value=({'path': 'Windows 11 path'}, {})), patch('pc_tips_ai.ask_codex', return_value=({'path': 'Correct Windows 10 path'}, {})) as chat:
            local_ai.ask(self.data, self.project, 'Create', {'type': 'object'}, validator=valid)
        chat.assert_called_once()

    def test_draft_fallback_review_requires_compatibility_only_on_episode(self):
        PcTipsTests.seed(self)
        value=problem_plan()
        def codex(config,project,prompt,schema,timeout,**kwargs):
            if schema != local_ai.REVIEW_SCHEMA:
                self.assertIn('Set compatibility to windows10_only on the episode only.',prompt)
                return value,{}
            contract=json.loads(prompt.split('\nCandidate output schema:\n')[1].split('\nCandidate:\n')[0])
            candidate=json.loads(prompt.split('\nCandidate:\n')[1])
            self.assertEqual(contract,pc.PLAN_SCHEMA)
            self.assertIn('compatibility',contract['required'])
            for shot_schema,shot in [(contract['properties']['problem'],candidate['problem']),
                                    *[(contract['properties']['steps']['items'],step) for step in candidate['steps']]]:
                self.assertNotIn('compatibility',shot_schema['properties'])
                self.assertNotIn('compatibility',shot)
                self.assertEqual(shot['os'],'Windows 10')
            self.assertIn('do not add or require it in problem or individual steps',prompt)
            return {'passed':True,'issues':[]},{}
        with patch('pc_tips_ai.connections',return_value=self.routes()), \
             patch('pc_tips_ai.ask_antigravity',side_effect=ValueError('Antigravity returned an invalid scene plan. Retry analysis.')), \
             patch('pc_tips_ai.ask_codex',side_effect=codex) as chat:
            pc.draft(self.project,self.data)
        self.assertEqual(chat.call_count,2)
        self.assertEqual(pc.state(self.project)['status'],'preparing')
        self.assertEqual(pc.state(self.project)['plan']['compatibility'],'windows10_only')

    def test_quality_rejection_retries_generation_with_fallback(self):
        replies = [({'path': 'Plausible but wrong'}, {}), ({'passed': False, 'issues': ['Not supported on Windows 10']}, {})]
        with patch('pc_tips_ai.connections', return_value=self.routes()), patch('pc_tips_ai.ask_antigravity', side_effect=replies) as google, patch('pc_tips_ai.ask_codex', side_effect=[({'path': 'Correct'}, {}), ({'passed': True, 'issues': []}, {})]) as chat:
            result = local_ai.ask(self.data, self.project, 'Create', {'type': 'object'}, quality_prompt='Verify official paths')
        self.assertEqual(result['path'], 'Correct'); self.assertEqual(google.call_count, 2); self.assertEqual(chat.call_count, 2)
        self.assertIn('Not supported on Windows 10', chat.call_args_list[0].args[2])

    def test_walkthrough_repairs_missing_problem_and_runs_quality_review_again(self):
        calls=[]
        def reply(config,project,prompt,schema,timeout,**kwargs):
            calls.append(prompt)
            if schema==local_ai.REVIEW_SCHEMA:return {'passed':True,'issues':[]},{}
            return (storyboard() if len(calls)==1 else window_storyboard()),{}
        with patch('pc_tips_ai.connections',return_value=self.routes()),patch('pc_tips_ai.ask_antigravity',side_effect=reply),patch('pc_tips_ai.ask_codex') as chat:
            result=local_ai.ask(self.data,self.project,'Keep this tip.',walkthrough.SCHEMA,
                validator=lambda value:walkthrough.validate(value,problem_plan()),
                quality_prompt=walkthrough.CAPABILITIES,repair_attempts=1)
        self.assertEqual(len(result['steps']),3);self.assertEqual(len(calls),3);chat.assert_not_called()
        self.assertIn('expected 3 steps',calls[1]);self.assertIn('"candidate"',calls[1]);self.assertIn('Keep this tip.',calls[1])
        rows=read_cache(self.project/'reference/pc-ai-routing.json')['attempts']
        self.assertEqual([row['status'] for row in rows],['trying','rejected','repairing','accepted'])

    def test_rejected_repair_is_bounded_and_falls_back_with_both_reasons(self):
        def valid(value):
            if not value.get('valid'):raise ValueError(value['reason'])
        with patch('pc_tips_ai.connections',return_value=self.routes()),patch('pc_tips_ai.ask_antigravity',side_effect=[
            ({'valid':False,'reason':'Missing problem'},{}),({'valid':False,'reason':'Wrong step count'}, {})]) as google,patch(
            'pc_tips_ai.ask_codex',return_value=({'valid':True},{})) as chat:
            result=local_ai.ask(self.data,self.project,'Create',{'type':'object'},validator=valid,repair_attempts=1)
        self.assertTrue(result['valid']);self.assertEqual(google.call_count,2);chat.assert_called_once()
        prompt=chat.call_args.args[2]
        self.assertIn('Missing problem',prompt);self.assertIn('Wrong step count',prompt)

    def test_quality_repair_does_not_bypass_independent_review(self):
        with patch('pc_tips_ai.connections',return_value=self.routes()[:1]),patch('pc_tips_ai.ask_antigravity',side_effect=[
            ({'valid':True},{}),({'passed':False,'issues':['Missing visible overlap']},{}),
            ({'valid':True},{}),({'passed':True,'issues':[]},{})]) as google:
            result=local_ai.ask(self.data,self.project,'Create',{'type':'object'},quality_prompt='Show overlap',repair_attempts=1)
        self.assertTrue(result['valid']);self.assertEqual(google.call_count,4)
        self.assertIn('Missing visible overlap',google.call_args_list[2].args[2])

    def test_connection_failure_skips_repair_and_uses_fallback(self):
        with patch('pc_tips_ai.connections',return_value=self.routes()),patch('pc_tips_ai.ask_antigravity',side_effect=ValueError('quota')) as google,patch(
            'pc_tips_ai.ask_codex',return_value=({'valid':True},{})) as chat:
            local_ai.ask(self.data,self.project,'Create',{'type':'object'},repair_attempts=1)
        google.assert_called_once();chat.assert_called_once()

    def test_animated_draft_and_reviewer_receive_renderer_capabilities(self):
        saved=PcTipsTests.seed(self);saved['recording_mode']='illustrated'
        pc.save_state(self.project,saved)
        with patch('pc_tips_ai.ask',return_value=problem_plan()) as ask:
            pc.draft(self.project,self.data)
        self.assertIn(walkthrough.CAPABILITIES,ask.call_args.args[2])
        self.assertIn(walkthrough.CAPABILITIES,ask.call_args.kwargs['quality_prompt'])

    def test_animated_performance_is_constrained_to_a_supported_documented_effect(self):
        saved=PcTipsTests.seed(self)
        saved.update(idea='',idea_source='automatic',category='performance',recording_mode='illustrated')
        pc.save_state(self.project,saved)
        with patch('pc_tips_ai.ask',return_value=transparency_plan()) as ask:
            pc.draft(self.project,self.data)
        schema=ask.call_args.args[3]
        self.assertEqual(schema['properties']['topic_key']['enum'],[walkthrough.PERFORMANCE_TOPIC])
        self.assertIn(walkthrough.PERFORMANCE_GUIDANCE,ask.call_args.args[2])
        self.assertIn(walkthrough.PERFORMANCE_GUIDANCE,ask.call_args.kwargs['quality_prompt'])
        with self.assertRaisesRegex(ValueError,'documented transparency'):
            ask.call_args.kwargs['validator'](problem_plan())

    def test_used_animated_performance_effect_stops_before_provider_calls(self):
        saved=PcTipsTests.seed(self)
        saved.update(idea='',idea_source='automatic',category='performance',recording_mode='illustrated')
        pc.save_state(self.project,saved)
        write_json(self.data/'pc_tips/series.json',{'episodes':[
            {'project':'earlier','topic':'Acrylic effect','topic_key':walkthrough.PERFORMANCE_TOPIC}]})
        with patch('pc_tips_ai.ask') as ask:
            with self.assertRaisesRegex(ValueError,'already appeared'):
                pc.draft(self.project,self.data)
        ask.assert_not_called()

    def test_draft_schema_enforces_step_and_recording_action_counts(self):
        saved=PcTipsTests.seed(self)
        saved.update(recording_mode='illustrated')
        pc.save_state(self.project,saved)
        with patch('pc_tips_ai.ask',return_value=problem_plan()) as ask:
            pc.draft(self.project,self.data)
        schema=ask.call_args.args[3]
        self.assertEqual(schema['properties']['steps']['minItems'],2)
        self.assertEqual(schema['properties']['steps']['maxItems'],5)
        for shot in (schema['properties']['problem'],schema['properties']['steps']['items']):
            instructions=shot['properties']['capture_instructions']
            self.assertEqual(instructions['minItems'],1)
            self.assertEqual(instructions['maxItems'],8)

    def test_failed_repair_keeps_the_candidate_for_diagnosis(self):
        PcTipsTests.seed(self)
        rejected=problem_plan()
        invalid=problem_plan();invalid['steps']=[]
        with patch('pc_tips_ai.connections',return_value=self.routes()[1:]), \
             patch('pc_tips_ai.ask_codex',side_effect=[(rejected,{}),({'passed':False,'issues':['Wrong video type.']},{}),(invalid,{})]):
            with self.assertRaisesRegex(ValueError,'2 to 5 short steps'):
                pc.draft(self.project,self.data)
        candidate=read_cache(self.project/'reference/pc-last-candidate-codex.json')
        self.assertEqual(candidate['candidate'],invalid)
        self.assertEqual(candidate['stage'],'Idea & Egyptian Arabic script')
        self.assertEqual(candidate['attempt'],1)

    def test_automatic_draft_repairs_rejected_fallback_and_reviews_the_new_tip(self):
        saved=PcTipsTests.seed(self)
        saved.update(idea='',idea_source='automatic',category='performance',recording_mode='illustrated')
        pc.save_state(self.project,saved)
        rejected=problem_plan();rejected.update(topic='Close Calculator',topic_key=walkthrough.PERFORMANCE_TOPIC)
        corrected=transparency_plan()
        issues=['Calculator minimize, restore and close are unsupported.',
                'A missing app row does not prove lower resource usage.',
                'The final step must repeat the opening action.']
        replies=[(rejected,{}),({'passed':False,'issues':issues},{}),
                 (corrected,{}),({'passed':True,'issues':[]},{})]
        with patch('pc_tips_ai.connections',return_value=self.routes()), \
             patch('pc_tips_ai.ask_antigravity',side_effect=ValueError('Antigravity returned an invalid scene plan. Retry analysis.')) as google, \
             patch('pc_tips_ai.ask_codex',side_effect=replies) as chat:
            pc.draft(self.project,self.data)
        google.assert_called_once();self.assertEqual(chat.call_count,4)
        repair=chat.call_args_list[2].args[2]
        self.assertIn('may choose a different technique',repair)
        self.assertIn('requested video type',repair)
        self.assertNotIn('Preserve the tutorial',repair)
        self.assertIn('Antigravity returned an invalid scene plan',repair)
        for issue in issues:self.assertIn(issue,repair)
        reviewed=json.loads(chat.call_args_list[3].args[2].split('\nCandidate:\n')[1])
        self.assertEqual(reviewed['topic_key'],corrected['topic_key'])
        self.assertEqual(pc.state(self.project)['plan']['topic_key'],corrected['topic_key'])
        rows=read_cache(self.project/'reference/pc-ai-routing.json')['attempts']
        self.assertEqual([row['status'] for row in rows],['trying','rejected','trying','rejected','repairing','accepted'])

    def test_user_draft_repair_preserves_the_requested_technique(self):
        PcTipsTests.seed(self)
        value=problem_plan()
        with patch('pc_tips_ai.connections',return_value=self.routes()[1:]), \
             patch('pc_tips_ai.ask_codex',side_effect=[(value,{}),({'passed':False,'issues':['Repeat the opening action.']},{}),
                                                       (value,{}),({'passed':True,'issues':[]},{})]) as chat:
            pc.draft(self.project,self.data)
        repair=chat.call_args_list[2].args[2]
        self.assertIn('Preserve the tutorial',repair)
        self.assertNotIn('may choose a different technique',repair)

    def test_exhausted_draft_repairs_keep_saved_progress(self):
        saved=PcTipsTests.seed(self)
        before={name:(self.project/name).read_bytes() for name in ('pc_tips.json','script.txt','studio.json')}
        value=problem_plan()
        with patch('pc_tips_ai.connections',return_value=self.routes()), \
             patch('pc_tips_ai.ask_antigravity',side_effect=ValueError('Google quota reached')), \
             patch('pc_tips_ai.ask_codex',side_effect=[(value,{}),({'passed':False,'issues':['No visible result.']},{}),
                                                       (value,{}),({'passed':False,'issues':['Still no visible result.']},{})]) as chat:
            with self.assertRaisesRegex(ValueError,'No connected subscription produced an acceptable result'):
                pc.draft(self.project,self.data)
        self.assertEqual(chat.call_count,4)
        for name,content in before.items():self.assertEqual((self.project/name).read_bytes(),content)
        self.assertEqual(pc.state(self.project)['plan'],saved['plan'])

    def test_failed_final_review_is_not_overridden_by_another_reviewer(self):
        with patch('pc_tips_ai.connections', return_value=self.routes()), patch('pc_tips_ai.ask_antigravity', return_value=({'passed': False, 'issues': ['Missing visible symptom']}, {})), patch('pc_tips_ai.ask_codex') as chat:
            result = local_ai.ask(self.data, self.project, 'Review rendered output', local_ai.REVIEW_SCHEMA, validator=local_ai.validate_review)
        self.assertFalse(result['passed']); chat.assert_not_called()

    def test_exhausted_routes_stop_without_returning_bad_output(self):
        with patch('pc_tips_ai.connections', return_value=self.routes()), patch('pc_tips_ai.ask_antigravity', side_effect=ValueError('quota')), patch('pc_tips_ai.ask_codex', side_effect=ValueError('not signed in')):
            with self.assertRaisesRegex(ValueError, 'No connected subscription produced an acceptable result'):
                local_ai.ask(self.data, self.project, 'Create')
        rows = read_cache(self.project / 'reference/pc-ai-routing.json')['attempts']
        self.assertEqual(rows[-1]['status'], 'rejected')

    def test_google_vision_receives_only_requested_image_paths(self):
        image = self.project / 'screen.png'; Image.new('RGB', (256, 256), 'blue').save(image)
        with patch('pc_tips_ai.ask_antigravity', return_value=({'passed': True, 'issues': []}, {})) as google:
            local_ai.request(self.routes()[0], self.project, 'Review', local_ai.REVIEW_SCHEMA, 60, [image])
        self.assertIn(json.dumps(str(image.resolve())), google.call_args.args[2])
        self.assertIn('visually inspect EVERY', google.call_args.args[2])

    def test_google_subscription_does_not_forward_api_credentials(self):
        import os
        response = Mock(returncode=0, stdout=json.dumps({'event': 'result', 'result': {'status': 'SUCCESS', 'response': 'READY'}}), stderr='')
        with patch.dict(os.environ, {'GOOGLE_API_KEY': 'private', 'GEMINI_API_KEY': 'private', 'OPENAI_API_KEY': 'private'}), patch('reference_styles.read_cache', return_value={}), patch('reference_styles.subprocess.run', return_value=response) as run:
            self.assertEqual(reference_styles.ask_antigravity(self.routes()[0], self.project, 'Ready'), 'READY')
        self.assertTrue(run.call_args.kwargs['input'].endswith(chr(10)))
        for name in ('GOOGLE_API_KEY', 'GEMINI_API_KEY', 'OPENAI_API_KEY'):
            self.assertNotIn(name, run.call_args.kwargs['env'])
        self.assertNotIn('--dangerously-skip-permissions', run.call_args.args[0])

    def test_google_unseen_images_trigger_fallback_instead_of_fake_approval(self):
        image = self.project / 'frame.png'
        Image.new('RGB', (256,256)).save(image)
        config = {**self.routes()[0], 'required_images': [image]}
        result = {'event': 'result', 'result': {'status': 'SUCCESS', 'structured_output': {'passed': True, 'issues': []}}}
        response = Mock(returncode=0, stdout=json.dumps(result), stderr='')
        with patch('reference_styles.read_cache', return_value={}), patch('reference_styles.subprocess.run', return_value=response):
            with self.assertRaisesRegex(ValueError, 'every requested review image was opened'):
                reference_styles.ask_antigravity(config, self.project, 'Review', local_ai.REVIEW_SCHEMA)
        view = {'event': 'step_update', 'step_update': {'state': 'DONE', 'tool_info': {'name': 'view_file', 'parameters': {'AbsolutePath': str(image)}}}}
        response.stdout = json.dumps(view) + chr(10) + json.dumps(result)
        with patch('reference_styles.read_cache', return_value={}), patch('reference_styles.subprocess.run', return_value=response):
            report, _ = reference_styles.ask_antigravity(config, self.project, 'Review', local_ai.REVIEW_SCHEMA)
        self.assertTrue(report['passed'])

    def test_google_extra_credit_opt_in_is_refused_without_changing_settings(self):
        with patch('reference_styles.read_cache', return_value={'useG1Credits': True}), patch('reference_styles.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'extra-credit spending is enabled'):
                reference_styles.ask_antigravity(self.routes()[0], self.project, 'Ready')
        run.assert_not_called()

    def test_google_native_conversation_artifact_is_accepted_but_arbitrary_home_image_is_not(self):
        fake_home = self.root / 'home'
        artifact = fake_home / '.gemini/antigravity-cli/brain/episode/setup.png'
        artifact.parent.mkdir(parents=True); Image.new('RGB', (512,768)).save(artifact)
        with patch('pc_tips_ai.Path.home', return_value=fake_home):
            self.assertEqual(local_ai.image_artifact(self.project, {'image_file': str(artifact), 'error': ''}), artifact.resolve())
            outside = fake_home / 'private.png'; artifact.replace(outside)
            with self.assertRaises(ValueError):
                local_ai.image_artifact(self.project, {'image_file': str(outside), 'error': ''})

    def test_google_unavailable_image_tool_falls_back_before_copying(self):
        source = self.project / 'new.png'; Image.new('RGB', (256, 384), 'navy').save(source)
        target = self.project / 'media/pc-tips/intro.png'
        with patch('pc_tips_ai.connections', return_value=self.routes()), patch('pc_tips_ai.ask_antigravity', return_value=({'image_file': '', 'error': 'Native tool unavailable'}, {})), patch('pc_tips_ai.ask_codex', side_effect=[({'image_file': str(source), 'error': ''}, {}), ({'passed': True, 'issues': []}, {})]):
            local_ai.generate_image(self.data, self.project, 'PC setup', target)
        self.assertTrue(target.is_file())
        rows = read_cache(self.project / 'reference/pc-ai-routing.json')['attempts']
        self.assertEqual(rows[-1]['provider'], 'codex')


if __name__ == '__main__': unittest.main()
