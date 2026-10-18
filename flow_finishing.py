"""Deterministic, quiet sound design for the local Flow finishing pass."""
from array import array
import math
from pathlib import Path
import random
import shutil
import sys
import wave
from flow_style import finishing_style

from pipeline_common import file_digest, file_signature, fingerprint, read_cache, write_json

SAMPLE_RATE = 48000


def sound_cues(timeline):
    fps = timeline['fps']
    cues = []
    for index, block in enumerate(timeline['blocks']):
        style=finishing_style(block.get('flowFinishing'))
        if style['sound']=='none': continue
        start = block['startFrame']
        end = start + block['durationFrames']
        if index and style['transition']!='cut':
            cues.append({'kind': 'whoosh', 'seconds': max(0, start / fps - .12)})
        if style['headlines'] and block.get('flowText'):
            cues.append({'kind': 'tap', 'seconds': min(start + .3 * fps, end - 1) / fps})
            continue
        words = [w for w in timeline['words'] if w['endFrame'] > start and w['startFrame'] < end]
        # One soft text accent per scene; avoid clicking on every spoken word.
        groups = words[::4]
        target = next((w for w in groups if w['startFrame'] >= start + .4 * fps), None) if index else (groups[0] if groups else None)
        if target:
            cues.append({'kind': 'tap', 'seconds': max(start, target['startFrame']) / fps})
    return cues


def write_sound_track(path, duration, cues):
    length = round(duration * SAMPLE_RATE)
    samples = array('f', [0]) * (length * 2)
    for index, cue in enumerate(cues):
        whoosh = cue['kind'] == 'whoosh'
        count = round((.34 if whoosh else .17) * SAMPLE_RATE)
        start = round(cue['seconds'] * SAMPLE_RATE)
        noise = random.Random(9100 + index)
        low = 0.
        for i in range(count):
            at = start + i
            if at >= length:
                break
            p = i / count
            t = i / SAMPLE_RATE
            low = .91 * low + .09 * noise.uniform(-1, 1)
            if whoosh:
                value = low * math.sin(math.pi * p) ** 2 * .15
                pan = .3 + .4 * p
            else:
                attack = min(1, t / .004)
                value = attack * math.exp(-t * 32) * (
                    math.sin(2 * math.pi * (740 * t - 460 * t * t)) * .021 + low * .035)
                pan = .5
            samples[at * 2] += value * math.sqrt(1 - pan)
            samples[at * 2 + 1] += value * math.sqrt(pan)
    pcm = array('h', (round(max(-1, min(1, value)) * 32767) for value in samples))
    if sys.byteorder != 'little':
        pcm.byteswap()
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm.tobytes())


def prepare_flow_audio(timeline, voice, output, public):
    blocks = timeline.get('blocks', [])
    if not blocks or not all(b.get('layout') == 'flow_clip' and b.get('flowFinish', True) for b in blocks):
        return None
    output, public, voice = Path(output), Path(public), Path(voice)
    output.mkdir(parents=True, exist_ok=True)
    cues = sound_cues(timeline)
    target = output / 'flow_sfx.wav'
    manifest = output / 'flow_sfx_manifest.json'
    key = fingerprint({'version': 1, 'generator': file_digest(Path(__file__)), 'duration': timeline['totalDuration'], 'cues': cues})
    old = read_cache(manifest)
    if old.get('key') != key or not target.is_file() or old.get('output') != file_signature(target):
        write_sound_track(target, timeline['totalDuration'], cues)
        write_json(manifest, {'key': key, 'cues': cues, 'output': file_signature(target)})
    audio_dir = public / 'flow-audio'
    audio_dir.mkdir(parents=True, exist_ok=True)
    for source, name in ((target, 'effects.wav'), (voice, 'voiceover' + voice.suffix)):
        destination = audio_dir / name
        if not destination.is_file() or source.stat().st_mtime_ns != destination.stat().st_mtime_ns or source.stat().st_size != destination.stat().st_size:
            shutil.copy2(source, destination)
    timeline['flowAudio'] = {'voice': 'flow-audio/voiceover' + voice.suffix, 'effects': 'flow-audio/effects.wav'}
    return target
