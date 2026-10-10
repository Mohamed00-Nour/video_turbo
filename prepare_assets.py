"""
prepare_assets.py — Auto-download game assets before running build_video.py
============================================================================

USAGE
-----
1.  Pass --project to both scripts, or set their PROJECT_DIR defaults.

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
        python prepare_assets.py --project "path/to/project"

5.  Then run your normal:
        python build_video.py --project "path/to/project"

WHAT IT DOES PER GAME
---------------------
  ✅  Creates  games/<folder>/
  ✅  Downloads only the two needed sections (video only, best quality ≤ 1080p)
  ✅  Reads words.json to estimate each game's clip duration
  ✅  Cuts  top.mp4    from ~25% into the source video
  ✅  Cuts  bottom.mp4 from ~60% into the source video  (different section)
  ✅  Downloads logo from IGDB  → logo.png  (falls back gracefully if API not set)

Existing clips are checked before any network access. New clips are cached in
output/gameplay_cache beside this script, so other projects can reuse them.
Existing raw_gameplay files are reused locally; new full videos are not downloaded.

REQUIREMENTS
------------
  pip install yt-dlp requests
  ffmpeg must be on PATH (same requirement as build_video.py)
"""

from __future__ import annotations
import hashlib
import json
import argparse
import math
import os
import re
import subprocess
import sys
import shutil
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from pipeline_common import file_signature, fingerprint, read_cache, write_json, voiceover_path, plan_game_timing

# ==========================================
# SETTINGS  (edit only this line per video)
# ==========================================
PROJECT_DIR = "G:/A Steady/Anti-vids/game 6"
# ==========================================

# ── Clip extraction ────────────────────────────────────────────────────────────
# top.mp4   is taken from  TOP_POSITION_RATIO   × video_length  into the video
# bottom.mp4 is taken from BOTTOM_POSITION_RATIO × video_length  into the video
# Both ratios avoid the very start and end (intros / outros / sponsor segments).
TOP_POSITION_RATIO    = 0.25   # 25 % into the video
BOTTOM_POSITION_RATIO = 0.60   # 60 % into the video

# Fallback duration when no voiceover is available yet
DEFAULT_CLIP_DURATION = 20.0

# ── IGDB ───────────────────────────────────────────────────────────────────────
IGDB_CLIENT_ID     = os.environ.get("IGDB_CLIENT_ID", "")
IGDB_CLIENT_SECRET = os.environ.get("IGDB_CLIENT_SECRET", "")

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_PATH = Path(PROJECT_DIR).resolve()
ENGINE_DIR   = Path(__file__).resolve().parent
GAMES_DIR    = PROJECT_PATH / "games"
GAMES_TXT    = PROJECT_PATH / "games.txt"
OUTPUT_DIR   = PROJECT_PATH / "output"
# Shared by all projects using this script; generated media stays out of Git.
GAMEPLAY_CACHE_DIR = ENGINE_DIR / "output" / "gameplay_cache"
VIDEO_FORMAT = "bestvideo[height<=1080][ext=mp4]/bestvideo[height<=1080]"
CLIP_CACHE_VERSION = 1

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


def configure_project(project: Path) -> None:
    global PROJECT_PATH, GAMES_DIR, GAMES_TXT, OUTPUT_DIR
    PROJECT_PATH = Path(project).resolve()
    GAMES_DIR = PROJECT_PATH / "games"
    GAMES_TXT = PROJECT_PATH / "games.txt"
    OUTPUT_DIR = PROJECT_PATH / "output"


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
        if not folder or not url:
            raise ValueError("Each games.txt line needs a folder and a URL.")
        path = (GAMES_DIR / folder).resolve()
        if not path.is_relative_to(GAMES_DIR.resolve()):
            raise ValueError(f"Game folder must be inside games/: {folder}")
        games.append({"folder": folder, "url": url, "game_name": game_name})

    if not games:
        log("ERROR: games.txt is empty or has no valid lines.")
        sys.exit(1)

    log(f"Found {len(games)} game(s) in games.txt.")
    return games


# ──────────────────────────────────────────────────────────────────────────────
# Clip duration estimation from existing transcription / words.json
# ──────────────────────────────────────────────────────────────────────────────

