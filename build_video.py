"""
Autonomous Video Generation Script for TikTok Reels
Pass --project to select a video folder, or keep the PROJECT_DIR default.
Cached stages are reused only when their inputs are unchanged.
"""

from pathlib import Path
import os
import sys
import json
import re
import shutil
import difflib
import subprocess
import urllib.request
import argparse
import math
import video_sections
from pipeline_common import (file_digest, file_signature, fingerprint, read_cache,
                             write_json, voiceover_path, plan_game_timing)

# ==========================================
# SETTINGS (edit only this line per video)
# ==========================================
PROJECT_DIR = "G:/A Steady/Anti-vids/game 6"
# ==========================================

# ------------------------------------------
# LOOK & FEEL (change only if you want to tweak the style)
# All of these can also be overridden per project in config.json.
# ------------------------------------------
# Multiplier applied to the background blur your Remotion component already uses.
# 1.0 = unchanged, 0.6 = 40% less blur, 0.0 = no blur.
BG_BLUR_SCALE = 0.6

# Top/bottom clips start stacked in the CENTER of the video, then slide out to
# their final positions in this many frames (30 fps -> 14 frames ~ 0.47 s).
REVEAL_FRAMES = 14

# Logo placed between the top and bottom clips, with a wiggly wave effect.
LOGO_WAVE_AMPLITUDE = 14     # displacement strength of the wave (px)
LOGO_WAVE_SPEED = 0.18       # how fast the wave moves
LOGO_WAVE_FREQUENCY = 0.03   # how tight the ripples are (radians per px)

# Extra seconds kept after the voiceover ends. 0.0 = video ends with the voiceover
# (the old 1.0 s "ending" block with random GTA cuts is removed).
# If > 0, the last block (CTA) is simply held longer - no random frames.
END_PADDING_SECONDS = 0.0

# Words Whisper tends to get wrong. Used for the prompt AND for post-correction.
DEFAULT_VOCABULARY = ["إمكانيات", "بيسي", "ألعاب", "مجانية", "لايك", "فولو"]
# Exact fixes (wrong -> right). Add more here, or under "corrections" in config.json.
DEFAULT_CORRECTIONS = {"مكانيات": "إمكانيات"}

PROJECT_PATH = Path(PROJECT_DIR).resolve()
ENGINE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_PATH / "output"
CODE_DIR = PROJECT_PATH / "code" if (PROJECT_PATH / "code").exists() else ENGINE_DIR / "code"
PUBLIC_DIR = CODE_DIR / "public"
FONTS_DIR = PROJECT_PATH / "fonts" if (PROJECT_PATH / "fonts").exists() else ENGINE_DIR / "fonts"
GAMES_DIR = PROJECT_PATH / "games"

# Ensure environment paths on Windows
ADDITIONAL_PATHS = [
    r"C:\Users\COMPUMARTS\AppData\Local\Programs\Python\Python311",
    r"C:\Users\COMPUMARTS\AppData\Local\Programs\Python\Python311\Scripts",
    r"C:\Users\COMPUMARTS\AppData\Local\Microsoft\WinGet\Links",
]
for p in ADDITIONAL_PATHS:
    if p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = p + ";" + os.environ.get("PATH", "")
os.environ["PYTHONIOENCODING"] = "utf-8"


def configure_project(project: Path) -> None:
    global PROJECT_PATH, OUTPUT_DIR, CODE_DIR, PUBLIC_DIR, FONTS_DIR, GAMES_DIR
    PROJECT_PATH = Path(project).resolve()
    OUTPUT_DIR = PROJECT_PATH / "output"
    CODE_DIR = PROJECT_PATH / "code" if (PROJECT_PATH / "code").is_dir() else ENGINE_DIR / "code"
    PUBLIC_DIR = CODE_DIR / "public"
    FONTS_DIR = PROJECT_PATH / "fonts" if (PROJECT_PATH / "fonts").is_dir() else ENGINE_DIR / "fonts"
    GAMES_DIR = PROJECT_PATH / "games"


if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg: str):
    try:
        print(f"[BUILD_VIDEO] {msg}", flush=True)
    except UnicodeEncodeError:
        print(f"[BUILD_VIDEO] {msg.encode('ascii', 'backslashreplace').decode('ascii')}", flush=True)


def check_required_files():
    log("Checking required input files...")

    # 1. Background video (check project folder, fallback to engine folder)
    gta_bg = PROJECT_PATH / "gta_background.mp4"
    needs_background = any(row.get("layout") != "reference_style" for row in load_config().get("sections", [{}]))
    if needs_background and not gta_bg.exists():
        if (ENGINE_DIR / "gta_background.mp4").exists():
            gta_bg = ENGINE_DIR / "gta_background.mp4"
        else:
            log(f"ERROR: Required file missing: gta_background.mp4")
            log(f"Expected location: {gta_bg}")
            sys.exit(1)

    # Accept MP3, WAV and other FFmpeg-supported voiceover formats.
    voiceover_path(PROJECT_PATH)

    # 3. Games directory
    if "sections" not in load_config() and (not GAMES_DIR.exists() or not any(GAMES_DIR.iterdir())):
        log(f"ERROR: Required folder missing or empty: games/")
        log(f"Expected location: {GAMES_DIR}")
        sys.exit(1)

    # 4. Font file (fallback: download from Google Fonts)
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    font_file = FONTS_DIR / "Lalezar-Regular.ttf"
    if not font_file.exists():
        otf = FONTS_DIR / "Lalezar-Regular.otf"
        if otf.exists():
            shutil.copy(otf, font_file)
            log("Copied Lalezar-Regular.otf to Lalezar-Regular.ttf")
        else:
            log("Downloading Lalezar Regular from Google Fonts...")
            url = "https://github.com/google/fonts/raw/main/ofl/lalezar/Lalezar-Regular.ttf"
            urllib.request.urlretrieve(url, str(font_file))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log("Required files verified.")


