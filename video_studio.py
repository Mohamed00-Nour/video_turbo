"""Local browser UI for Video Turbo. Run: python video_studio.py"""
from __future__ import annotations
import argparse
import copy
import json
import mimetypes
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from pipeline_common import read_cache, write_json, voiceover_path, fingerprint
import video_sections as sections
from ai_brief import parse_brief, image_url
from publishing import Publisher
from analytics import Analytics
from ai_generation import AIGenerator
from ai_series import SeriesLibrary
import reference_styles
import style_library
import recreate
import antigravity_brief
import flow_workflow
import voice_generation
import pc_tips

ENGINE = Path(__file__).resolve().parent
WEB = ENGINE / 'studio'
DATA = ENGINE / 'output'
PROJECTS = ENGINE / 'projects'
UPLOAD_EXTS = sections.VIDEO_EXTS | sections.IMAGE_EXTS | {'.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg'}


class Studio:
    def __init__(self, data=DATA, projects=PROJECTS):
        self.data, self.projects = Path(data), Path(projects)
        self.registry = read_cache(self.data / 'studio_registry.json')
        self.removed_projects = read_cache(self.data / 'studio_removed_projects.json')
        self.presets = read_cache(self.data / 'studio_presets.json')
        self.lock = threading.RLock()
        self.job = None
        self.processes = {}
        self.jobs = {}
        self.pending = []
        self.workers = {}
        self.max_parallel = 2
        self.stopping = False
        self.token = secrets.token_urlsafe(32)
        self.publisher = Publisher(self.data, self.project)
        self.analytics = Analytics(self.data, self.publisher, self.analytics_projects)
        self.ai = AIGenerator(self.data)
        self.voice = voice_generation.ElevenLabs(self.data)
        self.series = SeriesLibrary(self.data)
        saved = read_cache(self.data / 'ai/jobs.json')
        self.max_parallel = saved.get('max_parallel', 2)
        if not isinstance(self.max_parallel, int) or not 1 <= self.max_parallel <= 4: self.max_parallel = 2
        records = saved.get('jobs', []) or [read_cache(self.data / 'ai/job.json')]
        for saved_job in records:
            if not saved_job: continue
            saved_job.setdefault('id', uuid.uuid4().hex)
            self.jobs[saved_job['id']] = saved_job
            self.job = saved_job
            if saved_job.get('status') in ('queued', 'running', 'cancelling'):
                saved_job.update(status='interrupted', stage='Production interrupted', finished=time.time(),
                                 error='Studio restarted. Your files are saved; retry the interrupted step.')
                if saved_job.get('project') in self.registry:
                    project = self.project(saved_job['project'])
                    action = saved_job.get('next_action', saved_job.get('action', ''))
                    filename = 'pc_tips.json' if action.startswith('pc_') else 'reference_style.json' if action.startswith('reference_') else 'ai_workflow.json'
                    path = project / filename
                    if path.is_file():
                        workflow = read_cache(path)
                        workflow.update(status='interrupted', error=saved_job['error'])
                        write_json(path, workflow)
        if self.job: self.persist_jobs()

    def all_jobs(self):
        jobs = dict(self.jobs)
        if self.job: jobs[self.job.get('id', 'legacy')] = self.job
        return list(jobs.values())

    def project_job(self, identifier):
        return next((job for job in reversed(self.all_jobs()) if job.get('project') == identifier
                     and job.get('status') in ('queued', 'running', 'cancelling')), None)

    def persist_jobs(self):
        jobs = self.all_jobs()
        write_json(self.data / 'ai/jobs.json', {'max_parallel': self.max_parallel, 'jobs': jobs})
        write_json(self.data / 'ai/job.json', self.job or {})

    def production_state(self):
        with self.lock:
            return {'jobs': copy.deepcopy(self.all_jobs()), 'max_parallel': self.max_parallel}

    def configure_production(self, value):
        with self.lock:
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4:
                raise ValueError('Choose 1 to 4 simultaneous videos.')
            self.max_parallel = value
            self.persist_jobs(); self._dispatch_jobs()
            return self.production_state()

    def enqueue(self, job, target, *args):
        with self.lock:
            job['status'] = 'queued'
            job['queued_at'] = time.time()
            self.pending.append((job, target, args))
            self._dispatch_jobs(); self.persist_jobs()

    def _dispatch_jobs(self):
        if self.stopping: return
        while self.pending and sum(job.get('status') in ('running', 'cancelling') for job in self.all_jobs()) < self.max_parallel:
            job, target, args = self.pending.pop(0)
            if job.get('cancel'): continue
            job.update(status='running', started=time.time())
            worker = threading.Thread(target=self._execute_job, args=(job, target, args), daemon=True)
            self.workers[job['id']] = worker
            worker.start()

    def _execute_job(self, job, target, args):
        try:
            target(job, *args)
        except Exception:
            with self.lock:
                job.update(status='cancelled' if job.get('cancel') else 'failed', stage='Production failed', error='Production failed. Your project is saved; retry its step.')
                if job.get('style'): style_library.end_analysis(self.data, job['style'], job['status'], job['error'])
                if job.get('project') not in self.registry: return
                path = self.project(job['project'])
                action = job.get('next_action', job['action'])
                filename = 'pc_tips.json' if action.startswith('pc_') else 'reference_style.json' if action.startswith('reference_') else 'ai_workflow.json'
                if (path / filename).is_file():
                    workflow = read_cache(path / filename)
                    workflow.update(status=job['status'], failed_step=action, error=job['error'])
                    write_json(path / filename, workflow)
        finally:
            with self.lock:
                job['finished'] = time.time()
                self.persist_jobs(); self._dispatch_jobs()
                self.workers.pop(job['id'], None)

    def shutdown_jobs(self):
        with self.lock:
            self.stopping = True
            for job in self.all_jobs():
                if job.get('status') in ('queued', 'running'): self.cancel(job['id'])
            workers = list(self.workers.values())
        for worker in workers:
            if worker is not threading.current_thread(): worker.join(timeout=5)


    def analytics_projects(self):
        with self.lock:
            return [{'id': key, 'name': value['name']} for key, value in self.registry.items()]

    def persist(self):
        write_json(self.data / 'studio_registry.json', self.registry)

    def project(self, identifier):
        if identifier not in self.registry:
            raise ValueError('Project not found.')
        return Path(self.registry[identifier]['path']).resolve()

    def idle(self, identifier=None, allow_publishing=False):
        if not allow_publishing and self.publisher.running:
            raise ValueError('Wait for the publishing upload to finish before changing the video project.')
        # Unregistered legacy jobs have no project scope; managed jobs protect only their project.
        legacy = self.job and self.job.get('id') not in self.jobs and self.job.get('status') in ('running', 'cancelling')
        if legacy or identifier and self.project_job(identifier):
            raise ValueError('Wait for the current job for this project or cancel it before making changes.')

    def register(self, path):
        path = Path(path).resolve()
        for key, value in self.registry.items():
            if Path(value['path']) == path:
                return key
        if os.path.normcase(str(path)) in self.removed_projects:
            self.removed_projects.pop(os.path.normcase(str(path)))
            write_json(self.data / 'studio_removed_projects.json', self.removed_projects)
        identifier = uuid.uuid4().hex
        self.registry[identifier] = {'path': str(path), 'name': read_cache(path / 'studio.json').get('name') or path.name}
        self.persist()
        return identifier

    def rename_project(self, identifier, name):
        with self.lock:
            self.idle(identifier)
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
                raise ValueError('Project name must contain 1 to 80 characters.')
            path = self.project(identifier)
            editor = self.load(identifier)['editor']
            editor['name'] = name.strip()
            write_json(path / 'studio.json', editor)
            self.registry[identifier]['name'] = editor['name']
            self.persist()
            return self.load(identifier)

    def managed_project(self, path):
        return path.resolve().parent == self.projects.resolve()

    def delete_project(self, identifier, confirmed=False):
        with self.lock:
            self.idle(identifier)
            if confirmed is not True: raise ValueError('Confirm deletion before deleting the project.')
            path = self.project(identifier)
            trash = None
            if self.managed_project(path) and path.is_dir():
                trash = (self.data / 'deleted_projects' / identifier).resolve()
                if not trash.is_relative_to(self.data.resolve()) or trash == path or trash.is_relative_to(path):
                    raise ValueError('The project cannot be moved to this trash folder.')
                trash.parent.mkdir(parents=True, exist_ok=True)
                path.rename(trash)
            self.removed_projects[os.path.normcase(str(path))] = {'name': self.registry[identifier]['name'], 'trash': str(trash) if trash else '', 'deleted_at': time.time()}
            write_json(self.data / 'studio_removed_projects.json', self.removed_projects)
            self.registry.pop(identifier)
            self.persist()
            if self.job and self.job.get('project') == identifier:
                self.job = None
                write_json(self.data / 'ai' / 'job.json', {})
            self.jobs = {key: job for key, job in self.jobs.items() if job.get('project') != identifier}
            self.persist_jobs()
            return {'deleted': identifier, 'files_moved': bool(trash)}

    def create(self, name, preset='blank'):
        self.idle()
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Give the project a name.')
        slug = re.sub(r'[^\w -]', '', name).strip(' .')[:70] or 'video'
        path = self.projects / f'{slug}-{uuid.uuid4().hex[:6]}'
        if preset == 'games':
            editor = {'name': name, 'mode': 'games', 'script': '', 'games': [], 'sections': [], 'captions': True}
        else:
            defaults = {
                'blank': [{'title': 'Opening', 'layout': 'background', 'caption_y': .46}],
                'showcase': [{'title': 'Opening', 'layout': 'background', 'caption_y': .46},
                             {'title': 'Main content', 'layout': 'single'}, {'title': 'Closing', 'layout': 'background'}],
                'comparison': [{'title': 'Opening', 'layout': 'background', 'caption_y': .46},
                               {'title': 'Comparison', 'layout': 'split'}, {'title': 'Closing', 'layout': 'title'}],
            }
            selected = defaults.get(preset) or self.presets.get(preset)
            if selected is None:
                raise ValueError('Unknown layout preset.')
            editor = {'name': name, 'mode': 'sections', 'script': '', 'games': [],
                      'sections': copy.deepcopy(selected), 'captions': True}
        path.mkdir(parents=True, exist_ok=False)
        write_json(path / 'studio.json', editor)
        return self.register(path)

    def create_pc_tips(self, name='', idea='', recording_mode=None, auto_produce=None, voice_source=None, category='auto'):
        self.idle()
        options = pc_tips.settings(self.data)
        selected_type = pc_tips.category(category)
        if not isinstance(name, str) or len(name.strip()) > 80: raise ValueError('Keep the project name below 80 characters.')
        if not isinstance(idea, str) or len(idea.strip()) > 10000: raise ValueError('Keep the video idea below 10,000 characters.')
        name = name.strip() or f'PC Tips & Tricks - Part {pc_tips.next_part(self.data):02}'
        idea = idea.strip()
        if recording_mode is None: recording_mode = options['recording_mode']
        if auto_produce is None: auto_produce = options['auto_produce']
        if voice_source is None: voice_source = options['voice_source']
        if recording_mode not in pc_tips.RECORDING_MODES: raise ValueError('Choose an animated walkthrough or a real Windows recording.')
        if not isinstance(auto_produce, bool): raise ValueError('Choose automatic production or script review.')
        if voice_source not in ('upload', 'elevenlabs'): raise ValueError('Choose a narration source.')
        pc_tips.pc_tips_ai.require_connection(self.data)
        identifier = self.create(name, 'blank')
        path = self.project(identifier)
        part = pc_tips.reserve(self.data, identifier, idea, selected_type['id'])
        selected = {**voice_generation.DEFAULTS, **self.voice.snapshot()['defaults'], 'source': voice_source}
        write_json(path / 'voiceover.json', selected)
        options = pc_tips.settings(self.data)
        pc_tips.save_state(path, {'project': identifier, 'part': part, 'idea': idea, 'idea_source': 'manual' if idea else 'automatic',
            'category': selected_type['id'], 'theme': pc_tips.theme(part),
            'recording_mode': recording_mode, 'auto_produce': auto_produce, 'status': 'writing_script',
            'script_model': options['script_model'], 'ai_connection': 'google-first-subscriptions', 'error': ''})
        return self.start_pc_tips(identifier)

    def start_pc_tips(self, identifier, recording_mode=None, add_problem=False):
        with self.lock:
            self.idle(identifier)
            path = self.project(identifier)
            saved = pc_tips.state(path)
            if not saved: raise ValueError('Create a PC Tips & Tricks episode first.')
            if saved.get('stale'): raise ValueError('Save the current script before continuing production.')
            pc_tips.pc_tips_ai.require_connection(self.data)
            options = pc_tips.settings(self.data)
            if recording_mode is not None: pc_tips.change_mode(saved, recording_mode)
            saved.update(script_model=options['script_model'], ai_connection='google-first-subscriptions')
            saved.pop('image_model', None)
            if not isinstance(add_problem, bool): raise ValueError('Choose whether to add the problem opening.')
            drafting = not saved.get('plan')
            pc_tips.save_state(path, saved, 'writing_script' if drafting else 'preparing', error='')
            job = self._ai_job(identifier, 'pc_draft' if drafting else 'pc_problem' if add_problem and not saved['plan'].get('problem') else 'pc_produce', 'Writing PC tutorial' if drafting else 'Preparing PC tutorial')
            self.enqueue(job, self.run, path, read_cache(path / 'config.json'), 0)
            return {'project': self.load(identifier), 'job': copy.deepcopy(job)}

    def create_reference(self, name, script, instructions='', provider=None, workflow='reference', idea='', styles=None, style_mix=None, source=None, scene_mode='templates'):
        self.idle()
        if scene_mode not in ('templates', 'custom'): raise ValueError('Choose built-in templates or Claude draws each scene.')
        if scene_mode == 'custom' and (workflow != 'reference' or (provider or reference_styles.settings(self.data).get('provider')) != 'claude'):
            raise ValueError('Claude draws each scene with Video Turbo animation and the Claude provider.')
        if workflow not in ('reference', 'flow'): raise ValueError('Choose a supported creation path.')
        if source is not None:
            # Recreate a source video's idea: the script is drafted later, for review.
            if workflow != 'reference': raise ValueError('Recreating a video works with Video Turbo animation.')
            if not styles: raise ValueError('Choose at least one saved style for the recreated video.')
            source = recreate.options(source)
            script = ''
        library = None
        if styles:
            if workflow != 'reference': raise ValueError('Saved styles work with Video Turbo animation. Choose it under Video creation.')
            library = style_library.snapshot(self.data, styles)
            style_mix = style_library.validate_mix(style_mix, len(library))
        if not isinstance(idea, str) or len(idea) > 10000: raise ValueError('Keep your idea below 10,000 characters.')
        if not isinstance(script, str) or len(script.strip()) > 100000 or (not script.strip() and not (workflow == 'flow' and idea.strip()) and source is None):
            raise ValueError('Provide your spoken script, or a video idea for Google Flow.')
        if not isinstance(instructions, str) or len(instructions) > 10000:
            raise ValueError('Keep style instructions below 10,000 characters.')
        provider = provider or reference_styles.settings(self.data).get('provider', 'antigravity')
        if provider not in reference_styles.PROVIDER_NAMES: raise ValueError(reference_styles.PROVIDER_CHOICE)
        identifier = self.create(name, 'blank')
        editor = self.load(identifier)['editor']
        editor.update(script=script.strip(), sections=[{'layout': 'title', 'title': 'Reference style', 'captions': True}])
        self.save(identifier, editor)
        state = {'status': 'awaiting_inputs', 'reference_file': '', 'instructions': instructions, 'analysis_provider': provider, 'workflow': workflow, 'idea': idea.strip(), 'error': ''}
        if library: state.update(library_styles=library, style_mix=style_mix)
        if source is not None: state['recreate'] = source
        if scene_mode == 'custom': state['scene_mode'] = 'custom'
        write_json(self.project(identifier) / 'reference_style.json', state)
        return self.load(identifier)

    def approve_recreate_script(self, identifier, script):
        self.idle(identifier)
        path = self.project(identifier)
        state = read_cache(path / 'reference_style.json')
        if not recreate.is_recreate(state) or state.get('status') != 'script_review': raise ValueError('Draft a script from the source video first.')
        if state['recreate'].get('drafted_source') != reference_styles.file_signature(recreate.source_path(path, state)):
            raise ValueError('Your source video changed. Draft the script again first.')
        if not isinstance(script, str) or not 1 <= len(script.strip()) <= 100000: raise ValueError('Provide the script you reviewed.')
        editor = self.load(identifier)['editor']; editor['script'] = script.strip()
        self.save(identifier, editor)
        state.update(status='awaiting_inputs', draft_script='', error='')
        write_json(path / 'reference_style.json', state)
        return self.load(identifier)

    def approve_flow_script(self, identifier, script):
        self.idle(identifier)
        path = self.project(identifier)
        state = read_cache(path / 'reference_style.json')
        if state.get('workflow') != 'flow' or state.get('status') != 'script_review': raise ValueError('Generate a Flow script draft first.')
        if state.get('draft_reference_signature') != reference_styles.file_signature(reference_styles.media_reference(path, state.get('reference_file', ''))):
            raise ValueError('Your reference changed. Generate a fresh script draft first.')
        flow_workflow.text(script, 100000, 'spoken script')
        editor = self.load(identifier)['editor']; editor['script'] = script.strip()
        self.save(identifier, editor)
        state.update(status='awaiting_inputs', draft_script='', error='')
        write_json(path / 'reference_style.json', state)
        return self.load(identifier)

    def reference_state(self, identifier):
        path = self.project(identifier)
        state = read_cache(path / 'reference_style.json')
        if not state: return {}
        source = state.get('recreate')
        if isinstance(source, dict) and source.get('source_file') and 'source_matches_style' not in source:
            # Projects created before this check: compare their source once with the saved style videos.
            try: source['source_matches_style'] = style_library.matching_source(self.data, recreate.source_path(path, state))
            except (OSError, ValueError): source['source_matches_style'] = ''
            write_json(path / 'reference_style.json', state)
        state = copy.deepcopy(state)
        script = (path / 'script.txt').read_text('utf-8-sig').strip() if (path / 'script.txt').is_file() else ''
        stale = state.get('script_hash') != fingerprint(script)
        try:
            stale = stale or state.get('voice_signature') != reference_styles.file_signature(voiceover_path(path))
            if not reference_styles.uses_library(state):
                stale = stale or state.get('reference_signature') != reference_styles.file_signature(reference_styles.media_reference(path, state.get('reference_file', '')))
        except (ValueError, FileNotFoundError): stale = True
        state['stale'] = stale
        if state.get('workflow') == 'flow' and state.get('flow_plan'):
            state['flow_visual_direction'] = flow_workflow.visual_direction(state['flow_plan'])
            state['flow_scenes'] = [{**row, 'image_prompt': flow_workflow.prompt_for(state['flow_plan'], row, 'image'),
                                    'motion_prompt': flow_workflow.prompt_for(state['flow_plan'], row, 'motion')}
                                   for row in flow_workflow.scene_rows(state['flow_plan'])]
        if state.get('status') == 'analyzing' and not self.project_job(identifier):
            state.update(status='interrupted', error='Analysis was interrupted. Your files are saved; retry analysis.')
        return state

    def save_voice(self, identifier, settings):
        self.idle(identifier)
        path = self.project(identifier)
        saved = read_cache(path / 'voiceover.json')
        saved.update(voice_generation.options(settings))
        write_json(path / 'voiceover.json', saved)
        return self.load(identifier)

    def start_voice(self, identifier, build=False, force=False, continuation=''):
        with self.lock:
            self.idle(identifier)
            path = self.project(identifier)
            if build and pc_tips.state(path): return self.start_pc_tips(identifier)
            selected = voice_generation.options(voice_generation.project_state(path))
            if selected['source'] != 'elevenlabs': raise ValueError('Choose ElevenLabs as your voiceover source first.')
            if not self.voice.snapshot()['configured']: raise ValueError('Connect ElevenLabs in Voice settings first.')
            if not selected['voice_id'] or not selected['model_id']: raise ValueError('Choose an ElevenLabs voice and model first.')
            script = (path / 'script.txt').read_text('utf-8-sig').strip() if (path / 'script.txt').exists() else ''
            if not script: raise ValueError('Add your spoken script before generating a voiceover.')
            workflow = self.workflow(identifier)
            if workflow and workflow.get('source') != 'import' and workflow.get('approved_script_hash') != fingerprint(script):
                raise ValueError('Review and approve the current AI script before generating a voiceover.')
            reference = self.reference_state(identifier)
            action = continuation or ((('reference_plan' if reference.get('workflow') == 'flow' else 'reference_build') if reference else 'build') if build else '')
            config = read_cache(path / 'config.json')
            if action.startswith('reference_'):
                if not reference_styles.uses_library(reference): reference_styles.media_reference(path, reference.get('reference_file', ''))
                connections = reference_styles.settings(self.data)
                provider = reference.get('analysis_provider') or connections['provider']
                if provider not in reference_styles.PROVIDER_NAMES: raise ValueError(reference_styles.PROVIDER_CHOICE)
                if not connections['providers'][provider]['installed']: raise ValueError('Connect the local analysis provider before generating and building.')
            elif action:
                if workflow and workflow.get('source') != 'import' and (workflow.get('status') not in ('assets_ready', 'complete', 'failed', 'interrupted') or self.load(identifier)['editor']['mode'] != 'games'):
                    raise ValueError('Wait for asset preparation to finish before generating and building.')
                if 'sections' in config: sections.validate_sections(config, path)
                elif not config.get('games'): raise ValueError('Save your game list before generating and building.')
            job = self._ai_job(identifier, 'voice_build' if action else 'voice_generate', 'Preparing ElevenLabs voiceover')
            job.update(next_action=action, force_voice=force is True)
            write_json(self.data / 'ai' / 'job.json', job)
            if workflow and action == 'build':
                if workflow.get('source') == 'import':
                    editor = self.load(identifier)['editor']
                    workflow.update(approved_script=script, approved_script_hash=fingerprint(script), prepared_inputs_hash=self.asset_inputs_hash(editor))
                workflow.update(status='rendering', error='')
                write_json(path / 'ai_workflow.json', workflow)
            self.enqueue(job, self.run, path, config, 0)
            return {'project': self.load(identifier), 'job': copy.deepcopy(job)}

    def set_scene_mode(self, identifier, mode):
        with self.lock:
            self.idle(identifier)
            path = self.project(identifier)
            state = read_cache(path / 'reference_style.json')
            if not state or state.get('workflow') == 'flow': raise ValueError('Scene drawing works with Video Turbo animation projects.')
            if mode not in ('templates', 'custom'): raise ValueError('Choose built-in templates or Claude draws each scene.')
            if mode == 'custom' and state.get('analysis_provider') != 'claude': raise ValueError('Choose Claude as the analysis provider first.')
            state['scene_mode'] = mode
            if mode == 'templates':
                # Keep Claude's files on disk, but render the built-in templates.
                config = read_cache(path / 'config.json')
                for row in config.get('sections', []): row.pop('custom_scene', None); row.pop('custom_images', None)
                write_json(path / 'config.json', config)
                editor = read_cache(path / 'studio.json'); editor['sections'] = config.get('sections', []); write_json(path / 'studio.json', editor)
                state.pop('custom_scenes', None)
            write_json(path / 'reference_style.json', state)
            return self.load(identifier)

    def draw_scenes(self, identifier):
        """Have Claude draw each scene from the saved plan, without a new analysis."""
        with self.lock:
            self.idle(identifier)
            path = self.project(identifier)
            state = self.reference_state(identifier)
            if state.get('scene_mode') != 'custom': raise ValueError('Choose "Claude draws each scene" first.')
            if not state.get('analysis') or state.get('stale') or state.get('status') not in ('ready', 'complete', 'render_failed', 'failed'):
                raise ValueError('Analyze & plan scenes first.')
            if not reference_styles.settings(self.data)['providers']['claude']['installed']: raise ValueError('Connect Claude first.')
            job = self._ai_job(identifier, 'reference_scenes', 'Claude is drawing your scenes')
            self.enqueue(job, self.run, path, read_cache(path / 'config.json'), 0)
            return {'project': self.load(identifier), 'job': copy.deepcopy(job)}

    def start_reference(self, identifier, build=True, provider=None):
        with self.lock:
            self.idle(identifier)
            path = self.project(identifier)
            state = self.reference_state(identifier)
            if not state: raise ValueError('Create a Reference Styles project first.')
            if reference_styles.uses_library(state):
                state['library_styles'] = style_library.refresh(self.data, state['library_styles'])
            else:
                reference_styles.media_reference(path, state.get('reference_file', ''))
            flow = state.get('workflow') == 'flow'
            if flow: build = False
            unscripted = not (path / 'script.txt').read_text('utf-8-sig').strip()
            recreating = recreate.is_recreate(state) and unscripted
            drafting = (flow or recreating) and unscripted
            if recreating:
                build = False
                recreate.require_source(path, state)
            selected_voice = voice_generation.project_state(path)
            if not drafting and selected_voice['source'] == 'elevenlabs' and (not selected_voice.get('generated_current') or selected_voice.get('stale')):
                if provider and provider not in reference_styles.PROVIDER_NAMES: raise ValueError(reference_styles.PROVIDER_CHOICE)
                state['analysis_provider'] = provider or state.get('analysis_provider')
                state.pop('stale', None)
                write_json(path / 'reference_style.json', state)
                return self.start_voice(identifier, continuation='reference_build' if build else 'reference_plan')
            if not drafting: voiceover_path(path)
            connections = reference_styles.settings(self.data)
            provider = provider or state.get('analysis_provider') or connections.get('provider', 'antigravity')
            if provider not in reference_styles.PROVIDER_NAMES: raise ValueError(reference_styles.PROVIDER_CHOICE)
            selected = connections.get('providers', {}).get(provider, connections)
            if not selected['installed']:
                raise ValueError('Connect the selected local AI provider before analyzing.')
            if drafting and flow and not state.get('idea'): raise ValueError('Add a video idea first.')
            if not drafting and not (path / 'script.txt').read_text('utf-8-sig').strip(): raise ValueError('Add your spoken script first.')
            state.update(analysis_provider=provider)
            state.pop('stale', None)
            write_json(path / 'reference_style.json', state)
            job = self._ai_job(identifier, 'reference_build' if build else 'reference_plan', ('Drafting your script with ' if recreating else 'Analyzing reference with ') + reference_styles.PROVIDER_NAMES[provider])
            self.enqueue(job, self.run, path, read_cache(path / 'config.json'), 0)
            return {'project': self.load(identifier), 'job': copy.deepcopy(job)}

    def active_styles(self):
        return {job['style'] for job in self.all_jobs() if job.get('style') and job.get('status') in ('queued', 'running', 'cancelling')}

    def list_styles(self):
        with self.lock:
            jobs = {job['style']: job for job in self.all_jobs() if job.get('style') and job.get('status') in ('queued', 'running', 'cancelling')}
            rows = style_library.list_styles(self.data, set(jobs))
            for row in rows:
                job = jobs.get(row['id'])
                if job: row['job'] = {'id': job['id'], 'status': job['status'], 'stage': job.get('stage', ''), 'progress': job.get('progress', 0)}
            return {'styles': rows, 'fields': style_library.FIELDS, 'categories': style_library.CATEGORY_LABELS,
                    'layout_choices': {key: list(value) for key, value in style_library.LAYOUT_CHOICES.items()},
                    'layout_labels': style_library.LAYOUT_LABELS, 'layout_categories': style_library.LAYOUT_CATEGORY,
                    'max_styles': style_library.MAX_STYLES, 'providers': reference_styles.PROVIDER_NAMES}

    def start_style_analysis(self, style_id, provider=None, model=None):
        with self.lock:
            if style_id in self.active_styles(): raise ValueError('This style is already being analyzed.')
            value = style_library.begin_analysis(self.data, style_id, provider, model)
            job = {'id': uuid.uuid4().hex, 'project': '', 'style': style_id, 'label': 'Style: ' + value['name'],
                   'action': 'style_analysis', 'status': 'queued', 'stage': 'Analyzing style with ' + reference_styles.PROVIDER_NAMES[value['provider']],
                   'progress': 0, 'logs': [], 'started': time.time(), 'cancel': False}
            self.jobs[job['id']] = job
            self.enqueue(job, self.run_style, style_id)
            return self.list_styles()

    def run_style(self, job, style_id):
        command = [sys.executable, '-u', str(ENGINE / 'style_library.py'), '--style', style_id, '--data', str(self.data)]
        try:
            with self.lock:
                if job['cancel']: return
                process = subprocess.Popen(command, cwd=ENGINE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                           encoding='utf-8', errors='replace', env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'},
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                self.processes[job['id']] = process
            for line in process.stdout:
                line = line.strip()
                if not line: continue
                with self.lock:
                    job['logs'] = (job['logs'] + [line])[-600:]
                    if '[STYLE]' in line: job['stage'] = line.split('[STYLE]', 1)[1].strip()
                    if 'breaking down' in line: job['progress'] = 40
            code = process.wait()
            with self.lock:
                if job['cancel']: job.update(status='cancelled', stage='Cancelled', progress=0)
                elif code: job.update(status='failed', stage='Style analysis failed', error=style_library.record(self.data, style_id).get('error') or 'Style analysis failed. Check the log and retry.')
                else: job.update(status='complete', stage='Style saved to your library', progress=100)
        except Exception as error:
            with self.lock: job.update(status='cancelled' if job['cancel'] else 'failed', stage='Style analysis failed', error=str(error))
        finally:
            with self.lock:
                self.processes.pop(job['id'], None)
                job['finished'] = time.time()
                if job['status'] != 'complete':
                    style_library.end_analysis(self.data, style_id, 'cancelled' if job['status'] == 'cancelled' else 'failed', job.get('error', ''))
                self.persist_jobs()

    def import_brief(self, raw):
        self.idle()
        parsed = parse_brief(raw)
        editor = parsed['editor']
        identifier = self.create(editor['name'], 'games')
        self.save(identifier, editor)
        config_path = self.project(identifier) / 'config.json'
        config = read_cache(config_path)
        config['brief_sources'] = True
        write_json(config_path, config)
        write_json(self.project(identifier) / 'ai_workflow.json', self.workflow(identifier))
        return self.load(identifier)

    def start_brief_automation(self, conversation_id, request='', build=True, identifier='', episode_mode='new'):
        with self.lock:
            self.idle(identifier)
            conversation_id, request = antigravity_brief.inputs(conversation_id, request)
            episode_mode = antigravity_brief.episode_mode(episode_mode)
            if not isinstance(build, bool): raise ValueError('Choose import only or import and build.')
            if not reference_styles.settings(self.data)['providers']['antigravity']['installed'] and (episode_mode == 'new' or not antigravity_brief.transcript_path(conversation_id).is_file()):
                raise ValueError('Connect the local Antigravity CLI before importing a conversation.')
            if identifier:
                previous = self.workflow(identifier)
                if previous.get('source') != 'import' or previous.get('failed_step') != 'brief_import':
                    raise ValueError('Only an interrupted Antigravity import can be resumed here.')
                selected = voice_generation.options(voice_generation.project_state(self.project(identifier)))
            else:
                selected = voice_generation.options(self.voice.snapshot()['defaults'])
            if build:
                selected['source'] = 'elevenlabs'
                if not self.voice.snapshot()['configured'] or not selected['voice_id'] or not selected['model_id']:
                    raise ValueError('Save a default ElevenLabs voice and speech model in Voice settings before automatic building. You can still import without building.')
            if not identifier: identifier = self.create('Antigravity video', 'games')
            path = self.project(identifier)
            write_json(path / 'voiceover.json', selected)
            write_json(self.data / 'brief_automation/settings.json', {'conversation_id': conversation_id, 'request': request})
            write_json(path / 'ai_workflow.json', {
                'source': 'import', 'status': 'fetching_brief', 'conversation_id': conversation_id,
                'brief_request': request, 'episode_mode': episode_mode, 'build_video': build, 'auto_build': build,
                'failed_step': 'brief_import', 'error': ''})
            job = self._ai_job(identifier, 'brief_import', 'Generating the next Antigravity episode' if episode_mode == 'new' else 'Reading latest Antigravity brief')
            self.enqueue(job, self.run_brief_automation, path)
            return {'project': self.load(identifier), 'job': copy.deepcopy(job)}

    def run_brief_automation(self, job, path):
        delegated = False
        process = None
        try:
            with self.lock:
                if job['cancel']: return
                process = subprocess.Popen([sys.executable, '-u', str(ENGINE / 'antigravity_brief.py'),
                    '--project', str(path), '--data', str(self.data)], cwd=ENGINE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'},
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                self.processes[job['id']] = process
            message = ''
            for line in process.stdout:
                line = line.strip()
                if not line: continue
                with self.lock:
                    job['logs'] = (job['logs'] + [line])[-600:]
                    if line.startswith('[BRIEF] '): job['stage'] = line[8:]
                    if line.startswith('[BRIEF ERROR] '): message = line[14:]
            code = process.wait()
            with self.lock:
                self.processes.pop(job['id'], None)
                if job['cancel']: return
                if code: raise ValueError(message or 'Antigravity import failed. Check the job log and retry.')
                brief = read_cache(path / 'ai_brief.json')
                parsed = parse_brief(brief)
                identifier = job['project']
                self.save(identifier, parsed['editor'], job_id=job['id'])
                self.registry[identifier]['name'] = parsed['editor']['name']; self.persist()
                config = read_cache(path / 'config.json'); config['brief_sources'] = True
                write_json(path / 'config.json', config)
                workflow = self.workflow(identifier)
                workflow.update(status='awaiting_assets', warnings=parsed['warnings'], failed_step='', error='')
                if workflow['build_video']:
                    workflow.update(status='rendering', approved_script=parsed['editor']['script'],
                        approved_script_hash=fingerprint(parsed['editor']['script']),
                        prepared_inputs_hash=self.asset_inputs_hash(parsed['editor']))
                    job.update(next_action='build', generate_voice=True, stage='Preparing voiceover and video', progress=5)
                else:
                    job.update(status='complete', stage='Brief imported; ready to edit', progress=100)
                write_json(path / 'ai_workflow.json', workflow)
            if workflow['build_video']:
                delegated = True
                self.run(job, path, config, 0)
        except Exception as error:
            with self.lock:
                job.update(status='failed', stage='Antigravity import failed',
                    error=str(error) if isinstance(error, ValueError) else 'Antigravity import failed. Your project is saved; retry the import.')
        finally:
            if process and process.stdout: process.stdout.close()
            if not delegated:
                with self.lock:
                    self.processes.pop(job['id'], None)
                    if job['cancel']: job.update(status='cancelled', stage='Cancelled', error='')
                    if job['status'] in ('failed', 'cancelled'):
                        workflow = self.workflow(job['project'])
                        workflow.update(status=job['status'], failed_step='brief_import', error=job.get('error', ''))
                        write_json(path / 'ai_workflow.json', workflow)
                    job['finished'] = time.time()
                    self.persist_jobs()

    def list_projects(self):
        # Discover existing video folders without modifying their contents.
        for path in ENGINE.parent.iterdir():
            if os.path.normcase(str(path.resolve())) not in self.removed_projects and path.is_dir() and (path / 'script.txt').is_file() and ((path / 'games').is_dir() or (path / 'studio.json').is_file()):
                self.register(path)
        return [{'id': key, 'name': value['name'], 'path': value['path'], 'managed': self.managed_project(Path(value['path']))}
                for key, value in self.registry.items() if Path(value['path']).is_dir() and os.path.normcase(value['path']) not in self.removed_projects]

    def media(self, path):
        files = []
        for directory in ('media', 'games'):
            for item in (path / directory).rglob('*'):
                if item.is_file() and item.suffix.lower() in sections.VIDEO_EXTS | sections.IMAGE_EXTS and item.resolve().is_relative_to(path.resolve()) and not item.name.startswith('raw_gameplay'):
                    files.append({'path': item.relative_to(path).as_posix(), 'name': item.name,
                                  'kind': 'video' if item.suffix.lower() in sections.VIDEO_EXTS else 'image'})
        return files

    def load(self, identifier):
        path = self.project(identifier)
        editor = read_cache(path / 'studio.json')
        config = read_cache(path / 'config.json')
        tutorial = pc_tips.state(path)
        if not editor:
            sources = {}
            if (path / 'games.txt').exists():
                for line in (path / 'games.txt').read_text('utf-8-sig').splitlines():
                    if '|' in line and not line.lstrip().startswith('#'):
                        folder, url = line.split('|', 1)
                        sources[folder.strip()] = url.strip()
            games = config.get('games') or [{'folder': p.name, 'title': re.sub(r'^\d+[_ -]*', '', p.name)} for p in sorted((path / 'games').glob('*')) if p.is_dir()]
            editor = {'name': path.name, 'mode': 'sections' if 'sections' in config else 'games',
                      'sections': config.get('sections', []), 'games': [{**g, 'url': sources.get(g['folder'], '')} for g in games],
                      'captions': config.get('captions_in_game_blocks', True)}
        editor['script'] = (path / 'script.txt').read_text('utf-8-sig') if (path / 'script.txt').exists() else editor.get('script', '')
        try:
            voice = voiceover_path(path).name
        except FileNotFoundError:
            voice = ''
        return {'id': identifier, 'path': str(path), 'editor': editor, 'media': self.media(path),
                'voiceover': voice, 'music': (path / 'music.mp3').is_file(),
                'background': (path / 'gta_background.mp4').is_file(),
                'final': (path / 'output/final.mp4').is_file() and (not tutorial or tutorial.get('status') == 'complete' and not tutorial.get('stale') and not tutorial.get('voice_stale') and not tutorial.get('render_stale')), 'preview': (path / 'output/studio_preview.png').is_file(),
                'ai_workflow': self.workflow(identifier), 'reference_style': self.reference_state(identifier),
                'voice_settings': voice_generation.project_state(path), 'pc_tips': tutorial}

    def save(self, identifier, editor, *, job_id=None):
        if job_id is None:
            self.idle(identifier)
        elif not any(job.get('id') == job_id and job.get('project') == identifier and job.get('status') == 'running' for job in self.all_jobs()):
            raise ValueError('The AI generation job changed; reload the project.')
        path = self.project(identifier)
        if not isinstance(editor, dict) or editor.get('mode') not in ('sections', 'games'):
            raise ValueError('Invalid project settings.')
        if not isinstance(editor.get('script', ''), str):
            raise ValueError('Script must be text.')
        config = read_cache(path / 'config.json')
        config['captions_in_game_blocks'] = bool(editor.get('captions', True))
        if editor['mode'] == 'sections':
            draft = editor.get('sections', [])
            if not isinstance(draft, list) or not draft:
                raise ValueError('Add a section first.')
            # A draft may have empty media slots; check referenced files now,
            # while full readiness is validated before preview/build.
            for section in draft:
                if section.get('layout', 'single') not in sections.LAYOUTS:
                    raise ValueError('Invalid section layout.')
                for field in ('media', 'secondary_media'):
                    if section.get(field):
                        sections.media_path(path, section[field])
            config['sections'] = draft
            config.pop('games', None)
        else:
            games = editor.get('games', [])
            if not isinstance(games, list) or not games:
                raise ValueError('Add at least one game.')
            seen = set()
            for i, game in enumerate(games):
                folder = (game.get('folder') or f'{i + 1:02d}_game').strip(' .')
                if not re.fullmatch(r'[\w .()-]+', folder) or folder in ('.', '..'):
                    raise ValueError('Use a unique, simple folder name for each game.')
                if folder.casefold() in seen:
                    raise ValueError('Use a unique folder name for each game.')
                seen.add(folder.casefold())
                game['folder'] = folder
                if game.get('url') and (urlparse(game['url']).scheme not in ('http', 'https') or urlparse(game['url']).hostname not in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be')):
                    raise ValueError('Game download sources must be YouTube URLs.')
                game['logo_url'] = image_url(game.get('logo_url'))
                for field in ('top', 'bottom', 'logo'):
                    if game.get(field):
                        source = sections.media_path(path, game[field])
                        if field != 'logo' and source.suffix.lower() != '.mp4':
                            raise ValueError('Use MP4 files for game clips.')
                        if field == 'logo' and source.suffix.lower() not in sections.IMAGE_EXTS:
                            raise ValueError('Choose an image for the game logo.')
            for game in games:
                target = path / 'games' / game['folder']
                if not target.resolve().is_relative_to(path):
                    raise ValueError('Game folder points outside the project.')
                target.mkdir(parents=True, exist_ok=True)
                for field in ('top', 'bottom', 'logo'):
                    if game.get(field):
                        source = sections.media_path(path, game[field])
                        dest = target / (field + source.suffix.lower())
                        if source.resolve() != dest.resolve():
                            shutil.copy2(source, dest)
            config.pop('sections', None)
            config['games'] = []
            for game in games:
                spec = {key: game.get(key, []) if key == 'spoken_names' else game.get(key, '')
                        for key in ('folder', 'title', 'spoken_names', 'logo_url')}
                spec['manual_logo'] = bool(game.get('logo'))
                spec['logo_file'] = ('logo' + Path(game['logo']).suffix.lower()) if game.get('logo') else ''
                config['games'].append(spec)
            (path / 'games.txt').write_text('\n'.join(f"{g['folder']} | {g['url']}" for g in games if g.get('url')), encoding='utf-8')
        tutorial = pc_tips.state(path)
        if tutorial: pc_tips.sync_script(path, tutorial, editor.get('script', ''))
        write_json(path / 'config.json', config)
        write_json(path / 'studio.json', editor)
        (path / 'script.txt').write_text(editor.get('script', ''), encoding='utf-8')
        self.registry[identifier]['name'] = editor.get('name') or path.name
        self.persist()
        workflow = self.workflow(identifier)
        imported_changed = workflow.get('source') == 'import' and workflow.get('prepared_inputs_hash') and workflow['prepared_inputs_hash'] != self.asset_inputs_hash(editor)
        if job_id is None and (imported_changed or workflow.get('approved_script_hash') and workflow['approved_script_hash'] != fingerprint(editor.get('script', '').strip())):
            workflow.update(status='awaiting_assets' if workflow.get('source') == 'import' else 'awaiting_review', approved_script_hash='', prepared_inputs_hash='', error='')
            write_json(path / 'ai_workflow.json', workflow)
        return self.load(identifier)

    def workflow(self, identifier):
        path = self.project(identifier)
        workflow = read_cache(path / 'ai_workflow.json')
        config = read_cache(path / 'config.json')
        if not workflow and config.get('brief_sources') and 'sections' not in config:
            # Existing imports get the same preparation controls as new briefs.
            return {'source': 'import', 'status': 'awaiting_assets', 'auto_build': True, 'error': ''}
        return workflow

    @staticmethod
    def asset_inputs_hash(editor):
        return fingerprint({'mode': editor['mode'], 'script': editor.get('script', '').strip(), 'games': editor.get('games', [])})

    def prepare_imported_assets(self, identifier):
        with self.lock:
            self.idle(identifier)
            workflow = self.workflow(identifier)
            editor = self.load(identifier)['editor']
            if workflow.get('source') != 'import' or editor['mode'] != 'games':
                raise ValueError('Import an AI brief before preparing its assets.')
            if not editor.get('script', '').strip() or not editor.get('games'):
                raise ValueError('Provide your spoken script and game list before preparing assets.')
            path = self.project(identifier)
            workflow.update(status='preparing_assets', approved_script=editor['script'].strip(),
                            approved_script_hash=fingerprint(editor['script'].strip()),
                            prepared_inputs_hash=self.asset_inputs_hash(editor), auto_build=True, failed_step='', error='')
            write_json(path / 'ai_workflow.json', workflow)
            job = self._ai_job(identifier, 'ai_prepare', 'Preparing gameplay and logos')
            self.enqueue(job, self.run, path, read_cache(path / 'config.json'), 0)
            return {'project': self.load(identifier), 'job': copy.deepcopy(job)}

    def _ai_job(self, identifier, action, stage):
        job = {'id': uuid.uuid4().hex, 'project': identifier, 'action': action, 'status': 'queued',
               'stage': stage, 'progress': 0, 'logs': [], 'started': time.time(), 'cancel': False}
        self.job = job
        self.jobs[job['id']] = job
        self.persist_jobs()
        return job

    def create_ai(self, name, provider, idea, language, series_id=''):
        self.idle()
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80: raise ValueError('Give the AI project a name of 1 to 80 characters.')
        account = self.ai.account(provider)
        if not isinstance(idea, str) or not 1 <= len(idea.strip()) <= 10000: raise ValueError('Describe your video idea in 1 to 10,000 characters.')
        if not isinstance(language, str) or not 1 <= len(language.strip()) <= 100: raise ValueError('Choose the script language or dialect.')
        if not isinstance(series_id, str): raise ValueError('Choose a saved series.')
        context = self.series.context(series_id) if series_id else None
        identifier = self.create(name, 'blank')
        workflow = {'provider': provider, 'model': account['model'], 'idea': idea.strip(), 'language': language.strip(),
                    'status': 'writing_script', 'approved_script_hash': '', 'auto_build': True, 'error': ''}
        if context: workflow.update(series_id=series_id, series_context=context)
        write_json(self.project(identifier) / 'ai_workflow.json', workflow)
        job = self._ai_job(identifier, 'ai_script', 'Writing your script')
        self.enqueue(job, self.run_ai, account)
        return {'project': self.load(identifier), 'job': copy.deepcopy(job)}

    def retry_ai(self, identifier):
        self.idle(identifier)
        workflow = self.workflow(identifier)
        if not workflow or workflow.get('status') not in ('failed','cancelled','interrupted'): raise ValueError('There is no failed AI step to retry.')
        if workflow.get('source') == 'import':
            if workflow.get('failed_step') == 'brief_import':
                return self.start_brief_automation(workflow['conversation_id'], workflow.get('brief_request', ''), workflow.get('build_video', False), identifier, episode_mode=workflow.get('episode_mode', 'new'))
            return self.prepare_imported_assets(identifier)
        account = self.ai.account(workflow['provider'])
        if workflow.get('approved_script_hash'):
            return self.approve_ai(identifier, self.load(identifier)['editor']['script'], True)
        workflow.update(status='writing_script', model=account['model'], error='')
        write_json(self.project(identifier) / 'ai_workflow.json', workflow)
        job = self._ai_job(identifier, 'ai_script', 'Writing your script')
        self.enqueue(job, self.run_ai, account)
        return {'project': self.load(identifier), 'job': copy.deepcopy(job)}

    def approve_ai(self, identifier, script, approved=False):
        self.idle(identifier)
        workflow = self.workflow(identifier)
        if approved is not True: raise ValueError('Review and approve the script before preparing assets.')
        if not workflow.get('outline'): raise ValueError('Generate a script before approving it.')
        if workflow.get('status') not in ('awaiting_review','failed','cancelled','interrupted'):
            raise ValueError('This script is already approved. Wait for preparation to finish.')
        if not isinstance(script, str) or not 1 <= len(script.strip()) <= 100000: raise ValueError('Provide the complete script you reviewed.')
        account = self.ai.account(workflow['provider'])
        editor = self.load(identifier)['editor']; editor['script'] = script.strip()
        self.save(identifier, editor)
        workflow.update(status='finding_sources', approved_script_hash=fingerprint(script.strip()), approved_script=script.strip(), model=account['model'], error='')
        write_json(self.project(identifier) / 'ai_workflow.json', workflow)
        if workflow.get('series_id'):
            self.series.record_approval(workflow['series_id'], identifier, editor['name'], workflow['idea'], script.strip(),
                                        [game['exact_name'] for game in workflow['outline']['games']])
        job = self._ai_job(identifier, 'ai_prepare', 'Finding gameplay and logos')
        self.enqueue(job, self.run_ai, account)
        return {'project': self.load(identifier), 'job': copy.deepcopy(job)}

    def run_ai(self, job, account):
        identifier = job['project']; path = self.project(identifier)
        workflow = self.workflow(identifier)
        try:
            with self.lock:
                if job['cancel']: return
            if job['action'] == 'ai_script':
                request = {k: workflow[k] for k in ('idea','language')}
                if workflow.get('series_context'): request['series'] = workflow['series_context']
                outline = self.ai.script(workflow['provider'], account, request)
                with self.lock:
                    if job['cancel']: return
                    editor = self.load(identifier)['editor']; editor['script'] = outline['script']
                    self.save(identifier, editor, job_id=job['id'])
                    workflow.update(status='awaiting_review', outline=outline, error='')
                    write_json(path / 'ai_workflow.json', workflow)
                    job.update(status='complete', stage='Script ready for review', progress=100)
            else:
                script = self.load(identifier)['editor']['script'].strip()
                options = {'series': workflow['series_context']} if workflow.get('series_context') else {}
                brief, parsed = self.ai.brief(workflow['provider'], account, workflow['outline'], script, **options)
                with self.lock:
                    if job['cancel']: return
                    editor = parsed['editor']; editor['name'] = self.registry[identifier]['name']
                    brief['project_name'] = editor['name']
                    self.save(identifier, editor, job_id=job['id'])
                    config = read_cache(path / 'config.json'); config['brief_sources'] = True
                    write_json(path / 'config.json', config); write_json(path / 'ai_brief.json', brief)
                    if workflow.get('series_id'):
                        self.series.record_approval(workflow['series_id'], identifier, editor['name'], workflow['idea'], script,
                                                    [game['title'] for game in editor['games']])
                    workflow.update(status='preparing_assets', warnings=parsed['warnings'], error='')
                    write_json(path / 'ai_workflow.json', workflow)
                    job.update(stage='Preparing gameplay and logos', progress=25)
                self.run(job, path, config, 0)
                return
        except Exception as error:
            # Do not echo arbitrary provider content or transport errors into logs.
            message = str(error) if isinstance(error, ValueError) else 'AI generation failed. Your project is saved; retry the step.'
            with self.lock:
                workflow.update(status='failed', failed_step=job['action'], error=message); write_json(path / 'ai_workflow.json', workflow)
                job.update(status='failed', stage='AI generation failed', error=message)
        finally:
            with self.lock:
                if job['cancel']:
                    job.update(status='cancelled', stage='Cancelled')
                    workflow.update(status='cancelled', error=''); write_json(path / 'ai_workflow.json', workflow)
                job['finished'] = time.time()
                self.persist_jobs()

    def maybe_auto_build(self, identifier):
        with self.lock:
            tutorial = pc_tips.state(self.project(identifier))
            if tutorial:
                if tutorial.get('status') not in ('awaiting_voice', 'awaiting_recording', 'awaiting_runner'): return
                if self.publisher.running or self.project_job(identifier): return
                if not tutorial.get('plan') or tutorial.get('stale'): return
                if tutorial.get('status') == 'awaiting_voice':
                    try: voiceover_path(self.project(identifier))
                    except FileNotFoundError: return
                elif not tutorial.get('recordings'): return
                self.start_pc_tips(identifier)
                return
            workflow = self.workflow(identifier)
            if workflow.get('status') != 'assets_ready' or not workflow.get('auto_build'): return
            if self.publisher.running or self.project_job(identifier): return
            selected_voice = voice_generation.project_state(self.project(identifier))
            if selected_voice['source'] == 'elevenlabs' and (not self.voice.snapshot()['configured'] or not selected_voice.get('voice_id') or not selected_voice.get('model_id')): return
            if selected_voice['source'] != 'elevenlabs':
                try: voiceover_path(self.project(identifier))
                except FileNotFoundError: return
            editor = self.load(identifier)['editor']
            if workflow.get('approved_script_hash') != fingerprint(editor['script'].strip()): return
            if workflow.get('source') == 'import' and workflow.get('prepared_inputs_hash') != self.asset_inputs_hash(editor): return
            self.start(identifier, 'build')

    def start(self, identifier, action, at=0):
        with self.lock:
            self.idle(identifier)
            if action == 'build' and pc_tips.state(self.project(identifier)):
                return self.start_pc_tips(identifier)['job']
            if action not in ('build', 'preview'):
                raise ValueError('Choose build or preview.')
            path = self.project(identifier)
            selected_voice = voice_generation.project_state(path)
            if selected_voice['source'] == 'elevenlabs' and (not selected_voice.get('generated_current') or selected_voice.get('stale')):
                if action == 'preview': raise ValueError('Generate your voiceover before rendering a preview frame.')
                return self.start_voice(identifier, build=True)['job']
            voiceover_path(path)
            config = read_cache(path / 'config.json')
            workflow = self.workflow(identifier)
            reference = self.reference_state(identifier)
            if reference and (reference.get('status') not in ('ready', 'complete', 'render_failed') or reference.get('stale')):
                raise ValueError('Analyze the current reference, script and voiceover before building.')
            if reference.get('workflow') == 'flow': flow_workflow.validate_build(path, reference, config)
            if workflow and workflow.get('source') != 'import' and (workflow.get('status') not in ('assets_ready','complete','rendering','failed','interrupted') or workflow.get('approved_script_hash') != fingerprint(self.load(identifier)['editor']['script'].strip())):
                raise ValueError('Approve the current script and prepare its assets before building.')
            if 'sections' in config:
                sections.validate_sections(config, path)
            elif not config.get('games') and not (path / 'games').is_dir():
                raise ValueError('Save your sections or game list first.')
            at = float(at)
            if not math.isfinite(at) or at < 0:
                raise ValueError('Choose a valid preview time.')
            job = {'id': uuid.uuid4().hex, 'project': identifier, 'action': action, 'status': 'queued',
                   'stage': 'Starting', 'progress': 0, 'logs': [], 'started': time.time(), 'cancel': False}
            self.job = job
            self.jobs[job['id']] = job
            if workflow and action == 'build':
                if workflow.get('source') == 'import':
                    editor = self.load(identifier)['editor']
                    workflow.update(approved_script=editor['script'].strip(), approved_script_hash=fingerprint(editor['script'].strip()),
                                    prepared_inputs_hash=self.asset_inputs_hash(editor))
                workflow.update(status='rendering', error=''); write_json(path / 'ai_workflow.json', workflow)
                write_json(self.data / 'ai' / 'job.json', job)
            self.enqueue(job, self.run, path, config, float(at))
            return copy.deepcopy(job)

    def run(self, job, path, config, at):
        commands = []
        action = job.get('next_action', job['action'])
        if action.startswith('pc_'):
            command = [sys.executable, '-u', str(ENGINE / 'pc_tips.py'), '--project', str(path), '--data', str(self.data)]
            if action == 'pc_draft': command.append('--draft')
            if action == 'pc_problem': command.append('--add-problem')
            commands.append(command)
        if job['action'].startswith('voice_') or job.get('generate_voice'):
            command = [sys.executable, '-u', str(ENGINE / 'voice_generation.py'), '--project', str(path), '--data', str(self.data)]
            if job.get('force_voice'): command.append('--force')
            commands.append(command)
        if action.startswith('reference_'):
            commands.append([sys.executable, '-u', str(ENGINE / 'reference_styles.py'), '--project', str(path), '--data', str(self.data),
                             *(['--scenes-only'] if action == 'reference_scenes' else [])])
        if action and not action.startswith('reference_') and 'sections' not in config and (path / 'games.txt').is_file() and (path / 'games.txt').read_text('utf-8').strip():
            command = [sys.executable, '-u', str(ENGINE / 'prepare_assets.py'), '--project', str(path)]
            if action == 'ai_prepare': command += ['--without-voiceover']
            commands.append(command)
        command = [sys.executable, '-u', str(ENGINE / 'build_video.py'), '--project', str(path), '--no-preview']
        if action == 'preview':
            command += ['--preview-only', '--preview-at', str(at)]
        if action and action not in ('ai_prepare', 'reference_plan', 'reference_scenes') and not action.startswith('pc_'): commands.append(command)
        try:
            for command in commands:
                with self.lock:
                    if job['cancel']:
                        break
                    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1', 'VIDEO_TURBO_RENDER_CONCURRENCY': str(max(1, min(4, (os.cpu_count() or 4) // self.max_parallel)))}
                    process = subprocess.Popen(command, cwd=ENGINE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                    text=True, encoding='utf-8', errors='replace', env=env,
                                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    self.processes[job['id']] = process
                for line in process.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    with self.lock:
                        job['logs'].append(line)
                        job['logs'] = job['logs'][-600:]
                        if 'Transcribing' in line: job['stage'] = 'Transcribing voiceover'
                        if 'Aligning' in line: job['stage'] = 'Aligning captions'
                        if '[PC TIPS]' in line: job['stage'] = line.split('[PC TIPS]', 1)[1].strip()
                        if '[VOICE]' in line: job['stage'] = line.split('[VOICE]', 1)[1].strip()
                        if '[REFERENCE]' in line: job['stage'] = line.split('[REFERENCE]', 1)[1].strip()
                        if '[PREPARE]' in line: job['stage'] = 'Preparing footage'
                        if 'Bundling' in line: job['stage'] = 'Preparing renderer'
                        for word, lower, span in [('Rendered', 10, 75), ('Encoded', 85, 12)]:
                            match = re.search(rf'{word}\s+(\d+)/(\d+)', line)
                            if match:
                                job['stage'] = 'Rendering frames' if word == 'Rendered' else 'Encoding video'
                                job['progress'] = lower + span * int(match[1]) / max(1, int(match[2]))
                        if 'Audio' in line or 'muxing' in line: job['stage'] = 'Finishing audio'
                code = process.wait()
                with self.lock:
                    self.processes.pop(job['id'], None)
                    if job['cancel']:
                        break
                if code != 0:
                    raise RuntimeError('Build step failed. See the job log for details.')
            with self.lock:
                job['status'] = 'cancelled' if job['cancel'] else 'complete'
                job['stage'] = 'Cancelled' if job['cancel'] else 'Ready'
                job['progress'] = 0 if job['cancel'] else 100
        except Exception as error:
            with self.lock:
                job['status'] = 'cancelled' if job['cancel'] else 'failed'
                job['error'] = str(error)
                job['stage'] = job['status'].capitalize()
        finally:
            with self.lock:
                self.processes.pop(job['id'], None)
                job['finished'] = time.time()
                if action.startswith('pc_'):
                    tutorial = pc_tips.state(path)
                    if job['status'] != 'complete':
                        pc_tips.save_state(path, tutorial, job['status'], error=tutorial.get('error') or job.get('error', ''))
                    elif tutorial.get('status') != 'complete':
                        job['stage'] = {'awaiting_review': 'Script ready for review', 'awaiting_voice': 'Waiting for your voiceover',
                            'awaiting_recording': 'Waiting for a screen recording', 'awaiting_runner': 'Waiting for the recording runner'}.get(tutorial.get('status'), 'Episode saved')
                reference = read_cache(path / 'reference_style.json')
                if reference and action:
                    if job['status'] == 'complete':
                        if action == 'reference_plan' and (reference.get('workflow') == 'flow' or reference.get('status') == 'script_review'): reference['error'] = ''
                        else: reference.update(status='ready' if action in ('reference_plan','reference_scenes','preview') else 'complete', error='')
                    else:
                        reference.update(status='render_failed' if action in ('build','preview') and reference.get('analysis') else job['status'], error=reference.get('error') or job.get('error',''))
                    write_json(path / 'reference_style.json', reference)
                workflow = self.workflow(job['project'])
                if workflow and action:
                    status = ('assets_ready' if action == 'ai_prepare' else 'complete') if job['status'] == 'complete' else job['status']
                    workflow.update(status=status, failed_step=action if job['status'] == 'failed' else '', error=job.get('error', ''))
                    write_json(path / 'ai_workflow.json', workflow)
                    write_json(self.data / 'ai' / 'job.json', job)
                self.persist_jobs()
            if job['action'] == 'ai_prepare' and job['status'] == 'complete': self.maybe_auto_build(job['project'])

    def cancel(self, job_id=''):
        with self.lock:
            job = next((row for row in self.all_jobs() if row.get('id') == job_id), None) if job_id else self.job
            if not job or job.get('status') not in ('queued', 'running'):
                raise ValueError('No running or queued job to cancel.')
            job['cancel'] = True
            queued = job['status'] == 'queued'
            job['status'] = 'cancelled' if queued else 'cancelling'
            if queued:
                self.pending = [item for item in self.pending if item[0] is not job]
                job.update(stage='Cancelled', finished=time.time())
                if job.get('style'): style_library.end_analysis(self.data, job['style'], 'cancelled')
            if queued and job.get('project') in self.registry:
                path = self.project(job['project'])
                filename = 'pc_tips.json' if job['action'].startswith('pc_') else 'reference_style.json' if job['action'].startswith('reference_') else 'ai_workflow.json'
                if (path / filename).is_file():
                    workflow = read_cache(path / filename); workflow.update(status='cancelled', error='')
                    write_json(path / filename, workflow)
            process = self.processes.get(job.get('id'))
            if process and process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, check=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    process.terminate()
            self.persist_jobs(); self._dispatch_jobs()
            return {'ok': True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    @property
    def studio(self): return self.server.studio

    def json_response(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def send_file(self, path):
        if not path.is_file():
            raise ValueError('File not found.')
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        request = self.headers.get('Range')
        if request:
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', request)
            if not match or int(match[1]) >= size:
                self.send_response(416); self.send_header('Content-Range', f'bytes */{size}'); self.end_headers(); return
            start = int(match[1]); end = min(end, int(match[2]) if match[2] else end); status = 206
            if end < start: raise ValueError('Invalid byte range.')
        self.send_response(status)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(max(0, end - start + 1)))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-store')
        if status == 206: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as source:
            source.seek(start); remaining = end - start + 1
            while remaining > 0:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk: break
                self.wfile.write(chunk); remaining -= len(chunk)

    def do_GET(self):
        try:
            parsed = urlparse(self.path); query = parse_qs(parsed.query)
            host = self.headers.get('Host', '')
            if host not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                self.json_response({'error': 'Use the localhost address.'}, 403); return
            if parsed.path == '/api/health':
                self.json_response({'app': 'video-turbo-studio', 'engine': str(ENGINE), 'features': ['ai-series', 'parallel-publishing', 'analytics', 'reference-styles', 'reference-codex', 'reference-models', 'elevenlabs-voice', 'google-flow-handoff', 'flow-portable-prompts', 'pc-tips', 'pc-chatgpt-sign-in', 'pc-auto-ideas', 'pc-visual-modes', 'pc-problem-first', 'pc-google-first', 'antigravity-brief-automation', 'antigravity-new-episodes', 'parallel-production', 'style-library', 'reference-claude', 'recreate-video', 'claude-scenes']})
            elif parsed.path == '/api/state':
                with self.studio.lock:
                    self.json_response({'token': self.studio.token, 'projects': self.studio.list_projects(),
                                        'presets': list(self.studio.presets), 'job': self.studio.job,
                                        'publishing_job': self.studio.publisher.active_job(), **self.studio.production_state()})
            elif parsed.path == '/api/pc-tips/settings':
                with self.studio.lock:
                    part = pc_tips.next_part(self.studio.data)
                    voice = self.studio.voice.snapshot()
                    self.json_response({**pc_tips.settings(self.studio.data), 'next_part': part, 'next_theme': pc_tips.theme(part),
                        'voice_ready': voice['configured'] and all(voice['defaults'].get(key) for key in ('voice_id', 'model_id'))})
            elif parsed.path == '/api/voice/settings':
                with self.studio.lock: self.json_response(self.studio.voice.snapshot())
            elif parsed.path == '/api/voice/catalog':
                self.json_response(self.studio.voice.catalog(refresh=query.get('refresh', ['0'])[0] == '1'))
            elif parsed.path == '/api/reference/flow/pack':
                with self.studio.lock:
                    path = self.studio.project(query['id'][0])
                    state = read_cache(path / 'reference_style.json')
                    flow_workflow.current_plan(path, state)
                    self.json_response({'text': flow_workflow.export_pack(state), 'filename': 'google-flow-production-pack.md'})
            elif parsed.path == '/api/reference/models':
                self.json_response(reference_styles.available_models(self.studio.data, query.get('provider', [''])[0]))
            elif parsed.path == '/api/reference/settings':
                self.json_response(reference_styles.settings(self.studio.data))
            elif parsed.path == '/api/ai/settings':
                with self.studio.lock: self.json_response(self.studio.ai.snapshot())
            elif parsed.path == '/api/ai/series':
                with self.studio.lock: self.json_response(self.studio.series.snapshot())
            elif parsed.path == '/api/ai/brief':
                with self.studio.lock:
                    brief = read_cache(self.studio.project(query['id'][0]) / 'ai_brief.json')
                    if not brief: raise ValueError('The generated JSON brief is not ready yet.')
                    self.json_response(brief)
            elif parsed.path == '/api/ai/workflow':
                with self.studio.lock: self.json_response(self.studio.workflow(query['id'][0]))
            elif parsed.path == '/api/project':
                with self.studio.lock: self.json_response(self.studio.load(query['id'][0]))
            elif parsed.path == '/api/brief/automation':
                self.json_response(antigravity_brief.settings(self.studio.data))
            elif parsed.path == '/api/jobs':
                self.json_response(self.studio.production_state())
            elif parsed.path == '/api/job':
                with self.studio.lock: self.json_response(self.studio.job)
            elif parsed.path == '/api/analytics':
                self.json_response(self.studio.analytics.snapshot())
            elif parsed.path == '/api/analytics/history':
                self.json_response(self.studio.analytics.history(query['video'][0], int(query.get('days', ['7'])[0])))
            elif parsed.path == '/api/publishing':
                self.json_response(self.studio.publisher.snapshot(query['id'][0]))
            elif parsed.path == '/api/publishing/job':
                self.json_response(self.studio.publisher.active_job())
            elif parsed.path == '/api/publishing/callback/youtube':
                self.studio.publisher.finish_oauth('youtube', query)
                payload = b'<!doctype html><meta charset="utf-8"><title>YouTube connected</title><p>YouTube is connected. Return to your Video Turbo Studio tab. You can close this tab.</p>'
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.end_headers()
                self.wfile.write(payload)
            elif parsed.path == '/media':
                project = self.studio.project(query['id'][0])
                relative = query['file'][0]
                path = (project / relative).resolve()
                if not path.is_relative_to(project) or path.suffix.lower() not in UPLOAD_EXTS:
                    raise ValueError('Invalid media path.')
                self.send_file(path)
            elif parsed.path == '/api/styles':
                self.json_response(self.studio.list_styles())
            elif parsed.path == '/api/styles/thumbnail':
                self.send_file(style_library.folder(self.studio.data, query['id'][0]) / 'thumb.jpg')
            elif parsed.path == '/caption-font.css':
                self.send_file(ENGINE / 'code/src/font.css')
            elif parsed.path.startswith('/library/'):
                name = unquote(parsed.path.split('/')[-1])
                aliases = {'gta_background.mp4': ['gta_background.mp4'], 'roblox.mp4': ['roblox.mp4', 'Roblox 1.mp4'], 'fortnite.mp4': ['fortnite.mp4', 'Fortnight.mp4']}
                if name not in aliases: raise ValueError('Unknown background.')
                source = next((ENGINE / alias for alias in aliases[name] if (ENGINE / alias).is_file()), None)
                if source is None: raise ValueError('Background not installed.')
                self.send_file(source)
            else:
                name = parsed.path.lstrip('/') or 'index.html'
                path = (WEB / name).resolve()
                if not path.is_relative_to(WEB.resolve()) or path.suffix not in ('.html', '.css', '.js', '.woff2'):
                    raise ValueError('Page not found.')
                self.send_file(path)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except (ValueError, KeyError, OSError) as error:
            self.json_response({'error': str(error)}, 400)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            expected = f'http://127.0.0.1:{self.server.server_port}'
            origin = self.headers.get('Origin')
            if self.headers.get('X-Studio-Token') != self.studio.token or (origin and origin not in (expected, f'http://localhost:{self.server.server_port}')):
                self.json_response({'error': 'Reload the studio page.'}, 403); return
            length = int(self.headers.get('Content-Length', '0'))
            query = parse_qs(parsed.query)
            if parsed.path == '/api/styles/upload':
                role = query.get('role', [''])[0]
                with self.studio.lock:
                    if query['id'][0] in self.studio.active_styles(): raise ValueError('Wait for this style analysis to finish.')
                    target = style_library.upload_target(self.studio.data, query['id'][0], role, Path(query['name'][0]).name)
                if not 0 < length <= 4 * 1024**3: raise ValueError('Use a supported media file, up to 4 GB.')
                target.parent.mkdir(parents=True, exist_ok=True)
                pending = target.with_name('.upload-' + uuid.uuid4().hex + target.suffix)
                try:
                    with pending.open('wb') as out:
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(1024 * 1024, remaining))
                            if not chunk: raise ValueError('Upload was interrupted.')
                            out.write(chunk); remaining -= len(chunk)
                    style_library.check_upload(role, pending)
                    with self.studio.lock:
                        pending.replace(target)
                        style = style_library.finish_upload(self.studio.data, query['id'][0], role, target)
                finally: pending.unlink(missing_ok=True)
                self.json_response({'style': style})
                return
            if parsed.path == '/api/upload':
                with self.studio.lock:
                    role = query.get('role', ['media'])[0]
                    upload_job = self.studio.project_job(query['id'][0])
                    preparation = upload_job and (upload_job.get('action') == 'ai_prepare' or upload_job.get('action', '').startswith('pc_')) and upload_job.get('status') == 'running'
                    if role != 'voice' or not preparation: self.studio.idle(query['id'][0])
                    elif self.studio.publisher.running: raise ValueError('Wait for the publishing upload to finish.')
                    project = self.studio.project(query['id'][0])
                    name = Path(query['name'][0]).name; ext = Path(name).suffix.lower()
                    if ext not in UPLOAD_EXTS or not 0 < length <= 4 * 1024**3:
                        raise ValueError('Use a supported media file, up to 4 GB.')
                    if role == 'voice':
                        if ext not in {'.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg'}: raise ValueError('Choose an audio file for the voiceover.')
                        target = project / ('voiceover' + ext)
                    elif role in ('music', 'background'):
                        if ext != ('.mp3' if role == 'music' else '.mp4'): raise ValueError('Use MP3 for music and MP4 for backgrounds.')
                        target = project / ('music.mp3' if role == 'music' else 'gta_background.mp4')
                    elif role == 'reference':
                        if ext not in sections.VIDEO_EXTS: raise ValueError('Choose a video reference.')
                        if not read_cache(project / 'reference_style.json'): raise ValueError('Create a Reference Styles project first.')
                        target = project / 'reference' / ('source-' + uuid.uuid4().hex[:12] + ext)
                    elif role == 'source':
                        if ext not in sections.VIDEO_EXTS: raise ValueError('Choose the source video (MP4, MOV, WebM or MKV).')
                        if not recreate.is_recreate(read_cache(project / 'reference_style.json')): raise ValueError('Create a Recreate project first.')
                        target = project / recreate.SOURCE_DIR / ('upload-' + uuid.uuid4().hex[:12] + ext)
                    elif role == 'flow_clip':
                        if ext not in sections.VIDEO_EXTS: raise ValueError('Choose a video downloaded from Flow.')
                        reference = read_cache(project / 'reference_style.json')
                        plan = flow_workflow.current_plan(project, reference)
                        if query.get('plan_hash', [''])[0] != reference['plan_hash']: raise ValueError('The storyboard changed. Reload before importing.')
                        scene = next((row for row in flow_workflow.scene_rows(plan) if row['id'] == query.get('scene', [''])[0]), None)
                        if not scene: raise ValueError('Choose a scene in the current Flow storyboard.')
                        target = project / 'media/flow' / (scene['id'] + '-' + uuid.uuid4().hex[:12] + ext)
                    elif role == 'pc_demo':
                        if ext not in sections.VIDEO_EXTS: raise ValueError('Choose a video screen recording.')
                        if not pc_tips.state(project): raise ValueError('Create a PC tutorial first.')
                        target = project / 'media/pc-tips' / ('uploaded-' + uuid.uuid4().hex[:12] + ext)
                    elif role == 'media':
                        if ext not in sections.VIDEO_EXTS | sections.IMAGE_EXTS: raise ValueError('Choose a clip or screenshot.')
                        target = project / 'media' / (uuid.uuid4().hex[:12] + '-' + re.sub(r'[^\w .()-]', '', Path(name).stem)[:60] + ext)
                    else: raise ValueError('Unknown upload type.')
                    if not target.resolve().is_relative_to(project): raise ValueError('Upload target points outside the project.')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    pending = target.with_name('.upload-' + uuid.uuid4().hex)
                    try:
                        with pending.open('wb') as out:
                            remaining = length
                            while remaining:
                                data = self.rfile.read(min(1024 * 1024, remaining))
                                if not data: raise ValueError('Upload was interrupted.')
                                out.write(data); remaining -= len(data)
                        if role == 'flow_clip': flow_workflow.clip_info(pending, scene['duration_seconds'])
                        if role == 'pc_demo': pc_tips.video_info(pending)
                        pending.replace(target)
                        if role == 'voice':
                            for suffix in ('.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg'):
                                old = project / ('voiceover' + suffix)
                                if old != target: old.unlink(missing_ok=True)
                    finally: pending.unlink(missing_ok=True)
                    if role == 'pc_demo':
                        tutorial = pc_tips.state(project)
                        pc_tips.save_state(project, tutorial, ('awaiting_review' if tutorial.get('status') == 'awaiting_review' else 'awaiting_recording') if tutorial.get('plan') else tutorial.get('status'), recordings=[{'file': target.relative_to(project).as_posix()}],
                                           recording_mode='upload', recording_report=[], quality_check={}, visual_source='recorded', visual_note='Uploaded real screen recording.')
                        if tutorial.get('status') != 'awaiting_review': self.studio.maybe_auto_build(query['id'][0])
                    if role == 'flow_clip':
                        flow_workflow.assign_clip(project, scene['id'], target.relative_to(project).as_posix(), plan_hash=reference['plan_hash'])
                    if role == 'reference':
                        reference = read_cache(project / 'reference_style.json')
                        reference.update(reference_file=target.relative_to(project).as_posix(), status='awaiting_inputs', error='')
                        write_json(project / 'reference_style.json', reference)
                    if role == 'source':
                        reference = read_cache(project / 'reference_style.json')
                        reference['recreate'].update(source_file=target.relative_to(project).as_posix(), source_url='', source_name=name[:200],
                                                     source_matches_style=style_library.matching_source(self.studio.data, target))
                        if reference.get('status') == 'script_review': reference.update(draft_script='')
                        reference.update(status='awaiting_inputs', error='')
                        write_json(project / 'reference_style.json', reference)
                    if role == 'voice':
                        voice_settings = read_cache(project / 'voiceover.json'); voice_settings['source'] = 'upload'
                        write_json(project / 'voiceover.json', voice_settings)
                        tutorial = pc_tips.state(project)
                        if tutorial: pc_tips.save_state(project, tutorial, needs_voice_upload=False)
                        if tutorial.get('plan') and tutorial.get('status') == 'complete':
                            pc_tips.save_state(project, tutorial, 'awaiting_voice')
                        self.studio.maybe_auto_build(query['id'][0])
                    self.json_response({'path': target.relative_to(project).as_posix(), 'project': self.studio.load(query['id'][0])})
                return
            if length > 2 * 1024**2: raise ValueError('Request too large.')
            data = json.loads(self.rfile.read(length))
            with self.studio.lock:
                if parsed.path == '/api/analytics/refresh':
                    result = self.studio.analytics.refresh()
                elif parsed.path == '/api/pc-tips/create':
                    result = self.studio.create_pc_tips(data.get('name', ''), data.get('idea', ''), data.get('recording_mode'),
                                                        data.get('auto_produce'), data.get('voice_source'), data.get('category', 'auto'))
                elif parsed.path == '/api/pc-tips/start':
                    result = self.studio.start_pc_tips(data['id'], data.get('recording_mode'), data.get('add_problem', False))
                elif parsed.path == '/api/pc-tips/check':
                    self.studio.idle(); result = pc_tips.pc_tips_ai.check_connection(self.studio.data)
                elif parsed.path == '/api/pc-tips/settings':
                    self.studio.idle(); result = pc_tips.configure(self.studio.data, data)
                elif parsed.path == '/api/create':
                    identifier = self.studio.create(data['name'], data.get('preset', 'blank')); result = self.studio.load(identifier)
                elif parsed.path == '/api/voice/settings':
                    self.studio.idle(); result = self.studio.voice.configure(data.get('api_key', ''), data.get('defaults'))
                elif parsed.path == '/api/voice/project':
                    result = self.studio.save_voice(data['id'], data['settings'])
                elif parsed.path == '/api/voice/start':
                    result = self.studio.start_voice(data['id'], data.get('build', False) is True, data.get('force', False) is True)
                elif parsed.path == '/api/reference/create':
                    result = self.studio.create_reference(data['name'], data['script'], data.get('instructions', ''), data.get('provider'), data.get('workflow', 'reference'), data.get('idea', ''),
                                                          data.get('styles') or None, data.get('style_mix'), data.get('recreate'), data.get('scene_mode', 'templates'))
                elif parsed.path == '/api/styles/create':
                    style = style_library.create(self.studio.data, data.get('name', ''), data.get('provider', 'antigravity'), data.get('model'))
                    result = {**self.studio.list_styles(), 'style': style}
                elif parsed.path == '/api/styles/analyze':
                    result = self.studio.start_style_analysis(data['id'], data.get('provider'), data.get('model'))
                elif parsed.path == '/api/styles/update':
                    if data['id'] in self.studio.active_styles(): raise ValueError('Wait for this style analysis to finish.')
                    style_library.update(self.studio.data, data['id'], data.get('name'), data.get('profile'))
                    result = self.studio.list_styles()
                elif parsed.path == '/api/styles/delete':
                    if data['id'] in self.studio.active_styles(): raise ValueError('Wait for this style analysis to finish.')
                    style_library.delete(self.studio.data, data['id'], data.get('confirmed') is True)
                    result = self.studio.list_styles()
                elif parsed.path == '/api/styles/from-project':
                    self.studio.idle(data['id'])
                    style = style_library.from_project(self.studio.data, self.studio.project(data['id']), data.get('name', ''))
                    result = {**self.studio.list_styles(), 'style': style}
                elif parsed.path == '/api/reference/recreate/approve':
                    result = self.studio.approve_recreate_script(data['id'], data['script'])
                elif parsed.path == '/api/reference/flow/approve':
                    result = self.studio.approve_flow_script(data['id'], data['script'])
                elif parsed.path == '/api/reference/flow/clip':
                    self.studio.idle(data['id'])
                    path = self.studio.project(data['id'])
                    flow_workflow.assign_clip(path, data['scene'], data['file'], data.get('offset_seconds', 0), data.get('plan_hash', ''))
                    result = self.studio.load(data['id'])
                elif parsed.path == '/api/reference/scene-mode':
                    result = self.studio.set_scene_mode(data['id'], data.get('mode'))
                elif parsed.path == '/api/reference/draw-scenes':
                    result = self.studio.draw_scenes(data['id'])
                elif parsed.path == '/api/reference/start':
                    result = self.studio.start_reference(data['id'], data.get('build', True) is True, data.get('provider'))
                elif parsed.path == '/api/reference/settings':
                    self.studio.idle(); result = reference_styles.configure(self.studio.data, data.get('cli_path',''), data.get('model'), data.get('provider','antigravity'))
                elif parsed.path == '/api/reference/check':
                    self.studio.idle(); result = reference_styles.check_connection(self.studio.data)
                elif parsed.path == '/api/ai/settings':
                    self.studio.idle(); result = self.studio.ai.configure(data['provider'], data.get('model',''), data.get('api_key',''))
                elif parsed.path == '/api/ai/series':
                    self.studio.idle(); result = self.studio.series.save(data.get('id',''), data['name'], data.get('platform','any'),
                                                                       data['instructions'], data.get('language','Egyptian Arabic'), data.get('reference_script',''))
                elif parsed.path == '/api/ai/create':
                    series_id = data.get('series_id','')
                    default_language = self.studio.series.get(series_id)['language'] if series_id else 'Egyptian Arabic'
                    result = self.studio.create_ai(data['name'], data.get('provider','gemini'), data['idea'], data.get('language',default_language), series_id)
                elif parsed.path == '/api/ai/approve': result = self.studio.approve_ai(data['id'], data['script'], data.get('approved',False))
                elif parsed.path == '/api/ai/retry': result = self.studio.retry_ai(data['id'])
                elif parsed.path == '/api/brief/automate':
                    result = self.studio.start_brief_automation(data.get('conversation_id'), data.get('request', ''), data.get('build', True), episode_mode=data.get('episode_mode', 'new'))
                elif parsed.path == '/api/brief/validate': result = parse_brief(data['brief'])
                elif parsed.path == '/api/brief/import': result = self.studio.import_brief(data['brief'])
                elif parsed.path == '/api/brief/prepare': result = self.studio.prepare_imported_assets(data['id'])
                elif parsed.path == '/api/import':
                    self.studio.idle(); path = Path(data['path']).resolve()
                    if not path.is_dir() or not (path / 'script.txt').is_file(): raise ValueError('Choose an existing video folder containing script.txt.')
                    result = self.studio.load(self.studio.register(path))
                elif parsed.path == '/api/project/rename': result = self.studio.rename_project(data['id'], data['name'])
                elif parsed.path == '/api/project/delete': result = self.studio.delete_project(data['id'], data.get('confirmed', False))
                elif parsed.path == '/api/save': result = self.studio.save(data['id'], data['editor'])
                elif parsed.path == '/api/start': result = self.studio.start(data['id'], data['action'], data.get('at', 0))
                elif parsed.path == '/api/production/settings': result = self.studio.configure_production(data.get('max_parallel'))
                elif parsed.path == '/api/cancel': result = self.studio.cancel(data.get('job_id', ''))
                elif parsed.path == '/api/publishing/save':
                    self.studio.idle(); result = self.studio.publisher.save_draft(data['id'], data['draft'])
                elif parsed.path == '/api/publishing/settings':
                    self.studio.idle(); result = self.studio.publisher.configure(data['platform'], data)
                elif parsed.path == '/api/publishing/connect':
                    self.studio.idle(); result = self.studio.publisher.connect(data['platform'], expected)
                elif parsed.path == '/api/publishing/oauth/finish':
                    self.studio.idle(); result = self.studio.publisher.finish_oauth(data['platform'], data['redirect_url'])
                elif parsed.path == '/api/publishing/token':
                    self.studio.idle(); result = self.studio.publisher.connect_token(data['platform'], data['access_token'], data.get('page_id', ''))
                elif parsed.path == '/api/publishing/instagram-page':
                    self.studio.idle(); result = self.studio.publisher.connect_instagram_page()
                elif parsed.path == '/api/publishing/check-account':
                    self.studio.idle(); result = self.studio.publisher.check_account(data['platform'])
                elif parsed.path == '/api/publishing/disconnect':
                    self.studio.idle(); result = self.studio.publisher.disconnect(data['platform'])
                elif parsed.path == '/api/publishing/start-many':
                    self.studio.idle(data['id'], allow_publishing=True)
                    result = self.studio.publisher.start_many(data['id'], data['platforms'], data['draft'],
                              data.get('reviewed', False), data.get('video_signature', ''))
                elif parsed.path == '/api/publishing/start':
                    self.studio.idle(data['id'], allow_publishing=True)
                    result = self.studio.publisher.start(data['id'], data['platform'], data['draft'],
                              data.get('reviewed', False), data.get('video_signature', ''))
                elif parsed.path == '/api/publishing/verify-youtube':
                    self.studio.idle(); result = self.studio.publisher.verify_youtube(data['id'], data['job_id'], data['url'])
                elif parsed.path == '/api/publishing/verify-instagram':
                    self.studio.idle(); result = self.studio.publisher.verify_instagram(data['id'], data['job_id'])
                elif parsed.path == '/api/publishing/verify-facebook':
                    self.studio.idle(); result = self.studio.publisher.verify_facebook(data['id'], data['job_id'])
                elif parsed.path == '/api/publishing/mark':
                    self.studio.idle(); result = self.studio.publisher.mark(data['id'], data['platform'], data.get('url', ''))
                elif parsed.path == '/api/preset':
                    self.studio.idle()
                    if not str(data['name']).strip(): raise ValueError('Name the preset.')
                    if data['name'] in ('blank', 'games', 'showcase', 'comparison'): raise ValueError('Choose another preset name.')
                    draft = copy.deepcopy(data['sections'])
                    if not isinstance(draft, list) or not draft: raise ValueError('Add sections to the preset.')
                    for section in draft:
                        for key in ('media', 'secondary_media', 'start_seconds', 'start_phrase'): section.pop(key, None)
                    self.studio.presets[data['name']] = draft
                    write_json(self.studio.data / 'studio_presets.json', self.studio.presets)
                    result = {'ok': True}
                else: raise ValueError('Unknown action.')
                if parsed.path in ('/api/create', '/api/reference/create', '/api/brief/import', '/api/ai/create') and data.get('voice_source') in ('upload', 'elevenlabs'):
                    project = result.get('project', result)
                    selected = {**voice_generation.DEFAULTS, **self.studio.voice.snapshot()['defaults'], 'source': data['voice_source']}
                    write_json(self.studio.project(project['id']) / 'voiceover.json', selected)
                    project['voice_settings'] = voice_generation.project_state(self.studio.project(project['id']))
            self.json_response(result)
        except (ValueError, KeyError, OSError, TypeError) as error:
            self.json_response({'error': str(error)}, 400)


class StudioServer(ThreadingHTTPServer):
    def server_bind(self):
        # Windows HTTPServer otherwise permits two listeners to share this port,
        # which can route UI requests to a stale backend with a different token.
        if os.name == 'nt':
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def running_studio(url, require_series=False, require_parallel=False, require_analytics=False, require_reference=False, require_codex=False, require_models=False, require_voice=False, require_flow=False, require_pc=False, require_brief=False, require_styles=False):
    """Identify this studio without changing its projects or interrupting a job."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + '/api/health', timeout=2) as response:
            data = json.loads(response.read(8192))
        return (isinstance(data, dict) and data.get('app') == 'video-turbo-studio'
                and isinstance(data.get('engine'), str) and Path(data['engine']).resolve() == ENGINE
                and (not require_pc or all(flag in data.get('features', []) for flag in ('pc-tips', 'pc-chatgpt-sign-in', 'pc-auto-ideas', 'pc-visual-modes', 'pc-problem-first', 'pc-google-first')))
                and (not require_brief or all(flag in data.get('features', []) for flag in ('antigravity-brief-automation', 'antigravity-new-episodes', 'parallel-production')))
                and (not require_styles or all(flag in data.get('features', []) for flag in ('style-library', 'reference-claude', 'recreate-video', 'claude-scenes')))
                and (not require_series or 'ai-series' in data.get('features', []))
                and (not require_parallel or 'parallel-publishing' in data.get('features', []))
                and (not require_analytics or 'analytics' in data.get('features', []))
                and (not require_reference or 'reference-styles' in data.get('features', []))
                and (not require_codex or 'reference-codex' in data.get('features', []))
                and (not require_models or 'reference-models' in data.get('features', []))
                and (not require_voice or 'elevenlabs-voice' in data.get('features', []))
                and (not require_flow or ('google-flow-handoff' in data.get('features', []) and 'flow-portable-prompts' in data.get('features', []))))
    except (OSError, ValueError, TypeError):
        return False


def running_studio_idle(url):
    """Do not load a second Studio against the same data while an older one is working."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + '/api/state', timeout=2) as response:
            data = json.loads(response.read(2 * 1024**2))
        return (isinstance(data, dict)
                and all(job.get('status') not in ('queued', 'running', 'cancelling') for job in data.get('jobs', [data.get('job') or {}]))
                and (data.get('publishing_job') or {}).get('status') not in ('running', 'cancelling'))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def main():
    parser = argparse.ArgumentParser(description='Start the local Video Turbo studio.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    port = args.port
    for attempt in range(2):
        url = f'http://127.0.0.1:{port}'
        try:
            server = StudioServer(('127.0.0.1', port), Handler)
            break
        except OSError as error:
            if running_studio(url, require_series=True, require_parallel=True, require_analytics=True, require_reference=True, require_codex=True, require_models=True, require_voice=True, require_flow=True, require_pc=True, require_brief=True, require_styles=True):
                print(f'Video Turbo Studio is already running: {url}', flush=True)
                if not args.no_browser: webbrowser.open(url)
                return 0
            if attempt == 0 and running_studio(url):
                if not running_studio_idle(url):
                    print(f'An older Studio is still working or could not be checked: {url}. Finish its jobs and close its server before relaunching.', file=sys.stderr)
                    return 1
                port = port + 1 if port < 65535 else 0
                print(f'An older Studio is running at {url}. Starting the updated Studio on another local port.', flush=True)
                continue
            print(f'Cannot start the studio on port {port}: {error}. Use the already running studio, or choose another --port.', file=sys.stderr)
            return 1
    server.studio = Studio()
    server.studio.analytics.start_auto()
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Video Turbo Studio: {url}', flush=True)
    if not args.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.studio.analytics.close()
        server.studio.shutdown_jobs()
        server.server_close()


if __name__ == '__main__': sys.exit(main())
