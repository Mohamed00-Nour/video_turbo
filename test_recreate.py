import json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import recreate
import reference_styles as ref
import video_studio as studio
from pipeline_common import read_cache, write_json
from test_reference_styles import valid_plan
from test_style_library import ready_style


def draft_answer(script='سكريبت جديد بكلامي'):
    return {'breakdown': {'title': 'Phone tips', 'source_language': 'en', 'summary': 'Three phone tips.', 'hook': 'A question',
                          'points': [{'time_seconds': 2, 'idea': 'Battery saver', 'visual': 'Settings screen'},
                                     {'time_seconds': 9, 'idea': 'Dark mode', 'visual': 'Phone in dark mode'}],
                          'ending': 'Follow for more'},
            'script': script, 'notes': 'Check the battery claim.'}


def sample(project, source, folder='reference/frames', max_seconds=180):
    frames = Path(project) / folder; frames.mkdir(parents=True, exist_ok=True)
    (frames / 'sheet-01.jpg').write_bytes(b'jpg')
    return {'duration_seconds': 30.0, 'sample_fps': 3, 'frame_count': 1, 'sheets': [f'{folder}/sheet-01.jpg']}


class OptionsTests(unittest.TestCase):
    def test_options_validate_link_language_and_length(self):
        value = recreate.options({'url': 'https://www.youtube.com/watch?v=abcdefghijk', 'language': ' Egyptian Arabic ', 'target_seconds': 59.6})
        self.assertEqual(value, {'source_url': 'https://www.youtube.com/watch?v=abcdefghijk', 'source_file': '', 'language': 'Egyptian Arabic', 'target_seconds': 60})
        self.assertIsNone(recreate.options({'language': 'English', 'target_seconds': ''})['target_seconds'])
        for bad in ({'url': 'https://example.com/video', 'language': 'English'}, {'language': ''}, {'language': 'x', 'target_seconds': 5},
                    {'language': 'x', 'target_seconds': 900}, {'language': 'x', 'target_seconds': True}, 'text'):
            with self.subTest(bad=bad), self.assertRaises(ValueError): recreate.options(bad)

    def test_draft_validation(self):
        self.assertTrue(recreate.validate_draft(draft_answer(), 30))
        for change in (lambda d: d.update(script=''), lambda d: d['breakdown'].update(points=[]),
                       lambda d: d['breakdown']['points'].reverse(), lambda d: d['breakdown']['points'][0].update(time_seconds=99),
                       lambda d: d['breakdown']['points'][0].update(visual='')):
            value = draft_answer(); change(value)
            with self.assertRaises(ValueError): recreate.validate_draft(value, 30)


