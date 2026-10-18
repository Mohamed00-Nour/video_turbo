"""Checks for narration-safe Flow sound design and the actual final audio mix."""
from array import array
import copy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

import build_video as build
import flow_finishing as finish
from flow_style import finishing_style, display_font_source


def sample_timeline():
    return {'fps':30, 'totalFrames':60, 'totalDuration':2,
        'blocks':[{'flowFinishing':{'sound':'subtle','transition':'blur'},'layout':'flow_clip','startFrame':0,'durationFrames':30},
                  {'flowFinishing':{'sound':'subtle','transition':'blur'},'layout':'flow_clip','startFrame':30,'durationFrames':30}],
        'words':[{'word':'word','startFrame':i,'endFrame':i+6} for i in range(0,60,6)]}


class FlowFinishingTests(unittest.TestCase):
    def test_a_fresh_clone_can_render_serif_text_without_a_local_font(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            fallback=root/'studio/ui-fonts/Amiri-Bold.ttf'
            fallback.parent.mkdir(parents=True)
            fallback.write_bytes(b'bundled font fixture')
            with patch.dict('os.environ', {'WINDIR':str(root/'not-installed')}):
                self.assertEqual(display_font_source(root),fallback)
                local=root/'fonts/Bodoni-Italic.ttf'
                local.parent.mkdir()
                local.write_bytes(b'local font fixture')
                self.assertEqual(display_font_source(root),local)

    def test_an_unanalysed_reference_does_not_inherit_the_current_preset(self):
        style=finishing_style()
        self.assertFalse(style['headlines'])
        self.assertFalse(style['show_grid'])
        self.assertEqual(style['depth_motif'], 'none')
        self.assertEqual(style['headline_font'], 'sans')
        self.assertEqual(style['sound'], 'none')
        timeline=sample_timeline()
        for block in timeline['blocks']: block.pop('flowFinishing')
        self.assertEqual(finish.sound_cues(timeline), [])

    def test_reference_profile_controls_sound_independently_of_caption_words(self):
        timeline=sample_timeline()
        for block in timeline['blocks']:
            block['flowFinishing']={'headlines':True, 'headline_font':'mono', 'sound':'none', 'depth_motif':'none'}
            block['flowText']={'headline':'A different reference'}
        self.assertEqual(finish.sound_cues(timeline), [])
        with self.assertRaises(ValueError): finishing_style({'depth_opacity':float('nan')})

    def test_audio_is_stereo_exact_length_deterministic_and_optional(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            voice=root/'voice.wav'
            voice.write_bytes(b'voice fixture')
            timeline=sample_timeline()
            target=finish.prepare_flow_audio(timeline,voice,root/'output',root/'public')
            first=target.read_bytes()
            with wave.open(str(target),'rb') as audio:
                self.assertEqual((audio.getnchannels(),audio.getframerate(),audio.getnframes()),(2,48000,96000))
            self.assertEqual(first,(root/'public/flow-audio/effects.wav').read_bytes())
            target.unlink()
            finish.prepare_flow_audio(timeline,voice,root/'output',root/'public')
            self.assertEqual(first,target.read_bytes())
            self.assertTrue(any(first[44:]))
            for block in timeline['blocks']: block['flowFinish']=False
            self.assertIsNone(finish.prepare_flow_audio(timeline,voice,root/'disabled',root/'public'))
            self.assertFalse((root/'disabled').exists())
            self.assertIsNone(finish.prepare_flow_audio({'words':[]},voice,root/'other',root/'public'))

    def test_cues_stay_inside_recording_without_moving_timestamps(self):
        timeline=sample_timeline()
        before=copy.deepcopy(timeline)
        cues=finish.sound_cues(timeline)
        self.assertEqual(timeline,before)
        self.assertEqual(sum(c['kind']=='whoosh' for c in cues),1)
        self.assertTrue(all(0<=c['seconds']<2 for c in cues))
        self.assertLessEqual(sum(c['kind']=='tap' for c in cues),len(timeline['blocks']))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_final_mix_includes_effects_and_invalidates_audio_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            output=root/'output'; output.mkdir()
            voice=root/'voice.wav'; raw=output/'raw.mp4'; final=output/'final.mp4'
            def run(args):
                return subprocess.run(args,capture_output=True,check=True)
            run(['ffmpeg','-nostdin','-y','-v','error','-f','lavfi','-i',
                 'sine=frequency=997:sample_rate=48000:duration=0.25','-af','apad=whole_dur=1.2',str(voice)])
            run(['ffmpeg','-nostdin','-y','-v','error','-f','lavfi','-i',
                 'color=c=black:s=160x90:r=30:d=1.2','-an','-c:v','libx264','-pix_fmt','yuv420p',str(raw)])
            effects=output/'effects.wav'
            finish.write_sound_track(effects,1.2,[{'kind':'whoosh','seconds':.7}])
            def late_energy():
                pcm=run(['ffmpeg','-v','error','-i',str(final),'-ss','0.8','-t','0.15','-f','s16le','-ac','1','-']).stdout
                samples=array('h'); samples.frombytes(pcm)
                return sum(abs(s) for s in samples)/len(samples)
            real_run=subprocess.run
            def quiet(*args,**kwargs):
                if not kwargs.get('capture_output'):
                    kwargs.update(stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                return real_run(*args,**kwargs)
            with patch.object(build,'PROJECT_PATH',root), patch.object(build,'OUTPUT_DIR',output), patch.object(build,'log'), patch.object(build.subprocess,'run',side_effect=quiet):
                build.process_audio_and_mux(raw,final,1.2,voice)
                silent=late_energy()
                build.process_audio_and_mux(raw,final,1.2,voice,sfx=effects)
                self.assertGreater(late_energy(),silent+5)
                # Exercise the three-input voice + music + effects graph too.
                shutil.copy2(voice,root/'music.mp3')
                build.process_audio_and_mux(raw,final,1.2,voice,sfx=effects)
                self.assertGreater(late_energy(),silent+5)


if __name__=='__main__': unittest.main()
