import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

import custom_scenes as cs
import reference_styles as ref
import video_sections
import video_studio as studio
from pipeline_common import read_cache, write_json
from test_reference_styles import valid_plan
from test_style_library import ready_style

GOOD = """import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {type SceneProps} from '../kit';
export default function Scene({text, palette}: SceneProps) {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{background: palette.background}}><svg xmlns="http://www.w3.org/2000/svg"/>{text.title}{frame}</AbsoluteFill>;
}
"""


def project_with_plan(root):
    plan = valid_plan(); plan['analysis']['renderer_version'] = 3
    (root / 'media').mkdir(parents=True, exist_ok=True)
    sections = [{**row, 'layout': 'reference_style', 'media': '', 'secondary_media': ''} for row in plan['scenes']]
    for row in sections: row.update(variant='type')
    write_json(root / 'config.json', {'sections': sections, 'reference_style': plan['analysis']})
    write_json(root / 'studio.json', {'name': 'x', 'mode': 'sections', 'sections': sections})
    (root / 'script.txt').write_text('hello world again', encoding='utf-8')
    state = {'analysis_provider': 'claude', 'scene_mode': 'custom', 'resolved_assets': {}}
    write_json(root / 'reference_style.json', state)
    for row in plan['scenes']: row.update(media='', variant='type')
    plan['assets'] = []
    return plan, state


WORDS = [{'word': 'hello', 'start': .1, 'end': .4}, {'word': 'world', 'start': 2.2, 'end': 2.6}]
CONNECTION = {'provider': 'claude', 'providers': {'claude': {'cli_path': 'claude.exe', 'model': 'opus', 'installed': True}}}


class CodeCheckTests(unittest.TestCase):
    def test_allowed_scene_passes(self):
        self.assertEqual(cs.check_code(GOOD), '')

    def test_unsafe_or_incomplete_code_is_rejected(self):
        for code, word in [("import fs from 'fs';\nexport default 1", 'fs'), ('export default () => fetch("x")', 'fetch'),
                           ('export default () => Math.random()', 'Math.random'), ('export default () => window.x', 'window'),
                           ('export default () => <img src="https://evil.example/a.png"/>', 'External URL'),
                           ("export default () => import('react')", 'import'), ('const Scene = 1;', 'default export'),
                           ('export default () => new Date()', 'Date'), ('', 'empty')]:
            with self.subTest(word=word): self.assertIn(word, cs.check_code(code))
        self.assertEqual(cs.check_code('// fetch is mentioned in a comment\n' + GOOD), '')

    def test_registry_and_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); project = root / 'project'; (project / 'custom-scenes').mkdir(parents=True)
            (project / 'custom-scenes/scene-01.tsx').write_text(GOOD, encoding='utf-8')
            (project / 'custom-scenes/scene-02.tsx').write_text("import x from 'fs';\nexport default x", encoding='utf-8')
            write_json(project / 'config.json', {'sections': [{'custom_scene': 'scene-01'}, {'custom_scene': 'scene-02'}, {'custom_scene': '../x'}]})
            target = root / 'snapshot/custom'; (target / 'scenes').mkdir(parents=True); (target / 'scenes/stale.tsx').write_text('x')
            self.assertEqual(cs.install(project, target), ['scene-01'])  # unsafe files never reach the renderer
            registry = (target / 'registry.ts').read_text(encoding='utf-8')
            self.assertIn("import scene_01 from './scenes/scene-01';", registry); self.assertNotIn('scene_02', registry)
            self.assertFalse((target / 'scenes/stale.tsx').exists())


