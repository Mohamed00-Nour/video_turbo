import copy
import io
from contextlib import redirect_stdout, redirect_stderr
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import video_sections as sections
import video_studio as studio
from pipeline_common import write_json


class SectionTests(unittest.TestCase):
    def test_explicit_and_spoken_starts_share_remaining_time(self):
        rows = [{}, {'start_phrase': 'second topic'}, {}, {'start_seconds': 9}]
        words = [{'word': 'second', 'start': 3}, {'word': 'topic', 'start': 3.4}]
        self.assertEqual(sections.section_starts(rows, words, 12), [0, 90, 180, 270, 360])

    def test_missing_or_out_of_order_cues_are_rejected(self):
        for rows in [[{}, {'start_phrase': 'absent'}], [{}, {'start_seconds': 5}, {'start_seconds': 4}], [{'start_seconds': 1}], [{}, {'start_seconds': 7}]]:
            with self.assertRaises(ValueError): sections.section_starts(rows, [], 6)

    def test_media_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'image.png').write_bytes(b'image')
            self.assertEqual(sections.media_path(root, 'image.png'), (root / 'image.png').resolve())
            for relative in ('../image.png', str(root / 'image.png')):
                with self.assertRaises(ValueError): sections.media_path(root, relative)

    def test_mixed_layout_timeline_keeps_duration_and_video_loop_lengths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('clip.mp4', 'image.png', 'gta_background.mp4'): (root / name).write_bytes(b'asset')
            config = {'sections': [{'layout': 'background'}, {'layout': 'single', 'media': 'clip.mp4', 'start_seconds': 1},
                                   {'layout': 'split', 'media': 'image.png', 'secondary_media': 'clip.mp4', 'start_seconds': 2}], 'end_padding_seconds': .2}
            words = [{'word': 'hello', 'start': 0, 'end': .3}]
            result = sections.make_timeline(config, root, root, words, 3, lambda p: 1.2)
            self.assertEqual(result['totalFrames'], 96)
            self.assertEqual([b['durationFrames'] for b in result['blocks']], [30, 30, 36])
            self.assertEqual(result['blocks'][1]['media']['durationFrames'], 36)
            self.assertEqual(result['blocks'][2]['media']['kind'], 'image')

    def test_invalid_highlight_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'Highlight'):
                sections.validate_sections({'sections': [{'layout': 'background', 'highlight': {'x': 90, 'y': 0, 'width': 30, 'height': 20}}]}, Path(folder))


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.studio = studio.Studio(self.root / 'data', self.root / 'projects')

    def test_save_and_reopen_preserve_project_and_shared_config(self):
        identifier = self.studio.create('Arabic video', 'blank')
        project = self.studio.load(identifier); path = self.studio.project(identifier)
        write_json(path / 'config.json', {'whisper_model': 'medium', 'vocabulary': ['keep']})
        editor = project['editor']; editor['script'] = 'hello world'; editor['sections'][0]['label'] = 'Useful tip'
        self.studio.save(identifier, editor)
        restarted = studio.Studio(self.root / 'data', self.root / 'projects')
        self.assertEqual(restarted.load(identifier)['editor']['script'], 'hello world')
        config = json.loads((path / 'config.json').read_text())
        self.assertEqual(config['whisper_model'], 'medium')
        self.assertEqual(config['sections'][0]['label'], 'Useful tip')

    def test_existing_project_discovery_and_load_do_not_modify_sources(self):
        path = self.root / 'old'; (path / 'games/01_game').mkdir(parents=True)
        (path / 'script.txt').write_text('original')
        write_json(path / 'config.json', {'games': [{'folder': '01_game', 'title': 'Example'}]})
        before = sorted(p.relative_to(path).as_posix() for p in path.rglob('*'))
        identifier = self.studio.register(path)
        self.assertEqual(self.studio.load(identifier)['editor']['games'][0]['title'], 'Example')
        self.assertEqual(before, sorted(p.relative_to(path).as_posix() for p in path.rglob('*')))

    def test_running_job_blocks_mutation_and_second_job(self):
        identifier = self.studio.create('video')
        self.studio.job = {'status': 'running'}
        with self.assertRaises(ValueError): self.studio.save(identifier, self.studio.load(identifier)['editor'])
        with self.assertRaises(ValueError): self.studio.start(identifier, 'build')
        with self.assertRaises(ValueError): self.studio.create('second')

    def test_game_save_supports_uploads_and_youtube_with_arabic_aliases(self):
        identifier = self.studio.create('game', 'games'); path = self.studio.project(identifier)
        (path / 'media').mkdir(); (path / 'media/source.mp4').write_bytes(b'clip')
        editor = self.studio.load(identifier)['editor']
        editor['games'] = [{'folder': '01_Game', 'title': 'Game', 'spoken_names': ['لعبة'], 'url': 'https://youtu.be/abc', 'top': 'media/source.mp4'}]
        self.studio.save(identifier, editor)
        self.assertEqual((path / 'games/01_Game/top.mp4').read_bytes(), b'clip')
        self.assertIn('https://youtu.be/abc', (path / 'games.txt').read_text())


