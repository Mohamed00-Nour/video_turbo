# Arabic Gaming Reel Builder

Build vertical gaming videos with Arabic voiceover, word-by-word captions, stacked gameplay clips, animated logos, and normalized audio. Python prepares assets and caption timing, Remotion renders the video, and FFmpeg mixes audio and creates the final MP4.

## Setup

Install Python 3.11 or newer, Node.js with npm, and FFmpeg. Make sure `ffmpeg` and `ffprobe` are on your PATH, then install dependencies:

```powershell
python -m pip install -r requirements.txt
npm ci --prefix code
```

The first transcription downloads the faster-whisper `large-v3` model and runs on the CPU. Model downloads and optional asset downloads require internet access.

## Prepare a video project

Set `PROJECT_DIR` in both `build_video.py` and `prepare_assets.py` to your local video project folder. The scripts currently point to the author's `game 4` folder; change that path for another computer or project.

```text
your-video-project/
  voiceover.mp3          # Also accepts "voice over.mp3"
  gta_background.mp4    # May instead live beside build_video.py
  script.txt            # Optional exact caption spelling, in spoken order
  music.mp3             # Optional background music
  config.json           # Optional style settings and game names
  games.txt             # Optional gameplay download list
  games/
    01_GameName/
      top.mp4
      bottom.mp4
      logo.png          # Optional; other image formats are supported
```

The checked-in `config.json` and `games.txt` are examples from existing projects. Adapt their folder names and game names to your video. Additional gameplay backgrounds and Lalezar font files may live in the project folder or beside the scripts. The builder downloads Lalezar if it is missing.

To download and trim gameplay using `games.txt`:

```powershell
python prepare_assets.py
```

For IGDB logo downloads, provide `IGDB_CLIENT_ID` and `IGDB_CLIENT_SECRET` as environment variables. Keep credentials out of committed configuration files.

## Build

```powershell
python build_video.py --force
```

The final video is saved to `<PROJECT_DIR>/output/final.mp4`, with preview frames and caption data in the output folder. The caption timeline is generated at `code/src/timeline.json` before rendering. Media, generated timelines, downloaded fonts, and installed dependencies are excluded from Git.

Captions use recorded word timestamps when available. If transcription misses a passage, the script estimates missing words' timing between matched words and logs a warning. These timings are approximate. `output/words.json` caches transcription; remove it when replacing the voiceover or when you need a new transcription.

## Verify caption alignment

```powershell
python -m unittest -v test_caption_alignment.py
```
