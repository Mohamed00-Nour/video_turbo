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

Pass the same `--project` folder to both scripts. You can also keep using the `PROJECT_DIR` defaults at the top of the scripts.

```text
your-video-project/
  voiceover.mp3          # Also accepts voiceover.wav, M4A, FLAC, AAC, OGG and "voice over"
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
python prepare_assets.py --project "G:\A Steady\Anti-vids\game 5"
```

Asset preparation checks existing `top.mp4` / `bottom.mp4` first. For missing
clips, it reuses local `raw_gameplay` footage or downloads only the required
sections around 25% and 60% of the source video. New clips are video-only H.264,
using the best available video format up to 1080p. Actual network savings depend
on the source stream and keyframe spacing.

Clips are shared across projects through `output/gameplay_cache` beside
`prepare_assets.py`. Cache entries depend on the source video, section position,
duration, and encoding settings. This generated cache is excluded from Git.
Automatically generated clips have a local `.gameplay_manifest.json`. They are
refreshed when their URL, requested duration, position, or encoding settings
change. Existing clips without a manifest and manually replaced clips are kept.
Legacy untracked `raw_gameplay` footage is assumed to match its current URL;
remove it when changing that URL before its first managed preparation.

When a voiceover is present, asset preparation transcribes it once and uses the
same timing planner as the builder, including Arabic and multiword `spoken_names`.
The builder then reuses that transcription. Without a voiceover, preparation
falls back to 20-second clips; rerun after adding the voiceover to adjust generated
clip lengths. A failed preparation exits with a nonzero status.

For IGDB logo downloads, provide `IGDB_CLIENT_ID` and `IGDB_CLIENT_SECRET` as environment variables. Keep credentials out of committed configuration files.

## Build

```powershell
python build_video.py --project "G:\A Steady\Anti-vids\game 5" --no-preview
```

The final video is saved to `<PROJECT_DIR>/output/final.mp4`, with preview frames and caption data in the output folder. The caption timeline is generated at `code/src/timeline.json` before rendering. Media, generated timelines, downloaded fonts, and installed dependencies are excluded from Git.

Use `--force` to render again, `--retranscribe` to request fresh transcription,
and omit `--no-preview` to export JPEG previews every second. Transcription and
render manifests detect changed input files automatically. Existing caches
without validation metadata are rebuilt once. Render reuse includes the timeline,
React components, configuration effects, and synchronized asset signatures.
Media signatures use file size and modification time to avoid hashing large
videos; voiceover transcription uses the audio content hash.

Game blocks follow detected spoken names; missing starts are interpolated between
known starts. Short voiceovers keep all blocks within the recording duration.
Short gameplay and background videos loop to cover their blocks. Asset sync copies
only selected clips and logos, skips unchanged copies, and removes obsolete media
from the generated Remotion public folder. Original project media is preserved.

The complete voice/music mix is normalized in two passes to -14 LUFS with a
-1.5 dB true-peak target. Music loops if it is shorter than the video, with fades
at the start and end. Unchanged normalized mixes are cached.

When `script.txt` is present, captions align the supplied text directly to the voiceover using the installed Whisper model's audio attention. This includes words omitted by transcription, such as English game names in Arabic narration. The text must match what you actually said. Short recordings align in one pass; longer ones use transcription to locate bounded audio windows. Several consecutive unplaced words stop the build with a clear error instead of producing guessed captions. Direct alignment is cached in `output/words_aligned.json` and refreshes when the audio, script, model or relevant timing inputs change. Without a script, captions use the transcription's word timestamps. `output/words.json` caches transcription and refreshes when the voiceover content changes. Scripts that cannot fit at least one frame per caption are rejected.

## Verify caption alignment

```powershell
python -m unittest -v test_caption_alignment.py
```

## Verify gameplay preparation

```powershell
python -m unittest -v test_prepare_assets.py
```

## Project settings

The optional `config.json` accepts `captions_in_game_blocks` (default `true`) and
`hook_caption_y`, `game_caption_y`, `cta_caption_y` positions as fractions of the
video height. For example, `0.72` means 72% down the frame. It also accepts
`hook_seconds` (default 3.5), `cta_seconds` (default 5), `end_padding_seconds`
(default 0), and `whisper_model` (default `large-v3`). Hook/CTA fallback durations
shrink for short recordings. Spoken game names take precedence over the fallback
hook duration. Use aliases matching the recorded words in each game's
`spoken_names` list.

## Verify the pipeline

```powershell
python -m unittest -v test_pipeline.py test_prepare_assets.py test_caption_alignment.py
```