class ProjectLibraryTests(unittest.TestCase):
    setUp = StudioTests.setUp
    def test_rename_preserves_script_media_config_and_folder(self):
        identifier=self.studio.create('Old name');path=self.studio.project(identifier)
        editor=self.studio.load(identifier)['editor'];editor['script']='Saved spoken script.'
        self.studio.save(identifier,editor)
        (path/'voiceover.wav').write_bytes(b'audio')
        write_json(path/'ai_workflow.json',{'status':'assets_ready','auto_build':True})
        config=(path/'config.json').read_bytes();workflow=(path/'ai_workflow.json').read_bytes()
        project=self.studio.rename_project(identifier,'  New name  ')
        self.assertEqual(project['editor']['name'],'New name')
        self.assertEqual(project['editor']['script'],'Saved spoken script.')
        self.assertEqual(self.studio.project(identifier),path)
        self.assertEqual((path/'voiceover.wav').read_bytes(),b'audio')
        self.assertEqual((path/'config.json').read_bytes(),config)
        self.assertEqual((path/'ai_workflow.json').read_bytes(),workflow)
        restarted=studio.Studio(self.root/'data',self.root/'projects')
        self.assertEqual(restarted.registry[identifier]['name'],'New name')

    def test_empty_game_draft_can_be_renamed_and_invalid_names_do_not_modify_it(self):
        identifier=self.studio.create('Draft','games')
        for name in ('',' '*3,'x'*81,None):
            with self.assertRaises(ValueError):self.studio.rename_project(identifier,name)
        project=self.studio.rename_project(identifier,'Renamed draft')
        self.assertEqual(project['editor']['name'],'Renamed draft')
        self.assertEqual(project['editor']['games'],[])

    def test_delete_requires_confirmation_and_moves_managed_project_to_trash(self):
        identifier=self.studio.create('Delete me');path=self.studio.project(identifier)
        (path/'script.txt').write_text('Saved script');(path/'voiceover.wav').write_bytes(b'audio')
        other=self.studio.create('Keep me');other_path=self.studio.project(other)
        with self.assertRaisesRegex(ValueError,'Confirm'):self.studio.delete_project(identifier)
        self.assertTrue(path.exists())
        self.studio.job={'project':identifier,'status':'complete'}
        result=self.studio.delete_project(identifier,True)
        self.assertTrue(result['files_moved']);self.assertFalse(path.exists())
        trash=self.studio.data/'deleted_projects'/identifier
        self.assertEqual((trash/'script.txt').read_text(),'Saved script')
        self.assertEqual((trash/'voiceover.wav').read_bytes(),b'audio')
        self.assertTrue(other_path.exists());self.assertIsNone(self.studio.job)
        with self.assertRaisesRegex(ValueError,'not found'):self.studio.load(identifier)
        restarted=studio.Studio(self.root/'data',self.root/'projects')
        self.assertNotIn(identifier,restarted.registry);self.assertIsNone(restarted.job)

    def test_external_delete_stays_removed_after_discovery_restart_and_can_be_reopened(self):
        engine=self.root/'engine';engine.mkdir()
        external=self.root/'Imported';external.mkdir();(external/'script.txt').write_text('Keep this script')
        write_json(external/'studio.json',{'name':'Saved title','mode':'games','games':[]})
        identifier=self.studio.register(external)
        before={p.name:p.read_bytes() for p in external.iterdir() if p.is_file()}
        result=self.studio.delete_project(identifier,True)
        self.assertFalse(result['files_moved'])
        with patch.object(studio,'ENGINE',engine):
            self.assertNotIn(identifier,[p['id'] for p in self.studio.list_projects()])
            restarted=studio.Studio(self.root/'data',self.root/'projects')
            self.assertFalse(restarted.list_projects())
        self.assertEqual({p.name:p.read_bytes() for p in external.iterdir() if p.is_file()},before)
        reopened=restarted.register(external)
        self.assertEqual(restarted.registry[reopened]['name'],'Saved title')
        self.assertTrue(restarted.list_projects())

    def test_active_build_and_publishing_block_rename_and_delete(self):
        identifier=self.studio.create('Keep me');path=self.studio.project(identifier)
        for owner in ('studio','publisher'):
            with self.subTest(owner=owner):
                job={'status':'running','project':identifier}
                if owner=='studio':self.studio.job=job
                else:self.studio.publisher.job=job
                with self.assertRaises(ValueError):self.studio.rename_project(identifier,'New name')
                with self.assertRaises(ValueError):self.studio.delete_project(identifier,True)
                self.assertTrue(path.exists());self.assertIn(identifier,self.studio.registry)
                self.studio.job=None;self.studio.publisher.job=None

    def test_project_root_and_nested_imports_are_never_moved_as_managed_projects(self):
        for path in (self.studio.projects,self.studio.projects/'container'/'nested'):
            with self.subTest(path=path):
                path.mkdir(parents=True,exist_ok=True);(path/'script.txt').write_text('Keep')
                identifier=self.studio.register(path)
                self.assertFalse(self.studio.delete_project(identifier,True)['files_moved'])
                self.assertTrue(path.exists())

    def test_failed_trash_move_keeps_project_registered(self):
        identifier=self.studio.create('Keep me')
        with patch.object(Path,'rename',side_effect=OSError('Folder is in use')):
            with self.assertRaises(OSError):self.studio.delete_project(identifier,True)
        self.assertIn(identifier,self.studio.registry)
        self.assertTrue(self.studio.project(identifier).exists());self.assertFalse(self.studio.removed_projects)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.app = studio.Studio(root / 'data', root / 'projects')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), studio.Handler); self.server.studio = self.app
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.identifier = self.app.create('HTTP test')

    def request(self, route, payload, token=True, extra=None):
        headers = {'X-Studio-Token': self.app.token} if token else {}
        headers.update(extra or {})
        return urllib.request.urlopen(urllib.request.Request(self.url + route, data=payload, headers=headers, method='POST'))

    def test_second_launch_opens_existing_studio_and_preserves_running_job(self):
        job = {'status': 'running', 'id': 'existing-job'}
        self.app.job = job
        with patch.object(studio.sys, 'argv', ['video_studio.py', '--port', str(self.server.server_port)]), patch.object(studio, 'StudioServer', side_effect=OSError('port occupied')), patch.object(studio, 'Studio') as create, patch.object(studio.webbrowser, 'open') as browser, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(studio.main(), 0)
        browser.assert_called_once_with(self.url)
        create.assert_not_called()
        self.assertIs(self.app.job, job)
        self.assertIn('already running', output.getvalue())

    def test_second_launch_respects_no_browser(self):
        with patch.object(studio.sys, 'argv', ['video_studio.py', '--port', str(self.server.server_port), '--no-browser']), patch.object(studio, 'StudioServer', side_effect=OSError('port occupied')), patch.object(studio.webbrowser, 'open') as browser, redirect_stdout(io.StringIO()):
            self.assertEqual(studio.main(), 0)
        browser.assert_not_called()

    def test_older_idle_server_starts_updated_studio_on_another_port(self):
        replacement = unittest.mock.MagicMock(server_port=8766)
        replacement.serve_forever.side_effect = KeyboardInterrupt
        with patch.object(studio.sys, 'argv', ['video_studio.py']), patch.object(studio, 'StudioServer', side_effect=[OSError('port occupied'), replacement]) as servers, patch.object(studio, 'running_studio', side_effect=[False, True]), patch.object(studio, 'running_studio_idle', return_value=True), patch.object(studio, 'Studio', return_value=self.app), patch.object(studio.webbrowser, 'open') as browser, redirect_stdout(io.StringIO()) as output:
            self.assertIsNone(studio.main())
        self.assertEqual(servers.call_args_list[1].args[0], ('127.0.0.1',8766))
        browser.assert_called_once_with('http://127.0.0.1:8766')
        self.assertIn('updated Studio', output.getvalue())

    def test_older_busy_server_does_not_start_another_studio_or_change_jobs(self):
        job={'id':'busy','status':'running'}; self.app.job=job
        with patch.object(studio.sys, 'argv', ['video_studio.py']), patch.object(studio, 'StudioServer', side_effect=OSError('port occupied')) as servers, patch.object(studio, 'running_studio', side_effect=[False, True]), patch.object(studio, 'running_studio_idle', return_value=False), patch.object(studio, 'Studio') as create, patch.object(studio.webbrowser, 'open') as browser, redirect_stderr(io.StringIO()):
            self.assertEqual(studio.main(), 1)
        create.assert_not_called(); browser.assert_not_called(); self.assertEqual(servers.call_count,1)
        self.assertIs(self.app.job,job)

    def test_next_launch_reuses_the_updated_server_on_the_fallback_port(self):
        with patch.object(studio.sys, 'argv', ['video_studio.py']), patch.object(studio, 'StudioServer', side_effect=OSError('port occupied')), patch.object(studio, 'running_studio', side_effect=[False,True,True]), patch.object(studio, 'running_studio_idle', return_value=True), patch.object(studio, 'Studio') as create, patch.object(studio.webbrowser, 'open') as browser, redirect_stdout(io.StringIO()):
            self.assertEqual(studio.main(),0)
        create.assert_not_called(); browser.assert_called_once_with('http://127.0.0.1:8766')

    def test_occupied_port_for_other_application_remains_an_error(self):
        with patch.object(studio.sys, 'argv', ['video_studio.py']), patch.object(studio, 'StudioServer', side_effect=OSError('port occupied')), patch.object(studio, 'running_studio', return_value=False), patch.object(studio.webbrowser, 'open') as browser, redirect_stderr(io.StringIO()) as output:
            self.assertEqual(studio.main(), 1)
        browser.assert_not_called()
        self.assertIn('choose another --port', output.getvalue())

    def test_studio_server_does_not_allow_a_second_listener_on_its_port(self):
        server = studio.StudioServer(('127.0.0.1', 0), studio.Handler)
        try:
            with self.assertRaises(OSError):
                duplicate = studio.StudioServer(('127.0.0.1', server.server_port), studio.Handler)
                duplicate.server_close()
        finally:
            server.server_close()

    def test_descriptive_json_fields_round_trip_through_http_import(self):
        brief = {'project_name': 'ألعاب PC مجانية - الحلقة 12', 'script': 'أول لعبة Helltaker.',
                 'games': [{'exact_name': 'Helltaker', 'spoken_names': ['Helltaker', 'هيل تيكر'],
                            'youtube_gameplay_url': 'https://www.youtube.com/watch?v=rAd_NqSSp0Q',
                            'logo_image_url': 'https://cdn.cloudflare.steamstatic.com/steam/apps/1289310/header.jpg'}]}
        payload = json.dumps({'brief': json.dumps(brief, ensure_ascii=False)}, ensure_ascii=False).encode('utf-8')
        with self.request('/api/brief/import', payload) as response:
            project = json.load(response)
        self.assertEqual(project['editor']['script'], brief['script'])
        game = project['editor']['games'][0]
        self.assertEqual(game['title'], 'Helltaker')
        self.assertEqual(game['spoken_names'], ['Helltaker', 'هيل تيكر'])
        self.assertEqual(game['url'], brief['games'][0]['youtube_gameplay_url'])
        self.assertEqual(game['logo_url'], brief['games'][0]['logo_image_url'])

    def test_brief_review_and_import_create_project_without_overwriting_manual(self):
        brief = {'project_name': 'HTTP brief', 'script': 'Play OpenTTD.',
                 'games': [{'name': 'OpenTTD', 'gameplay_url': 'https://youtu.be/ESlyTiZwsDk', 'logo_url': None}]}
        payload = json.dumps({'brief': json.dumps(brief)}).encode('utf-8')
        with self.request('/api/brief/validate', payload) as response:
            review = json.load(response)
        self.assertEqual(review['editor']['games'][0]['title'], 'OpenTTD')
        self.assertEqual(len(self.app.registry), 1)
        with self.request('/api/brief/import', payload) as response:
            imported = json.load(response)
        self.assertEqual(imported['editor']['script'], brief['script'])
        self.assertEqual(len(self.app.registry), 2)
        self.assertEqual(self.app.load(self.identifier)['editor']['mode'], 'sections')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/brief/import', payload, token=False)
        self.assertEqual(error.exception.code, 403)

    def test_project_rename_and_delete_http_validate_token_confirmation_and_missing_id(self):
        for route,payload in (('/api/project/rename',{'id':self.identifier,'name':'New name'}),('/api/project/delete',{'id':self.identifier,'confirmed':True})):
            with self.assertRaises(urllib.error.HTTPError) as error:self.request(route,json.dumps(payload).encode(),token=False)
            self.assertEqual(error.exception.code,403)
        with self.request('/api/project/rename',json.dumps({'id':self.identifier,'name':'Renamed HTTP'}).encode()) as response:
            self.assertEqual(json.load(response)['editor']['name'],'Renamed HTTP')
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/project/delete',json.dumps({'id':self.identifier}).encode())
        self.assertTrue(self.app.project(self.identifier).exists())
        with self.request('/api/project/delete',json.dumps({'id':self.identifier,'confirmed':True}).encode()) as response:
            self.assertEqual(json.load(response)['deleted'],self.identifier)
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/project/delete',json.dumps({'id':self.identifier,'confirmed':True}).encode())

    def test_upload_and_video_range_round_trip(self):
        with self.request(f'/api/upload?id={self.identifier}&name=screen.mp4&role=media', b'0123456789') as response:
            relative = json.load(response)['path']
        route = '/media?id=' + self.identifier + '&file=' + relative
        with urllib.request.urlopen(urllib.request.Request(self.url + route, headers={'Range': 'bytes=2-5'})) as response:
            self.assertEqual(response.status, 206); self.assertEqual(response.read(), b'2345')
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(self.url + route, headers={'Range': 'bytes=99-'}))
        self.assertEqual(error.exception.code, 416)

    def test_mutations_require_same_origin_token_and_paths_are_contained(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/create', b'{"name":"bad"}', token=False)
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/create', b'{"name":"bad"}', extra={'Origin': 'https://other.example'})
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.url + '/media?id=' + self.identifier + '&file=../../video_studio.py')

    def test_voice_upload_replaces_old_format_and_does_not_choose_stale_audio(self):
        with self.request(f'/api/upload?id={self.identifier}&name=voice.mp3&role=voice', b'old'): pass
        with self.request(f'/api/upload?id={self.identifier}&name=voice.wav&role=voice', b'new'): pass
        self.assertEqual(self.app.load(self.identifier)['voiceover'], 'voiceover.wav')
        self.assertFalse((self.app.project(self.identifier) / 'voiceover.mp3').exists())


if __name__ == '__main__': unittest.main()