class GenerateTests(unittest.TestCase):
    def run_generate(self, root, plan, state, draws, checks, review=None):
        replies = iter(draws + [review or ({}, {})])
        def ask(connection, project, prompt, images, timeout=1500): return next(replies)
        results = iter(checks)
        def check(project, blocks, analysis):
            outcome = next(results)  # one outcome function per test-render call
            return {name: outcome(name) for name in blocks}
        with patch.object(ref, 'settings', return_value=CONNECTION), patch.object(cs, 'ask', side_effect=ask) as asked, \
             patch.object(cs, 'check_render', side_effect=check), patch.object(cs, 'contact_sheets', return_value=[root / 'sheet.jpg']):
            passed = cs.generate(root, Path(root) / 'data', state, plan, WORDS, 5)
        return passed, asked

    def test_scenes_are_drawn_checked_and_applied(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); plan, state = project_with_plan(root)
            draws = [({1: {'index': 1, 'code': GOOD, 'notes': 'opening'}, 2: {'index': 2, 'code': GOOD, 'notes': ''}}, {'model': 'claude-opus-5-5'})]
            ok = lambda name: {'ok': True}
            passed, asked = self.run_generate(root, plan, state, draws, [ok, ok])
            self.assertEqual(passed, ['scene-01', 'scene-02'])
            prompt = asked.call_args_list[0].args[2]
            self.assertIn('captionTop', prompt); self.assertIn('"spoken": "hello"', prompt)
            sections = read_cache(root / 'config.json')['sections']
            self.assertEqual([row['custom_scene'] for row in sections], ['scene-01', 'scene-02'])
            saved = read_cache(root / 'reference_style.json')['custom_scenes']
            self.assertEqual(saved['model'], 'claude-opus-5-5'); self.assertEqual(saved['failed'], [])
            self.assertTrue((root / 'custom-scenes/scene-01.tsx').is_file())

    def test_failures_are_repaired_then_fall_back_to_templates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); plan, state = project_with_plan(root)
            broken = "import fs from 'fs';\nexport default fs"
            draws = [({1: {'index': 1, 'code': GOOD, 'notes': ''}, 2: {'index': 2, 'code': GOOD.replace('frame}', 'frame.x.y}'), 'notes': ''}}, {}),
                     ({2: {'index': 2, 'code': broken, 'notes': ''}}, {}),           # repair 1: unsafe, rejected before rendering
                     ({2: {'index': 2, 'code': GOOD.replace('frame}', 'oops}'), 'notes': ''}}, {})]  # repair 2: still crashes
            crash = lambda name: {'ok': name != 'scene-02', 'error': 'TypeError: x' if name == 'scene-02' else ''}
            passed, asked = self.run_generate(root, plan, state, draws, [crash, crash])
            self.assertEqual(passed, ['scene-01'])
            repair_prompt = asked.call_args_list[1].args[2]
            self.assertIn('TypeError: x', repair_prompt)
            sections = read_cache(root / 'config.json')['sections']
            self.assertEqual(sections[0]['custom_scene'], 'scene-01'); self.assertNotIn('custom_scene', sections[1])
            self.assertFalse((root / 'custom-scenes/scene-02.tsx').exists())
            self.assertIn('scene-02', read_cache(root / 'reference_style.json')['custom_scenes']['errors'])

    def test_review_changes_are_kept_only_when_they_render(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); plan, state = project_with_plan(root)
            draws = [({1: {'index': 1, 'code': GOOD, 'notes': ''}, 2: {'index': 2, 'code': GOOD, 'notes': ''}}, {})]
            improved = GOOD.replace('{frame}', '{frame + 1}')
            review = ({1: {'index': 1, 'code': improved, 'notes': ''}, 2: {'index': 2, 'code': improved, 'notes': ''}}, {})
            ok = lambda name: {'ok': True}
            review_check = lambda name: {'ok': name == 'scene-01', 'error': '' if name == 'scene-01' else 'crash'}
            self.run_generate(root, plan, state, draws, [ok, review_check], review)
            self.assertIn('frame + 1', (root / 'custom-scenes/scene-01.tsx').read_text(encoding='utf-8'))
            self.assertNotIn('frame + 1', (root / 'custom-scenes/scene-02.tsx').read_text(encoding='utf-8'))

    def test_unchanged_inputs_reuse_the_drawn_scenes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); plan, state = project_with_plan(root)
            draws = [({1: {'index': 1, 'code': GOOD, 'notes': ''}, 2: {'index': 2, 'code': GOOD, 'notes': ''}}, {})]
            ok = lambda name: {'ok': True}
            self.run_generate(root, plan, state, draws, [ok, ok])
            state = read_cache(root / 'reference_style.json')
            with patch.object(ref, 'settings', return_value=CONNECTION), patch.object(cs, 'ask') as asked, patch.object(cs, 'check_render') as check:
                self.assertEqual(cs.generate(root, root / 'data', state, plan, WORDS, 5), ['scene-01', 'scene-02'])
            asked.assert_not_called(); check.assert_not_called()

    def test_only_the_claude_provider_draws(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); plan, state = project_with_plan(root); state['analysis_provider'] = 'codex'
            with patch.object(ref, 'settings', return_value={'provider': 'codex', 'providers': {'codex': {}}}):
                with self.assertRaisesRegex(ValueError, 'Claude provider'): cs.generate(root, root / 'data', state, plan, WORDS, 5)


