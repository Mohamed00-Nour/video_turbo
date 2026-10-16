import contextlib
import io
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import build_video as build

from build_video import align_script_to_words


class CaptionAlignmentTests(unittest.TestCase):
    def align(self, script, words, duration=26.0):
        with contextlib.redirect_stdout(io.StringIO()):
            return align_script_to_words(script, words, duration)

    def test_truncated_transcription_uses_gap_between_anchors(self):
        # The supplied video has a fragment at 12s, followed by a jump to
        # 21.72s. Missing captions must continue through that entire window.
        missing = (
            "خفيف وسريع بيشتغل بسلاسة تامة على الأجهزة البطاطس تالت لعبة "
            "Realm of the Mad God مئات اللاعبين في سيرفر واحد بيحاربوا "
            "وحوش بكسل بدون ما تحس بأي تقطيع قولي مواصفات ال PC بتاعك "
            "وأنا أقولك ايه"
        ).split()
        script = ["توب-داون", *missing, "أفضل"]
        words = [
            {"word": "توب", "start": 11.56, "end": 11.88},
            {"word": "-داون", "start": 11.88, "end": 12.12},
            {"word": "خ", "start": 12.12, "end": 12.24},
            {"word": "أفضل", "start": 21.72, "end": 22.36},
        ]
        aligned = self.align(script, words)
        self.assertEqual([w["word"] for w in aligned], script)
        self.assertEqual(aligned[0]["start"], 11.56)
        self.assertEqual(aligned[-1]["start"], 21.72)
        recovered = aligned[1:-1]
        self.assertGreater(recovered[-1]["start"], 21.0)
        self.assertAlmostEqual(recovered[-1]["end"], 21.72, places=3)
        self.assertTrue(all(w["end"] - w["start"] > 0.08 for w in recovered))
        self.assertTrue(any(15 < w["start"] < 17 for w in recovered))

    def test_complete_gap_keeps_recorded_timing_and_silence(self):
        # Hyphenated words can span two Whisper tokens. When the entire gap
        # was heard, retain its narrow speech interval rather than the silence.
        words = [
            {"word": "begin", "start": 0.0, "end": 0.4},
            {"word": "alpha", "start": 2.0, "end": 2.3},
            {"word": "beta", "start": 2.3, "end": 2.6},
            {"word": "gamma", "start": 2.6, "end": 2.9},
            {"word": "end", "start": 5.0, "end": 5.4},
        ]
        aligned = self.align(["begin", "alpha-beta-gamma", "end"], words, 6.0)
        self.assertEqual(aligned[1], {
            "word": "alpha-beta-gamma", "start": 2.0, "end": 2.9,
        })
        self.assertEqual(aligned[-1]["start"], 5.0)

    def test_mixed_script_keeps_english_spelling_even_when_asr_is_arabic(self):
        script = "\u0627\u0633\u062a\u062e\u062f\u0645 USB-C \u0636\u062f (Juice Jacking) \u0645\u0639 Data Blocker."
        expected = ["\u0627\u0633\u062a\u062e\u062f\u0645", "USB-C", "\u0636\u062f", "Juice", "Jacking", "\u0645\u0639", "Data", "Blocker"]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "script.txt").write_text(script, encoding="utf-8-sig")
            with patch.object(build, "PROJECT_PATH", root):
                tokens = build.load_script_tokens()
        self.assertEqual(tokens, expected)
        # The recording may pronounce English phonetically. ASR text must never
        # replace the spelling supplied by the author.
        heard = ["\u0627\u0633\u062a\u062e\u062f\u0645", "\u064a\u0648\u0627\u0633\u0628\u064a", "\u0636\u062f", "\u062c\u0648\u0633", "\u062c\u0627\u0643\u064a\u0646\u062c", "\u0645\u0639", "\u062f\u0627\u062a\u0627", "\u0628\u0644\u0648\u0643\u0631"]
        aligned = self.align(tokens, [{"word":word,"start":i*.5,"end":i*.5+.4} for i,word in enumerate(heard)], 4.2)
        self.assertEqual([word["word"] for word in aligned], expected)
        self.assertTrue(all(0 <= word["start"] < word["end"] <= 4.2 for word in aligned))

    def test_direct_matches_keep_original_timestamps(self):
        words = [
            {"word": "one", "start": 0.1, "end": 0.5},
            {"word": "two", "start": 0.8, "end": 1.2},
            {"word": "three", "start": 1.5, "end": 2.0},
        ]
        self.assertEqual(self.align(["one", "two", "three"], words, 2.0), words)

    def test_fully_missing_gap_uses_available_interval(self):
        words = [
            {"word": "begin", "start": 0.0, "end": 1.0},
            {"word": "end", "start": 4.0, "end": 4.5},
        ]
        aligned = self.align(["begin", "missing", "speech", "end"], words, 5.0)
        self.assertEqual(aligned[1]["start"], 1.0)
        self.assertEqual(aligned[2]["end"], 4.0)