def load_config() -> dict:
    config_file = PROJECT_PATH / "config.json"
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# ------------------------------------------------------------------
# Arabic transcript correction
# Whisper sometimes drops a leading hamza/letter (إمكانيات -> مكانيات).
# We fix this deterministically after transcription using a vocabulary list
# and an explicit corrections map. Handles attached prefixes (و ف ب ل ك ال ...).
# ------------------------------------------------------------------
_AR_MARKS = re.compile("[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_AR_NORM = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي"})
_AR_PREFIXES = sorted(["و", "ف", "ب", "ل", "ك", "ال", "وال", "فال", "بال", "كال", "لل"],
                      key=len, reverse=True) + [""]
_FUZZY_MIN_LEN = 6      # fuzzy matching only for longer words (avoids false hits)
_FUZZY_THRESHOLD = 0.88


def _ar_norm(text: str) -> str:
    return _AR_MARKS.sub("", text).translate(_AR_NORM)


def build_corrector(config: dict):
    vocabulary = list(DEFAULT_VOCABULARY) + list(config.get("vocabulary", []))
    corrections = dict(DEFAULT_CORRECTIONS)
    corrections.update(config.get("corrections", {}))

    exact = {}  # normalized wrong/right form -> canonical spelling
    for v in vocabulary:
        exact[_ar_norm(v)] = v
    for wrong, right in corrections.items():
        exact[_ar_norm(wrong)] = right
    fuzzy_vocab = [(_ar_norm(v), v) for v in vocabulary if len(_ar_norm(v)) >= _FUZZY_MIN_LEN]

    def correct_word(word: str) -> str:
        clean = _AR_MARKS.sub("", word)
        m = re.match(r"^([^\w]*)(.*?)([^\w]*)$", clean, re.S)
        lead, core, trail = m.group(1), m.group(2), m.group(3)
        if len(core) < 3:
            return word
        core_n = core.translate(_AR_NORM)

        # Pass 1: exact (normalized) match, with or without a prefix
        for pre in _AR_PREFIXES:
            if pre and not core_n.startswith(pre):
                continue
            rest = core_n[len(pre):]
            if len(rest) >= 3 and rest in exact:
                fixed = lead + core[:len(pre)] + exact[rest] + trail
                return fixed if fixed != word else word

        # Pass 2: fuzzy match against vocabulary (catches dropped letters)
        for pre in _AR_PREFIXES:
            if pre and not core_n.startswith(pre):
                continue
            rest = core_n[len(pre):]
            if len(rest) < _FUZZY_MIN_LEN - 1:
                continue
            for v_norm, v in fuzzy_vocab:
                if difflib.SequenceMatcher(None, rest, v_norm).ratio() >= _FUZZY_THRESHOLD:
                    return lead + core[:len(pre)] + v + trail
        return word

    return correct_word


def apply_corrections(result: dict, config: dict) -> bool:
    correct_word = build_corrector(config)
    changed = False
    for w in result.get("words", []):
        fixed = correct_word(w["word"])
        if fixed != w["word"]:
            log(f"Corrected transcript word: '{w['word']}' -> '{fixed}' at {w['start']}s")
            w["word"] = fixed
            changed = True
    if changed or result.get("transcript"):
        old = result.get("transcript", "")
        new = " ".join(correct_word(t) for t in old.split())
        if new != old:
            result["transcript"] = new
            changed = True
    return changed