class TimelineTests(unittest.TestCase):
    def test_custom_scene_blocks_get_words_and_images(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'media').mkdir(); (root / 'media/logo.png').write_bytes(b'png')
            analysis = valid_plan()['analysis']
            config = {'reference_style': analysis, 'sections': [
                {'layout': 'reference_style', 'variant': 'type', 'title': 'A', 'custom_scene': 'scene-01', 'custom_images': {'logo': 'media/logo.png'}},
                {'layout': 'reference_style', 'variant': 'type', 'title': 'B', 'start_seconds': 2}]}
            timeline = video_sections.make_timeline(config, root, root, WORDS, 5, lambda path: 5)
            first, second = timeline['blocks']
            self.assertEqual(first['sceneWords'], [{'text': 'hello', 'frame': 3}])
            self.assertEqual(first['customImages'], {'logo': 'sections/media/logo.png'})
            self.assertNotIn('sceneWords', second)
            for bad in ({'custom_scene': '../evil'}, {'custom_scene': 'scene-01', 'custom_images': {'x': 'media/missing.png'}},
                        {'custom_scene': 'scene-01', 'layout': 'title', 'title': 'x'}):
                broken = json.loads(json.dumps(config)); broken['sections'][0].update(bad)
                with self.subTest(bad=bad), self.assertRaises(ValueError): video_sections.validate_sections(broken, root)


class StudioSceneModeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); root = Path(self.folder.name)
        self.app = studio.Studio(root / 'data', root / 'projects')
        self.style = ready_style(self.app.data, 'Dark')

    def tearDown(self): self.folder.cleanup()

    def test_custom_mode_needs_claude_and_can_be_switched_off(self):
        with self.assertRaisesRegex(ValueError, 'Claude provider'):
            self.app.create_reference('X', 'hello', provider='codex', styles=[self.style], scene_mode='custom')
        project = self.app.create_reference('X', 'hello', provider='claude', styles=[self.style], scene_mode='custom')
        self.assertEqual(project['reference_style']['scene_mode'], 'custom')
        path = Path(project['path']); config = read_cache(path / 'config.json')
        config['sections'][0].update(custom_scene='scene-01', custom_images={}); write_json(path / 'config.json', config)
        result = self.app.set_scene_mode(project['id'], 'templates')
        self.assertEqual(result['reference_style']['scene_mode'], 'templates')
        self.assertNotIn('custom_scene', read_cache(path / 'config.json')['sections'][0])

    def test_draw_scenes_runs_without_a_new_analysis(self):
        project = self.app.create_reference('X', 'hello', provider='claude', styles=[self.style], scene_mode='custom')
        with self.assertRaisesRegex(ValueError, 'Analyze & plan scenes first'): self.app.draw_scenes(project['id'])
        path = Path(project['path']); (path / 'voiceover.mp3').write_bytes(b'audio')
        state = read_cache(path / 'reference_style.json')
        state.update(status='ready', analysis=valid_plan()['analysis'], script_hash=ref.fingerprint('hello'),
                     voice_signature=ref.file_signature(path / 'voiceover.mp3'))
        write_json(path / 'reference_style.json', state)
        with patch.object(ref, 'settings', return_value=CONNECTION), patch.object(studio.threading, 'Thread'):
            result = self.app.draw_scenes(project['id'])
        self.assertEqual(result['job']['action'], 'reference_scenes')
        with patch.object(studio.subprocess, 'Popen') as popen:
            popen.return_value.stdout = iter([]); popen.return_value.wait.return_value = 0
            job = self.app.jobs[result['job']['id']]
            self.app.run(job, path, read_cache(path / 'config.json'), 0)
        command = popen.call_args_list[0].args[0]
        self.assertIn('--scenes-only', command); self.assertEqual(len(popen.call_args_list), 1)  # no build step


if __name__ == '__main__':
    unittest.main()