def estimate_game_durations(games: list[dict]) -> list[float]:
    """Use exactly the builder's timing, transcribing once if voiceover is ready."""
    config = load_config()
    try:
        voice = voiceover_path(PROJECT_PATH)
    except FileNotFoundError:
        log("Voiceover not available yet; using default clip duration. Rerun after adding it.")
        return [DEFAULT_CLIP_DURATION] * len(games)
    import build_video as builder
    builder.configure_project(PROJECT_PATH)
    duration = builder.get_audio_duration(voice)
    transcription = builder.transcribe_voiceover(voice)
    transcription = builder.apply_script(transcription, duration)
    specs = config.get("games") or [{**game, "title": game["game_name"],
                                     "spoken_names": [game["game_name"]]} for game in games]
    plan = plan_game_timing(specs, transcription["words"], duration, config)
    durations = {spec["folder"]: (end - start) / plan["fps"]
                 for spec, (start, end) in zip(specs, plan["gameRanges"])}
    if any(game["folder"] not in durations for game in games):
        raise ValueError("games.txt contains a folder missing from config.json games. Align the game lists.")
    return [durations[game["folder"]] for game in games]


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
# Gameplay sections and shared cache
# ──────────────────────────────────────────────────────────────────────────────

def clip_is_ready(path: Path, duration: float | None = None) -> bool:
    """Reject empty/broken files and incomplete cached downloads."""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    actual = get_video_duration(path)
    if not math.isfinite(actual) or actual <= 0:
        return False
    return duration is None or abs(actual - duration) <= 0.25


def source_cache_key(url: str) -> str:
    """Equivalent YouTube links share a cache; other sources use their full URL."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    video_id = None
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        parts = parsed.path.strip("/").split("/")
        if not video_id and len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            video_id = parts[1]
    identity = f"youtube:{video_id}" if video_id else url
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


def clip_cache_path(source_key: str, start: float, duration: float) -> Path:
    settings = [CLIP_CACHE_VERSION, VIDEO_FORMAT, source_key,
                round(float(start), 3), round(float(duration), 3), "h264-crf23-fast-noaudio"]
    digest = hashlib.sha256(json.dumps(settings).encode()).hexdigest()[:24]
    return GAMEPLAY_CACHE_DIR / f"{digest}.mp4"


def clip_ranges(video_duration: float, requested: float) -> tuple[float, float, float]:
    """Keep the usual 25% / 60% positions, bounding short videos at EOF."""
    if not math.isfinite(video_duration) or video_duration <= 0:
        raise ValueError("Source video has no usable duration (live streams are unsupported).")
    if not math.isfinite(requested) or requested <= 0:
        raise ValueError("Clip duration must be positive.")
    duration = round(min(requested, video_duration), 3)
    latest_start = max(0.0, video_duration - duration)
    safe_start = max(0.0, video_duration * 0.85 - duration)
    top = max(0.0, min(video_duration * TOP_POSITION_RATIO, safe_start))
    bottom = min(latest_start, max(top + duration + 1.0,
                                  min(video_duration * BOTTOM_POSITION_RATIO, safe_start)))
    return round(top, 3), round(bottom, 3), duration


def fetch_video_info(url: str) -> dict:
    import yt_dlp
    # Metadata only: no video or audio is downloaded here.
    with yt_dlp.YoutubeDL({"format": VIDEO_FORMAT, "noplaylist": True,
                          "quiet": True, "socket_timeout": 30}) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info or info.get("is_live") or not info.get("duration"):
        raise ValueError("Use an uploaded gameplay video with a known duration, not a live stream.")
    clip_ranges(float(info["duration"]), DEFAULT_CLIP_DURATION)
    return info


def copy_clip(src: Path, dest: Path) -> None:
    """Publish only complete files; an interrupted copy cannot become a cache hit."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".clip-", dir=dest.parent) as work:
        pending = Path(work) / "clip.mp4"
        shutil.copyfile(src, pending)
        pending.replace(dest)


