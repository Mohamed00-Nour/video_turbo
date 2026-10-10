import contextlib
import io
import unittest

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


if __name__ == "__main__":
    unittest.main()