def transcribe_voiceover(audio_path: Path, force: bool = False) -> dict:
    words_file = OUTPUT_DIR / "words.json"
    config = load_config()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model_name = config.get("whisper_model", "large-v3")
    cache_key = fingerprint({"version": 1, "audio": file_digest(audio_path),
                             "model": model_name, "language": "ar",
                             "vocabulary": config.get("vocabulary", []),
                             "corrections": config.get("corrections", {}),
                             "defaults": [DEFAULT_VOCABULARY, DEFAULT_CORRECTIONS]})
    result = read_cache(words_file)
    if not force and result.get("cacheKey") == cache_key and isinstance(result.get("words"), list):
        log("Voiceover unchanged; reusing cached transcription.")
        if apply_corrections(result, config):
            write_json(words_file, result)
        return result

    log(f"Transcribing voiceover with faster-whisper (model '{model_name}', language 'ar')...")
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8")

    vocab = list(DEFAULT_VOCABULARY) + list(config.get("vocabulary", []))
    # words from script.txt help Whisper hear the right words in the first place
    vocab += list(dict.fromkeys(load_script_tokens() or []))[:100]
    # initial_prompt + hotwords bias Whisper towards the correct spellings.
    # Whisper only supports up to ~448 positional encodings; keep the prompt
    # short (≤200 chars) so the audio tokens never exceed that limit.
    initial_prompt = " ".join(vocab)[:200]

    kwargs = dict(
        language="ar",
        word_timestamps=True,
        initial_prompt=initial_prompt,
        beam_size=5,
        best_of=5,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    try:
        segments, info = model.transcribe(str(audio_path), hotwords=" ".join(vocab), **kwargs)
    except TypeError:
        # older faster-whisper without 'hotwords'
        segments, info = model.transcribe(str(audio_path), **kwargs)

    words_data = []
    full_transcript = []

    for seg in segments:
        full_transcript.append(seg.text)
        for w in seg.words:
            words_data.append({
                "word": w.word.strip(),
                "start": round(w.start, 3),
                "end": round(w.end, 3),
                "probability": round(w.probability, 3)
            })

    result = {
        "cacheKey": cache_key,
        "transcript": " ".join(full_transcript),
        "words": words_data
    }
    apply_corrections(result, config)

    write_json(words_file, result)

    log(f"Transcription complete: {len(words_data)} words.")
    log(f"Transcript: {result['transcript']}")
    return result


# ------------------------------------------------------------------
# SCRIPT ALIGNMENT  (optional: put a script.txt next to voiceover.mp3)
# Whisper listens to the recording and gives us WHEN each word is spoken.
# script.txt gives us HOW each word is spelled. The final captions use the
# exact spelling from script.txt with the timing from the recording.
# ------------------------------------------------------------------
_EDGE_PUNCT = re.compile(r"^[^\w\u0610-\u061A\u064B-\u065F\u0670]+|[^\w\u0610-\u061A\u064B-\u065F\u0670]+$")
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_ANCHOR_MIN_SIM = 0.6   # a spoken word counts as "the same word" above this similarity
_MIN_WORD_SECONDS = 1 / 30
_MIN_ESTIMATED_WORD_SECONDS = 0.08  # reject implausibly fast interpolated speech


def _read_script_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        log("WARNING: script.txt is not UTF-8. Reading it as Windows Arabic (cp1256). "
            "Tip: in Notepad use Save As -> Encoding: UTF-8.")
        return raw.decode("cp1256", errors="replace")


def load_script_tokens():
    """Words of script.txt in order (spelling exactly as typed), or None if no script."""
    script_file = PROJECT_PATH / "script.txt"
    if not script_file.exists():
        return None
    tokens = []
    for line in _read_script_text(script_file).splitlines():
        if line.strip().startswith("#"):   # lines starting with # are comments
            continue
        for tok in line.split():
            tok = _EDGE_PUNCT.sub("", _INVISIBLE.sub("", tok))
            if tok:
                tokens.append(tok)
    return tokens


def _match_form(text: str) -> str:
    return re.sub(r"[^\w]", "", _ar_norm(text).lower())


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def align_script_to_words(script_tokens: list, whisper_words: list, vo_duration: float) -> list:
    S = script_tokens
    W = whisper_words
    n, m = len(S), len(W)
    sn = [_match_form(t) for t in S]
    wn = [_match_form(w["word"]) for w in W]

    out = []

    def spread(idxs, lo, hi):
        """Place script words idxs inside [lo, hi], proportionally to their length."""
        total = max(hi - lo, _MIN_WORD_SECONDS * len(idxs))
        weights = [max(1, len(sn[i])) for i in idxs]
        wsum = float(sum(weights))
        t = lo
        for i, wt in zip(idxs, weights):
            d = total * wt / wsum
            out.append({"word": S[i], "start": t, "end": t + d})
            t += d

    if m == 0:
        log("WARNING: no spoken words were detected; spreading the script evenly over the voiceover.")
        spread(list(range(n)), 0.0, vo_duration)
        return _finalize_aligned(out, vo_duration)

    # ---- Needleman-Wunsch alignment on word similarity ----
    GAP = -0.5
    sim = [[_similarity(sn[i], wn[j]) for j in range(m)] for i in range(n)]
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]   # 0 diag, 1 up (script word alone), 2 left (spoken word alone)
    for i in range(1, n + 1):
        score[i][0] = i * GAP
        back[i][0] = 1
    for j in range(1, m + 1):
        score[0][j] = j * GAP
        back[0][j] = 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = score[i - 1][j - 1] + (2 * sim[i - 1][j - 1] - 0.8)
            up = score[i - 1][j] + GAP
            left = score[i][j - 1] + GAP
            best = max(diag, up, left)
            score[i][j] = best
            back[i][j] = 0 if best == diag else (1 if best == up else 2)

    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        b = back[i][j]
        if b == 0:
            ops.append((i - 1, j - 1)); i -= 1; j -= 1
        elif b == 1:
            ops.append((i - 1, None)); i -= 1
        else:
            ops.append((None, j - 1)); j -= 1
    ops.reverse()

    # ---- Build the final word list: anchors keep real timing, gaps are interpolated ----
    gap_s, gap_w = [], []
    prev_end = 0.0
    anchors = 0
    notes = []   # human-readable things worth checking

    def flush(t_hi, edge=None):
        nonlocal gap_s, gap_w
        if gap_s:
            lo, hi = prev_end, t_hi
            if gap_w:
                wlo, whi = W[gap_w[0]]["start"], W[gap_w[-1]]["end"]
                lo2, hi2 = max(lo, wlo), min(hi, whi)
                heard = " ".join(W[k]["word"] for k in gap_w)
                said = " ".join(S[k] for k in gap_s)
                # Whisper can omit a whole stretch of speech while retaining
                # only a short fragment. That fragment's timestamps cannot
                # describe all the missing script words: use the full window
                # between reliable anchors instead of flashing words and then
                # holding the last one until the next anchor.
                coverage = _similarity(_match_form(heard), _match_form(said))
                enough_time = hi2 - lo2 >= _MIN_ESTIMATED_WORD_SECONDS * len(gap_s)
                if hi2 > lo2 and coverage >= _ANCHOR_MIN_SIM and enough_time:
                    lo, hi = lo2, hi2
                elif hi > lo:
                    log(f"WARNING: incomplete transcription near {lo:.2f}s; "
                        f"estimating {len(gap_s)} script words across "
                        f"{lo:.2f}-{hi:.2f}s between matched words.")
                if _match_form(heard) != _match_form(said):
                    notes.append(f"{lo:5.2f}s  recording: '{heard}'  | script: '{said}'")
            else:
                said = " ".join(S[k] for k in gap_s)
                notes.append(f"{lo:5.2f}s  not found in the recording: '{said}'")
                if edge == "lead":
                    lo = max(0.0, hi - 0.3 * len(gap_s))
                elif edge == "trail":
                    hi = min(vo_duration, lo + 0.3 * len(gap_s))
            spread(gap_s, lo, hi)
        elif gap_w:
            heard = " ".join(W[k]["word"] for k in gap_w)
            notes.append(f"{W[gap_w[0]]['start']:5.2f}s  heard but not in the script (ignored): '{heard}'")
        gap_s, gap_w = [], []

    for si, wj in ops:
        is_anchor = si is not None and wj is not None and sim[si][wj] >= _ANCHOR_MIN_SIM
        if is_anchor and sim[si][wj] < 1.0 and gap_s:
            # A fuzzy resemblance far ahead in the script is not a reliable
            # anchor if it leaves no time for the preceding missing words.
            # For example, Whisper's "-داون" can resemble the later "بدون".
            available = W[wj]["start"] - prev_end
            if available < _MIN_ESTIMATED_WORD_SECONDS * len(gap_s):
                is_anchor = False
        if is_anchor:
            flush(W[wj]["start"], edge="lead" if anchors == 0 else None)
            out.append({"word": S[si], "start": W[wj]["start"], "end": W[wj]["end"]})
            prev_end = W[wj]["end"]
            anchors += 1
        else:
            if si is not None:
                gap_s.append(si)
            if wj is not None:
                gap_w.append(wj)
    flush(vo_duration, edge="trail")

    pct = 100.0 * anchors / max(1, n)
    log(f"Script alignment: {anchors}/{n} words matched the recording directly ({pct:.0f}%).")
    if pct < 60:
        log("WARNING: the script and the recording differ a lot. Check that script.txt is the "
            "text you actually read, in the same order.")
    if notes:
        log("Places worth checking (script spelling is used anyway):")
        for line in notes[:25]:
            log("   " + line)
        if len(notes) > 25:
            log(f"   ... and {len(notes) - 25} more")
    return _finalize_aligned(out, vo_duration)


