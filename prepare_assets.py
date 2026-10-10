"""
prepare_assets.py — Auto-download game assets before running build_video.py
============================================================================

USAGE
-----
1.  Set PROJECT_DIR below to your project folder (same as in build_video.py).

2.  Create  <PROJECT_DIR>/games.txt  with one line per game:
        01_DDLC          | https://www.youtube.com/watch?v=XXXXXXX
        02_Sven_Co-op    | https://www.youtube.com/watch?v=YYYYYYY
        03_Trove         | https://www.youtube.com/watch?v=ZZZZZZZ

    - Left side  : folder name (will be created inside games/)
    - Right side : full YouTube URL for the gameplay video

3.  (Optional) Put IGDB_CLIENT_ID and IGDB_CLIENT_SECRET in the environment
    or in <PROJECT_DIR>/config.json under "igdb_client_id" / "igdb_client_secret"
    to enable automatic logo download from the IGDB game database.
    Register a free app at https://api-docs.igdb.com/#getting-started

4.  Run:
        python prepare_assets.py

5.  Then run your normal:
        python build_video.py

WHAT IT DOES PER GAME
---------------------
  ✅  Creates  games/<folder>/
  ✅  Downloads the YouTube video with yt-dlp  (best quality ≤ 1080p)
  ✅  Reads words.json / script.txt to estimate each game's clip duration
  ✅  Cuts  top.mp4    from ~25% into the downloaded video
  ✅  Cuts  bottom.mp4 from ~60% into the downloaded video  (different section)
  ✅  Downloads logo from IGDB  → logo.png  (falls back gracefully if API not set)

REQUIREMENTS
------------
  pip install yt-dlp requests
  ffmpeg must be on PATH (same requirement as build_video.py)
"""

from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import shutil
import urllib.request
from pathlib import Path

# ==========================================
# SETTINGS  (edit only this line per video)
# ==========================================
PROJECT_DIR = "G:/A Steady/Anti-vids/game 5"
# ==========================================

# ── Clip extraction ────────────────────────────────────────────────────────────
# top.mp4   is taken from  TOP_POSITION_RATIO   × video_length  into the video
# bottom.mp4 is taken from BOTTOM_POSITION_RATIO × video_length  into the video
# Both ratios avoid the very start and end (intros / outros / sponsor segments).
TOP_POSITION_RATIO    = 0.25   # 25 % into the video
BOTTOM_POSITION_RATIO = 0.60   # 60 % into the video

# Fallback clip duration (seconds) when we cannot read game timing from words.json
DEFAULT_CLIP_DURATION = 20.0

# Minimum / maximum clip duration we ever produce
MIN_CLIP_DURATION = 4.0
MAX_CLIP_DURATION = 60.0

# ── IGDB ───────────────────────────────────────────────────────────────────────
IGDB_CLIENT_ID     = os.environ.get("IGDB_CLIENT_ID", "")
IGDB_CLIENT_SECRET = os.environ.get("IGDB_CLIENT_SECRET", "")

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_PATH = Path(PROJECT_DIR).resolve()
ENGINE_DIR   = Path(__file__).resolve().parent
GAMES_DIR    = PROJECT_PATH / "games"
GAMES_TXT    = PROJECT_PATH / "games.txt"
OUTPUT_DIR   = PROJECT_PATH / "output"

# Ensure Python / ffmpeg are on PATH (mirrors build_video.py)
ADDITIONAL_PATHS = [
    r"C:\Users\COMPUMARTS\AppData\Local\Programs\Python\Python311",
    r"C:\Users\COMPUMARTS\AppData\Local\Programs\Python\Python311\Scripts",
    r"C:\Users\COMPUMARTS\AppData\Local\Microsoft\WinGet\Links",
]
for _p in ADDITIONAL_PATHS:
    if _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _p + ";" + os.environ.get("PATH", "")
os.environ["PYTHONIOENCODING"] = "utf-8"


