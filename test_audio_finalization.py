"""Regression coverage for final audio processing with Unicode project paths."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_video as build
from pipeline_common import file_signature


class AudioFinalizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='video-turbo-audio-')
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / '\u0645\u0634\u0631\u0648\u0639_\u0641\u064a\u062f\u064a\u0648_\u0639\u0631\u0628\u064a'
        self.output = self.project / 'output'
        self.output.mkdir(parents=True)
        for name, value in [('PROJECT_PATH', self.project), ('OUTPUT_DIR', self.output)]:
            replacement = patch.object(build, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        replacement = patch.object(build, 'log')
        replacement.start()
        self.addCleanup(replacement.stop)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                         'FFmpeg and ffprobe are required for the audio smoke test.')
    def test_real_normalization_and_mux_in_arabic_project_directory(self):
        duration = 1.2
        voice = self.project / 'voiceover.wav'
        raw_video = self.output / 'rendered_raw.mp4'
        final_video = self.output / 'final.mp4'
        subprocess.run([
            'ffmpeg', '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i',
            f'sine=frequency=997:sample_rate=48000:duration={duration}',
            '-c:a', 'pcm_s16le', str(voice),
        ], capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
        subprocess.run([
            'ffmpeg', '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i',
            f'color=c=black:s=160x90:r=30:d={duration}',
            '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(raw_video),
        ], capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)

        real_run = subprocess.run

        def quiet_run(*args, **kwargs):
            # Keep measurement capture exactly as production configures it.
            if not kwargs.get('capture_output'):
                kwargs.setdefault('stdout', subprocess.DEVNULL)
                kwargs.setdefault('stderr', subprocess.DEVNULL)
            return real_run(*args, **kwargs)

        with patch.object(build.subprocess, 'run', side_effect=quiet_run) as commands:
            build.process_audio_and_mux(raw_video, final_video, duration, voice)
        measurement = next(call for call in commands.call_args_list
                           if call.kwargs.get('capture_output'))
        self.assertEqual(measurement.kwargs.get('encoding'), 'utf-8')
        self.assertEqual(measurement.kwargs.get('errors'), 'replace')
        self.assertGreater(final_video.stat().st_size, 0)

        probe = subprocess.run([
            'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(final_video),
        ], capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
        media = json.loads(probe.stdout)
        self.assertEqual({stream['codec_type'] for stream in media['streams']}, {'audio', 'video'})
        audio = next(stream for stream in media['streams'] if stream['codec_type'] == 'audio')
        video = next(stream for stream in media['streams'] if stream['codec_type'] == 'video')
        self.assertEqual(audio['codec_name'], 'aac')
        self.assertEqual(audio['sample_rate'], '48000')
        self.assertEqual(video['codec_name'], 'h264')
        self.assertAlmostEqual(float(media['format']['duration']), duration, delta=0.08)
        self.assertAlmostEqual(float(audio['duration']), duration, delta=0.08)
        self.assertAlmostEqual(float(video['duration']), duration, delta=0.08)
        manifest = json.loads((self.output / 'audio_manifest.json').read_text(encoding='utf-8'))
        self.assertTrue(manifest['key'])
        self.assertEqual(manifest['output'], file_signature(self.output / 'normalized_audio.aac'))
        self.assertFalse((self.output / 'final_pending.mp4').exists())

    def test_missing_loudness_report_raises_clear_runtime_error(self):
        voice = self.project / 'voiceover.wav'
        voice.write_bytes(b'voiceover fixture')
        result = subprocess.CompletedProcess(['ffmpeg'], 0, stdout='', stderr=None)
        with patch.object(build.subprocess, 'run', return_value=result) as command:
            with self.assertRaisesRegex(RuntimeError, 'FFmpeg did not report loudness measurements'):
                build.process_audio_and_mux(self.output / 'rendered_raw.mp4',
                                            self.output / 'final.mp4', 1.2, voice)
        command.assert_called_once()
        self.assertFalse((self.output / 'audio_manifest.json').exists())
        self.assertFalse((self.output / 'final.mp4').exists())


if __name__ == '__main__':
    unittest.main()