import copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

import reference_styles as ref
import style_library as lib
import video_studio as studio
from pipeline_common import write_json, read_cache
from test_reference_styles import valid_plan


def profile(**analysis):
    base = valid_plan()['analysis']
    base.update(analysis)
    return {'analysis': base, 'layouts': {'variants': ['card', 'type'], 'backdrops': ['grid'], 'media_treatment': ['photo'],
                                          'text_position': ['center'], 'accent_style': ['underline'], 'motifs': ['none'],
                                          'transition_style': ['settle'], 'notes': ''}}


def result(returncode=0, stdout='', stderr=''):
    return type('Result', (), {'returncode': returncode, 'stdout': stdout, 'stderr': stderr})()


SIGNED_IN = result(stdout=json.dumps({'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'firstParty'}))


def stream(*events):
    return result(stdout='\n'.join(json.dumps(event) for event in events))


def success(value=None, text='READY'):
    event = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': text, 'session_id': 's1', 'num_turns': 2, 'duration_ms': 1500}
    if value is not None: event['structured_output'] = value
    return event


def read(path, tool_id='t1'):
    return {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': tool_id, 'name': 'Read', 'input': {'file_path': str(path)}}]}}


def ready_style(data, name='Soft', **analysis):
    created = lib.create(data, name, 'claude', 'opus')
    value = read_cache(lib.folder(data, created['id']) / 'style.json')
    value.update(status='ready', profile=profile(**analysis))
    write_json(lib.folder(data, created['id']) / 'style.json', value)
    return created['id']


class ClaudeProviderTests(unittest.TestCase):
    def test_claude_is_a_provider_with_blank_default_and_safe_model_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            config = ref.configure(Path(folder), model='', provider='claude')
            self.assertEqual(config['provider'], 'claude')
            self.assertEqual(config['model'], '')
            self.assertEqual(ref.configure(Path(folder), model='opus', provider='claude')['model'], 'opus')
            self.assertEqual(ref.check_model('claude', 'claude-opus-5-5'), 'claude-opus-5-5')
            for bad in ('--dangerously-skip-permissions', 'opus; rm', 'x' * 120):
                with self.assertRaises(ValueError): ref.check_model('claude', bad)

    def test_sign_in_must_be_a_claude_subscription(self):
        config = {'cli_path': 'claude.exe'}
        with patch.object(ref.subprocess, 'run', return_value=result(stdout=json.dumps({'loggedIn': False}))):
            with self.assertRaisesRegex(ValueError, 'Sign in to Claude'): ref.require_claude(config)
        api_key = result(stdout=json.dumps({'loggedIn': True, 'authMethod': 'api_key', 'apiProvider': 'firstParty'}))
        with patch.object(ref.subprocess, 'run', return_value=api_key):
            with self.assertRaisesRegex(ValueError, 'subscription'): ref.require_claude(config)
        bedrock = result(stdout=json.dumps({'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'bedrock'}))
        with patch.object(ref.subprocess, 'run', return_value=bedrock):
            with self.assertRaisesRegex(ValueError, 'subscription'): ref.require_claude(config)
        with self.assertRaisesRegex(ValueError, 'missing'): ref.require_claude({'cli_path': ''})

    def test_api_keys_are_removed_from_the_claude_environment(self):
        with patch.dict(ref.os.environ, {'ANTHROPIC_API_KEY': 'secret', 'ANTHROPIC_BASE_URL': 'http://proxy', 'CLAUDECODE': '1', 'KEEP_ME': 'yes'}):
            with patch.object(ref.subprocess, 'run', return_value=SIGNED_IN) as run:
                ref.require_claude({'cli_path': 'claude.exe'})
            env = run.call_args.kwargs['env']
        self.assertNotIn('ANTHROPIC_API_KEY', env); self.assertNotIn('ANTHROPIC_BASE_URL', env); self.assertNotIn('CLAUDECODE', env)
        self.assertEqual(env['KEEP_ME'], 'yes')
        self.assertEqual(run.call_args.args[0], ['claude.exe', 'auth', 'status', '--json'])

    def test_claude_runs_read_only_with_schema_and_returns_structured_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(ref.subprocess, 'run', side_effect=[SIGNED_IN, stream(success(valid_plan()))]) as run:
                plan, meta = ref.ask_claude({'cli_path': 'claude.exe', 'model': 'sonnet'}, root, 'Plan', ref.SCHEMA)
            self.assertEqual(plan, valid_plan()); self.assertEqual(meta['session_id'], 's1')
            command = run.call_args.args[0]
            for flag in ('-p', '--restricted', '--strict-mcp-config', '--no-session-persistence', '--json-schema'):
                self.assertIn(flag, command)
            self.assertEqual(command[command.index('--tools') + 1], 'Read,WebSearch,WebFetch')
            self.assertEqual(command[command.index('--permission-mode') + 1], 'dontAsk')
            self.assertEqual(command[command.index('--model') + 1], 'sonnet')
            self.assertFalse(any('bypass' in part or 'dangerously' in part for part in command))
            self.assertEqual(run.call_args.kwargs['input'], 'Plan')
            self.assertEqual(Path(run.call_args.kwargs['cwd']), root.resolve())

    def test_blank_model_uses_claude_default_and_text_answers_work(self):
        with patch.object(ref.subprocess, 'run', side_effect=[SIGNED_IN, stream(success())]) as run:
            self.assertEqual(ref.ask_claude({'cli_path': 'claude.exe', 'model': ''}, '.', 'Reply READY'), 'READY')
        self.assertNotIn('--model', run.call_args.args[0])

    def test_reference_sheets_must_actually_be_opened(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'reference').mkdir()
            (root / 'reference/sheet.jpg').write_bytes(b'image')
            write_json(root / 'reference/context.json', {'reference': {'sheets': ['reference/sheet.jpg']}, 'available_assets': []})
            with patch.object(ref.subprocess, 'run', side_effect=[SIGNED_IN, stream(success(valid_plan()))]):
                with self.assertRaisesRegex(ValueError, 'opened every reference image'):
                    ref.ask_claude({'cli_path': 'claude.exe'}, root, 'Plan', ref.SCHEMA)
            failed_read = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'is_error': True}]}}
            with patch.object(ref.subprocess, 'run', side_effect=[SIGNED_IN, stream(read(root / 'reference/sheet.jpg'), failed_read, success(valid_plan()))]):
                with self.assertRaisesRegex(ValueError, 'opened every reference image'):
                    ref.ask_claude({'cli_path': 'claude.exe'}, root, 'Plan', ref.SCHEMA)
            with patch.object(ref.subprocess, 'run', side_effect=[SIGNED_IN, stream(read('reference/sheet.jpg'), success(valid_plan()))]) as run:
                plan, _ = ref.ask_claude({'cli_path': 'claude.exe'}, root, 'Plan', ref.SCHEMA)
            self.assertEqual(plan, valid_plan())
            self.assertIn(str((root / 'reference/sheet.jpg').resolve()), run.call_args.kwargs['input'])

    def test_failures_are_explained_and_partial_answers_rejected(self):
        limited = stream({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True, 'result': 'Usage limit reached'})
        with patch.object(ref.subprocess, 'run', side_effect=[SIGNED_IN, limited]):
            with self.assertRaisesRegex(ValueError, 'usage limit'): ref.ask_claude({'cli_path': 'claude.exe'}, '.', 'Plan', ref.SCHEMA)
        with patch.object(ref.subprocess, 'run', side_effect=[SIGNED_IN, result(1, '', 'crashed')]):
            with self.assertRaisesRegex(ValueError, 'did not complete'): ref.ask_claude({'cli_path': 'claude.exe'}, '.', 'Plan')
        with patch.object(ref.subprocess, 'run', side_effect=[SIGNED_IN, stream(success(text='not json'))]):
            with self.assertRaisesRegex(ValueError, 'invalid structured'): ref.ask_claude({'cli_path': 'claude.exe'}, '.', 'Plan', ref.SCHEMA)

    def test_models_and_routing(self):
        with tempfile.TemporaryDirectory() as folder:
            connections = {'providers': {'claude': {'cli_path': 'claude.exe', 'installed': True}}}
            with patch.object(ref, 'settings', return_value=connections), patch.object(ref.subprocess, 'run', return_value=SIGNED_IN):
                models = ref.available_models(Path(folder), 'claude')['models']
            self.assertEqual([row['id'] for row in models], ['opus', 'sonnet', 'haiku'])
        with patch.object(ref, 'ask_claude', return_value=('answer', {})) as claude, patch.object(ref, 'ask_codex') as codex:
            ref.ask_provider({'provider': 'claude'}, '.', 'Analyze')
        claude.assert_called_once(); codex.assert_not_called()

    def test_vscode_extension_binary_is_discovered_newest_first(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            for version in ('2.1.99', '2.1.322'):
                binary = home / f'.vscode/extensions/anthropic.claude-code-{version}-win32-x64/resources/native-binary/claude.exe'
                binary.parent.mkdir(parents=True); binary.write_bytes(b'exe')
            with patch.object(ref.Path, 'home', return_value=home), patch.object(ref.shutil, 'which', return_value=None):
                config = ref.settings(home / 'data')['providers']['claude']
            self.assertTrue(config['installed']); self.assertIn('2.1.322', config['cli_path'])


class LibraryTests(unittest.TestCase):
    def test_create_upload_and_status(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            style = lib.create(data, '  Soft editorial ', 'claude', 'opus')
            self.assertEqual(style['name'], 'Soft editorial'); self.assertEqual(style['status'], 'awaiting_upload')
            with self.assertRaises(ValueError): lib.create(data, '', 'claude')
            with self.assertRaises(ValueError): lib.create(data, 'Bad provider', 'unknown')
            with self.assertRaises(ValueError): lib.upload_target(data, style['id'], 'reference', 'clip.exe')
            with self.assertRaises(ValueError): lib.upload_target(data, '../etc', 'reference', 'clip.mp4')
            target = lib.upload_target(data, style['id'], 'reference', 'clip.MP4')
            self.assertEqual(target.name, 'source.mp4'); target.write_bytes(b'video')
            self.assertEqual(lib.finish_upload(data, style['id'], 'reference', target)['status'], 'awaiting_analysis')
            screen = lib.upload_target(data, style['id'], 'screen', 'shot.png'); screen.parent.mkdir(parents=True); screen.write_bytes(b'png')
            self.assertEqual(lib.finish_upload(data, style['id'], 'screen', screen)['screens'], 1)

    def test_profile_validation_and_editing(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder); style_id = ready_style(data)
            edited = profile(accent='#ff0000', unknown_field='dropped')
            row = lib.update(data, style_id, 'Renamed', edited)
            self.assertEqual(row['name'], 'Renamed'); self.assertTrue(row['edited'])
            self.assertEqual(row['profile']['analysis']['accent'], '#ff0000')
            self.assertNotIn('unknown_field', row['profile']['analysis'])
            for bad in (profile(accent='red'), profile(caption_y=2), {**profile(), 'layouts': {**profile()['layouts'], 'variants': []}},
                        {**profile(), 'layouts': {**profile()['layouts'], 'backdrops': ['shell']}}):
                with self.assertRaises(ValueError): lib.update(data, style_id, profile=bad)

    def test_delete_moves_style_to_trash(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder); style_id = ready_style(data)
            with self.assertRaises(ValueError): lib.delete(data, style_id)
            lib.delete(data, style_id, True)
            self.assertEqual(lib.list_styles(data), [])
            self.assertTrue((data / 'reference_styles/deleted' / style_id / 'style.json').is_file())

    def test_snapshot_and_mix_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder); first, second = ready_style(data, 'A'), ready_style(data, 'B')
            pending = lib.create(data, 'Not analyzed', 'claude')['id']
            self.assertEqual([row['name'] for row in lib.snapshot(data, [first, second])], ['A', 'B'])
            for bad in ([], [first, first], [first, second, pending], [pending], 'abc'):
                with self.assertRaises(ValueError): lib.snapshot(data, bad)
        self.assertEqual(lib.validate_mix({'colors': 'b'}, 1), {})
        mix = lib.validate_mix({'colors': 'b'}, 2)
        self.assertEqual(mix['colors'], 'b'); self.assertEqual(mix['fonts'], 'mix'); self.assertEqual(set(mix), set(lib.CATEGORIES))
        for bad in ({'colors': 'c'}, {'sound': 'a'}, ['a']):
            with self.assertRaises(ValueError): lib.validate_mix(bad, 2)

    def test_one_style_is_copied_exactly(self):
        styles = [{'id': 'a', 'name': 'Soft', 'profile': profile(accent='#112233')}]
        plan = valid_plan(); plan['analysis']['accent'] = '#999999'
        lib.apply_mix(plan, styles, {})
        self.assertEqual(plan['analysis'], styles[0]['profile']['analysis'])

    def test_two_styles_enforce_fixed_categories_and_keep_ai_mix(self):
        a = profile(background='#111111', heading_font='serif', caption_style='word', contrast_background='#222222')
        b = profile(background='#eeeeee', heading_font='display', caption_style='phrase', entrance='zoom')
        b['analysis'].pop('contrast_background', None)
        styles = [{'id': 'a', 'name': 'Dark', 'profile': a}, {'id': 'b', 'name': 'Bright', 'profile': b}]
        plan = valid_plan()
        plan['analysis'].update(background='#777777', contrast_background='#555555', heading_font='sans', caption_style='phrase', entrance='slide')
        lib.apply_mix(plan, styles, {'colors': 'b', 'fonts': 'a', 'captions': 'a'})
        result = plan['analysis']
        self.assertEqual(result['background'], '#eeeeee'); self.assertNotIn('contrast_background', result)
        self.assertEqual(result['heading_font'], 'serif'); self.assertEqual(result['caption_style'], 'word')
        self.assertEqual(result['entrance'], 'slide')  # motion stayed on AI mix
        self.assertEqual(result['name'], 'Dark + Bright')
        self.assertTrue(all(row['detail'].startswith(('Dark: ', 'Bright: ')) for row in result['observations']))
        ref.validate_analysis(result)

    def test_planning_context_lists_styles_and_categories(self):
        styles = [{'id': 'a', 'name': 'Dark', 'profile': profile()}, {'id': 'b', 'name': 'Bright', 'profile': profile()}]
        context = lib.planning_context(styles, {'layouts': 'b'})
        self.assertEqual([row['label'] for row in context['saved_styles']], ['A', 'B'])
        self.assertEqual(context['style_mix']['layouts'], 'b')
        self.assertIn('transition_style', context['style_categories']['transitions'])
        self.assertIn('copy it exactly', lib.planning_context(styles[:1], {})['style_mix'])

    def test_analysis_saves_profile_thumbnail_and_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder); style_id = lib.create(data, 'Soft', 'claude', 'opus')['id']
            path = lib.folder(data, style_id)
            (path / 'source.mp4').write_bytes(b'video')
            value = read_cache(path / 'style.json'); value['source_file'] = 'source.mp4'; write_json(path / 'style.json', value)

            def sample(project, reference):
                frames = Path(project) / 'reference/frames'; frames.mkdir(parents=True, exist_ok=True)
                (frames / 'frame-0001.jpg').write_bytes(b'jpg'); (frames / 'sheet-01.jpg').write_bytes(b'jpg')
                return {'sheets': ['reference/frames/sheet-01.jpg'], 'duration_seconds': 4}
            connections = {'provider': 'antigravity', 'providers': {'claude': {'cli_path': 'claude.exe', 'model': 'haiku', 'installed': True}}}
            with patch.object(ref, 'sample_reference', side_effect=sample), patch.object(ref, 'settings', return_value=connections), \
                 patch.object(ref, 'ask_provider', return_value=(profile(), {'session_id': 's'})) as ask:
                lib.analyze(data, style_id)
            connection, cwd, prompt, schema = ask.call_args.args
            self.assertEqual(connection['provider'], 'claude'); self.assertEqual(connection['model'], 'opus')
            self.assertEqual(Path(cwd), path); self.assertIs(schema, lib.STYLE_SCHEMA)
            self.assertIn('Break down the visual style only', prompt)
            self.assertEqual(read_cache(path / 'reference/context.json')['reference']['sheets'], ['reference/frames/sheet-01.jpg'])
            row = lib.list_styles(data)[0]
            self.assertEqual(row['status'], 'ready'); self.assertTrue(row['thumbnail'])
            self.assertEqual(row['profile'], lib.validate_profile(profile()))
            with patch.object(ref, 'sample_reference', side_effect=sample), patch.object(ref, 'settings', return_value=connections), \
                 patch.object(ref, 'ask_provider', return_value=({'analysis': {}}, {})):
                with self.assertRaises(ValueError): lib.analyze(data, style_id)
            row = lib.list_styles(data)[0]
            self.assertEqual(row['status'], 'failed'); self.assertTrue(row['error'])
            self.assertEqual(row['profile'], lib.validate_profile(profile()))  # the previous result is kept

    def test_interrupted_analysis_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder); style_id = ready_style(data)
            value = read_cache(lib.folder(data, style_id) / 'style.json'); value['status'] = 'analyzing'
            write_json(lib.folder(data, style_id) / 'style.json', value)
            self.assertEqual(lib.list_styles(data, set())[0]['status'], 'interrupted')
            self.assertEqual(lib.list_styles(data, {style_id})[0]['status'], 'analyzing')

    def test_saving_an_analyzed_project_needs_no_ai(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); project = root / 'project'; (project / 'reference/frames').mkdir(parents=True)
            (project / 'reference/frames/frame-0001.jpg').write_bytes(b'jpg'); (project / 'clip.mp4').write_bytes(b'video')
            write_json(project / 'reference_style.json', {'analysis': {**valid_plan()['analysis'], 'renderer_version': 3},
                                                           'reference_file': 'clip.mp4', 'provider': 'codex'})
            write_json(project / 'config.json', {'sections': [
                {'layout': 'reference_style', 'variant': 'type', 'backdrop': 'orbits', 'transition_style': 'wipe'},
                {'layout': 'reference_style', 'variant': 'type'}, {'layout': 'reference_style', 'variant': 'hero'}]})
            with patch.object(ref, 'ask_provider') as ask:
                style = lib.from_project(root / 'data', project)
            ask.assert_not_called()
            self.assertEqual(style['status'], 'ready'); self.assertEqual(style['origin'], 'project')
            self.assertEqual(style['name'], 'Floating editorial'); self.assertTrue(style['has_source']); self.assertTrue(style['thumbnail'])
            self.assertEqual(style['profile']['layouts']['variants'], ['type', 'hero'])
            self.assertEqual(style['profile']['layouts']['backdrops'], ['orbits'])
            self.assertNotIn('renderer_version', style['profile']['analysis'])
            write_json(project / 'reference_style.json', {'workflow': 'flow', 'analysis': valid_plan()['analysis']})
            with self.assertRaises(ValueError): lib.from_project(root / 'data', project)


class StudioLibraryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); root = Path(self.folder.name)
        self.app = studio.Studio(root / 'data', root / 'projects')
        self.first, self.second = ready_style(self.app.data, 'Dark', background='#111111'), ready_style(self.app.data, 'Bright', background='#eeeeee')

    def tearDown(self): self.folder.cleanup()

    def test_create_project_from_saved_styles(self):
        project = self.app.create_reference('Story', 'hello world', provider='claude', styles=[self.first, self.second], style_mix={'colors': 'b'})
        state = project['reference_style']
        self.assertEqual([row['name'] for row in state['library_styles']], ['Dark', 'Bright'])
        self.assertEqual(state['style_mix']['colors'], 'b'); self.assertEqual(state['style_mix']['motion'], 'mix')
        self.assertEqual(state['analysis_provider'], 'claude')
        with self.assertRaisesRegex(ValueError, 'Video Turbo animation'):
            self.app.create_reference('Flow', 'hello', workflow='flow', styles=[self.first])
        with self.assertRaises(ValueError): self.app.create_reference('Bad', 'hello', styles=['000000000000'])

    def test_saved_style_projects_need_no_reference_video(self):
        project = self.app.create_reference('Story', 'hello', provider='claude', styles=[self.first])
        path = Path(project['path']); (path / 'voiceover.mp3').write_bytes(b'audio')
        lib.update(self.app.data, self.first, 'Dark edited')
        connections = {'provider': 'claude', 'installed': True, 'providers': {'claude': {'installed': True}}}
        with patch.object(ref, 'settings', return_value=connections), patch.object(studio.threading, 'Thread'):
            result = self.app.start_reference(project['id'], False)
        self.assertIn('Claude', result['job']['stage'])
        self.assertEqual(read_cache(path / 'reference_style.json')['library_styles'][0]['name'], 'Dark edited')

    def test_worker_applies_saved_styles_and_enforces_choices(self):
        import build_video
        project = self.app.create_reference('Story', 'hello world', provider='claude', styles=[self.first, self.second], style_mix={'colors': 'b'})
        root = Path(project['path']); (root / 'voiceover.mp3').write_bytes(b'audio'); (root / 'media').mkdir()
        from PIL import Image
        Image.new('RGBA', (20, 20), (255, 255, 255, 255)).save(root / 'media/hero.png')
        plan = valid_plan(); plan['analysis']['background'] = '#777777'
        words = {'words': [{'word': 'hello', 'start': 0, 'end': .5}]}
        connections = {'provider': 'claude', 'providers': {'claude': {'cli_path': 'claude.exe', 'model': 'opus'}}}
        with patch.object(ref, 'probe', return_value=(5, [])), patch.object(ref, 'sample_reference') as sample, \
             patch.object(build_video, 'configure_project'), patch.object(build_video, 'transcribe_voiceover', return_value=words), \
             patch.object(build_video, 'apply_script', return_value=words), patch.object(ref, 'settings', return_value=connections), \
             patch.object(ref, 'ask_claude', return_value=(plan, {'session_id': 's'})) as ask:
            ref.run_project(root, self.app.data)
        sample.assert_not_called()
        prompt = ask.call_args.args[2]
        self.assertIn('saved_styles', prompt); self.assertNotIn('VIEW EVERY contact sheet', prompt)
        context = read_cache(root / 'reference/context.json')
        self.assertEqual([row['name'] for row in context['saved_styles']], ['Dark', 'Bright']); self.assertNotIn('reference', context)
        config = read_cache(root / 'config.json'); state = read_cache(root / 'reference_style.json')
        self.assertEqual(config['reference_style']['background'], '#eeeeee')
        self.assertEqual(config['reference_style']['name'], 'Dark + Bright')
        self.assertEqual(config['reference_style']['renderer_version'], 3)
        self.assertEqual(state['status'], 'ready'); self.assertIsNone(state['reference_signature'])
        self.assertFalse(self.app.reference_state(project['id'])['stale'])

    def test_style_analysis_runs_as_a_production_job(self):
        path = lib.folder(self.app.data, self.first); (path / 'source.mp4').write_bytes(b'video')
        value = read_cache(path / 'style.json'); value['source_file'] = 'source.mp4'; write_json(path / 'style.json', value)
        connections = {'provider': 'claude', 'providers': {'claude': {'installed': True}}}
        with patch.object(ref, 'settings', return_value=connections), patch.object(studio.threading, 'Thread'):
            state = self.app.start_style_analysis(self.first)
            row = next(row for row in state['styles'] if row['id'] == self.first)
            self.assertEqual(row['status'], 'queued'); self.assertTrue(row['job'])
            with self.assertRaisesRegex(ValueError, 'already'): self.app.start_style_analysis(self.first)
            job = next(job for job in self.app.all_jobs() if job.get('style') == self.first)
            self.assertEqual(job['project'], ''); self.assertTrue(job['label'].startswith('Style: '))
            self.app.idle()  # style analysis does not lock video projects
            job['status'] = 'queued'; self.app.pending.append((job, self.app.run_style, (self.first,)))
            self.app.cancel(job['id'])
        self.assertEqual(lib.record(self.app.data, self.first)['status'], 'cancelled')
        self.assertEqual(lib.record(self.app.data, self.first)['profile']['analysis']['background'], '#111111')

    def test_failed_style_job_does_not_need_a_project(self):
        job = {'id': 'j1', 'project': '', 'style': self.first, 'action': 'style_analysis', 'status': 'running', 'logs': [], 'cancel': False}
        value = read_cache(lib.folder(self.app.data, self.first) / 'style.json'); value['status'] = 'analyzing'
        write_json(lib.folder(self.app.data, self.first) / 'style.json', value)
        self.app.jobs['j1'] = job
        self.app._execute_job(job, lambda job: (_ for _ in ()).throw(RuntimeError('boom')), ())
        self.assertEqual(job['status'], 'failed'); self.assertEqual(lib.record(self.app.data, self.first)['status'], 'failed')

    def test_listing_describes_the_editor(self):
        listing = self.app.list_styles()
        self.assertEqual(len(listing['styles']), 2); self.assertEqual(listing['max_styles'], 2)
        self.assertEqual(set(listing['categories']), {'colors', 'fonts', 'motion', 'transitions', 'captions', 'layouts'})
        self.assertTrue(all(field['category'] in listing['categories'] for field in listing['fields']))
        self.assertIn('claude', listing['providers'])


if __name__ == '__main__':
    unittest.main()