class DirectAudioAlignmentTests(unittest.TestCase):
    def test_short_audio_window_does_not_use_incomplete_transcription(self):
        # Original failure: ASR only starts at 9.86s. Full short audio must still
        # align from zero, with no estimated leading-word times as constraints.
        chunks, groups = build._alignment_chunks(
            ["first", "game", "second"], [], 27.09, lambda word: [len(word)])
        self.assertEqual(chunks, [(0, 3, 0., 27.09)])
        self.assertEqual(len(groups), 3)

    def test_long_alignment_stays_within_audio_and_token_context(self):
        tokens = [f"word{i}" for i in range(150)]
        guide = [{"start": i * .5, "end": i * .5 + .4} for i in range(150)]
        chunks, groups = build._alignment_chunks(tokens, guide, 75., lambda word: [1] * 9)
        covered = []
        for first, last, lo, hi in chunks:
            self.assertLessEqual(hi - lo, 30.)
            self.assertLessEqual(sum(map(len, groups[first:last])), 400)
            self.assertGreaterEqual(lo, 0.)
            self.assertLessEqual(hi, 75.)
            covered.extend(range(first, last))
        self.assertEqual(covered, list(range(150)))

    def test_maps_split_model_words_to_original_script_without_guessing(self):
        alignment = [
            {"tokens": [1], "start": .2, "end": .4},
            {"tokens": [2, 3], "start": .4, "end": .7},
            {"tokens": [4], "start": .9, "end": 1.1},
        ]
        words = build._map_audio_alignment(["OpenTTD", "Arabic"], [[1, 2, 3], [4]], alignment, 10.)
        self.assertEqual(words, [
            {"word": "OpenTTD", "start": 10.2, "end": 10.7},
            {"word": "Arabic", "start": 10.9, "end": 11.1},
        ])

    def test_incomplete_alignment_tokens_raise_error(self):
        with self.assertRaisesRegex(ValueError, "every script token"):
            build._map_audio_alignment(["missing"], [[1, 2]],
                                      [{"tokens": [1], "start": 0., "end": .3}], 0.)

    def test_alignment_cache_refreshes_on_script_and_voice_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "output").mkdir()
            (root / "voiceover.wav").write_bytes(b"first audio")
            script = root / "script.txt"
            script.write_text("first game", encoding="utf-8")
            transcription = {"words": [{"word": "game", "start": 9., "end": 9.3}]}
            def align(tokens, *args):
                return [{"word": word, "start": i * .3, "end": i * .3 + .2}
                        for i, word in enumerate(tokens)]
            with patch.object(build, "PROJECT_PATH", root), patch.object(build, "OUTPUT_DIR", root / "output"), patch.object(build, "align_script_to_audio", side_effect=align) as aligner, patch.object(build, "log"):
                result = build.apply_script(transcription, 10.)
                self.assertEqual(result["method"], "audio-attention")
                self.assertEqual(build.apply_script(transcription, 10.), result)
                self.assertEqual(aligner.call_count, 1)
                script.write_text("new game", encoding="utf-8")
                changed = build.apply_script(transcription, 10.)
                self.assertNotEqual(changed["cacheKey"], result["cacheKey"])
                (root / "voiceover.wav").write_bytes(b"other audio")
                changed_audio = build.apply_script(transcription, 10.)
                self.assertNotEqual(changed_audio["cacheKey"], changed["cacheKey"])
                self.assertEqual(aligner.call_count, 3)

    def test_failed_alignment_does_not_replace_valid_cache_with_estimates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "output").mkdir()
            (root / "voiceover.wav").write_bytes(b"audio")
            (root / "script.txt").write_text("first game", encoding="utf-8")
            cache = root / "output/words_aligned.json"
            cache.write_text('{"previous": true}', encoding="utf-8")
            with patch.object(build, "PROJECT_PATH", root), patch.object(build, "OUTPUT_DIR", root / "output"), patch.object(build, "align_script_to_audio", side_effect=ValueError("not located")), patch.object(build, "log"):
                with self.assertRaisesRegex(ValueError, "not located"):
                    build.apply_script({"words": []}, 10.)
            self.assertEqual(cache.read_text('utf-8'), '{"previous": true}')


if __name__ == "__main__":
    unittest.main()
