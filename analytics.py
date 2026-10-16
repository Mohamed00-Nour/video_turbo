"""Read-only platform view counts and local, timestamped analytics snapshots."""
from __future__ import annotations

import copy
import math
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import requests
from pipeline_common import fingerprint

PLATFORMS = ('youtube', 'instagram', 'facebook_page')
REFRESH_INTERVAL = 15 * 60
MANUAL_COOLDOWN = 60


class AnalyticsError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def count(value):
    if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)):
        raise AnalyticsError('unavailable', 'The platform did not return a valid view count.')
    result = int(value)
    if result > 9007199254740991:
        raise AnalyticsError('unavailable', 'The platform returned an unsupported view count.')
    return result


def get_json(session, url, token, params, platform):
    try:
        response = session.get(url, headers={'Authorization': 'Bearer ' + token}, params=params, timeout=(10, 30))
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise AnalyticsError('unavailable', 'Statistics could not be reached. Your last saved count is retained.') from None
    error = payload.get('error') if isinstance(payload, dict) else None
    if response.status_code == 401 or isinstance(error, dict) and error.get('code') == 190:
        raise AnalyticsError('reconnect', 'Reconnect the account with a fresh access token to refresh views.')
    details = error.get('errors') if isinstance(error, dict) else None
    reasons = [row.get('reason') for row in details if isinstance(row, dict)] if isinstance(details, list) else []
    if response.status_code == 429 or isinstance(error, dict) and error.get('code') in (4, 17, 32, 613) or any('quota' in str(reason).lower() for reason in reasons):
        raise AnalyticsError('rate_limited', 'The platform rate limit was reached. Saved counts remain available; try later.')
    if response.status_code == 403 or isinstance(error, dict) and error.get('code') in (10, 200):
        permission = 'instagram_manage_insights and pages_read_engagement' if platform == 'instagram' else 'read_insights and pages_read_engagement' if platform == 'facebook_page' else 'YouTube read access'
        raise AnalyticsError('permission', 'Analytics permission is needed: ' + permission + '. Reconnect after granting access.')
    if response.status_code >= 400 or error or not isinstance(payload, dict):
        raise AnalyticsError('unavailable', 'View statistics are unavailable for this post or its current permissions.')
    return payload