class DraftTests(unittest.TestCase):
    def project(self, root, **source):
        (root / 'reference/source').mkdir(parents=True, exist_ok=True)
        state = {'status': 'awaiting_inputs', 'analysis_provider': 'claude', 'workflow': 'reference', 'instructions': 'Keep it upbeat',
                 'library_styles': [], 'recreate': {'source_url': '', 'source_file': '', 'language': 'Egyptian Arabic', 'target_seconds': None, **source}}
        write_json(root / 'reference_style.json', state)
        write_json(root / 'config.json', {'sections': [{'layout': 'title', 'title': 'x'}]})
        (root / 'script.txt').write_text('', encoding='utf-8')
        return state

    def test_upload_is_transcribed_and_drafted_for_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); (root / 'reference/source').mkdir(parents=True)
            (root / 'reference/source/upload-1.mp4').write_bytes(b'video')
            self.project(root, source_file='reference/source/upload-1.mp4')
            transcript = {'key': 'k', 'language': 'en', 'segments': [{'start': 0, 'end': 2, 'text': 'Want a longer battery?'}]}
            connections = {'provider': 'claude', 'providers': {'claude': {'cli_path': 'claude.exe', 'model': 'opus'}}}
            with patch.object(ref, 'settings', return_value=connections), patch.object(ref, 'sample_reference', side_effect=sample) as sampled, \
                 patch.object(recreate, 'transcribe', return_value=transcript), patch.object(ref, 'probe', return_value=(5, [])), \
                 patch.object(ref, 'ask_claude', return_value=(draft_answer(), {'session_id': 's'})) as ask, \
                 patch('build_video.configure_project'):
                ref.run_project(root, root / 'data')
            self.assertEqual(sampled.call_args.kwargs, {'folder': 'reference/source/frames', 'max_seconds': 600})
            context = read_cache(root / 'reference/context.json')
            self.assertEqual(context['source_transcript'], transcript['segments'])
            self.assertEqual(context['target_seconds'], 30); self.assertEqual(context['target_words'], 72)
            self.assertEqual(context['reference']['sheets'], ['reference/source/frames/sheet-01.jpg'])
            prompt = ask.call_args.args[2]
            self.assertIn('in your own words', prompt); self.assertIn('Do not copy sentences', prompt)
            state = read_cache(root / 'reference_style.json')
            self.assertEqual(state['status'], 'script_review'); self.assertEqual(state['draft_script'], 'سكريبت جديد بكلامي')
            self.assertEqual(state['recreate']['breakdown']['points'][1]['idea'], 'Dark mode')
            self.assertTrue(state['recreate']['drafted_source'])
            self.assertEqual((root / 'script.txt').read_text(encoding='utf-8'), '')  # nothing is approved automatically

    def test_youtube_source_is_downloaded_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); (root / 'reference/source').mkdir(parents=True)
            fake = MagicMock(); fake.__enter__.return_value = fake
            fake.extract_info.return_value = {'id': 'abcdefghijk', 'duration': 120}
            fake_calls = []
            fake.download.side_effect = lambda urls: Path(fake_calls[-1]['outtmpl'].replace('.%(ext)s', '.mp4')).write_bytes(b'video')
            def factory(options):
                fake_calls.append(options); return fake
            with patch.dict('sys.modules', {'yt_dlp': SimpleNamespace(YoutubeDL=factory)}):
                path = recreate.download(root, 'https://youtu.be/abcdefghijk')
                self.assertEqual(path.name, 'youtube-abcdefghijk.mp4'); self.assertTrue(path.is_file())
                self.assertIn('ba', fake_calls[-1]['format'])  # audio is kept for the transcript
                recreate.download(root, 'https://youtu.be/abcdefghijk')
            self.assertEqual(fake.download.call_count, 1)
            fake.extract_info.return_value = {'id': 'abcdefghijk', 'duration': 1200}
            with patch.dict('sys.modules', {'yt_dlp': SimpleNamespace(YoutubeDL=factory)}):
                with self.assertRaisesRegex(ValueError, '10 minutes'): recreate.download(root, 'https://youtu.be/abcdefghijk')

    def test_transcript_is_cached_and_silent_sources_are_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'reference/source').mkdir(parents=True)
            source = root / 'clip.mp4'; source.write_bytes(b'video')
            with patch.object(ref, 'probe', return_value=(5, [{'codec_type': 'video'}])):
                self.assertEqual(recreate.transcribe(root, source)['segments'], [])
            segment = SimpleNamespace(start=0.0, end=1.5, text=' Hello there ')
            model = MagicMock(); model.transcribe.return_value = ([segment], SimpleNamespace(language='en'))
            source.write_bytes(b'video with audio')
            with patch.object(ref, 'probe', return_value=(5, [{'codec_type': 'audio'}])), \
                 patch.dict('sys.modules', {'faster_whisper': SimpleNamespace(WhisperModel=MagicMock(return_value=model))}):
                result = recreate.transcribe(root, source)
                self.assertEqual(result['segments'], [{'start': 0.0, 'end': 1.5, 'text': 'Hello there'}]); self.assertEqual(result['language'], 'en')
                recreate.transcribe(root, source)
            self.assertEqual(model.transcribe.call_count, 1)


class StudioRecreateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); root = Path(self.folder.name)
        self.app = studio.Studio(root / 'data', root / 'projects')
        self.style = ready_style(self.app.data, 'Dark')

    def tearDown(self): self.folder.cleanup()

    def create(self, **source):
        return self.app.create_reference('Recreated', 'ignored', provider='claude', styles=[self.style],
                                         source={'language': 'Egyptian Arabic', **source})

    def test_create_needs_styles_and_starts_without_a_script(self):
        project = self.create(url='https://www.youtube.com/watch?v=abcdefghijk')
        self.assertEqual(project['editor']['script'], '')
        self.assertEqual(project['reference_style']['recreate']['source_url'], 'https://www.youtube.com/watch?v=abcdefghijk')
        with self.assertRaisesRegex(ValueError, 'saved style'):
            self.app.create_reference('No style', '', source={'language': 'English'})
        with self.assertRaisesRegex(ValueError, 'Video Turbo animation'):
            self.app.create_reference('Flow', '', workflow='flow', styles=[self.style], source={'language': 'English'})

    def test_drafting_needs_a_source_but_no_voiceover(self):
        project = self.create()
        connections = {'provider': 'claude', 'installed': True, 'providers': {'claude': {'installed': True}}}
        with patch.object(ref, 'settings', return_value=connections), patch.object(studio.threading, 'Thread'):
            with self.assertRaisesRegex(ValueError, 'source video'): self.app.start_reference(project['id'], True)
            path = Path(project['path']); state = read_cache(path / 'reference_style.json')
            state['recreate']['source_url'] = 'https://youtu.be/abcdefghijk'; write_json(path / 'reference_style.json', state)
            result = self.app.start_reference(project['id'], True)
        self.assertEqual(result['job']['action'], 'reference_plan')  # never builds before the script is approved
        self.assertIn('Drafting your script', result['job']['stage'])

    def test_approve_saves_the_reviewed_script(self):
        project = self.create(); path = Path(project['path'])
        (path / 'reference/source').mkdir(parents=True); (path / 'reference/source/upload-1.mp4').write_bytes(b'video')
        state = read_cache(path / 'reference_style.json')
        state['recreate'].update(source_file='reference/source/upload-1.mp4', drafted_source=ref.file_signature(path / 'reference/source/upload-1.mp4'))
        state.update(status='script_review', draft_script='draft'); write_json(path / 'reference_style.json', state)
        with self.assertRaises(ValueError): self.app.approve_recreate_script(project['id'], '   ')
        result = self.app.approve_recreate_script(project['id'], ' My edited script ')
        self.assertEqual(result['editor']['script'], 'My edited script')
        self.assertEqual((path / 'script.txt').read_text(encoding='utf-8'), 'My edited script')
        self.assertEqual(result['reference_style']['status'], 'awaiting_inputs')
        with self.assertRaisesRegex(ValueError, 'Draft a script'): self.app.approve_recreate_script(project['id'], 'again')

    def test_changed_source_requires_a_new_draft(self):
        project = self.create(); path = Path(project['path'])
        (path / 'reference/source').mkdir(parents=True); (path / 'reference/source/upload-1.mp4').write_bytes(b'video')
        state = read_cache(path / 'reference_style.json')
        state['recreate'].update(source_file='reference/source/upload-1.mp4', drafted_source={'size': 1})
        state.update(status='script_review'); write_json(path / 'reference_style.json', state)
        with self.assertRaisesRegex(ValueError, 'changed'): self.app.approve_recreate_script(project['id'], 'Script')

    def test_planning_follows_the_source_breakdown(self):
        import build_video
        project = self.create(); root = Path(project['path'])
        state = read_cache(root / 'reference_style.json')
        state['recreate']['breakdown'] = draft_answer()['breakdown']; write_json(root / 'reference_style.json', state)
        (root / 'script.txt').write_text('hello world', encoding='utf-8'); (root / 'voiceover.mp3').write_bytes(b'audio'); (root / 'media').mkdir()
        from PIL import Image
        Image.new('RGBA', (20, 20), (255, 255, 255, 255)).save(root / 'media/hero.png')
        words = {'words': [{'word': 'hello', 'start': 0, 'end': .5}]}
        connections = {'provider': 'claude', 'providers': {'claude': {'cli_path': 'claude.exe', 'model': 'opus'}}}
        with patch.object(ref, 'probe', return_value=(5, [])), patch.object(build_video, 'configure_project'), \
             patch.object(build_video, 'transcribe_voiceover', return_value=words), patch.object(build_video, 'apply_script', return_value=words), \
             patch.object(ref, 'settings', return_value=connections), patch.object(ref, 'ask_claude', return_value=(valid_plan(), {})) as ask:
            ref.run_project(root, self.app.data)
        self.assertIn('source_breakdown', ask.call_args.args[2])
        self.assertEqual(read_cache(root / 'reference/context.json')['source_breakdown']['points'][0]['idea'], 'Battery saver')
        self.assertEqual(read_cache(root / 'reference_style.json')['status'], 'ready')

    def test_finished_draft_job_keeps_the_review_status(self):
        project = self.create(); path = Path(project['path'])
        state = read_cache(path / 'reference_style.json'); state['status'] = 'script_review'; write_json(path / 'reference_style.json', state)
        job = {'id': 'j', 'project': project['id'], 'action': 'reference_plan', 'status': 'running', 'logs': [], 'cancel': False}
        self.app.jobs['j'] = job
        with patch.object(studio.subprocess, 'Popen') as popen:
            popen.return_value.stdout = iter(['[REFERENCE] Script draft ready for your review\n']); popen.return_value.wait.return_value = 0
            self.app.run(job, path, read_cache(path / 'config.json'), 0)
        self.assertEqual(job['status'], 'complete')
        self.assertEqual(read_cache(path / 'reference_style.json')['status'], 'script_review')


    def test_source_that_is_a_saved_style_video_is_flagged(self):
        import style_library as lib
        style_dir = lib.folder(self.app.data, self.style); (style_dir / 'source.mp4').write_bytes(b'style video bytes')
        value = read_cache(style_dir / 'style.json'); value['source_file'] = 'source.mp4'; write_json(style_dir / 'style.json', value)
        project = self.create(); path = Path(project['path']); (path / 'reference/source').mkdir(parents=True)
        same = path / 'reference/source/upload-1.mp4'; same.write_bytes(b'style video bytes')
        other = path / 'reference/source/upload-2.mp4'; other.write_bytes(b'other video bytes')
        self.assertEqual(lib.matching_source(self.app.data, same), 'Dark')
        self.assertEqual(lib.matching_source(self.app.data, other), '')
        state = read_cache(path / 'reference_style.json'); state['recreate']['source_file'] = 'reference/source/upload-1.mp4'
        write_json(path / 'reference_style.json', state)
        self.assertEqual(self.app.reference_state(project['id'])['recreate']['source_matches_style'], 'Dark')
        self.assertEqual(read_cache(path / 'reference_style.json')['recreate']['source_matches_style'], 'Dark')  # checked once, then saved


