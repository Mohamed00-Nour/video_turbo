"""
Autonomous Video Generation Script for TikTok Reels
Reads PROJECT_DIR from a single variable at the top.
Can be re-run for any new video by changing only PROJECT_DIR.
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

# ==========================================
# SETTINGS (edit only this line per video)
# ==========================================
PROJECT_DIR = "G:/A Steady/Anti-vids/game 5"
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


def log(msg: str):
    print(f"[BUILD_VIDEO] {msg}", flush=True)


def check_required_files():
    log("Checking required input files...")

    # 1. Background video (check project folder, fallback to engine folder)
    gta_bg = PROJECT_PATH / "gta_background.mp4"
    if not gta_bg.exists():
        if (ENGINE_DIR / "gta_background.mp4").exists():
            gta_bg = ENGINE_DIR / "gta_background.mp4"
        else:
            log(f"ERROR: Required file missing: gta_background.mp4")
            log(f"Expected location: {gta_bg}")
            sys.exit(1)

    # 2. Voiceover audio
    vo = PROJECT_PATH / "voiceover.mp3"
    if not vo.exists():
        vo_space = PROJECT_PATH / "voice over.mp3"
        if vo_space.exists():
            shutil.copy(vo_space, vo)
            log("Found 'voice over.mp3' and copied to 'voiceover.mp3'")
        else:
            log(f"ERROR: Required file missing: voiceover.mp3")
            log(f"Expected location: {vo}")
            sys.exit(1)

    # 3. Games directory
    if not GAMES_DIR.exists() or not any(GAMES_DIR.iterdir()):
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


def transcribe_voiceover(audio_path: Path) -> dict:
    words_file = OUTPUT_DIR / "words.json"
    config = load_config()

    if words_file.exists():
        log("Existing words.json found. Reading transcription...")
        with open(words_file, "r", encoding="utf-8") as f:
            result = json.load(f)
        # Fix cached transcripts too, so you don't have to re-transcribe
        if apply_corrections(result, config):
            with open(words_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            log("words.json updated with corrected words.")
        return result

    log("Transcribing voiceover with faster-whisper (model 'large-v3', language 'ar')...")
    from faster_whisper import WhisperModel

    model = WhisperModel("large-v3", device="cpu", compute_type="int8")

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
        "transcript": " ".join(full_transcript),
        "words": words_data
    }
    apply_corrections(result, config)

    with open(words_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

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
    """Keep word start times strictly increasing (at least one frame apart)."""
    prev_start = None
    for w in words:
        if prev_start is not None and w["start"] < prev_start + _MIN_WORD_SECONDS:
            w["start"] = prev_start + _MIN_WORD_SECONDS
        if w["end"] < w["start"] + _MIN_WORD_SECONDS:
            w["end"] = w["start"] + _MIN_WORD_SECONDS
        prev_start = w["start"]
        w["start"] = round(w["start"], 3)
        w["end"] = round(w["end"], 3)
    return words


def apply_script(transcription: dict, vo_duration: float) -> dict:
    tokens = load_script_tokens()
    if tokens is None:
        return transcription
    if not tokens:
        log("WARNING: script.txt is empty. Using the transcribed words instead.")
        return transcription
    log(f"script.txt found ({len(tokens)} words). Aligning the script with the recording...")
    aligned = align_script_to_words(tokens, transcription["words"], vo_duration)
    result = {"transcript": " ".join(tokens), "words": aligned}
    with open(OUTPUT_DIR / "words_aligned.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def get_audio_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(json.loads(res.stdout)["format"]["duration"])


def build_timeline(transcription: dict, vo_duration: float) -> dict:
    log("Building timeline blocks from voiceover...")
    words = transcription["words"]
    fps = 30

    # Read config.json if present
    config = load_config()
    bg_blur_scale = float(config.get("bg_blur_scale", BG_BLUR_SCALE))
    reveal_frames = int(config.get("reveal_frames", REVEAL_FRAMES))

    # Detect game folders
    game_folders = []
    if "games" in config and len(config["games"]) > 0:
        for g_cfg in config["games"]:
            g_path = GAMES_DIR / g_cfg["folder"]
            game_folders.append({
                "path": g_path,
                "folder": g_cfg["folder"],
                "title": g_cfg.get("title", g_cfg["folder"]),
                "spoken_names": g_cfg.get("spoken_names", [])
            })
    else:
        # Discover directories
        for p in sorted(GAMES_DIR.iterdir()):
            if p.is_dir() and not p.name.startswith("."):
                name = p.name
                clean_name = name.split("_", 1)[1] if "_" in name else name
                game_folders.append({
                    "path": p,
                    "folder": name,
                    "title": clean_name.replace("-", " ").replace("_", " ").title(),
                    "spoken_names": [clean_name.lower()]
                })

    captions_in_game_blocks = config.get("captions_in_game_blocks", True)

    # Match game timestamps in words
    num_games = len(game_folders)
    game_start_times = []

    for g in game_folders:
        match_time = None
        spoken_keywords = [k.lower() for k in g["spoken_names"]]
        for w in words:
            w_text = w["word"].lower()
            if any(k in w_text or w_text in k for k in spoken_keywords):
                match_time = w["start"]
                break
        game_start_times.append(match_time)

    # If first game is found, clamp hook to 2.5-4.0s
    first_game_time = game_start_times[0] if game_start_times and game_start_times[0] else 3.5
    hook_end = max(2.5, min(4.0, first_game_time))

    # Determine game block boundaries
    # Each game block should last 4-7 s. If not matched, split evenly.
    game_boundaries = []
    prev_end = hook_end
    cta_duration = 5.0
    cta_start = vo_duration - cta_duration

    for i in range(num_games):
        st = game_start_times[i]
        if st is None or st < prev_end or st > vo_duration - 4.0:
            # Distribute evenly
            remaining_time = max(1.0, cta_start - prev_end)
            block_len = remaining_time / (num_games - i)
            block_len = max(4.0, min(7.0, block_len))
            st = prev_end
            end_t = st + block_len
        else:
            if i + 1 < num_games and game_start_times[i + 1]:
                end_t = game_start_times[i + 1]
            else:
                end_t = max(st + 4.5, cta_start)

        # Clamp length to 4.0 - 7.0
        dur = end_t - st
        if dur < 4.0:
            end_t = min(vo_duration, st + 4.0)
        elif dur > 7.0:
            end_t = st + 7.0

        game_boundaries.append((st, end_t))
        prev_end = end_t

    cta_start = game_boundaries[-1][1] if game_boundaries else hook_end
    cta_end = vo_duration + END_PADDING_SECONDS  # video ends with the voiceover

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
        "captionY": 0.46
    })

    # GTA offset generator avoiding 0s
    gta_offsets = [4.2, 8.0, 2.0, 6.0, 10.0]

    # 2. GAME BLOCKS
    current_frame = hook_frames
    for i, g in enumerate(game_folders):
        st, et = game_boundaries[i]
        dur_sec = et - st
        dur_f = int(round(dur_sec * fps))

        # Check clips in game folder
        top_clip = g["path"] / "top.mp4"
        bottom_clip = g["path"] / "bottom.mp4"
        pub_logo = next(iter(sorted((PUBLIC_DIR / "games" / g["folder"]).glob("_logo.*"))), None)

        # Fallbacks as per spec
        all_mp4s = list(g["path"].glob("*.mp4"))
        if not top_clip.exists() and all_mp4s:
            top_clip = all_mp4s[0]
        if not bottom_clip.exists():
            if len(all_mp4s) > 1:
                bottom_clip = all_mp4s[1]
            else:
                bottom_clip = top_clip

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
            # It fades/scales in right when the reveal animation finishes.
            "logoEffect": {
                "type": "wiggleWave",
                "position": "center",
                "appearAfterFrames": min(reveal_frames, max(1, dur_f - 1)),
                "amplitude": LOGO_WAVE_AMPLITUDE,
                "speed": LOGO_WAVE_SPEED,
                "frequency": LOGO_WAVE_FREQUENCY
            }
        })
        current_frame += dur_f

    # 3. CTA BLOCK
    # Fill exactly up to the end of the voiceover so video and audio end together
    cta_frames = max(1, int(round(cta_end * fps)) - current_frame)
    cta_bg = "roblox.mp4" if (PUBLIC_DIR / "roblox.mp4").exists() or (PROJECT_PATH / "Roblox 1.mp4").exists() else "gta_background.mp4"
    blocks.append({
        "type": "cta",
        "startFrame": current_frame,
        "durationFrames": cta_frames,
        "gtaOffset": 7.0,
        "bgVideo": cta_bg,
        "captionY": 0.72
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

    # Save timeline
    with open(CODE_DIR / "src" / "timeline.json", "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)
    with open(OUTPUT_DIR / "timeline.json", "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)

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


def find_logo_source(game_path: Path):
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


def sync_public_assets():
    log("Syncing assets to Remotion public directory...")
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    # GTA background
    src_gta = PROJECT_PATH / "gta_background.mp4"
    if not src_gta.exists():
        src_gta = ENGINE_DIR / "gta_background.mp4"
    shutil.copy(src_gta, PUBLIC_DIR / "gta_background.mp4")

    # Extra gameplay backgrounds matching reference video if available
    extra_bgs = [
        ("Roblox 1.mp4", "roblox.mp4"),
        ("roblox.mp4", "roblox.mp4"),
        ("Fortnight.mp4", "fortnite.mp4"),
        ("fortnite.mp4", "fortnite.mp4"),
    ]
    for src_name, dst_name in extra_bgs:
        src_path = PROJECT_PATH / src_name
        if not src_path.exists():
            src_path = ENGINE_DIR / src_name
        if src_path.exists():
            shutil.copy(src_path, PUBLIC_DIR / dst_name)

    # Games
    pub_games = PUBLIC_DIR / "games"
    pub_games.mkdir(parents=True, exist_ok=True)
    for g_dir in GAMES_DIR.iterdir():
        if not g_dir.is_dir():
            continue
        dest = pub_games / g_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        for f in g_dir.iterdir():
            if f.is_file():
                shutil.copy(f, dest / f.name)
        logo_src = find_logo_source(g_dir)
        if logo_src:
            name = prepare_logo(logo_src, dest)
            log(f"Logo for '{g_dir.name}': {logo_src.name} -> {name}")
        else:
            log(f"WARNING: no logo image found in games/{g_dir.name} (the text title will be used)")
    log("Public assets synchronized.")


def render_remotion_video(raw_output: Path):
    log("Rendering video with Remotion CLI...")
    npx_bin = shutil.which("npx") or ("npx.cmd" if os.name == "nt" else "npx")
    cmd = [
        str(npx_bin), "--prefix", str(CODE_DIR), "remotion", "render",
        str(CODE_DIR / "src" / "index.ts"), "MainVideo",
        str(raw_output),
        f"--public-dir={PUBLIC_DIR}"
    ]
    subprocess.run(cmd, cwd=str(ENGINE_DIR), shell=(os.name == "nt"), check=True)
    log("Remotion render complete.")


def process_audio_and_mux(raw_video: Path, final_output: Path, total_duration: float):
    log("Normalizing audio to -14 LUFS and muxing...")
    norm_audio = OUTPUT_DIR / "normalized_audio.aac"
    vo = PROJECT_PATH / "voiceover.mp3"
    music = PROJECT_PATH / "music.mp3"

    pad = f",apad=pad_dur={END_PADDING_SECONDS}" if END_PADDING_SECONDS > 0 else ""
    fade_out_start = max(0.0, total_duration - 1.0)

    if music.exists():
        log("music.mp3 detected. Mixing under voiceover at -22 dB with 0.5s fade-in, 1.0s fade-out...")
        cmd_norm = [
            "ffmpeg", "-i", str(vo), "-i", str(music),
            "-filter_complex",
            f"[0:a]loudnorm=I=-14:LRA=11:TP=-1.5[vo];"
            f"[1:a]volume=-22dB,afade=t=in:ss=0:d=0.5,afade=t=out:st={fade_out_start}:d=1.0[bgm];"
            f"[vo][bgm]amix=inputs=2:duration=longest{pad}",
            "-t", str(total_duration),
            "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
            str(norm_audio), "-y"
        ]
    else:
        cmd_norm = [
            "ffmpeg", "-i", str(vo),
            "-af", f"loudnorm=I=-14:LRA=11:TP=-1.5{pad}",
            "-t", str(total_duration),
            "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
            str(norm_audio), "-y"
        ]
    subprocess.run(cmd_norm, check=True)

    log(f"Muxing {raw_video.name} and {norm_audio.name} into final.mp4...")
    cmd_mux = [
        "ffmpeg", "-i", str(raw_video), "-i", str(norm_audio),
        "-c:v", "copy", "-c:a", "copy",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest", str(final_output), "-y"
    ]
    subprocess.run(cmd_mux, check=True)
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


def main():
    log(f"Starting build for PROJECT_DIR: {PROJECT_PATH}")
    check_required_files()
    vo_file = PROJECT_PATH / "voiceover.mp3"
    vo_duration = get_audio_duration(vo_file)
    log(f"Voiceover duration: {vo_duration:.2f} s")

    sync_public_assets()
    transcription = transcribe_voiceover(vo_file)
    transcription = apply_script(transcription, vo_duration)   # uses script.txt if present
    timeline = build_timeline(transcription, vo_duration)

    raw_video = OUTPUT_DIR / "rendered_raw.mp4"
    force_render = "--force" in sys.argv or "-f" in sys.argv
    if raw_video.exists() and raw_video.stat().st_mtime < Path(__file__).stat().st_mtime:
        log("build_video.py changed since the last render -> forcing a fresh render.")
        force_render = True
    if force_render or not raw_video.exists():
        if raw_video.exists():
            raw_video.unlink()
        render_remotion_video(raw_video)
    else:
        log("rendered_raw.mp4 already exists. Re-using for muxing.")

    final_mp4 = OUTPUT_DIR / "final.mp4"
    process_audio_and_mux(raw_video, final_mp4, timeline["totalDuration"])
    export_preview_frames(final_mp4)

    log("=" * 60)
    log("BUILD COMPLETE!")
    log(f"Output Video: {final_mp4}")
    log(f"Duration: {timeline['totalDuration']} s")
    log("Block Timings:")
    for b in timeline["blocks"]:
        start_s = b["startFrame"] / 30.0
        end_s = (b["startFrame"] + b["durationFrames"]) / 30.0
        desc = b.get("title", b["type"])
        log(f"  [{b['type'].upper():7s}] {start_s:5.2f}s -> {end_s:5.2f}s : {desc}")
    log("=" * 60)


if __name__ == "__main__":
    main()