def _finalize_aligned(words: list, vo_duration: float) -> list:
    """Keep captions ordered and bounded; reject scripts that cannot fit."""
    if len(words) * _MIN_WORD_SECONDS > vo_duration + .001:
        raise ValueError("Too many script words for the voiceover duration. Check script.txt.")
    previous = -_MIN_WORD_SECONDS
    for i, word in enumerate(words):
        latest = vo_duration - (len(words) - i) * _MIN_WORD_SECONDS
        start = max(previous + _MIN_WORD_SECONDS, min(max(0., word["start"]), latest))
        end = min(vo_duration, max(start + _MIN_WORD_SECONDS, word["end"]))
        word["start"], word["end"] = round(start, 3), round(end, 3)
        previous = start
    return words


def _alignment_chunks(script_tokens, guide, duration, encode):
    """Keep each alignment inside Whisper's 30-second / 448-token context."""
    groups = [encode(" " + word) for word in script_tokens]
    if any(not group for group in groups):
        raise ValueError("script.txt contains a word that cannot be tokenized.")
    if duration <= 30 and sum(map(len, groups)) <= 400:
        return [(0, len(groups), 0., duration)], groups
    chunks = []
    first = 0
    while first < len(groups):
        lo = max(0., guide[first]["start"] - .35)
        last, count = first, 0
        while last < len(groups):
            size = len(groups[last])
            if count + size > 400 or guide[last]["end"] - lo > 29.6:
                break
            count += size
            last += 1
        if last == first:
            raise ValueError("Cannot locate a safe audio window for the script. Check that script.txt matches the voiceover.")
        hi = min(duration, guide[last - 1]["end"] + .35, lo + 30.)
        if hi <= lo:
            raise ValueError("Invalid script alignment window; check the voiceover and script.")
        chunks.append((first, last, lo, hi))
        first = last
    return chunks, groups


def _map_audio_alignment(script_tokens, token_groups, alignment, offset):
    """Map token spans back to original whitespace words, including split tokens."""
    spans = []
    cursor = 0
    for item in alignment:
        count = len(item["tokens"])
        spans.append((cursor, cursor + count, item))
        cursor += count
    if cursor != sum(map(len, token_groups)):
        raise ValueError("The audio aligner did not return every script token.")
    words, cursor = [], 0
    for word, group in zip(script_tokens, token_groups):
        finish = cursor + len(group)
        hits = [item for lo, hi, item in spans if lo < finish and hi > cursor]
        words.append({"word": word, "start": offset + float(hits[0]["start"]),
                      "end": offset + float(hits[-1]["end"])})
        cursor = finish
    return words


def align_script_to_audio(script_tokens, whisper_words, vo_duration, audio_path, model_name):
    """Time the supplied text against audio attention, rather than estimating gaps."""
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio, pad_or_trim
    from faster_whisper.tokenizer import Tokenizer

    if len(script_tokens) * _MIN_WORD_SECONDS > vo_duration + .001:
        raise ValueError("Too many script words for the voiceover duration. Check script.txt.")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                          task="transcribe", language="ar")
    # Short recordings align in one pass, independently of an incomplete ASR
    # transcript. Longer recordings use ASR only to locate bounded audio windows.
    groups = [tokenizer.encode(" " + word) for word in script_tokens]
    guide = ([] if vo_duration <= 30 and sum(map(len, groups)) <= 400 else
             align_script_to_words(script_tokens, whisper_words, vo_duration))
    chunks, groups = _alignment_chunks(script_tokens, guide, vo_duration, tokenizer.encode)
    audio = decode_audio(str(audio_path), sampling_rate=16000)
    out = []
    for first, last, lo, hi in chunks:
        log(f"Aligning script words {first + 1}-{last} directly to audio ({lo:.2f}-{hi:.2f}s)...")
        waveform = audio[int(round(lo * 16000)):int(round(hi * 16000))]
        if len(waveform) < 400:
            raise ValueError("Not enough audio for script alignment.")
        features = model.feature_extractor(waveform)
        frames = min(features.shape[-1], model.feature_extractor.nb_max_frames)
        encoded = model.encode(pad_or_trim(features, length=model.feature_extractor.nb_max_frames))
        text_tokens = [token for group in groups[first:last] for token in group]
        alignment = model.find_alignment(tokenizer, [text_tokens], encoded, frames)[0]
        out.extend(_map_audio_alignment(script_tokens[first:last], groups[first:last], alignment, lo))
    # Several unplaced words mean the script/window does not match the audio.
    # Do not quietly turn an unrecognized passage into rapidly flashing captions.
    instant = [w["end"] - w["start"] < .01 for w in out]
    run = 0
    for failed in instant:
        run = run + 1 if failed else 0
        if run >= 4:
            raise ValueError("Audio alignment could not locate several consecutive script words. Check that script.txt matches what you said.")
    if sum(instant) > max(2, len(out) * .2):
        raise ValueError("Too many script words could not be located in the audio. Check script.txt.")
    log(f"Direct audio alignment complete: {len(out)} script words.")
    return _finalize_aligned(out, vo_duration)