class Analytics:
    def __init__(self, data, publisher, project_list, session_factory=requests.Session, clock=time.time):
        self.publisher, self.project_list = publisher, project_list
        self.session_factory, self.clock = session_factory, clock
        self.path = Path(data) / 'analytics.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock, self.db_lock = threading.RLock(), threading.RLock()
        self.stop_event = threading.Event()
        self.scheduler = None
        self.completed_keys = set()
        self.job = {'status': 'idle', 'completed': 0, 'total': 0, 'successful': 0}
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS stats (
                    post_key TEXT PRIMARY KEY, views INTEGER, metric TEXT,
                    updated REAL, checked REAL, status TEXT, message TEXT);
                CREATE TABLE IF NOT EXISTS samples (
                    post_key TEXT, recorded INTEGER, views INTEGER, metric TEXT,
                    PRIMARY KEY (post_key, recorded));
                CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value REAL);
            ''')
            row = db.execute("SELECT value FROM metadata WHERE name='last_refresh'").fetchone()
            self.last_refresh = row['value'] if row else 0

    @contextmanager
    def _db(self):
        with self.db_lock:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            finally:
                db.close()

    def catalog(self):
        posts, seen = [], set()
        for project in self.project_list():
            try:
                with self.publisher.lock:
                    history = copy.deepcopy(self.publisher._record(project['id']).get('history', []))
            except (ValueError, OSError):
                continue
            for entry in history:
                platform, remote = entry.get('platform'), str(entry.get('remote_id') or '')
                if platform not in PLATFORMS or entry.get('status') not in ('complete', 'manual'):
                    continue
                identity = (platform, remote) if remote else (platform, entry['id'])
                if identity in seen:
                    continue
                seen.add(identity)
                video_key = fingerprint({'project': project['id'], 'version': entry.get('video_signature') or entry['id']})
                posts.append({'key': fingerprint(identity), 'video': video_key, 'project': project['id'],
                    'project_name': project['name'], 'title': entry.get('title') or project['name'],
                    'platform': platform, 'remote_id': remote, 'destination_id': entry.get('destination_id', ''),
                    'account': entry.get('destination_name', ''), 'url': entry.get('url', ''),
                    'published': entry.get('created') or entry.get('finished') or 0,
                    'connection_type': entry.get('instagram_connection_type', '')})
        return posts

    def snapshot(self):
        posts = self.catalog()
        with self._db() as db:
            saved = {row['post_key']: dict(row) for row in db.execute('SELECT * FROM stats')}
        for post in posts:
            post.update(saved.get(post['key'], {'views': None, 'metric': '', 'updated': None,
                'checked': None, 'status': 'pending', 'message': 'Waiting for the first statistics refresh.'}))
        videos = {}
        for post in posts:
            video = videos.setdefault(post['video'], {'id': post['video'], 'project': post['project'],
                'title': post['title'], 'project_name': post['project_name'], 'published': post['published'], 'posts': []})
            video['posts'].append(post)
            video['published'] = min(video['published'], post['published'])
        with self.lock:
            job, last_refresh = copy.deepcopy(self.job), self.last_refresh
        return {'videos': sorted(videos.values(), key=lambda video: video['published'], reverse=True),
            'job': job, 'last_refresh': last_refresh or None, 'refresh_interval': REFRESH_INTERVAL,
            'next_manual_refresh': last_refresh + MANUAL_COOLDOWN if last_refresh else 0}

    def refresh(self):
        with self.lock:
            if self.job['status'] == 'running':
                return {'started': False, 'message': 'Statistics are already refreshing.', 'job': copy.deepcopy(self.job)}
            remaining = self.last_refresh + MANUAL_COOLDOWN - self.clock()
            if remaining > 0:
                return {'started': False, 'message': 'Refresh is available in ' + str(math.ceil(remaining)) + ' seconds.', 'job': copy.deepcopy(self.job)}
            self.last_refresh = self.clock()
            self.job = {'status': 'running', 'started': self.last_refresh, 'completed': 0, 'total': 0, 'successful': 0}
            with self._db() as db:
                db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_refresh', ?)", (self.last_refresh,))
            threading.Thread(target=self._run, daemon=True).start()
            return {'started': True, 'job': copy.deepcopy(self.job)}

    def _save(self, post, result):
        now = self.clock()
        with self._db() as db:
            old = db.execute('SELECT * FROM stats WHERE post_key=?', (post['key'],)).fetchone()
            if result.get('status') == 'ready':
                values = (result['views'], result['metric'], now)
                db.execute('INSERT OR REPLACE INTO samples VALUES (?,?,?,?)',
                           (post['key'], int(now), result['views'], result['metric']))
            else:
                values = (old['views'], old['metric'], old['updated']) if old else (None, '', None)
            db.execute('INSERT OR REPLACE INTO stats VALUES (?,?,?,?,?,?,?)',
                (post['key'], *values, now, result['status'], result.get('message', '')))
        with self.lock:
            if post['key'] not in self.completed_keys:
                self.completed_keys.add(post['key'])
                self.job['completed'] += 1
                self.job['successful'] += result.get('status') == 'ready'

    def _account(self, platform):
        try:
            with self.publisher.lock:
                return self.publisher._access_account(platform)
        except (ValueError, OSError):
            raise AnalyticsError('reconnect', 'Reconnect this account in Publishing to refresh its view statistics.') from None

    def _run_group(self, platform, posts):
        valid = []
        for post in posts:
            pattern = r'[A-Za-z0-9_-]{1,128}' if platform == 'youtube' else r'\d{1,80}'
            if not re.fullmatch(pattern, post['remote_id']):
                self._save(post, {'status': 'unavailable', 'message': 'A published post ID is needed before statistics can be read.'})
            else:
                valid.append(post)
        if not valid:
            return
        try:
            account = self._account(platform)
        except AnalyticsError as error:
            for post in valid: self._save(post, {'status': error.status, 'message': str(error)})
            return
        destination = account.get('page_id') if platform == 'facebook_page' else account.get('user_id') if platform == 'instagram' else account.get('channel_id', '')
        matching = []
        for post in valid:
            if post['destination_id'] and post['destination_id'] != destination:
                self._save(post, {'status': 'reconnect', 'message': 'Connect the account originally used for this upload to refresh its views.'})
            else:
                matching.append(post)
        with self.session_factory() as session:
            if platform == 'youtube':
                for offset in range(0, len(matching), 50):
                    batch = matching[offset:offset + 50]
                    try:
                        data = get_json(session, 'https://www.googleapis.com/youtube/v3/videos', account['access_token'],
                            {'part': 'statistics', 'id': ','.join(post['remote_id'] for post in batch)}, platform)
                        rows = data.get('items')
                        items = {row['id']: row for row in rows if isinstance(row, dict) and row.get('id')} if isinstance(rows, list) else {}
                    except AnalyticsError as error:
                        for post in batch: self._save(post, {'status': error.status, 'message': str(error)})
                        continue
                    for post in batch:
                        try:
                            statistics = items.get(post['remote_id'], {}).get('statistics')
                            value = count(statistics.get('viewCount') if isinstance(statistics, dict) else None)
                            self._save(post, {'status': 'ready', 'views': value, 'metric': 'viewCount'})
                        except AnalyticsError as error:
                            self._save(post, {'status': error.status, 'message': 'Views are unavailable; this video may be private, removed or inaccessible.'})
                return
            for post in matching:
                try:
                    if platform == 'instagram':
                        host = 'graph.facebook.com' if account.get('connection_type') == 'facebook' else 'graph.instagram.com'
                        data = get_json(session, 'https://' + host + '/v26.0/' + post['remote_id'] + '/insights',
                                        account['access_token'], {'metric': 'views'}, platform)
                        rows = data.get('data')
                        metric = next((row for row in rows if isinstance(row, dict) and row.get('name') == 'views'), {}) if isinstance(rows, list) else {}
                        values, total = metric.get('values'), metric.get('total_value')
                        value = count(values[0].get('value') if isinstance(values, list) and values and isinstance(values[0], dict)
                                      else total.get('value') if isinstance(total, dict) else None)
                    else:
                        data = get_json(session, 'https://graph.facebook.com/v26.0/' + post['remote_id'],
                            account['access_token'], {'fields': 'id,from,views'}, platform)
                        owner = data.get('from')
                        if str(data.get('id')) != post['remote_id'] or not isinstance(owner, dict) or str(owner.get('id')) != account.get('page_id'):
                            raise AnalyticsError('unavailable', 'The connected Page did not confirm ownership of this video.')
                        value = count(data.get('views'))
                    self._save(post, {'status': 'ready', 'views': value, 'metric': 'views'})
                except AnalyticsError as error:
                    self._save(post, {'status': error.status, 'message': str(error)})

    def _run(self):
        try:
            posts = self.catalog()
            with self.lock:
                self.completed_keys.clear()
                self.job.update(total=len(posts), completed=0, successful=0)
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [(pool.submit(self._run_group, platform, group), group)
                    for platform in PLATFORMS if (group := [post for post in posts if post['platform'] == platform])]
                for future, group in futures:
                    try:
                        future.result()
                    except Exception:
                        for post in group:
                            if post['key'] not in self.completed_keys:
                                self._save(post, {'status': 'unavailable', 'message': 'Statistics refresh was interrupted. Your saved count is retained.'})
            with self.lock: self.job.update(status='complete', finished=self.clock())
        except Exception:
            with self.lock: self.job.update(status='failed', finished=self.clock(), message='Statistics could not be refreshed. Try again.')

    def history(self, video_key, days=7):
        if days not in (7, 30): raise ValueError('Choose a 7-day or 30-day view.')
        posts = [post for post in self.catalog() if post['video'] == video_key]
        if not posts: raise ValueError('Choose an uploaded video from the dashboard.')
        start, end, series = self.clock() - days * 86400, self.clock(), []
        with self._db() as db:
            for post in posts:
                stat = db.execute('SELECT metric FROM stats WHERE post_key=?', (post['key'],)).fetchone()
                metric = stat['metric'] if stat else ''
                baseline = db.execute('SELECT recorded,views FROM samples WHERE post_key=? AND metric=? AND recorded<? ORDER BY recorded DESC LIMIT 1', (post['key'], metric, start)).fetchone()
                values = list(db.execute('SELECT recorded,views FROM samples WHERE post_key=? AND metric=? AND recorded>=? ORDER BY recorded', (post['key'], metric, start)))
                if baseline: values.insert(0, baseline)
                step = max(1, math.ceil(len(values) / 239))
                points = [dict(row) for row in values[::step]]
                if values and (not points or points[-1]['recorded'] != values[-1]['recorded']): points.append(dict(values[-1]))
                series.append({'platform': post['platform'], 'account': post['account'], 'post_key': post['key'],
                    'metric': metric, 'points': points, 'change': values[-1]['views'] - values[0]['views'] if len(values) > 1 else None})
        return {'video': video_key, 'days': days, 'start': start, 'end': end, 'series': series}

    def start_auto(self):
        if self.scheduler and self.scheduler.is_alive(): return
        def loop():
            while not self.stop_event.is_set():
                self.refresh()
                self.stop_event.wait(REFRESH_INTERVAL)
        self.scheduler = threading.Thread(target=loop, daemon=True)
        self.scheduler.start()

    def close(self):
        self.stop_event.set()
