"""Saved writing instructions and approved episode history, kept separately per series."""
from __future__ import annotations
import copy
import time
import uuid
from pathlib import Path
from pipeline_common import read_cache, write_json


class SeriesLibrary:
    def __init__(self, data):
        self.path = Path(data) / 'ai' / 'series.json'
        self.series = read_cache(self.path)

    def get(self, identifier):
        if not isinstance(identifier, str) or identifier not in self.series:
            raise ValueError('Series not found. Choose a saved series or create a new one.')
        return copy.deepcopy(self.series[identifier])

    def snapshot(self):
        return {'series': [copy.deepcopy(value) for value in self.series.values()]}

    def save(self, identifier, name, platform, instructions, language, reference_script=''):
        if not isinstance(identifier, str): raise ValueError('Choose a saved series or create a new one.')
        for value, limit, label in ((name, 80, 'Series name'), (instructions, 10000, 'Series instructions'), (language, 100, 'Default script language')):
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
                raise ValueError(f'{label} must contain 1 to {limit:,} characters.')
        if not isinstance(platform, str) or platform not in ('pc', 'mobile', 'any'): raise ValueError('Choose PC games, mobile games, or any platform.')
        if not isinstance(reference_script, str) or len(reference_script) > 100000:
            raise ValueError('The reference script must be text, up to 100,000 characters.')
        current = self.get(identifier) if identifier else {'id': uuid.uuid4().hex, 'episodes': []}
        current.update(name=name.strip(), platform=platform, instructions=instructions.strip(), language=language.strip(), reference_script=reference_script.strip())
        saved = {**self.series, current['id']: current}
        write_json(self.path, saved)
        self.series = saved
        return self.snapshot()

    def context(self, identifier):
        current = self.get(identifier)
        covered = list(dict.fromkeys(game for episode in current['episodes'] for game in episode['games']))
        return {key: current[key] for key in ('id', 'name', 'platform', 'instructions', 'language', 'reference_script')} | {
            'approved_episode_count': len(current['episodes']), 'covered_games': covered,
            'recent_episodes': [{key: episode[key] for key in ('name', 'idea', 'games')} for episode in current['episodes'][-10:]]}

    def record_approval(self, identifier, project, name, idea, script, games):
        current = self.get(identifier)
        episode = {'project': project, 'name': name, 'idea': idea, 'games': list(dict.fromkeys(games)), 'approved_at': time.time()}
        episodes = current['episodes']
        existing = next((index for index, value in enumerate(episodes) if value['project'] == project), None)
        if existing is None: episodes.append(episode)
        else: episodes[existing] = episode
        current['reference_script'] = script
        saved = {**self.series, identifier: current}
        write_json(self.path, saved)
        self.series = saved