def apply_script(transcription: dict, vo_duration: float) -> dict:
    tokens = load_script_tokens()
    if tokens is None:
        (OUTPUT_DIR / "words_aligned.json").unlink(missing_ok=True)
        return transcription
    if not tokens:
        log("WARNING: script.txt is empty. Using the transcribed words instead.")
        return transcription
    audio = voiceover_path(PROJECT_PATH)
    model_name = load_config().get("whisper_model", "large-v3")
    cache_key = fingerprint({"version": 2, "method": "audio-attention",
                             "audio": file_digest(audio), "script": tokens,
                             "duration": vo_duration, "model": model_name,
                             "guide": transcription.get("words", []) if vo_duration > 30 else None})
    path = OUTPUT_DIR / "words_aligned.json"
    cached = read_cache(path)
    if cached.get("cacheKey") == cache_key and isinstance(cached.get("words"), list):
        log("Voiceover and script unchanged; reusing direct audio alignment.")
        return cached
    log(f"script.txt found ({len(tokens)} words). Aligning the text directly with the recording...")
    aligned = align_script_to_audio(tokens, transcription["words"], vo_duration, audio, model_name)
    result = {"cacheKey": cache_key, "method": "audio-attention",
              "transcript": " ".join(tokens), "words": aligned}
    write_json(path, result)
    return result


def get_audio_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    return float(json.loads(res.stdout)["format"]["duration"])


def get_game_definitions(config: dict) -> list[dict]:
    if config.get("games"):
        games = config["games"]
    else:
        games = []
        for path in sorted(GAMES_DIR.iterdir()):
            if path.is_dir() and not path.name.startswith("."):
                title = re.sub(r"^\d+[_\-\s]+", "", path.name).replace("_", " ").replace("-", " ")
                games.append({"folder": path.name, "title": title, "spoken_names": [title]})
    result = []
    for game in games:
        path = (GAMES_DIR / game["folder"]).resolve()
        if not path.is_relative_to(GAMES_DIR.resolve()):
            raise ValueError(f"Game folder must be inside games/: {game['folder']}")
        result.append({**game, "path": path, "title": game.get("title", game["folder"]),
                       "spoken_names": game.get("spoken_names", [])})
    if not result:
        raise ValueError("No games configured or found in games/.")
    return result


def resolve_game_clips(path: Path) -> tuple[Path, Path]:
    if not path.is_dir():
        raise FileNotFoundError(f"Game folder missing: {path}")
    candidates = sorted(p for p in path.glob("*.mp4") if p.is_file() and not p.name.startswith("raw_gameplay"))
    top, bottom = path / "top.mp4", path / "bottom.mp4"
    if not top.is_file():
        if not candidates:
            raise FileNotFoundError(f"No gameplay clips in {path}. Run prepare_assets.py first.")
        top = candidates[0]
    if not bottom.is_file():
        bottom = next((p for p in candidates if p != top), top)
    return top, bottom


def validate_timeline(timeline: dict) -> None:
    frame = 0
    for block in timeline["blocks"]:
        if block["startFrame"] != frame or block["durationFrames"] <= 0:
            raise ValueError("Timeline blocks must be contiguous and have positive duration.")
        frame += block["durationFrames"]
    if frame != timeline["totalFrames"]:
        raise ValueError("Timeline length does not match its blocks.")
    previous = -1
    for word in timeline["words"]:
        if not (previous < word["startFrame"] < word["endFrame"] <= frame):
            raise ValueError(f"Caption timing is invalid near {word['word']!r}; check the script and transcription.")
        previous = word["startFrame"]


