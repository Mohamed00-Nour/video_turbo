import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import build_video as build
import video_studio as studio
from pipeline_common import read_cache, write_json


class ParallelProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = studio.Studio(self.root / 'data', self.root / 'projects')
        self.releases = []
        self.addCleanup(self.close_workers)

    def close_workers(self):
        for event in self.releases: event.set()
        self.app.shutdown_jobs()

    def wait_for(self, predicate):
        limit = time.monotonic() + 5
        while not predicate() and time.monotonic() < limit: time.sleep(.01)
        self.assertTrue(predicate())

    def task(self, name):
        identifier = self.app.create(name)
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def work(job):
            started.set(); release.wait(5)
            with self.app.lock:
                job.update(status='cancelled' if job['cancel'] else 'complete', progress=100)
        with self.app.lock:
            job = self.app._ai_job(identifier, 'build', 'Rendering ' + name)
            self.app.enqueue(job, work)
        return identifier, job, started, release

    def test_two_videos_run_together_and_third_waits_then_starts(self):
        first = self.task('First'); second = self.task('Second'); third = self.task('Third')
        self.assertTrue(first[2].wait(2)); self.assertTrue(second[2].wait(2))
        self.assertEqual(third[1]['status'], 'queued'); self.assertFalse(third[2].is_set())
        with self.assertRaises(ValueError): self.app.idle(first[0])
        independent = self.app.create('Editable while rendering')
        self.app.save(independent, self.app.load(independent)['editor'])
        first[3].set(); self.assertTrue(third[2].wait(2))
        self.assertEqual(second[1]['status'], 'running')
        second[3].set(); third[3].set()
        self.wait_for(lambda: all(job['status'] == 'complete' for job in self.app.all_jobs()))

    def test_queued_cancellation_never_launches_that_video(self):
        first = self.task('First'); second = self.task('Second'); third = self.task('Queued')
        self.app.cancel(third[1]['id'])
        self.assertEqual(third[1]['status'], 'cancelled')
        first[3].set(); second[3].set()
        self.wait_for(lambda: first[1]['status'] == second[1]['status'] == 'complete')
        self.assertFalse(third[2].is_set())

    def test_cancelling_one_running_video_does_not_cancel_its_neighbor(self):
        first = self.task('First'); second = self.task('Second')
        self.assertTrue(first[2].wait(2)); self.assertTrue(second[2].wait(2))
        process_a = MagicMock(pid=111); process_a.poll.return_value = None
        process_b = MagicMock(pid=222); process_b.poll.return_value = None
        self.app.processes = {first[1]['id']: process_a, second[1]['id']: process_b}
        with patch.object(studio.subprocess, 'run') as kill:
            self.app.cancel(first[1]['id'])
        self.assertTrue(first[1]['cancel']); self.assertFalse(second[1]['cancel'])
        self.assertEqual(second[1]['status'], 'running')
        if studio.os.name == 'nt': self.assertEqual(kill.call_args.args[0][2], '111')
        self.assertIs(self.app.processes[second[1]['id']], process_b)
        first[3].set(); second[3].set()
        self.wait_for(lambda: first[1]['status'] == 'cancelled' and second[1]['status'] == 'complete')

    def test_concurrency_limit_can_release_more_queued_videos(self):
        self.app.configure_production(1)
        first = self.task('First'); second = self.task('Second')
        self.assertTrue(first[2].wait(2)); self.assertEqual(second[1]['status'], 'queued')
        self.app.configure_production(2); self.assertTrue(second[2].wait(2))
        for value in (0, 5, True, '2'):
            with self.assertRaises(ValueError): self.app.configure_production(value)
        first[3].set(); second[3].set()
        self.wait_for(lambda: all(job['status'] == 'complete' for job in self.app.all_jobs()))

    def test_background_job_can_save_its_own_project_after_another_job_starts(self):
        with patch.object(studio.threading, 'Thread'):
            first = self.task('First'); second = self.task('Second')
        self.assertEqual(self.app.job['id'], second[1]['id'])
        editor = self.app.load(first[0])['editor']; editor['script'] = 'Saved by the first worker.'
        self.app.save(first[0], editor, job_id=first[1]['id'])
        self.assertEqual(self.app.load(first[0])['editor']['script'], editor['script'])
        with self.assertRaises(ValueError): self.app.save(first[0], editor)

    def test_restart_recovers_all_running_and_queued_jobs(self):
        with patch.object(studio.threading, 'Thread'):
            tasks = [self.task(str(index)) for index in range(3)]
        for identifier, _, _, _ in tasks:
            write_json(self.app.project(identifier) / 'ai_workflow.json', {'source': 'import', 'status': 'rendering'})
        restarted = studio.Studio(self.app.data, self.app.projects)
        self.assertEqual(len(restarted.all_jobs()), 3)
        self.assertTrue(all(job['status'] == 'interrupted' for job in restarted.all_jobs()))
        self.assertTrue(all(restarted.workflow(item[0])['status'] == 'interrupted' for item in tasks))

    def test_independent_subprocesses_keep_their_own_handles_and_outputs(self):
        identifiers = [self.app.create(name) for name in ('One', 'Two')]
        releases = {identifier: threading.Event() for identifier in identifiers}
        self.releases.extend(releases.values())
        entered = {identifier: threading.Event() for identifier in identifiers}
        processes = {}
        def spawn(command, **kwargs):
            project = Path(command[command.index('--project') + 1])
            identifier = next(key for key in identifiers if self.app.project(key) == project)
            def output():
                entered[identifier].set(); yield 'Rendered 1/2\n'
                releases[identifier].wait(5)
                (project / 'output').mkdir(exist_ok=True)
                (project / 'output/final.mp4').write_text(identifier)
            process = MagicMock(stdout=output()); process.wait.return_value = 0
            processes[identifier] = process
            return process
        with patch.object(studio.subprocess, 'Popen', side_effect=spawn):
            jobs = []
            for identifier in identifiers:
                path = self.app.project(identifier); (path / 'voiceover.wav').write_bytes(b'audio')
                self.app.save(identifier, self.app.load(identifier)['editor'])
                jobs.append(self.app.start(identifier, 'build'))
            self.assertTrue(all(event.wait(2) for event in entered.values()))
            self.assertEqual(len(self.app.processes), 2)
            for identifier, job in zip(identifiers, jobs):
                self.assertIs(self.app.processes[job['id']], processes[identifier])
            for release in releases.values(): release.set()
            self.wait_for(lambda: all(job['status'] == 'complete' for job in self.app.all_jobs()))
        for identifier in identifiers:
            self.assertEqual((self.app.project(identifier) / 'output/final.mp4').read_text(), identifier)


