import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import antigravity_brief as brief
import reference_styles
import video_studio as studio
from pipeline_common import read_cache, write_json

CONVERSATION = brief.DEFAULT_CONVERSATION
EXAMPLE = {'project_name': 'Imported game video', 'script': 'Play OpenTTD.', 'games': [
    {'exact_name': 'OpenTTD', 'spoken_names': ['OpenTTD'],
     'youtube_gameplay_url': 'https://youtu.be/ESlyTiZwsDk', 'logo_image_url': None}]}
VOICE = {'configured': True, 'defaults': {'source': 'elevenlabs', 'voice_id': 'saved_voice', 'model_id': 'eleven_multilingual_v2'}}


class BriefAutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = studio.Studio(self.root / 'data', self.root / 'projects')
        self.connection = patch.object(reference_styles, 'settings', return_value={
            'providers': {'antigravity': {'installed': True, 'cli_path': 'agy.exe', 'model': 'gemini-test'}}})
        self.connection.start(); self.addCleanup(self.connection.stop)
        transcript = patch.object(brief, 'transcript_path', return_value=self.root / 'transcript.jsonl')
        transcript.start(); self.addCleanup(transcript.stop)

    def start(self, build=False):
        with patch.object(studio.threading, 'Thread'), patch.object(self.app.voice, 'snapshot', return_value=VOICE):
            return self.app.start_brief_automation(CONVERSATION, build=build)

    def exporter_process(self, command, **kwargs):
        project = Path(command[command.index('--project') + 1])
        write_json(project / 'ai_brief.json', EXAMPLE)
        return MagicMock(stdout=io.StringIO('[BRIEF] JSON brief validated and saved\n'), wait=MagicMock(return_value=0))

    def test_default_conversation_and_invalid_inputs(self):
        self.assertEqual(brief.settings(self.app.data)['conversation_id'], CONVERSATION)
        for value in ('', 'latest', '--continue', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.app.start_brief_automation(value)
        with self.assertRaises(ValueError): self.app.start_brief_automation(CONVERSATION, request=[])
        self.assertEqual(self.app.registry, {})

    def test_voice_preflight_and_busy_job_do_not_create_projects(self):
        with self.assertRaisesRegex(ValueError, 'ElevenLabs'):
            self.app.start_brief_automation(CONVERSATION)
        self.assertEqual(self.app.registry, {})
        self.app.job = {'status': 'running'}
        with self.assertRaisesRegex(ValueError, 'current job'): self.start()
        self.assertEqual(self.app.registry, {})

    def test_import_only_validates_and_saves_without_starting_production(self):
        result = self.start(); job = self.app.job; path = self.app.project(result['project']['id'])
        with patch.object(studio.subprocess, 'Popen', side_effect=self.exporter_process) as process, patch.object(self.app, 'run') as produce:
            self.app.run_brief_automation(job, path)
        produce.assert_not_called(); self.assertEqual(process.call_count, 1)
        project = self.app.load(job['project'])
        self.assertEqual(project['editor']['script'], EXAMPLE['script'])
        self.assertEqual(project['editor']['name'], EXAMPLE['project_name'])
        self.assertEqual(self.app.registry[job['project']]['name'], EXAMPLE['project_name'])
        self.assertEqual(project['ai_workflow']['status'], 'awaiting_assets')
        self.assertFalse(project['ai_workflow']['auto_build'])
        self.assertTrue(read_cache(path / 'config.json')['brief_sources'])
        self.assertEqual(job['status'], 'complete')

    def test_automatic_build_runs_voice_assets_then_renderer_in_same_job(self):
        result = self.start(build=True); job = self.app.job; path = self.app.project(result['project']['id'])
        calls = []
        def process(command, **kwargs):
            calls.append(command)
            if 'antigravity_brief.py' in command[2]: return self.exporter_process(command, **kwargs)
            return MagicMock(stdout=io.StringIO(''), wait=MagicMock(return_value=0))
        with patch.object(studio.subprocess, 'Popen', side_effect=process):
            self.app.run_brief_automation(job, path)
        self.assertEqual([Path(command[2]).name for command in calls], [
            'antigravity_brief.py', 'voice_generation.py', 'prepare_assets.py', 'build_video.py'])
        self.assertEqual(job['status'], 'complete')
        self.assertEqual(self.app.workflow(job['project'])['status'], 'complete')
        self.assertEqual(read_cache(path / 'voiceover.json')['voice_id'], 'saved_voice')

    def test_invalid_provider_brief_stops_before_voice_and_render(self):
        result = self.start(build=True); job = self.app.job; path = self.app.project(result['project']['id'])
        write_json(path / 'ai_brief.json', {'script': 'Invalid'})
        with patch.object(studio.subprocess, 'Popen', return_value=MagicMock(stdout=io.StringIO(''), wait=MagicMock(return_value=0))), patch.object(self.app, 'run') as produce:
            self.app.run_brief_automation(job, path)
        self.assertEqual(job['status'], 'failed'); produce.assert_not_called()
        self.assertEqual(self.app.workflow(job['project'])['failed_step'], 'brief_import')

    def test_failed_import_retries_same_project_and_request(self):
        result = self.start(); job = self.app.job; path = self.app.project(result['project']['id'])
        with patch.object(studio.subprocess, 'Popen', return_value=MagicMock(stdout=io.StringIO('[BRIEF ERROR] Check the conversation ID.\n'), wait=MagicMock(return_value=1))):
            self.app.run_brief_automation(job, path)
        self.assertIn('conversation ID', job['error'])
        with patch.object(studio.threading, 'Thread'):
            retried = self.app.retry_ai(job['project'])
        self.assertEqual(retried['project']['id'], job['project']); self.assertEqual(len(self.app.registry), 1)

    def test_cancelled_import_never_starts_voice_or_build(self):
        result = self.start(build=True); job = self.app.job; job['cancel'] = True
        path = self.app.project(result['project']['id'])
        with patch.object(studio.subprocess, 'Popen') as process, patch.object(self.app, 'run') as produce:
            self.app.run_brief_automation(job, path)
        process.assert_not_called(); produce.assert_not_called(); self.assertEqual(job['status'], 'cancelled')

    def test_restart_marks_fetch_interrupted_and_keeps_retry_metadata(self):
        result = self.start()
        restarted = studio.Studio(self.app.data, self.app.projects)
        workflow = restarted.workflow(result['project']['id'])
        self.assertEqual(workflow['status'], 'interrupted')
        self.assertEqual(workflow['failed_step'], 'brief_import')
        self.assertEqual(workflow['conversation_id'], CONVERSATION)

    def test_fetch_uses_exact_conversation_and_rejects_wrong_conversation(self):
        self.root.mkdir(exist_ok=True)
        with patch.object(reference_styles, 'ask_antigravity', return_value=({'brief': EXAMPLE, 'error': ''}, {'conversation_id': CONVERSATION})) as ask:
            self.assertEqual(brief.fetch(self.root, self.app.data, CONVERSATION, mode='latest'), EXAMPLE)
        self.assertEqual(ask.call_args.args[0]['conversation_id'], CONVERSATION)
        self.assertTrue(ask.call_args.args[0]['subscription_only'])
        self.assertIn('most recent COMPLETE', ask.call_args.args[2])
        with patch.object(reference_styles, 'ask_antigravity', return_value=({'brief': EXAMPLE, 'error': ''}, {'conversation_id': 'other'})):
            with self.assertRaisesRegex(ValueError, 'did not resume'): brief.fetch(self.root, self.app.data, CONVERSATION, mode='latest')

    def test_empty_or_incomplete_conversation_never_creates_brief(self):
        for value in ({'brief': None, 'error': 'No brief'}, {'brief': {}, 'error': ''}):
            with patch.object(reference_styles, 'ask_antigravity', return_value=(value, {'conversation_id': CONVERSATION})):
                with self.assertRaisesRegex(ValueError, 'complete brief'): brief.fetch(self.root, self.app.data, CONVERSATION, mode='latest')
        self.assertFalse((self.root / 'ai_brief.json').exists())

    def test_local_desktop_history_imports_latest_assistant_brief_without_cli(self):
        older = {**EXAMPLE, 'project_name': 'Older episode'}
        rows = [{'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'step_index': 1, 'content': json.dumps(older)},
                {'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'status': 'DONE', 'content': json.dumps(older)},
                {'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'step_index': 3, 'content': '```json\n' + json.dumps(EXAMPLE) + '\n```'}]
        (self.root / 'transcript.jsonl').write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
        with patch.object(reference_styles, 'ask_antigravity') as ask:
            self.assertEqual(brief.fetch(self.root, self.app.data, CONVERSATION, mode='latest'), EXAMPLE)
        ask.assert_not_called()
        self.assertEqual(read_cache(self.root / 'brief_automation_result.json')['step_index'], 3)

    def test_invalid_latest_desktop_brief_does_not_fall_back_to_old_episode(self):
        rows = [{'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': json.dumps(EXAMPLE)},
                {'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': json.dumps({**EXAMPLE, 'games': []})}]
        with self.assertRaises(ValueError): brief.latest_brief(rows)
        rows[-1]['status'] = 'RUNNING'
        with self.assertRaisesRegex(ValueError, 'still writing'): brief.latest_brief(rows)
        with self.assertRaisesRegex(ValueError, 'No complete'): brief.latest_brief([{'source': 'USER_EXPLICIT', 'content': json.dumps(EXAMPLE)}])

    def test_desktop_followup_uses_history_as_context_instead_of_unavailable_cli_id(self):
        row = {'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': json.dumps(EXAMPLE)}
        (self.root / 'transcript.jsonl').write_text(json.dumps(row), encoding='utf-8')
        fresh = {**EXAMPLE, 'script': 'Explore a brand new game today.'}
        with patch.object(reference_styles, 'ask_antigravity', return_value=({'brief': fresh, 'error': ''}, {'conversation_id': 'new-cli-id'})) as ask:
            brief.fetch(self.root, self.app.data, CONVERSATION, 'Make the next episode')
        self.assertNotIn('conversation_id', ask.call_args.args[0])
        self.assertIn('Imported game video', ask.call_args.args[2])
        self.assertEqual(read_cache(self.root / 'brief_automation_result.json')['source'], 'cli_context')

    def test_episode_number_supports_the_arabic_series_title(self):
        self.assertEqual(brief.episode_number({'project_name': '\u0623\u0644\u0639\u0627\u0628 - \u0627\u0644\u062d\u0644\u0642\u0629 18'}), 18)
        self.assertEqual(brief.episode_number({'project_name': 'Episode 19'}), 19)

    def test_default_action_generates_new_episode_even_with_blank_preferences(self):
        result = self.start(build=True)
        self.assertEqual(result['project']['ai_workflow']['episode_mode'], 'new')
        self.assertEqual(result['project']['ai_workflow']['brief_request'], '')
        self.assertIn('Generating', result['job']['stage'])

    def test_blank_preferences_generate_next_episode_and_advance_saved_history(self):
        old = {**EXAMPLE, 'project_name': 'Episode 18'}
        fresh = {**EXAMPLE, 'project_name': 'Episode 19', 'script': 'Discover Endless Sky today.'}
        following = {**EXAMPLE, 'project_name': 'Episode 20', 'script': 'Find a different adventure tomorrow.'}
        row = {'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': json.dumps(old)}
        (self.root / 'transcript.jsonl').write_text(json.dumps(row), encoding='utf-8')
        replies = [({'brief': fresh, 'error': ''}, {'conversation_id': 'cli-19'}),
                   ({'brief': following, 'error': ''}, {'conversation_id': 'cli-20'})]
        with patch.object(reference_styles, 'ask_antigravity', side_effect=replies) as ask:
            self.assertEqual(brief.fetch(self.root / 'one', self.app.data, CONVERSATION), fresh)
            self.assertIn('required next episode number is 19', ask.call_args.args[2])
            self.assertEqual(brief.fetch(self.root / 'one', self.app.data, CONVERSATION), fresh)
            self.assertEqual(ask.call_count, 1, 'A retry must reuse the saved new episode')
            self.assertEqual(brief.fetch(self.root / 'two', self.app.data, CONVERSATION), following)
            self.assertIn('required next episode number is 20', ask.call_args.args[2])
            self.assertIn('Discover Endless Sky today.', ask.call_args.args[2])
        self.assertEqual(len(read_cache(brief.episode_archive(self.app.data, CONVERSATION))['episodes']), 2)

    def test_parallel_requests_for_same_series_generate_different_episode_numbers(self):
        from concurrent.futures import ThreadPoolExecutor
        import re
        import time
        old = {**EXAMPLE, 'project_name': 'Episode 18'}
        row = {'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': json.dumps(old)}
        (self.root / 'transcript.jsonl').write_text(json.dumps(row), encoding='utf-8')
        def generate(config, project, prompt, *args, **kwargs):
            number = int(re.search(r'required next episode number is (\d+)', prompt)[1])
            time.sleep(.1)
            return {'brief': {**EXAMPLE, 'project_name': f'Episode {number}', 'script': f'Fresh narration for episode {number}.'}, 'error': ''}, {'conversation_id': 'cli'}
        with patch.object(reference_styles, 'ask_antigravity', side_effect=generate):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda name: brief.fetch(self.root / name, self.app.data, CONVERSATION), ['one', 'two']))
        self.assertEqual({brief.episode_number(value) for value in results}, {19, 20})
        self.assertEqual(len(read_cache(brief.episode_archive(self.app.data, CONVERSATION))['episodes']), 2)

    def test_reused_script_and_repeated_episode_number_stop_before_build(self):
        old = {**EXAMPLE, 'project_name': 'Episode 18'}
        row = {'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': json.dumps(old)}
        (self.root / 'transcript.jsonl').write_text(json.dumps(row), encoding='utf-8')
        for candidate, message in [(old, 'previous script'), ({**old, 'script': 'A fresh script with an old number.'}, 'episode 19')]:
            with patch.object(reference_styles, 'ask_antigravity', return_value=({'brief': candidate, 'error': ''}, {'conversation_id': 'cli'})):
                with self.assertRaisesRegex(ValueError, message):
                    brief.fetch(self.root / 'new', self.app.data, CONVERSATION)
        self.assertFalse((self.root / 'new/ai_brief.json').exists())

    def test_episode_mode_is_validated_and_latest_mode_is_preserved_for_retry(self):
        with self.assertRaises(ValueError): self.app.start_brief_automation(CONVERSATION, episode_mode='unknown')
        with patch.object(studio.threading, 'Thread'):
            result = self.app.start_brief_automation(CONVERSATION, build=False, episode_mode='latest')
        identifier = result['project']['id']
        workflow = self.app.workflow(identifier); workflow.update(status='failed')
        write_json(self.app.project(identifier) / 'ai_workflow.json', workflow)
        self.app.job['status'] = 'failed'
        with patch.object(self.app, 'start_brief_automation', return_value={}) as start:
            self.app.retry_ai(identifier)
        self.assertEqual(start.call_args.kwargs['episode_mode'], 'latest')

    def test_timed_out_research_is_finalized_once_without_repeating_searches(self):
        fresh = {**EXAMPLE, 'script': 'A fresh episode after bounded research.'}
        interrupted = reference_styles.AntigravityIncomplete('No final JSON', CONVERSATION, 'timeout')
        with patch.object(reference_styles, 'ask_antigravity', side_effect=[interrupted, ({'brief': fresh, 'error': ''}, {'conversation_id': CONVERSATION})]) as ask:
            self.assertEqual(brief.fetch(self.root, self.app.data, CONVERSATION), fresh)
        self.assertEqual(ask.call_count, 2)
        self.assertIn('at most EIGHT search_web calls', ask.call_args_list[0].args[2])
        self.assertIn('Stop researching now', ask.call_args_list[1].args[2])
        self.assertEqual(ask.call_args_list[1].kwargs['timeout'], 120)
        self.assertEqual(ask.call_args_list[1].args[0]['conversation_id'], CONVERSATION)

    def test_saved_unfinished_research_resumes_instead_of_starting_again(self):
        write_json(self.root / 'reference/antigravity-response.json', {'result': {
            'status': 'SUCCESS', 'conversation_id': CONVERSATION, 'response': '', 'duration_seconds': 600}})
        fresh = {**EXAMPLE, 'script': 'Recovered fresh narration.'}
        with patch.object(reference_styles, 'ask_antigravity', return_value=({'brief': fresh, 'error': ''}, {'conversation_id': CONVERSATION})) as ask:
            brief.fetch(self.root, self.app.data, CONVERSATION)
        ask.assert_called_once()
        self.assertIn('Stop researching now', ask.call_args.args[2])

    def test_permission_failure_is_reported_without_automatic_permission_bypass(self):
        denied = reference_styles.AntigravityIncomplete('A tool permission was denied.', CONVERSATION, 'permission')
        with patch.object(reference_styles, 'ask_antigravity', side_effect=denied) as ask:
            with self.assertRaises(reference_styles.AntigravityIncomplete):
                brief.fetch(self.root, self.app.data, CONVERSATION)
        ask.assert_called_once()

    def test_large_old_conversation_text_is_not_repeated_in_generation_prompt(self):
        rows = [{'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': 'old research ' * 10000},
                {'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'content': 'Keep the intro short.'}]
        (self.root / 'transcript.jsonl').write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
        with patch.object(reference_styles, 'ask_antigravity', return_value=({'brief': EXAMPLE, 'error': ''}, {'conversation_id': 'new'})) as ask:
            brief.fetch(self.root, self.app.data, CONVERSATION)
        self.assertLess(len(ask.call_args.args[2]), 10000)
        self.assertIn('Keep the intro short.', ask.call_args.args[2])
        self.assertNotIn('old research old research', ask.call_args.args[2])

    def test_missing_links_use_real_matching_youtube_results(self):
        fresh = {**EXAMPLE, 'script': 'Try a fresh OpenTTD episode.',
                 'games': [{**EXAMPLE['games'][0], 'youtube_gameplay_url': None}]}
        entries = [
            {'id': 'aaaaaaaaaaa', 'title': 'A different game', 'duration': 600},
            {'id': 'bbbbbbbbbbb', 'title': 'OpenTTD gameplay', 'duration': 600, 'live_status': 'is_live'},
            {'id': 'bad-id', 'title': 'OpenTTD gameplay', 'duration': 600},
            {'id': 'ESlyTiZwsDk', 'title': 'Open TTD gameplay no commentary', 'duration': 600}]
        with patch.object(reference_styles, 'ask_antigravity', return_value=({'brief': fresh, 'error': ''}, {'conversation_id': CONVERSATION})), patch('yt_dlp.YoutubeDL') as search:
            search.return_value.__enter__.return_value.extract_info.return_value = {'entries': entries}
            value = brief.fetch(self.root, self.app.data, CONVERSATION)
        self.assertEqual(value['games'][0]['youtube_gameplay_url'], 'https://www.youtube.com/watch?v=ESlyTiZwsDk')
        search.return_value.__enter__.return_value.extract_info.assert_called_once_with('ytsearch5:OpenTTD gameplay no commentary', download=False)
        self.assertEqual(read_cache(self.root / 'ai_brief.json')['script'], fresh['script'])

    def test_gameplay_lookup_failure_preserves_script_for_retry_without_ai(self):
        fresh = {**EXAMPLE, 'script': 'Saved new narration for OpenTTD.'}
        draft = {**fresh, 'games': [{**fresh['games'][0], 'youtube_gameplay_url': None}]}
        with patch.object(reference_styles, 'ask_antigravity', return_value=({'brief': draft, 'error': ''}, {'conversation_id': CONVERSATION})), patch.object(brief, 'resolve_gameplay_sources', side_effect=ValueError('YouTube temporarily unavailable')):
            with self.assertRaisesRegex(ValueError, 'temporarily unavailable'):
                brief.fetch(self.root, self.app.data, CONVERSATION)
        self.assertFalse((self.root / 'ai_brief.json').exists())
        self.assertEqual(read_cache(self.root / 'brief_automation_draft.json')['brief']['script'], fresh['script'])
        with patch.object(reference_styles, 'ask_antigravity') as ask, patch.object(brief, 'resolve_gameplay_sources', return_value=fresh):
            self.assertEqual(brief.fetch(self.root, self.app.data, CONVERSATION), fresh)
        ask.assert_not_called()

    def test_draft_is_regenerated_if_another_project_advanced_the_episode_number(self):
        old = {**EXAMPLE, 'project_name': 'Episode 18'}
        row = {'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': json.dumps(old)}
        (self.root / 'transcript.jsonl').write_text(json.dumps(row), encoding='utf-8')
        draft = {**EXAMPLE, 'project_name': 'Episode 19', 'script': 'First draft narration.'}
        with patch.object(reference_styles, 'ask_antigravity', return_value=({'brief': draft, 'error': ''}, {'conversation_id': 'cli'})), patch.object(brief, 'resolve_gameplay_sources', side_effect=ValueError('lookup failed')):
            with self.assertRaises(ValueError): brief.fetch(self.root, self.app.data, CONVERSATION)
        produced = {**EXAMPLE, 'project_name': 'Episode 19', 'script': 'Another project finished episode nineteen.'}
        write_json(brief.episode_archive(self.app.data, CONVERSATION), {'episodes': {'another': produced}})
        next_episode = {**EXAMPLE, 'project_name': 'Episode 20', 'script': 'A fresh episode twenty.'}
        with patch.object(reference_styles, 'ask_antigravity', return_value=({'brief': next_episode, 'error': ''}, {'conversation_id': 'cli'})) as ask:
            self.assertEqual(brief.fetch(self.root, self.app.data, CONVERSATION), next_episode)
        self.assertIn('required next episode number is 20', ask.call_args.args[2])

    def test_missing_or_invalid_gameplay_does_not_select_unrelated_or_live_video(self):
        missing = {**EXAMPLE, 'games': [{**EXAMPLE['games'][0], 'youtube_gameplay_url': None}]}
        with patch('yt_dlp.YoutubeDL') as search:
            search.return_value.__enter__.return_value.extract_info.return_value = {'entries': [
                {'id': 'aaaaaaaaaaa', 'title': 'OpenTTD live gameplay', 'duration': 600, 'live_status': 'is_live'},
                {'id': 'bbbbbbbbbbb', 'title': 'Other game gameplay', 'duration': 600}]}
            with self.assertRaisesRegex(ValueError, 'No matching YouTube'): brief.resolve_gameplay_sources(missing)
        invalid = {**EXAMPLE, 'games': [{**EXAMPLE['games'][0], 'youtube_gameplay_url': 'https://example.com/watch'}]}
        with patch('yt_dlp.YoutubeDL') as search:
            with self.assertRaisesRegex(ValueError, 'YouTube video'): brief.resolve_gameplay_sources(invalid)
        search.assert_not_called()

    def test_latest_export_does_not_fill_links_or_change_saved_episode(self):
        missing = {**EXAMPLE, 'games': [{**EXAMPLE['games'][0], 'youtube_gameplay_url': None}]}
        with patch.object(reference_styles, 'ask_antigravity', return_value=({'brief': missing, 'error': ''}, {'conversation_id': CONVERSATION})), patch.object(brief, 'resolve_gameplay_sources') as resolve:
            with self.assertRaises(ValueError): brief.fetch(self.root, self.app.data, CONVERSATION, mode='latest')
        resolve.assert_not_called()

    def test_missing_cli_conversation_has_actionable_error(self):
        result = {'event': 'result', 'result': {'status': 'ERROR', 'error': 'trajectory not found'}}
        with patch.object(reference_styles.subprocess, 'run', return_value=MagicMock(returncode=1, stdout=json.dumps(result), stderr='')):
            with self.assertRaisesRegex(ValueError, 'not found in the connected'):
                reference_styles.ask_antigravity({'cli_path': 'agy.exe', 'model': 'gemini-test', 'conversation_id': CONVERSATION}, self.root, 'Export')

    def test_cli_resume_flag_is_passed_as_an_argument(self):
        config = {'cli_path': 'agy.exe', 'model': 'gemini-test', 'conversation_id': CONVERSATION}
        output = {'event': 'result', 'result': {'status': 'SUCCESS', 'response': 'done'}}
        with patch.object(reference_styles.subprocess, 'run', return_value=MagicMock(returncode=0, stdout=json.dumps(output), stderr='')) as run:
            self.assertEqual(reference_styles.ask_antigravity(config, self.root, 'Export brief'), 'done')
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('--conversation') + 1], CONVERSATION)
        self.assertNotIn('--dangerously-skip-permissions', command)


if __name__ == '__main__': unittest.main()
