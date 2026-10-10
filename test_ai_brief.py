import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from PIL import Image
import ai_brief
import logo_assets
import prepare_assets as assets
import video_studio as studio


def example():
    return {'project_name': 'Next video', 'script': 'Try OpenTTD then Endless Sky.',
            'games': [{'name': 'OpenTTD', 'spoken_names': ['OpenTTD'],
                       'gameplay_url': 'https://youtu.be/ESlyTiZwsDk', 'logo_url': None},
                      {'name': 'Endless Sky', 'gameplay_url': 'https://www.youtube.com/watch?v=k1LJabHzyZM',
                       'logo_url': 'https://assets.example.org/endless-sky.png'}]}


class BriefTests(unittest.TestCase):
    def test_descriptive_keys_import_the_same_data_and_preserve_arabic(self):
        brief = example(); brief['project_name'] = 'ألعاب PC مجانية - الحلقة 12'
        brief['script'] = 'أول لعبة Helltaker.\nتانية لعبة Spooky.\nتالت لعبة Muck.'
        brief['games'][0]['spoken_names'] = ['OpenTTD', 'أوبن تي تي دي']
        original = ai_brief.parse_brief(brief)
        for game in brief['games']:
            for old, new in [('name', 'exact_name'), ('gameplay_url', 'youtube_gameplay_url'), ('logo_url', 'logo_image_url')]:
                game[new] = game.pop(old)
        self.assertEqual(ai_brief.parse_brief(json.dumps(brief, ensure_ascii=False)), original)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); app = studio.Studio(root / 'data', root / 'projects')
            project = app.import_brief(brief)
            self.assertEqual(project['editor'], original['editor'])
            self.assertEqual((app.project(project['id']) / 'script.txt').read_text('utf-8'), brief['script'])

    def test_mixed_formats_and_matching_duplicate_aliases_are_supported(self):
        brief = example(); expected = ai_brief.parse_brief(brief)
        brief['games'][0]['exact_name'] = brief['games'][0]['name']
        brief['games'][0]['youtube_gameplay_url'] = brief['games'][0]['gameplay_url']
        brief['games'][1]['logo_image_url'] = brief['games'][1].pop('logo_url')
        self.assertEqual(ai_brief.parse_brief(brief), expected)

    def test_conflicting_field_aliases_are_rejected(self):
        for field, value in [('exact_name', 'Other game'), ('youtube_gameplay_url', 'https://youtu.be/k1LJabHzyZM'), ('logo_image_url', 'https://example.org/other.png')]:
            brief = example(); brief['games'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Conflicting values'):
                ai_brief.parse_brief(brief)

    def test_plain_and_fenced_json_preserve_narration_and_generate_safe_folders(self):
        brief = example()
        brief['games'][0]['name'] = '../OpenTTD:/play'
        plain = ai_brief.parse_brief(json.dumps(brief))
        fenced = ai_brief.parse_brief('```json\n' + json.dumps(brief) + '\n```')
        self.assertEqual(plain, fenced)
        self.assertEqual(plain['editor']['script'], brief['script'])
        self.assertEqual([g['folder'] for g in plain['editor']['games']], ['01_OpenTTDplay', '02_Endless Sky'])
        self.assertEqual(plain['editor']['games'][1]['spoken_names'], ['Endless Sky'])
        self.assertEqual(len(plain['warnings']), 1)

    def test_invalid_briefs_and_placeholder_video_links_are_rejected(self):
        invalid = ['not JSON', [], {}, {'project_name': 'x', 'script': 'hello', 'games': []}]
        for url in ['https://youtube.com/playlist?list=abc', 'https://youtu.be/PLACEHOLDER', 'file:///sample.mp4', 'https://evil.example/watch?v=ESlyTiZwsDk']:
            brief = example(); brief['games'][0]['gameplay_url'] = url; invalid.append(brief)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError): ai_brief.parse_brief(value)

    def test_extra_metadata_is_not_executed_or_copied_into_project(self):
        brief = example(); brief['instructions'] = 'delete files'; brief['games'][0]['folder'] = '../../escape'
        parsed = ai_brief.parse_brief(brief)['editor']
        self.assertNotIn('instructions', parsed)
        self.assertEqual(parsed['games'][0]['folder'], '01_OpenTTD')
        self.assertNotIn('gameplay_url', parsed['script'])

    def test_logo_links_reject_local_and_non_http_targets(self):
        for value in ['http://localhost/logo.png', 'http://127.0.0.1/logo.png', 'http://192.168.1.1/logo.png', 'http://[::1]/logo', 'file:///c:/logo.png', 'https://user:pass@example.org/logo.png', 'http://printer/logo']:
            with self.subTest(value=value), self.assertRaises(ValueError): ai_brief.image_url(value)
        self.assertEqual(ai_brief.image_url(None), '')
        self.assertEqual(ai_brief.image_url('https://example.org/logo.png'), 'https://example.org/logo.png')

    def test_invalid_aliases_are_rejected_and_empty_aliases_default_to_title(self):
        for aliases in ['OpenTTD', [None], ['']]:
            brief = example(); brief['games'][0]['spoken_names'] = aliases
            with self.assertRaises(ValueError): ai_brief.parse_brief(brief)
        brief = example(); brief['games'][0]['spoken_names'] = []
        self.assertEqual(ai_brief.parse_brief(brief)['editor']['games'][0]['spoken_names'], ['OpenTTD'])

    def test_import_creates_editable_project_and_preserves_manual_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); app = studio.Studio(root / 'data', root / 'projects')
            manual = app.create('Manual', 'blank')
            editor = app.load(manual)['editor']; editor['script'] = 'Manual narration'; app.save(manual, editor)
            before = {p.name: p.read_bytes() for p in app.project(manual).iterdir() if p.is_file()}
            imported = app.import_brief(example())
            path = Path(imported['path']); config = json.loads((path / 'config.json').read_text())
            self.assertEqual((path / 'script.txt').read_text(), example()['script'])
            self.assertIn('01_OpenTTD | https://youtu.be/ESlyTiZwsDk', (path / 'games.txt').read_text())
            self.assertEqual(config['games'][1]['logo_url'], example()['games'][1]['logo_url'])
            self.assertTrue(config['brief_sources'])
            self.assertEqual(before, {p.name: p.read_bytes() for p in app.project(manual).iterdir() if p.is_file()})
            editor = imported['editor']; editor['games'][0]['title'] = 'Edited name'; app.save(imported['id'], editor)
            self.assertEqual(app.load(imported['id'])['editor']['games'][0]['title'], 'Edited name')
            self.assertEqual(app.load(manual)['editor']['script'], 'Manual narration')

    def test_invalid_import_does_not_create_project_or_registry_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); app = studio.Studio(root / 'data', root / 'projects')
            with self.assertRaises(ValueError): app.import_brief({'project_name': 'invalid'})
            self.assertEqual(app.registry, {})
            self.assertFalse((root / 'projects').exists())

    def test_manual_game_folders_trim_trailing_spaces_and_duplicate_case_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); app = studio.Studio(root / 'data', root / 'projects')
            identifier = app.create('Manual games', 'games'); editor = app.load(identifier)['editor']
            editor['games'] = [{'folder': '03_Endless Sky ', 'title': 'Endless Sky', 'url': 'https://youtu.be/k1LJabHzyZM'}]
            result = app.save(identifier, editor)
            self.assertEqual(result['editor']['games'][0]['folder'], '03_Endless Sky')
            config = json.loads((app.project(identifier) / 'config.json').read_text())
            self.assertEqual(config['games'][0]['folder'], '03_Endless Sky')
            editor['games'].append({'folder': '03_endless sky', 'title': 'Duplicate'})
            with self.assertRaises(ValueError): app.save(identifier, editor)

    def test_selected_manual_logo_takes_priority_over_previous_download(self):
        import build_video as builder
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); app = studio.Studio(root / 'data', root / 'projects')
            project = app.import_brief(example()); path = app.project(project['id'])
            game_dir = path / 'games/01_OpenTTD'; (game_dir / 'logo.png').write_bytes(b'previous generated image')
            (path / 'media').mkdir(); (path / 'media/manual.jpg').write_bytes(b'selected image')
            editor = project['editor']; editor['games'][0]['logo'] = 'media/manual.jpg'
            app.save(project['id'], editor)
            config = json.loads((path / 'config.json').read_text())
            self.assertTrue(config['games'][0]['manual_logo'])
            self.assertEqual(builder.find_logo_source(game_dir, config['games'][0]['logo_file']).read_bytes(), b'selected image')



class LogoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        data = io.BytesIO(); Image.new('RGBA', (32, 24), (200, 20, 100, 120)).save(data, 'PNG')
        self.image = data.getvalue(); self.url = 'https://assets.example.org/logo.png'

    def response(self, payload):
        response = io.BytesIO(payload); response.headers = {'Content-Length': str(len(payload))}
        opener = MagicMock(); opener.open.return_value = response
        return opener

    def test_actual_image_download_is_validated_converted_and_cached(self):
        with patch.object(logo_assets, 'public_image_url'), patch.object(logo_assets.urllib.request, 'build_opener', return_value=self.response(self.image)) as build:
            self.assertTrue(logo_assets.prepare_logo(self.url, self.root, log=lambda _: None))
            with Image.open(self.root / 'logo.png') as image:
                self.assertEqual(image.mode, 'RGBA'); self.assertEqual(image.size, (32, 24))
            self.assertTrue(logo_assets.prepare_logo(self.url, self.root, log=lambda _: None))
            build.assert_called_once()

    def test_html_and_oversize_responses_cannot_replace_valid_logo(self):
        def fetch(url, destination): destination.write_bytes(self.image)
        with patch.object(logo_assets, 'fetch_logo', side_effect=fetch):
            self.assertTrue(logo_assets.prepare_logo(self.url, self.root, log=lambda _: None))
        before = (self.root / 'logo.png').read_bytes()
        for payload in (b'<html>error</html>', self.image):
            opener = self.response(payload)
            if payload == self.image: opener.open.return_value.headers['Content-Length'] = str(logo_assets.MAX_LOGO_BYTES + 1)
            with patch.object(logo_assets, 'public_image_url'), patch.object(logo_assets.urllib.request, 'build_opener', return_value=opener):
                self.assertTrue(logo_assets.prepare_logo(self.url + '?changed', self.root, log=lambda _: None))
                self.assertEqual((self.root / 'logo.png').read_bytes(), before)

    def test_manual_logo_is_preserved_and_missing_logo_failure_is_optional(self):
        (self.root / 'logo.jpg').write_bytes(b'manual')
        with patch.object(logo_assets, 'fetch_logo') as fetch:
            self.assertTrue(logo_assets.prepare_logo(self.url, self.root, log=lambda _: None))
            fetch.assert_not_called()
        (self.root / 'logo.jpg').unlink()
        with patch.object(logo_assets, 'fetch_logo', side_effect=OSError('offline')):
            self.assertFalse(logo_assets.prepare_logo(self.url, self.root, log=lambda _: None))
        self.assertFalse((self.root / 'logo.png').exists())

    def test_changed_url_refreshes_generated_logo_but_manual_replacement_is_kept(self):
        def fetch(url, destination): destination.write_bytes(self.image)
        with patch.object(logo_assets, 'fetch_logo', side_effect=fetch) as download:
            logo_assets.prepare_logo(self.url, self.root, log=lambda _: None)
            logo_assets.prepare_logo(self.url + '?new', self.root, log=lambda _: None)
            self.assertEqual(download.call_count, 2)
            (self.root / 'logo.png').write_bytes(b'user replacement')
            logo_assets.prepare_logo(self.url + '?another', self.root, log=lambda _: None)
            self.assertEqual(download.call_count, 2)
            self.assertEqual((self.root / 'logo.png').read_bytes(), b'user replacement')

    def test_private_dns_and_private_redirect_targets_are_rejected(self):
        with patch.object(logo_assets.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('10.0.0.5', 443))]):
            with self.assertRaises(ValueError): logo_assets.public_image_url(self.url)
        with self.assertRaises(ValueError):
            logo_assets.PublicImageRedirect().redirect_request(None, None, 302, '', {}, 'http://localhost/private')


