import tempfile
import unittest
from pathlib import Path
from ai_series import SeriesLibrary


class SeriesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.library = SeriesLibrary(self.temp.name)

    def save(self, name, platform='pc', instructions='Hook, three games, then a closing.'):
        return self.library.save('', name, platform, instructions, 'Egyptian Arabic')['series'][-1]['id']

    def test_pc_and_mobile_keep_independent_instructions_reference_and_history_after_restart(self):
        pc = self.save('PC games')
        mobile = self.save('Mobile games', 'mobile', 'Explain touch controls and offline play.')
        self.library.record_approval(pc, 'pc-project', 'PC episode', 'Free PC games', 'Approved PC script.', ['OpenTTD'])
        self.library.record_approval(mobile, 'mobile-project', 'Mobile episode', 'Offline games', 'Approved mobile script.', ['Mindustry'])
        reopened = SeriesLibrary(Path(self.temp.name))
        pc_context, mobile_context = reopened.context(pc), reopened.context(mobile)
        self.assertEqual(pc_context['reference_script'], 'Approved PC script.')
        self.assertEqual(pc_context['covered_games'], ['OpenTTD'])
        self.assertEqual(mobile_context['platform'], 'mobile')
        self.assertEqual(mobile_context['instructions'], 'Explain touch controls and offline play.')
        self.assertEqual(mobile_context['reference_script'], 'Approved mobile script.')
        self.assertEqual(mobile_context['covered_games'], ['Mindustry'])

    def test_editing_series_and_reapproving_a_project_preserve_history_without_duplicates(self):
        identifier = self.save('PC games')
        self.library.record_approval(identifier, 'project', 'Episode', 'Games', 'First script.', ['OpenTTD'])
        self.library.save(identifier, 'PC games revisited', 'pc', 'Use a new opening.', 'English', 'Manual reference.')
        self.assertEqual(self.library.context(identifier)['covered_games'], ['OpenTTD'])
        self.library.record_approval(identifier, 'project', 'Edited episode', 'Games', 'Edited script.', ['SuperTuxKart'])
        context = self.library.context(identifier)
        self.assertEqual(context['approved_episode_count'], 1)
        self.assertEqual(context['reference_script'], 'Edited script.')
        self.assertEqual(context['instructions'], 'Use a new opening.')
        self.assertEqual(context['covered_games'], ['SuperTuxKart'])

    def test_recent_context_is_bounded_but_remembers_older_game_names(self):
        identifier = self.save('PC games')
        for number in range(12):
            self.library.record_approval(identifier, str(number), f'Episode {number}', 'Games', 'Approved script.', [f'Game {number}'])
        context = self.library.context(identifier)
        self.assertEqual(len(context['recent_episodes']), 10)
        self.assertEqual(context['recent_episodes'][0]['name'], 'Episode 2')
        self.assertIn('Game 0', context['covered_games'])
        snapshot = self.library.snapshot(); snapshot['series'][0]['episodes'].clear()
        self.assertEqual(self.library.context(identifier)['approved_episode_count'], 12)

    def test_invalid_series_is_rejected_before_any_write(self):
        values = {'identifier':'', 'name':'PC games', 'platform':'pc', 'instructions':'Three games.', 'language':'English'}
        for invalid in ({'name':''}, {'name':'x'*81}, {'platform':'console'}, {'instructions':''}, {'language':''}, {'reference_script':False}, {'identifier':[]}, {'identifier':'unknown'}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.library.save(**{**values, **invalid})
        self.assertEqual(self.library.snapshot(), {'series':[]})
        self.assertFalse(self.library.path.exists())


if __name__ == '__main__': unittest.main()