class RendererIsolationTests(unittest.TestCase):
    def test_projects_have_separate_public_assets_and_timeline_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); engine = root / 'engine'; source = engine / 'code/src'
            source.mkdir(parents=True)
            (source / 'index.ts').write_text('import timeline from "./timeline.json";')
            write_json(source / 'timeline.json', {'original': True})
            names = ['PROJECT_PATH', 'OUTPUT_DIR', 'CODE_DIR', 'PUBLIC_DIR', 'FONTS_DIR', 'GAMES_DIR', 'ENGINE_DIR']
            with patch.multiple(build, **{name: getattr(build, name) for name in names}):
                build.ENGINE_DIR = engine
                entries, publics = [], []
                for name in ('one', 'two'):
                    project = root / name; project.mkdir()
                    build.configure_project(project)
                    write_json(build.OUTPUT_DIR / 'timeline.json', {'project': name})
                    entries.append(build.renderer_entry()); publics.append(build.PUBLIC_DIR)
                self.assertNotEqual(entries[0], entries[1]); self.assertNotEqual(publics[0], publics[1])
                self.assertEqual(read_cache(entries[0].with_name('timeline.json')), {'project': 'one'})
                self.assertEqual(read_cache(entries[1].with_name('timeline.json')), {'project': 'two'})
                self.assertEqual(read_cache(source / 'timeline.json'), {'original': True})


if __name__ == '__main__': unittest.main()