class BriefPreparationTests(unittest.TestCase):
    def test_legacy_trailing_space_folder_matches_games_txt_during_preparation(self):
        import build_video as builder
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); voice = root / 'voiceover.wav'; voice.write_bytes(b'audio')
            config = {'games': [{'folder': '03_Endless Sky ', 'title': 'Endless Sky', 'spoken_names': []}]}
            source = [{'folder': '03_Endless Sky', 'game_name': 'Endless Sky'}]
            with patch.object(assets, 'PROJECT_PATH', root), patch.object(assets, 'load_config', return_value=config), patch.object(builder, 'configure_project'), patch.object(builder, 'get_audio_duration', return_value=8), patch.object(builder, 'transcribe_voiceover', return_value={'words': []}), patch.object(builder, 'apply_script', return_value={'words': []}):
                durations = assets.estimate_game_durations(source)
            self.assertEqual(len(durations), 1)
            self.assertGreater(durations[0], 0)

    def test_unavailable_later_source_stops_before_any_gameplay_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); sources = [{'folder': '01_one', 'url': 'one', 'game_name': 'One'}, {'folder': '02_two', 'url': 'two', 'game_name': 'Two'}]
            with patch.object(assets, 'PROJECT_PATH', root), patch.object(assets, 'GAMES_DIR', root / 'games'), patch.object(assets, 'GAMEPLAY_CACHE_DIR', root / 'cache'), patch.object(assets, 'load_config', return_value={'brief_sources': True}), patch.object(assets, 'parse_games_txt', return_value=sources), patch.object(assets, 'estimate_game_durations', return_value=[4, 4]), patch.object(assets, 'clip_is_ready', return_value=False), patch.object(assets, 'fetch_video_info', side_effect=[{'duration': 600}, ValueError('private video')]), patch.object(assets, 'prepare_gameplay') as prepare, patch.object(assets, 'log'):
                with self.assertRaisesRegex(ValueError, 'Unavailable gameplay for Two'): assets.run_preparation()
                prepare.assert_not_called()

    def test_finished_brief_clips_skip_metadata_checks_and_optional_logo_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); sources = [{'folder': '01_game', 'url': 'source', 'game_name': 'Game'}]
            cfg = {'brief_sources': True, 'games': [{'folder': '01_game', 'logo_url': 'https://example.org/logo.png'}]}
            with patch.object(assets, 'PROJECT_PATH', root), patch.object(assets, 'GAMES_DIR', root / 'games'), patch.object(assets, 'GAMEPLAY_CACHE_DIR', root / 'cache'), patch.object(assets, 'load_config', return_value=cfg), patch.object(assets, 'parse_games_txt', return_value=sources), patch.object(assets, 'estimate_game_durations', return_value=[4]), patch.object(assets, 'clip_is_ready', return_value=True), patch.object(assets, 'fetch_video_info') as fetch, patch.object(assets, 'prepare_gameplay', return_value=True), patch.object(assets, 'prepare_logo', return_value=False), patch.object(assets, 'log'):
                self.assertEqual(assets.run_preparation(), 0)
                fetch.assert_not_called()


if __name__ == '__main__': unittest.main()