def build_timeline(transcription: dict, vo_duration: float) -> dict:
    log("Building timeline blocks from voiceover...")
    words = transcription["words"]
    fps = 30

    # Read config.json if present
    config = load_config()
    if "sections" in config:
        timeline = video_sections.make_timeline(config, PROJECT_PATH, PUBLIC_DIR, words, vo_duration, get_audio_duration)
        validate_timeline(timeline)
        write_json(CODE_DIR / "src" / "timeline.json", timeline)
        write_json(OUTPUT_DIR / "timeline.json", timeline)
        log("Section timeline built successfully.")
        return timeline
    bg_blur_scale = float(config.get("bg_blur_scale", BG_BLUR_SCALE))
    reveal_frames = int(config.get("reveal_frames", REVEAL_FRAMES))

    game_folders = get_game_definitions(config)
    captions_in_game_blocks = config.get("captions_in_game_blocks", True)
    timing_config = {"end_padding_seconds": END_PADDING_SECONDS, **config}
    plan = plan_game_timing(game_folders, words, vo_duration, timing_config, fps)
    hook_end = plan["hookFrames"] / fps
    cta_end = plan["totalFrames"] / fps
    media_lengths = {}

    def media_frames(relative: str) -> int:
        if relative not in media_lengths:
            duration = get_audio_duration(PUBLIC_DIR / relative)
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError(f"Invalid or empty video: {relative}")
            media_lengths[relative] = max(1, math.floor(duration * fps))
        return media_lengths[relative]

    # Prepare Blocks
    blocks = []
    # 1. HOOK
    hook_frames = int(round(hook_end * fps))
    blocks.append({
        "type": "hook",
        "startFrame": 0,
        "durationFrames": hook_frames,
        "gtaOffset": 0.8,
        "bgVideo": "gta_background.mp4",
        "bgDurationFrames": media_frames("gta_background.mp4"),
        "captionY": float(config.get("hook_caption_y", 0.46))
    })

    # GTA offset generator avoiding 0s
    gta_offsets = [4.2, 8.0, 2.0, 6.0, 10.0]

    # 2. GAME BLOCKS
    current_frame = hook_frames
    for i, g in enumerate(game_folders):
        dur_f = plan["gameRanges"][i][1] - plan["gameRanges"][i][0]

        top_clip, bottom_clip = resolve_game_clips(g["path"])
        pub_logo = next(iter(sorted((PUBLIC_DIR / "games" / g["folder"]).glob("_logo.*"))), None)

        # Match background style: GTA for game 0, Roblox for game 1, Fortnite for game 2 (if present)
        bg_candidates = ["gta_background.mp4", "roblox.mp4", "fortnite.mp4"]
        chosen_bg = bg_candidates[i % len(bg_candidates)]
        if not (PUBLIC_DIR / chosen_bg).exists() and not (PROJECT_PATH / chosen_bg).exists():
            chosen_bg = "gta_background.mp4"

        blocks.append({
            "type": "game",
            "startFrame": current_frame,
            "durationFrames": dur_f,
            "gtaOffset": gta_offsets[i % len(gta_offsets)],
            "bgVideo": chosen_bg,
            "folder": g["folder"],
            "title": g["title"],
            "captionY": float(config.get("game_caption_y", 1205 / 1920)),
            "bgDurationFrames": media_frames(chosen_bg),
            "topDurationFrames": media_frames(f"games/{g['folder']}/{top_clip.name}"),
            "bottomDurationFrames": media_frames(f"games/{g['folder']}/{bottom_clip.name}"),
            "topClip": f"games/{g['folder']}/{top_clip.name}",
            "bottomClip": f"games/{g['folder']}/{bottom_clip.name}",
            "logo": f"games/{g['folder']}/{pub_logo.name}" if pub_logo else "",
            "hasLogo": pub_logo is not None,
            # Top/bottom clips start stacked at the video center, then slide out
            # to their normal top/bottom positions. The shake effect continues after.
            "reveal": {
                "startFromCenter": True,
                "durationFrames": min(reveal_frames, max(1, dur_f - 1)),
                "easing": "easeOutCubic"
            },
            # Logo sits in the middle (between top and bottom clips) with a wiggly wave.
            # Its entrance animation accompanies the clip reveal.
            "logoEffect": {
                "type": "wiggleWave",
                "position": "center",
                "amplitude": LOGO_WAVE_AMPLITUDE,
                "speed": LOGO_WAVE_SPEED,
                "frequency": LOGO_WAVE_FREQUENCY
            }
        })
        current_frame += dur_f

    # 3. CTA BLOCK
    # Fill exactly up to the end of the voiceover so video and audio end together
    cta_frames = max(1, int(round(cta_end * fps)) - current_frame)
    cta_bg = "roblox.mp4" if (PUBLIC_DIR / "roblox.mp4").is_file() else "gta_background.mp4"
    blocks.append({
        "type": "cta",
        "startFrame": current_frame,
        "durationFrames": cta_frames,
        "gtaOffset": 7.0,
        "bgVideo": cta_bg,
        "bgDurationFrames": media_frames(cta_bg),
        "captionY": float(config.get("cta_caption_y", 0.72))
    })
    current_frame += cta_frames

    # (The old 1.0 s ENDING block with random GTA cuts was removed on purpose:
    #  the video now ends right after the CTA block.)
    total_frames = current_frame
    total_duration = total_frames / fps

    # Words with frames
    processed_words = []
    for i, w in enumerate(words):
        s_f = int(round(w["start"] * fps))
        if i < len(words) - 1:
            e_f = int(round(words[i + 1]["start"] * fps))
        else:
            e_f = total_frames
        processed_words.append({
            "word": w["word"],
            "start": w["start"],
            "end": w["end"],
            "startFrame": s_f,
            "endFrame": max(e_f, s_f + 1)
        })

    timeline = {
        "fps": fps,
        "totalFrames": total_frames,
        "totalDuration": round(total_duration, 3),
        "captionsInGameBlocks": captions_in_game_blocks,
        "style": {
            # Multiply your existing background blur by this value (e.g. blur * blurScale)
            "bgBlurScale": bg_blur_scale
        },
        "blocks": blocks,
        "words": processed_words
    }

    validate_timeline(timeline)
    write_json(CODE_DIR / "src" / "timeline.json", timeline)
    write_json(OUTPUT_DIR / "timeline.json", timeline)

    log("Timeline built successfully.")
    return timeline


# ------------------------------------------------------------------
# Logo handling: accepts ANY image type / any file name
# (logo.png, logo.jfif, Logo.JPG, "Bloon logo.webp", ...)
# The real format is detected from the file's bytes, not its extension, and the
# logo is published to the Remotion public folder as "_logo.<ext>".
# ------------------------------------------------------------------
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jfif", ".jpe", ".pjpeg", ".pjp", ".webp",
              ".gif", ".bmp", ".tif", ".tiff", ".avif", ".heic", ".heif", ".svg", ".ico"}
_EXT_PRIORITY = {".png": 0, ".webp": 1, ".svg": 2, ".jpg": 3, ".jpeg": 3, ".jfif": 3}


def find_logo_source(game_path: Path, preferred: str = ""):
    if preferred:
        selected = (game_path / preferred).resolve()
        if selected.is_relative_to(game_path.resolve()) and selected.is_file() and selected.suffix.lower() in IMAGE_EXTS:
            return selected
    imgs = [f for f in game_path.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS and not f.name.startswith("_logo")]
    if not imgs:
        return None
    pool = ([f for f in imgs if f.stem.lower() == "logo"]
            or [f for f in imgs if "logo" in f.stem.lower()]
            or imgs)
    return sorted(pool, key=lambda f: (_EXT_PRIORITY.get(f.suffix.lower(), 9), f.name.lower()))[0]


def sniff_image_ext(path: Path):
    """Return a browser-safe extension based on the file's real content, or None."""
    with open(path, "rb") as f:
        head = f.read(2048)
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"  # JPEG / JFIF / EXIF
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:2] == b"BM":
        return ".bmp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"avif", b"avis"):
        return ".avif"
    low = head.lower()
    if b"<svg" in low:
        return ".svg"
    return None


def prepare_logo(src: Path, dest_dir: Path):
    """Copy/convert the logo into dest_dir as _logo.<ext>. Returns the file name or None."""
    for old in dest_dir.glob("_logo.*"):
        old.unlink()

    ext = sniff_image_ext(src)
    if ext:
        out = dest_dir / f"_logo{ext}"
        shutil.copy(src, out)
        return out.name

    # Unusual format (TIFF, HEIC, ICO ...) -> convert to PNG
    out = dest_dir / "_logo.png"
    try:
        from PIL import Image
        Image.open(src).convert("RGBA").save(out)
        return out.name
    except Exception:
        pass
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                        "-frames:v", "1", str(out)], check=True)
        return out.name
    except Exception:
        log(f"WARNING: could not read logo image {src.name}")
        return None


