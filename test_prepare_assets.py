import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main()