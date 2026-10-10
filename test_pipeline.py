import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import build_video as build
import prepare_assets as prepare
from pipeline_common import plan_game_timing, voiceover_path, write_json


class TimingTests(unittest.TestCase):
    def specs(self):
        return [{'folder': f'0{i}_game', 'spoken_names': [name]} for i, name in enumerate(['first', 'second', 'third'])]

    def test_real_mentions_keep_absolute_starts(self):
        words = [{'word': name, 'start': t} for name, t in zip(['first', 'second', 'third'], [5, 18, 30])]
        plan = plan_game_timing(self.specs(), words, 45)
        self.assertEqual(plan['gameRanges'], [(150, 540), (540, 900), (900, 1200)])
        self.assertEqual(plan['hookFrames'], 150)
        self.assertEqual(plan['totalFrames'], 1350)

    def test_short_recording_fits_all_blocks(self):
        plan = plan_game_timing(self.specs(), [], 8)
        self.assertEqual(plan['totalFrames'], 240)
        previous = plan['hookFrames']
        for start, end in plan['gameRanges']:
            self.assertEqual(start, previous)
            self.assertGreater(end, start)
            previous = end
        self.assertEqual(previous, plan['ctaStartFrame'])
        self.assertLess(previous, 240)

    def test_missing_middle_game_is_interpolated_between_anchors(self):
        words = [{'word': 'first', 'start': 5}, {'word': 'third', 'start': 30}]
        plan = plan_game_timing(self.specs(), words, 45)
        self.assertEqual(plan['gameRanges'][0][0], 150)
        self.assertEqual(plan['gameRanges'][1][0], 525)
        self.assertEqual(plan['gameRanges'][2][0], 900)

    def test_arabic_and_multiword_aliases_use_word_boundaries(self):
        games = [{'folder': 'realm', 'spoken_names': ['Realm of the Mad God']},
                 {'folder': 'arabic', 'spoken_names': ['إمكانيات']}]
        words = [{'word': w, 'start': t} for w, t in [('of', 1), ('Realm', 5), ('of', 5.2), ('the', 5.3), ('Mad', 5.5), ('God', 5.6), ('امكانيات', 18)]]
        plan = plan_game_timing(games, words, 25)
        self.assertEqual([a for a, b in plan['gameRanges']], [150, 540])

    def test_script_overflow_is_rejected(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'Too many script words'):
            build.align_script_to_words(['word'] * 30, [], .5)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.addCleanup(patch.stopall)
        for module, names in [(build, ['PROJECT_PATH', 'OUTPUT_DIR', 'CODE_DIR', 'PUBLIC_DIR', 'FONTS_DIR', 'GAMES_DIR', 'ENGINE_DIR']),
                              (prepare, ['PROJECT_PATH', 'OUTPUT_DIR', 'GAMES_DIR', 'GAMES_TXT'])]:
            for name in names:
                patch.object(module, name, getattr(module, name)).start()
        engine = self.root / 'engine'
        engine.mkdir()
        build.ENGINE_DIR = engine
        for path in ['code/src', 'output', 'games/01_game', 'fonts']:
            (self.root / path).mkdir(parents=True)
        (self.root / 'voiceover.wav').write_bytes(b'voiceone')
        (self.root / 'gta_background.mp4').write_bytes(b'background')
        (self.root / 'fonts/Lalezar-Regular.ttf').write_bytes(b'font')
        (self.root / 'games/01_game/top.mp4').write_bytes(b'top')
        (self.root / 'games/01_game/bottom.mp4').write_bytes(b'bottom')
        (self.root / 'code/src/Caption.tsx').write_text('original caption')
        write_json(self.root / 'config.json', {'games': [{'folder': '01_game', 'title': 'Game', 'spoken_names': ['game']}]})
        build.configure_project(self.root)
        prepare.configure_project(self.root)
        patch.object(build, 'log').start()
        patch.object(prepare, 'log').start()

    def test_voice_cache_detects_content_change_even_with_same_size_and_mtime(self):
        word = types.SimpleNamespace(word='game', start=1., end=1.3, probability=.9)
        segment = types.SimpleNamespace(text='game', words=[word])
        model = Mock()
        model.transcribe.return_value = (iter([segment]), None)
        constructor = Mock(return_value=model)
        with patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=constructor)}):
            voice = voiceover_path(self.root)
            first = build.transcribe_voiceover(voice)
            self.assertEqual(build.transcribe_voiceover(voice)['cacheKey'], first['cacheKey'])
            self.assertEqual(constructor.call_count, 1)
            before = voice.stat()
            voice.write_bytes(b'voicetwo')
            os.utime(voice, ns=(before.st_atime_ns, before.st_mtime_ns))
            model.transcribe.return_value = (iter([segment]), None)
            second = build.transcribe_voiceover(voice)
            self.assertNotEqual(second['cacheKey'], first['cacheKey'])
            self.assertEqual(constructor.call_count, 2)

    def test_sync_skips_unchanged_files_and_does_not_copy_raw_footage(self):
        raw = self.root / 'games/01_game/raw_gameplay.mp4'
        raw.write_bytes(b'unused full gameplay')
        logo = self.root / 'games/01_game/logo.png'
        logo.write_bytes(b'\x89PNG\r\n\x1a\nrest')
        build.sync_public_assets()
        self.assertFalse((build.PUBLIC_DIR / 'games/01_game/raw_gameplay.mp4').exists())
        with patch.object(build.shutil, 'copy2', wraps=shutil.copy2) as copy, patch.object(build, 'prepare_logo', wraps=build.prepare_logo) as convert:
            build.sync_public_assets()
            copy.assert_not_called()
            convert.assert_not_called()
        logo.unlink()
        build.sync_public_assets()
        self.assertFalse((build.PUBLIC_DIR / 'games/01_game/_logo.png').exists())

    def test_timeline_and_preparation_share_the_same_clip_length(self):
        words = [{'word': 'game', 'start': 5., 'end': 5.3}]
        with patch.object(build, 'get_audio_duration', return_value=20.), patch.object(build, 'transcribe_voiceover', return_value={'words': words}), patch.object(build, 'apply_script', side_effect=lambda data, duration: data):
            build.sync_public_assets()
            timeline = build.build_timeline({'words': words}, 20.)
            durations = prepare.estimate_game_durations([{'folder': '01_game', 'game_name': 'Game'}])
        game = next(block for block in timeline['blocks'] if block['type'] == 'game')
        self.assertEqual(game['startFrame'], 150)
        self.assertEqual(durations, [game['durationFrames'] / timeline['fps']])
        self.assertEqual(timeline['totalFrames'], 600)

    def test_render_reuses_only_unchanged_inputs(self):
        timeline = {'totalDuration': 2., 'words': []}
        def render(path):
            path.write_bytes(b'rendered video')
        with patch.object(build, 'get_audio_duration', return_value=2.), patch.object(build, 'sync_public_assets', return_value={}), patch.object(build, 'transcribe_voiceover', return_value={'words': []}), patch.object(build, 'apply_script', side_effect=lambda data, duration: data), patch.object(build, 'build_timeline', return_value=timeline), patch.object(build, 'process_audio_and_mux'), patch.object(build, 'render_remotion_video', side_effect=render) as renderer:
            args = ['--project', str(self.root), '--no-preview']
            self.assertEqual(build.main(args), 0)
            self.assertEqual(build.main(args), 0)
            self.assertEqual(renderer.call_count, 1)
            (self.root / 'code/src/Caption.tsx').write_text('changed caption')
            self.assertEqual(build.main(args), 0)
            self.assertEqual(renderer.call_count, 2)
            timeline['words'] = [{'word': 'new script'}]
            self.assertEqual(build.main(args), 0)
            self.assertEqual(renderer.call_count, 3)

    def test_asset_failure_returns_nonzero(self):
        (self.root / 'games.txt').write_text('01_game | https://youtu.be/test')
        with patch.object(prepare, 'estimate_game_durations', return_value=[4.]), patch.object(prepare, 'prepare_gameplay', return_value=False):
            self.assertEqual(prepare.main(['--project', str(self.root)]), 1)


if __name__ == '__main__':
    unittest.main()