def sync_public_assets() -> dict:
    """Copy only referenced assets, and only when their source or copy changed."""
    log("Syncing required assets to Remotion public directory...")
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = PUBLIC_DIR / ".asset_manifest.json"
    previous = read_cache(manifest_path)
    sources, outputs = {}, {}
    copied = 0

    def publish(source: Path, relative: str, logo=False):
        nonlocal copied
        target = PUBLIC_DIR / relative
        signature = file_signature(source)
        unchanged = (previous.get("sources", {}).get(relative) == signature
                     and target.is_file()
                     and previous.get("outputs", {}).get(relative) == file_signature(target))
        if not unchanged:
            target.parent.mkdir(parents=True, exist_ok=True)
            if logo:
                if prepare_logo(source, target.parent) != target.name:
                    raise ValueError(f"Could not prepare logo: {source}")
            else:
                shutil.copy2(source, target)
            copied += 1
        sources[relative] = signature
        outputs[relative] = file_signature(target)

    config = load_config()
    needs_background = any(row.get("layout") != "reference_style" for row in config.get("sections", [{}]))
    for name, aliases in {
        "gta_background.mp4": ["gta_background.mp4"],
        "roblox.mp4": ["roblox.mp4", "Roblox 1.mp4"],
        "fortnite.mp4": ["fortnite.mp4", "Fortnight.mp4"],
    }.items():
        source = next((base / alias for base in (PROJECT_PATH, ENGINE_DIR)
                       for alias in aliases if (base / alias).is_file()), None)
        if source:
            publish(source, name)
        elif name == "gta_background.mp4" and needs_background:
            raise FileNotFoundError("gta_background.mp4 is missing.")

    config = load_config()
    if "sections" in config:
        for section in video_sections.validate_sections(config, PROJECT_PATH):
            for field in ("media", "secondary_media"):
                if section.get(field):
                    publish(video_sections.media_path(PROJECT_PATH, section[field]), video_sections.public_media(section[field]))
    if config.get("reference_style"):
        for name in ("ibm-plex-sans-arabic-700.woff2", "Amiri-Bold.ttf"):
            publish(ENGINE_DIR / "studio/ui-fonts" / name, "reference-fonts/" + name)
    for game in ([] if "sections" in config else get_game_definitions(config)):
        top, bottom = resolve_game_clips(game["path"])
        for clip in {top, bottom}:
            publish(clip, f"games/{game['folder']}/{clip.name}")
        logo = find_logo_source(game["path"], game.get("logo_file", ""))
        if logo:
            ext = sniff_image_ext(logo) or ".png"
            publish(logo, f"games/{game['folder']}/_logo{ext}", logo=True)

    # Remove obsolete generated copies, including legacy raw-gameplay copies.
    # Original project assets are never touched; only regular files under public/.
    stale = list((PUBLIC_DIR / "games").rglob("*")) + list((PUBLIC_DIR / "sections").rglob("*"))
    stale += [PUBLIC_DIR / name for name in ("gta_background.mp4", "roblox.mp4", "fortnite.mp4")]
    for path in stale:
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(PUBLIC_DIR.resolve()):
            continue
        relative = path.relative_to(PUBLIC_DIR).as_posix()
        if relative not in sources and (path.suffix.lower() in IMAGE_EXTS | {".mp4", ".mov", ".mkv", ".webm"}):
            path.unlink()
    manifest = {"sources": sources, "outputs": outputs}
    write_json(manifest_path, manifest)
    log(f"Assets synchronized: {copied} file(s) copied or converted.")
    return manifest


def render_cache_key(timeline: dict, assets: dict) -> str:
    dependencies = [Path(__file__), ENGINE_DIR / "pipeline_common.py", ENGINE_DIR / "video_sections.py", CODE_DIR / "package-lock.json", CODE_DIR / "package.json"]
    dependencies += sorted(path for path in (CODE_DIR / "src").rglob("*")
                           if path.suffix in {".ts", ".tsx", ".css"})
    return fingerprint({"version": 1, "timeline": timeline, "assets": assets,
                        "code": {str(path.resolve()): file_digest(path) for path in dependencies if path.is_file()}})