def log(msg: str) -> None:
    print(f"[PREPARE] {msg}", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# games.txt parser
# ──────────────────────────────────────────────────────────────────────────────

def parse_games_txt() -> list[dict]:
    """
    Returns a list of dicts: {folder, url, game_name}
    Lines starting with # are comments. Blank lines are skipped.
    Format:  01_DDLC | https://youtube.com/watch?v=...
    """
    if not GAMES_TXT.exists():
        log(f"ERROR: games.txt not found at {GAMES_TXT}")
        log("Create it with lines like:  01_GameName | https://youtube.com/...")
        sys.exit(1)

    games = []
    for raw in GAMES_TXT.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "|" not in line:
            log(f"WARNING: skipping malformed line (missing |): {line!r}")
            continue
        folder_raw, url_raw = line.split("|", 1)
        folder = folder_raw.strip()
        url    = url_raw.strip()
        # Derive a clean game name from the folder (e.g. "01_Sven_Co-op" → "Sven Co-op")
        game_name = re.sub(r"^\d+[_\-\s]+", "", folder).replace("-", " ").replace("_", " ").strip()
        games.append({"folder": folder, "url": url, "game_name": game_name})

    if not games:
        log("ERROR: games.txt is empty or has no valid lines.")
        sys.exit(1)

    log(f"Found {len(games)} game(s) in games.txt.")
    return games


# ──────────────────────────────────────────────────────────────────────────────
# Clip duration estimation from existing transcription / words.json
# ──────────────────────────────────────────────────────────────────────────────

def _load_words_json() -> list[dict] | None:
    words_file = OUTPUT_DIR / "words.json"
    aligned    = OUTPUT_DIR / "words_aligned.json"
    target = aligned if aligned.exists() else words_file
    if not target.exists():
        return None
    with open(target, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("words", [])


def estimate_game_durations(games: list[dict]) -> list[float]:
    """
    Try to read words.json to estimate how long each game's block is.
    Falls back to DEFAULT_CLIP_DURATION if the file is not available yet.
    """
    words = _load_words_json()
    if not words:
        log("words.json not found — using default clip duration for all games.")
        return [DEFAULT_CLIP_DURATION] * len(games)

    total_duration = words[-1]["end"] if words else 0.0

    # Try to find each game's mention in the transcript to get timing
    game_start_times: list[float | None] = []
    for g in games:
        keywords = g["game_name"].lower().split()
        found = None
        for w in words:
            w_lc = w["word"].lower()
            if any(k in w_lc or w_lc in k for k in keywords if len(k) > 2):
                found = w["start"]
                break
        game_start_times.append(found)

    # Build durations from start → next start (or end of voiceover)
    hook_end    = 3.5
    cta_seconds = 5.0
    cta_start   = total_duration - cta_seconds

    durations = []
    prev_end = hook_end
    for i, st in enumerate(game_start_times):
        if st is None or st < prev_end:
            # Distribute remaining time evenly
            remaining = max(1.0, cta_start - prev_end)
            dur = remaining / (len(games) - i)
        else:
            next_st = next((t for t in game_start_times[i + 1:] if t is not None), cta_start)
            dur = next_st - st

        dur = max(MIN_CLIP_DURATION, min(MAX_CLIP_DURATION, dur))
        durations.append(round(dur, 2))
        prev_end = (st or prev_end) + dur

    log("Estimated clip durations (seconds):")
    for g, d in zip(games, durations):
        log(f"  {g['folder']}: {d:.1f}s")
    return durations


# ──────────────────────────────────────────────────────────────────────────────
# ffprobe — get video duration
# ──────────────────────────────────────────────────────────────────────────────

def get_video_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(json.loads(res.stdout)["format"]["duration"])
    except Exception as e:
        log(f"WARNING: could not read duration of {path.name}: {e}")
        return 0.0


# ──────────────────────────────────────────────────────────────────────────────
# yt-dlp — download YouTube video
# ──────────────────────────────────────────────────────────────────────────────

def download_youtube(url: str, dest_dir: Path) -> Path | None:
    """
    Download the best quality video (≤1080p) to dest_dir.
    Returns the path of the downloaded file, or None on failure.
    """
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        log("ERROR: yt-dlp is not installed. Run:  pip install yt-dlp")
        sys.exit(1)

    out_template = str(dest_dir / "raw_gameplay.%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--format", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--output", out_template,
        "--no-playlist",
        "--quiet", "--progress",
        url
    ]
    log(f"  Downloading: {url}")
    result = subprocess.run(cmd, cwd=str(dest_dir))
    if result.returncode != 0:
        log("  WARNING: yt-dlp reported an error. Trying generic fallback format...")
        cmd_fallback = [
            sys.executable, "-m", "yt_dlp",
            "--format", "best[ext=mp4]/best",
            "--output", out_template,
            "--no-playlist",
            "--quiet", "--progress",
            url
        ]
        result = subprocess.run(cmd_fallback, cwd=str(dest_dir))
        if result.returncode != 0:
            log("  ERROR: Download failed. Check the URL and your internet connection.")
            return None

    # Find the downloaded file
    candidates = list(dest_dir.glob("raw_gameplay.*"))
    if not candidates:
        log("  ERROR: Download completed but file not found.")
        return None
    return candidates[0]


# ──────────────────────────────────────────────────────────────────────────────
# ffmpeg — cut a clip
# ──────────────────────────────────────────────────────────────────────────────

def cut_clip(src: Path, start_sec: float, duration: float, dest: Path) -> bool:
    """Cut a clip from src starting at start_sec with given duration into dest."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(round(start_sec, 3)),
        "-i", str(src),
        "-t",  str(round(duration, 3)),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(dest)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        log(f"  WARNING: ffmpeg error cutting {dest.name}")
        if res.stderr:
            log(f"  {res.stderr[-300:]}")
        return False
    return True


def extract_clips(raw_video: Path, clip_duration: float, game_dir: Path) -> tuple[bool, bool]:
    """
    Extract top.mp4 and bottom.mp4 from two different sections of raw_video.
    Returns (top_ok, bottom_ok).
    """
    vid_len = get_video_duration(raw_video)
    if vid_len < 10:
        log(f"  WARNING: video is very short ({vid_len:.1f}s), clips may be truncated.")

    safe_len = vid_len * 0.85  # avoid last 15 % (outros/end screens)

    # top.mp4: from TOP_POSITION_RATIO into the safe zone
    top_start = vid_len * TOP_POSITION_RATIO
    top_start = max(0.0, min(top_start, safe_len - clip_duration))

    # bottom.mp4: from BOTTOM_POSITION_RATIO into the safe zone
    bottom_start = vid_len * BOTTOM_POSITION_RATIO
    bottom_start = max(top_start + clip_duration + 1.0,  # must start after top ends
                       min(bottom_start, safe_len - clip_duration))

    log(f"  Video length: {vid_len:.1f}s")
    log(f"  top.mp4    : {top_start:.1f}s → {top_start + clip_duration:.1f}s ({clip_duration:.1f}s)")
    log(f"  bottom.mp4 : {bottom_start:.1f}s → {bottom_start + clip_duration:.1f}s ({clip_duration:.1f}s)")

    top_path    = game_dir / "top.mp4"
    bottom_path = game_dir / "bottom.mp4"

    top_ok    = cut_clip(raw_video, top_start,    clip_duration, top_path)
    bottom_ok = cut_clip(raw_video, bottom_start, clip_duration, bottom_path)

    return top_ok, bottom_ok


# ──────────────────────────────────────────────────────────────────────────────
# IGDB logo download
# ──────────────────────────────────────────────────────────────────────────────

def _igdb_token(client_id: str, client_secret: str) -> str | None:
    url  = f"https://id.twitch.tv/oauth2/token?client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())["access_token"]
    except Exception as e:
        log(f"  WARNING: could not get IGDB token: {e}")
        return None


def _igdb_query(endpoint: str, body: str, client_id: str, token: str) -> list:
    req = urllib.request.Request(
        f"https://api.igdb.com/v4/{endpoint}",
        data=body.encode(),
        headers={
            "Client-ID":     client_id,
            "Authorization": f"Bearer {token}",
            "Content-Type":  "text/plain",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log(f"  WARNING: IGDB query failed: {e}")
        return []


def download_logo_igdb(game_name: str, dest: Path, client_id: str, client_secret: str) -> bool:
    """Download the best logo/cover for game_name from IGDB. Returns True on success."""
    token = _igdb_token(client_id, client_secret)
    if not token:
        return False

    # Search for the game
    search_results = _igdb_query(
        "games",
        f'search "{game_name}"; fields id,name,cover; limit 5;',
        client_id, token
    )
    if not search_results:
        log(f"  WARNING: IGDB — no results for '{game_name}'")
        return False

    # Pick the first result that has a cover
    cover_id = None
    for r in search_results:
        if r.get("cover"):
            cover_id = r["cover"]
            log(f"  IGDB match: {r.get('name', game_name)}")
            break

    if cover_id is None:
        log(f"  WARNING: IGDB — no cover image found for '{game_name}'")
        return False

    # Get the cover image URL
    covers = _igdb_query(
        "covers",
        f"fields image_id; where id = {cover_id};",
        client_id, token
    )
    if not covers or "image_id" not in covers[0]:
        return False

    image_id  = covers[0]["image_id"]
    # t_cover_big = 264×374, t_1080p = 1920×1080
    image_url = f"https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.png"

    try:
        urllib.request.urlretrieve(image_url, str(dest))
        log(f"  Logo saved: {dest.name}")
        return True
    except Exception as e:
        log(f"  WARNING: could not download IGDB logo: {e}")
        return False


def get_igdb_credentials(config: dict) -> tuple[str, str]:
    cid = config.get("igdb_client_id", IGDB_CLIENT_ID).strip()
    sec = config.get("igdb_client_secret", IGDB_CLIENT_SECRET).strip()
    return cid, sec


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg = PROJECT_PATH / "config.json"
    if cfg.exists():
        with open(cfg, encoding="utf-8") as f:
            return json.load(f)
    return {}


def main() -> None:
    log(f"Starting asset preparation for: {PROJECT_PATH}")
    config  = load_config()
    games   = parse_games_txt()
    GAMES_DIR.mkdir(parents=True, exist_ok=True)

    # Estimate per-game clip durations from existing transcription (if available)
    durations = estimate_game_durations(games)

    igdb_id, igdb_secret = get_igdb_credentials(config)
    igdb_available = bool(igdb_id and igdb_secret)
    if not igdb_available:
        log("IGDB credentials not set — logos will be skipped.")
        log("  Add igdb_client_id / igdb_client_secret to config.json, or set environment vars.")

    for game, clip_dur in zip(games, durations):
        folder   = game["folder"]
        url      = game["url"]
        name     = game["game_name"]
        game_dir = GAMES_DIR / folder

        log("")
        log(f"{'-'*60}")
        log(f"Processing: {folder}  ({name})")
        log(f"{'-'*60}")

        game_dir.mkdir(parents=True, exist_ok=True)

        # ── 1. Download YouTube video ──────────────────────────────────────
        raw_video = next(iter(sorted(game_dir.glob("raw_gameplay.*"))), None)
        if raw_video and raw_video.exists():
            log(f"  raw_gameplay already exists ({raw_video.name}), skipping download.")
        else:
            raw_video = download_youtube(url, game_dir)
            if raw_video is None:
                log(f"  SKIPPING {folder} — download failed.")
                continue

        # ── 2. Extract top.mp4 and bottom.mp4 ─────────────────────────────
        top_exists    = (game_dir / "top.mp4").exists()
        bottom_exists = (game_dir / "bottom.mp4").exists()

        if top_exists and bottom_exists:
            log("  top.mp4 and bottom.mp4 already exist, skipping clip extraction.")
        else:
            top_ok, bottom_ok = extract_clips(raw_video, clip_dur, game_dir)
            if not top_ok:
                log(f"  WARNING: top.mp4 could not be created for {folder}")
            if not bottom_ok:
                log(f"  WARNING: bottom.mp4 could not be created for {folder}")

        # ── 3. Download logo from IGDB ─────────────────────────────────────
        logo_dest = game_dir / "logo.png"
        webp_dest = game_dir / "logo.webp"
        if logo_dest.exists() or webp_dest.exists():
            log("  Logo already exists, skipping.")
        elif igdb_available:
            ok = download_logo_igdb(name, logo_dest, igdb_id, igdb_secret)
            if not ok:
                log(f"  Could not download logo for '{name}'. Add it manually as logo.png.")
        else:
            log("  Logo skipped (no IGDB credentials).")

    log("=" * 60)
    log("Asset preparation complete!")
    log("You can now run:  python build_video.py")
    log("=" * 60)


if __name__ == "__main__":
    main()