def cut_clip(src: Path, start_sec: float, duration: float, dest: Path) -> bool:
    """Precisely cut an existing local video, encoding only the requested section."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".clip-", dir=dest.parent) as work:
        pending = Path(work) / "clip.mp4"
        cmd = [
            "ffmpeg", "-nostdin", "-y", "-ss", str(start_sec), "-i", str(src),
            "-t", str(duration), "-map", "0:v:0", "-an",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(pending),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not clip_is_ready(pending, duration):
            log(f"  WARNING: ffmpeg could not cut {dest.name}")
            if res.stderr:
                log(f"  {res.stderr[-300:]}")
            return False
        pending.replace(dest)
    return True


def download_youtube(info: dict, start: float, duration: float, dest: Path) -> bool:
    """yt-dlp/FFmpeg seek into the remote video and download just one section."""
    import copy
    import yt_dlp
    from yt_dlp.utils import download_range_func

    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=dest.parent) as work:
        pending = Path(work) / "clip.mp4"
        options = {
            "format": VIDEO_FORMAT,
            "outtmpl": str(pending),
            "noplaylist": True,
            "quiet": True,
            "socket_timeout": 30,
            "download_ranges": download_range_func(None, [(start, start + duration)]),
            # Re-encode this small section once for accurate, playable H.264 cuts.
            "force_keyframes_at_cuts": True,
            "external_downloader_args": {"ffmpeg_o": [
                "-t", str(duration), "-map", "0:v:0", "-an",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4",
            ]},
            "fixup": "never",
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            # Reuse freshly resolved stream URLs for both clips; do not extract twice.
            ydl.process_ie_result(copy.deepcopy(info), download=True)
        if not clip_is_ready(pending, duration):
            log("  WARNING: section download is incomplete; it will not be cached.")
            return False
        pending.replace(dest)
    return True


def prepare_gameplay(url: str, clip_duration: float, game_dir: Path) -> bool:
    """Reuse finished clips/cache/local footage before requesting remote sections."""
    game_dir.mkdir(parents=True, exist_ok=True)
    paths = [game_dir / "top.mp4", game_dir / "bottom.mp4"]
    source_key = source_cache_key(url)
    request = fingerprint({"source": source_key, "duration": float(clip_duration),
                           "top": TOP_POSITION_RATIO, "bottom": BOTTOM_POSITION_RATIO,
                           "format": VIDEO_FORMAT, "version": CLIP_CACHE_VERSION})
    manifest_path = game_dir / ".gameplay_manifest.json"
    manifest = read_cache(manifest_path)
    records = manifest.get("clips", {})
    ready = []
    for path in paths:
        valid = clip_is_ready(path)
        record = records.get(path.name, {})
        generated = valid and record.get("output") == file_signature(path)
        ready.append(valid and (not generated or record.get("request") == request))
        if valid and record and not generated:
            records.pop(path.name, None)  # A user replaced this generated clip.
    if all(ready):
        log("  top.mp4 and bottom.mp4 are ready; skipping gameplay download.")
        return True

    GAMEPLAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    metadata_path = GAMEPLAY_CACHE_DIR / f"{source_key}.json"
    raw_video = next((p for p in sorted(game_dir.glob("raw_gameplay.*"))
                      if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
                      and clip_is_ready(p)), None)
    if raw_video and manifest.get("rawSource", manifest.get("source")) not in (None, source_key):
        log("  URL changed; old raw_gameplay footage will not be reused.")
        raw_video = None
    info = None
    try:
        if raw_video:
            log(f"  Reusing local footage: {raw_video.name}")
            video_duration = get_video_duration(raw_video)
            manifest["rawSource"] = source_key
        else:
            try:
                video_duration = float(json.loads(metadata_path.read_text(encoding="utf-8"))["duration"])
                clip_ranges(video_duration, clip_duration)
            except (OSError, ValueError, KeyError, TypeError):
                log("  Reading YouTube video duration (metadata only)...")
                info = fetch_video_info(url)
                video_duration = float(info["duration"])
                write_json(metadata_path, {"duration": video_duration})

        top, bottom, duration = clip_ranges(video_duration, clip_duration)
        log(f"  Video length: {video_duration:.1f}s; clip duration: {duration:.1f}s")
        for i, (dest, start) in enumerate(zip(paths, [top, bottom])):
            if ready[i]:
                log(f"  {dest.name} already exists, keeping it.")
                continue
            cached = clip_cache_path(source_key, start, duration)
            if clip_is_ready(cached, duration):
                log(f"  Reusing cached {dest.name} ({start:.1f}s - {start + duration:.1f}s).")
            elif raw_video:
                if not cut_clip(raw_video, start, duration, cached):
                    continue
            else:
                if info is None:
                    info = fetch_video_info(url)
                log(f"  Downloading {dest.name} only: {start:.1f}s - {start + duration:.1f}s (no audio).")
                if not download_youtube(info, start, duration, cached):
                    continue
            copy_clip(cached, dest)
            records[dest.name] = {"request": request, "output": file_signature(dest)}
            manifest["source"] = source_key
            manifest["clips"] = records
            write_json(manifest_path, manifest)
            ready[i] = True
    except ImportError:
        log("  ERROR: yt-dlp is not installed. Run: pip install yt-dlp")
    except Exception as e:
        log(f"  ERROR: gameplay preparation failed: {e}")
    return all(ready)


# IGDB logo download

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


def run_preparation() -> int:
    failures = 0
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

        # Check completed clips first, then cache / local footage / remote sections.
        if not prepare_gameplay(url, clip_dur, game_dir):
            failures += 1
            log(f"  WARNING: gameplay clips are incomplete for {folder}. Retry after resolving the error.")

        # Download logo from IGDB.
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
    if failures:
        log(f"Asset preparation incomplete: {failures} game(s) failed. Fix the errors and retry.")
        return 1
    log("Asset preparation complete! Run python build_video.py with the same --project.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prepare gameplay clips and logos.")
    parser.add_argument("--project", type=Path, default=PROJECT_PATH, help="Video project folder")
    args = parser.parse_args(argv)
    configure_project(args.project)
    try:
        return run_preparation()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        log(f"ERROR: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
