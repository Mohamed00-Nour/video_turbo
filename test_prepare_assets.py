import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import prepare_assets as assets


class GameplayPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.game = self.root / 'game'
        self.game.mkdir()
        self.url = 'https://www.youtube.com/watch?v=sample'
        self.addCleanup(patch.stopall)
        patch.object(assets, 'GAMEPLAY_CACHE_DIR', self.cache).start()
        patch.object(assets, 'log').start()
        patch.object(assets, 'get_video_duration', side_effect=self.fake_duration).start()
        self.fetch = patch.object(assets, 'fetch_video_info', return_value={'duration': 600.0}).start()
        self.download = patch.object(assets, 'download_youtube', side_effect=self.fake_download).start()
        self.cut = patch.object(assets, 'cut_clip', side_effect=self.fake_cut).start()

    @staticmethod
    def fake_duration(path):
        try:
            return float(path.read_text())
        except (OSError, ValueError):
            return 0.0

    @staticmethod
    def fake_download(info, start, duration, dest):
        dest.write_text(str(duration))
        return True

    @staticmethod
    def fake_cut(src, start, duration, dest):
        dest.write_text(str(duration))
        return True

    def test_installed_node_is_enabled_for_youtube_challenges(self):
        with patch.object(assets.shutil,'which',return_value='C:/node/node.exe'):
            self.assertEqual(assets.youtube_runtime_options()['js_runtimes']['node']['path'],'C:/node/node.exe')
        with patch.object(assets.shutil,'which',return_value=None):
            self.assertEqual(assets.youtube_runtime_options(),{})

    def test_preflight_metadata_reuses_resolved_streams_without_extraction(self):
        self.assertTrue(assets.prepare_gameplay(self.url, 4, self.game, info={'duration': 600}))
        self.fetch.assert_not_called()
        self.assertEqual(self.download.call_count, 2)
        self.assertEqual(float((self.game / 'top.mp4').read_text()), 4.0)

    def test_finished_clips_skip_all_network_without_raw_video(self):
        (self.game / 'top.mp4').write_text('10.0')
        (self.game / 'bottom.mp4').write_text('10.0')
        self.assertTrue(assets.prepare_gameplay(self.url, 4, self.game))
        self.fetch.assert_not_called()
        self.download.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_only_missing_clip_is_downloaded_and_partial_raw_is_ignored(self):
        (self.game / 'top.mp4').write_text('10.0')
        (self.game / 'raw_gameplay.mp4.part').write_text('600.0')
        self.assertTrue(assets.prepare_gameplay(self.url, 4, self.game))
        self.assertEqual((self.game / 'top.mp4').read_text(), '10.0')
        self.download.assert_called_once()
        self.assertEqual(self.download.call_args.args[1:3], (360.0, 4.0))
        self.cut.assert_not_called()

    def test_second_project_reuses_clips_and_metadata_without_network(self):
        self.assertTrue(assets.prepare_gameplay(self.url, 4, self.game))
        self.fetch.reset_mock()
        self.download.reset_mock()
        other = self.root / 'other_project' / 'different_game_folder'
        alias = 'https://youtu.be/sample?t=60'
        self.assertTrue(assets.prepare_gameplay(alias, 4, other))
        self.fetch.assert_not_called()
        self.download.assert_not_called()
        self.assertEqual((other / 'top.mp4').read_bytes(), (self.game / 'top.mp4').read_bytes())

    def test_cache_separates_video_identity_duration_and_position(self):
        assets.prepare_gameplay(self.url, 4, self.game)
        assets.prepare_gameplay(self.url, 6, self.root / 'longer')
        assets.prepare_gameplay('https://youtu.be/another', 4, self.root / 'another')
        with patch.object(assets, 'TOP_POSITION_RATIO', 0.3):
            assets.prepare_gameplay(self.url, 4, self.root / 'new_position')
        self.assertEqual(self.download.call_count, 7)  # Unchanged bottom section is reused.
        self.assertEqual(self.fetch.call_count, 4)  # Fresh stream URLs are needed for each cache miss.

    def test_broken_cached_clip_is_replaced(self):
        self.cache.mkdir()
        key = assets.source_cache_key(self.url)
        (self.cache / f'{key}.json').write_text(json.dumps({'duration': 600}))
        broken = assets.clip_cache_path(key, 150, 4)
        broken.write_text('broken')
        self.assertTrue(assets.prepare_gameplay(self.url, 4, self.game))
        self.assertEqual(float(broken.read_text()), 4.0)
        self.assertEqual(self.download.call_count, 2)

    def test_local_full_video_can_finish_missing_clip_offline(self):
        (self.game / 'raw_gameplay.mp4').write_text('600.0')
        (self.game / 'top.mp4').write_text('4.0')
        self.assertTrue(assets.prepare_gameplay(self.url, 4, self.game))
        self.fetch.assert_not_called()
        self.download.assert_not_called()
        self.cut.assert_called_once()
        self.assertEqual(self.cut.call_args.args[1:3], (360.0, 4.0))

    def test_failed_section_keeps_completed_top_for_retry(self):
        # Simulate successful publication for the first section, then failure.
        def download(info, start, duration, dest):
            if start == 150:
                return self.fake_download(info, start, duration, dest)
            return False
        self.download.side_effect = download
        self.assertFalse(assets.prepare_gameplay(self.url, 4, self.game))
        self.assertTrue((self.game / 'top.mp4').exists())
        self.assertFalse((self.game / 'bottom.mp4').exists())
        self.download.side_effect = self.fake_download
        self.download.reset_mock()
        self.assertTrue(assets.prepare_gameplay(self.url, 4, self.game))
        self.assertEqual(self.download.call_count, 1)
        self.assertEqual(self.download.call_args.args[1], 360)

    def test_starter_clips_are_trimmed_for_recording_without_network_and_stay_cached(self):
        self.assertTrue(assets.prepare_gameplay(self.url, 20, self.game))
        key=assets.source_cache_key(self.url)
        starter_paths=[assets.clip_cache_path(key,start,20) for start in (150,360)]
        self.fetch.reset_mock();self.download.reset_mock()
        self.assertTrue(assets.prepare_gameplay(self.url, 7.5, self.game))
        self.fetch.assert_not_called();self.download.assert_not_called()
        self.assertEqual(self.cut.call_count,2)
        for call in self.cut.call_args_list:
            self.assertEqual(call.args[1:3],(0,7.5))
        for path in starter_paths:self.assertEqual(float(path.read_text()),20)
        for name in ('top.mp4','bottom.mp4'):self.assertEqual(float((self.game/name).read_text()),7.5)
        self.cut.reset_mock()
        self.assertTrue(assets.prepare_gameplay(self.url, 7.5, self.game))
        self.cut.assert_not_called();self.fetch.assert_not_called();self.download.assert_not_called()
        # An explanation can later grow without downloading again if the starter covers it.
        self.assertTrue(assets.prepare_gameplay(self.url, 12, self.game))
        self.assertEqual(self.cut.call_count,2);self.fetch.assert_not_called();self.download.assert_not_called()

    def test_short_source_starters_trim_at_correct_relative_positions(self):
        self.fetch.return_value={'duration':40}
        self.assertTrue(assets.prepare_gameplay(self.url, 20, self.game))
        self.fetch.reset_mock();self.download.reset_mock()
        self.assertTrue(assets.prepare_gameplay(self.url, 7, self.game))
        self.assertEqual([call.args[1] for call in self.cut.call_args_list],[0,4])
        self.fetch.assert_not_called();self.download.assert_not_called()

    def test_other_project_can_trim_starter_cache_without_network(self):
        self.assertTrue(assets.prepare_gameplay(self.url, 20, self.game))
        self.fetch.reset_mock();self.download.reset_mock()
        other=self.root/'another_project'
        self.assertTrue(assets.prepare_gameplay('https://youtu.be/sample', 6.8, other))
        self.assertEqual(self.cut.call_count,2)
        self.fetch.assert_not_called();self.download.assert_not_called()

    def test_longer_recording_downloads_when_starter_is_not_long_enough(self):
        self.assertTrue(assets.prepare_gameplay(self.url, 20, self.game))
        self.download.reset_mock()
        self.assertTrue(assets.prepare_gameplay(self.url, 25, self.game))
        self.assertEqual(self.download.call_count,2);self.cut.assert_not_called()

    def test_changed_source_does_not_trim_old_starter_cache(self):
        self.assertTrue(assets.prepare_gameplay(self.url, 20, self.game))
        self.download.reset_mock()
        self.assertTrue(assets.prepare_gameplay('https://youtu.be/changed', 7.1, self.game))
        self.assertEqual(self.download.call_count,2);self.cut.assert_not_called()

    def test_broken_starter_cache_downloads_fresh_footage(self):
        self.assertTrue(assets.prepare_gameplay(self.url, 20, self.game))
        key=assets.source_cache_key(self.url)
        for start in (150,360):assets.clip_cache_path(key,start,20).write_text('broken')
        self.download.reset_mock()
        self.assertTrue(assets.prepare_gameplay(self.url, 7.5, self.game))
        self.assertEqual(self.download.call_count,2);self.cut.assert_not_called()

    def test_changed_duration_refreshes_generated_clips(self):
        self.assertTrue(assets.prepare_gameplay(self.url, 4, self.game))
        self.download.reset_mock()
        self.assertTrue(assets.prepare_gameplay(self.url, 6, self.game))
        self.assertEqual(self.download.call_count, 2)
        self.assertEqual(float((self.game / 'top.mp4').read_text()), 6.)

    def test_url_change_does_not_reuse_old_raw_footage(self):
        (self.game / 'raw_gameplay.mp4').write_text('600.0')
        self.assertTrue(assets.prepare_gameplay(self.url, 4, self.game))
        self.cut.reset_mock()
        self.assertTrue(assets.prepare_gameplay('https://youtu.be/changed', 4, self.game))
        self.cut.assert_not_called()
        self.assertEqual(self.download.call_count, 2)

    def test_url_change_rejects_raw_footage_added_after_remote_generation(self):
        self.assertTrue(assets.prepare_gameplay(self.url, 4, self.game))
        (self.game / 'raw_gameplay.mp4').write_text('600.0')
        self.download.reset_mock()
        self.assertTrue(assets.prepare_gameplay('https://youtu.be/changed', 4, self.game))
        self.cut.assert_not_called()
        self.assertEqual(self.download.call_count, 2)

    def test_manually_replaced_clip_is_preserved_when_url_changes(self):
        assets.prepare_gameplay(self.url, 4, self.game)
        (self.game / 'top.mp4').write_text('manual 10')
        # This fake media probe treats the manual clip as a valid 10s video.
        original = self.fake_duration
        with patch.object(assets, 'get_video_duration', side_effect=lambda p: 10 if p.name == 'top.mp4' else original(p)):
            self.download.reset_mock()
            self.assertTrue(assets.prepare_gameplay('https://youtu.be/new', 4, self.game))
        self.assertEqual((self.game / 'top.mp4').read_text(), 'manual 10')
        self.assertEqual(self.download.call_count, 1)

    def test_short_sources_never_request_beyond_end(self):
        for length in (1, 8, 20, 40, 100, 1200):
            top, bottom, duration = assets.clip_ranges(length, 20)
            for start in (top, bottom):
                self.assertGreaterEqual(start, 0)
                self.assertLessEqual(start + duration, length)
        self.assertEqual(assets.clip_ranges(1200, 20), (300, 720, 20))


class SectionDownloadRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dest = Path(self.temp.name) / 'clip.mp4'
        self.info = {'duration': 75, 'webpage_url': 'https://www.youtube.com/watch?v=sample', 'url': 'old-stream'}
        self.attempts = []
        self.failures = []
        self.addCleanup(patch.stopall)
        self.fetch = patch.object(assets, 'fetch_video_info', return_value={**self.info, 'url': 'fresh-stream'}).start()
        patch.object(assets, 'get_video_duration', side_effect=GameplayPreparationTests.fake_duration).start()
        patch.object(assets, 'log').start()
        patch('yt_dlp.YoutubeDL', side_effect=self.downloader).start()

    def downloader(self, options):
        manager = MagicMock()
        def process(info, download):
            self.attempts.append(info['url'])
            pending = Path(options['outtmpl'])
            pending.write_text('2' if self.failures and self.failures[0] == 'partial' else '10')
            if self.failures:
                failure = self.failures.pop(0)
                if failure != 'partial': raise failure
        manager.__enter__.return_value.process_ie_result.side_effect = process
        return manager

    def test_failed_stream_refreshes_link_and_publishes_only_complete_retry(self):
        from yt_dlp.utils import DownloadError
        self.failures = [DownloadError('ffmpeg exited with code 3436169992')]
        self.assertTrue(assets.download_youtube(self.info, 18.75, 10, self.dest))
        self.assertEqual(self.attempts, ['old-stream', 'fresh-stream'])
        self.fetch.assert_called_once_with(self.info['webpage_url'])
        self.assertEqual(self.dest.read_text(), '10')
        self.assertEqual(list(self.dest.parent.glob('.download-*')), [])

    def test_incomplete_section_is_retried_without_caching_partial_media(self):
        self.failures = ['partial']
        self.assertTrue(assets.download_youtube(self.info, 18.75, 10, self.dest))
        self.assertEqual(self.attempts, ['old-stream', 'fresh-stream'])
        self.assertEqual(self.dest.read_text(), '10')

    def test_persistent_failure_is_bounded_and_preserves_existing_clip(self):
        from yt_dlp.utils import DownloadError
        self.dest.write_text('existing clip')
        self.failures = [DownloadError('HTTP Error 403')] * 3
        self.assertFalse(assets.download_youtube(self.info, 18.75, 10, self.dest))
        self.assertEqual(len(self.attempts), 3)
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(self.dest.read_text(), 'existing clip')
        self.assertEqual(list(self.dest.parent.glob('.download-*')), [])

    def test_success_reuses_preflight_stream_without_repeating_extraction(self):
        self.assertTrue(assets.download_youtube(self.info, 18.75, 10, self.dest))
        self.fetch.assert_not_called()
        self.assertEqual(self.attempts, ['old-stream'])


if __name__ == '__main__':
    unittest.main()