if __name__ == '__main__':
    unittest.main()


class QuickFixTests(unittest.TestCase):
    def test_claude_runs_at_high_effort_and_reports_its_model(self):
        signed_in = type('R', (), {'returncode': 0, 'stdout': json.dumps({'loggedIn': True, 'authMethod': 'claude.ai'}), 'stderr': ''})()
        events = [{'type': 'system', 'subtype': 'init', 'model': 'claude-opus-5-5'},
                  {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '{}', 'structured_output': {'ok': True}}]
        answer = type('R', (), {'returncode': 0, 'stdout': '\n'.join(json.dumps(e) for e in events), 'stderr': ''})()
        with tempfile.TemporaryDirectory() as folder, patch.object(ref.subprocess, 'run', side_effect=[signed_in, answer]) as run:
            value, meta = ref.ask_claude({'cli_path': 'claude.exe', 'model': 'opus'}, folder, 'Plan', {'type': 'object'})
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('--effort') + 1], 'high')
        self.assertEqual(meta['model'], 'claude-opus-5-5')
        with patch.object(ref.subprocess, 'run', side_effect=[signed_in, answer]) as run:
            ref.ask_claude({'cli_path': 'claude.exe'}, '.', 'Reply READY')
        self.assertNotIn('--effort', run.call_args.args[0])  # quick connection checks stay light

    def test_planner_receives_source_and_style_frames(self):
        import style_library as lib
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / 'data'; style_id = ready_style(data, 'Dark')
            frames = lib.folder(data, style_id) / 'reference/frames'; frames.mkdir(parents=True)
            for name in ('sheet-01.jpg', 'sheet-02.jpg', 'sheet-03.jpg'): (frames / name).write_bytes(b'jpg')
            project = Path(folder) / 'project'; (project / 'reference/source/frames').mkdir(parents=True)
            (project / 'reference/source/frames/sheet-01.jpg').write_bytes(b'jpg')
            source = recreate.planning_images(project, {'recreate': {}})
            styles = lib.planning_images(data, project, [{'id': style_id, 'name': 'Dark'}])
            self.assertEqual([row['path'] for row in source], ['reference/source/frames/sheet-01.jpg'])
            self.assertEqual([row['path'] for row in styles], ['reference/styles/A-01.jpg', 'reference/styles/A-02.jpg'])
            self.assertIn('"Dark"', styles[0]['shows'])
            self.assertEqual(recreate.planning_images(project, {}), [])

    def test_broken_image_link_falls_back_to_typography(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'media').mkdir()
            plan = valid_plan()
            plan['assets'] = [{'id': 'logo', 'kind': 'image', 'source': 'https://example.com/logo.png', 'start_seconds': 0, 'duration_seconds': 1}]
            plan['scenes'][0].update(media='logo', variant='hero')
            write_json(root / 'config.json', {}); write_json(root / 'studio.json', {'name': 'x', 'mode': 'sections'})
            with patch('logo_assets.fetch_reference_image', side_effect=ValueError('not an image')):
                ref.finish_preparation(root, plan, {})
            scene = read_cache(root / 'config.json')['sections'][0]
            self.assertEqual(scene['variant'], 'type'); self.assertEqual(scene['media'], '')