def run_remotion_command(cmd):
    """Stream render logs and retry one transient Chrome connection timeout."""
    for attempt in range(2):
        command = cmd if attempt == 0 else [*cmd, "--log=verbose"]
        browser_timeout = False
        with subprocess.Popen(command, cwd=str(ENGINE_DIR), shell=(os.name == "nt"),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace") as process:
            for line in process.stdout:
                print(line, end="", flush=True)
                if re.search(r"Timed out after \d+ ms while trying to connect to the browser", line):
                    browser_timeout = True
            returncode = process.wait()
        if returncode == 0:
            return
        if not browser_timeout:
            raise subprocess.CalledProcessError(returncode, command)
        if attempt == 1:
            raise RuntimeError("Chrome did not start after two attempts. Check the browser startup log above, then retry the build.")
        log("Chrome startup timed out. Retrying once with browser diagnostics...")


def render_remotion_video(raw_output: Path):
    log("Rendering video with Remotion CLI...")
    npx_bin = shutil.which("npx") or ("npx.cmd" if os.name == "nt" else "npx")
    cmd = [
        str(npx_bin), "--prefix", str(CODE_DIR), "remotion", "render",
        str(CODE_DIR / "src" / "index.ts"), "MainVideo",
        str(raw_output),
        f"--public-dir={PUBLIC_DIR}"
    ]
    run_remotion_command(cmd)
    log("Remotion render complete.")


def process_audio_and_mux(raw_video: Path, final_output: Path, total_duration: float,
                          vo: Path | None = None):
    """Measure and normalize the complete mix, then mux it with the rendered video."""
    vo = vo or voiceover_path(PROJECT_PATH)
    norm_audio = OUTPUT_DIR / "normalized_audio.aac"
    cache_path = OUTPUT_DIR / "audio_manifest.json"
    music = PROJECT_PATH / "music.mp3"
    inputs = ["-i", str(vo)]
    if music.is_file():
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        fade = max(0., total_duration - 1.)
        mix = (f"[0:a]apad,atrim=duration={total_duration}[vo];"
               f"[1:a]volume=-22dB,atrim=duration={total_duration},"
               f"afade=t=in:st=0:d=0.5,afade=t=out:st={fade}:d=1[bgm];"
               "[vo][bgm]amix=inputs=2:duration=first:normalize=0[mix];")
    else:
        mix = f"[0:a]apad,atrim=duration={total_duration}[mix];"
    key = fingerprint({"version": 1, "voice": file_digest(vo),
                       "music": file_digest(music) if music.is_file() else None,
                       "mix": mix, "normalization": "two-pass-I-14-TP-1.5-LRA11"})
    old = read_cache(cache_path)
    valid = (old.get("key") == key and norm_audio.is_file()
             and old.get("output") == file_signature(norm_audio))
    if not valid:
        log("Measuring final voiceover/music mix for -14 LUFS normalization...")
        base = "loudnorm=I=-14:LRA=11:TP=-1.5"
        measure = ["ffmpeg", "-nostdin", *inputs, "-filter_complex",
                   mix + f"[mix]{base}:print_format=json[out]", "-map", "[out]",
                   "-t", str(total_duration), "-f", "null", "-"]
        result = subprocess.run(measure, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        matches = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', result.stderr or "", re.S)
        if not matches:
            raise RuntimeError("FFmpeg did not report loudness measurements.")
        stats = json.loads(matches[-1])
        norm = base
        if all(math.isfinite(float(stats[k])) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")):
            norm += (f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
                     f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
                     f":offset={stats['target_offset']}:linear=true")
        pending = OUTPUT_DIR / "normalized_pending.aac"
        subprocess.run(["ffmpeg", "-nostdin", "-y", *inputs, "-filter_complex",
                        mix + f"[mix]{norm}[out]", "-map", "[out]", "-t", str(total_duration),
                        "-ar", "48000", "-c:a", "aac", "-b:a", "192k", str(pending)], check=True)
        pending.replace(norm_audio)
        write_json(cache_path, {"key": key, "output": file_signature(norm_audio)})
    else:
        log("Audio inputs unchanged; reusing normalized mix.")
    pending_video = final_output.with_name("final_pending.mp4")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", str(raw_video), "-i", str(norm_audio),
                    "-c:v", "copy", "-c:a", "copy", "-map", "0:v:0", "-map", "1:a:0",
                    "-t", str(total_duration), "-movflags", "+faststart", str(pending_video)], check=True)
    pending_video.replace(final_output)
    log("final.mp4 created successfully.")


def export_preview_frames(final_mp4: Path):
    log("Exporting preview frames every 1 s to OUTPUT_DIR/preview/...")
    preview_dir = OUTPUT_DIR / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-i", str(final_mp4),
        "-vf", "fps=1",
        str(preview_dir / "frame_%02d.jpg"),
        "-y"
    ]
    subprocess.run(cmd, check=True)
    log(f"Preview frames exported to {preview_dir}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a captioned gaming video.")
    parser.add_argument("--project", type=Path, default=PROJECT_PATH, help="Video project folder")
    parser.add_argument("--force", "-f", action="store_true", help="Render again even if cached")
    parser.add_argument("--retranscribe", action="store_true", help="Ignore cached voiceover transcription")
    parser.add_argument("--no-preview", action="store_true", help="Skip JPEG preview frame export")
    parser.add_argument("--preview-only", action="store_true", help="Render one preview frame without building the full video")
    parser.add_argument("--preview-at", type=float, default=0, help="Preview time in seconds")
    args = parser.parse_args(argv)
    configure_project(args.project)
    try:
        log(f"Starting build for PROJECT_DIR: {PROJECT_PATH}")
        check_required_files()
        vo_file = voiceover_path(PROJECT_PATH)
        vo_duration = get_audio_duration(vo_file)
        log(f"Voiceover duration: {vo_duration:.2f}s")
        assets = sync_public_assets()
        transcription = transcribe_voiceover(vo_file, force=args.retranscribe)
        transcription = apply_script(transcription, vo_duration)
        timeline = build_timeline(transcription, vo_duration)

        if args.preview_only:
            if not math.isfinite(args.preview_at) or not 0 <= args.preview_at < timeline["totalDuration"]:
                raise ValueError("Preview time must be within the voiceover duration.")
            npx = shutil.which("npx") or "npx.cmd"
            target = OUTPUT_DIR / "studio_preview_pending.png"
            run_remotion_command([npx, "--prefix", str(CODE_DIR), "remotion", "still", str(CODE_DIR / "src/index.ts"), "MainVideo", str(target), f"--frame={min(timeline['totalFrames'] - 1, round(args.preview_at * timeline['fps']))}", f"--public-dir={PUBLIC_DIR}"])
            target.replace(OUTPUT_DIR / "studio_preview.png")
            log(f"PREVIEW COMPLETE: {OUTPUT_DIR / 'studio_preview.png'}")
            return 0

        raw_video = OUTPUT_DIR / "rendered_raw.mp4"
        manifest_path = OUTPUT_DIR / "render_manifest.json"
        key = render_cache_key(timeline, assets)
        previous = read_cache(manifest_path)
        valid = (raw_video.is_file() and previous.get("key") == key
                 and previous.get("output") == file_signature(raw_video))
        if args.force or not valid:
            pending = OUTPUT_DIR / "rendered_pending.mp4"
            pending.unlink(missing_ok=True)
            render_remotion_video(pending)
            if abs(get_audio_duration(pending) - timeline["totalDuration"]) > .1:
                raise ValueError("Rendered video duration does not match the timeline.")
            pending.replace(raw_video)
            write_json(manifest_path, {"key": key, "output": file_signature(raw_video)})
        else:
            log("Timeline, assets and code unchanged; reusing rendered video.")

        final_mp4 = OUTPUT_DIR / "final.mp4"
        process_audio_and_mux(raw_video, final_mp4, timeline["totalDuration"], vo_file)
        if not args.no_preview:
            export_preview_frames(final_mp4)
        log(f"BUILD COMPLETE: {final_mp4} ({timeline['totalDuration']}s)")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        log(f"ERROR: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
