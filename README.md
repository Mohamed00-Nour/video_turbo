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


## Local Video Turbo Studio

Double-click `start_studio.cmd`, or run:

```powershell
python video_studio.py
```

The studio opens at `http://127.0.0.1:8765`. Keep the launcher running while
editing/rendering. Opening the launcher again opens the existing studio and
leaves its active job running. Use `--port 8767` if another application occupies
that port, or `--no-browser` to start without opening a tab. The UI server uses Python's standard library;
rendering still uses the existing project requirements and Remotion installation.

Create a project, upload a voiceover, and paste the exact spoken script. Add
clips/screenshots and arrange your sections. New projects live under `projects/`
and are excluded from Git. Existing video folders alongside the engine appear
in the sidebar; **Open existing folder** can import another project. Opening a
folder only reads its assets; saving applies the editor settings to its config
and script. Unknown configuration settings are preserved. Local registry and
saved layout presets live under `output/` and are also excluded from Git.

The flexible editor handles any subject, with background-only, one-media,
stacked-media and title-card layouts. Mix layouts in one video, add labels,
choose contain/cover framing, adjust caption height, set clip offsets/zoom,
and optionally highlight an area with percentages of the media card. Save a
layout preset to reuse that arrangement in another project; media and start
cues are cleared in reusable presets. Showcase and comparison presets are
starting arrangements, not restrictions on video categories.

Sections can start at an explicit second or at a phrase in the spoken script.
Use one of those controls per section. The first section begins at zero, and
later sections must follow the recording order. Unspecified starts divide time
evenly between explicit anchors. A section ends when the next begins; the final
section runs to the end of the voiceover. Clips loop silently; the voiceover and
optional MP3 music supply the audio. A custom MP4 background replaces the main
background for that project, and the existing GTA/Roblox/Fortnite library remains
available. Missing secondary backgrounds fall back to the main background.

The Game series preset retains the existing game pipeline: add each game,
spoken-name aliases and a YouTube URL, or select uploaded MP4 top/bottom clips.
Logos are optional. Saving selected clips copies them into the corresponding
game folder. The UI runs preparation before building when YouTube sources are
present; its cache avoids unnecessary downloads.

The live layout preview illustrates the current section. **Render preview
frame** runs the actual caption alignment and renderer at your chosen second;
its first run can take time while the model loads. **Build video** saves the
project and runs the pipeline, shows stage/progress/logs, and provides playback
and download of the finished MP4. Editing is disabled during a job. Only one job
runs at a time because the existing renderer shares its generated assets and
timeline. **Cancel job** stops the job's process tree on Windows before a retry.
Do not run a separate CLI build concurrently with a studio job.

The same scripts still work directly with `--project`. Flexible projects store
sections in `config.json` instead of a fixed game list. For a still preview:

```powershell
python build_video.py --project "path/to/project" --preview-only --preview-at 3
```

Verify the studio and original pipeline:

```powershell
python -m unittest -v test_video_studio.py test_pipeline.py test_prepare_assets.py test_caption_alignment.py
```


## Optional AI brief import

Both workflows remain available. **New video** opens the manual editor for any
subject. **Import AI brief** creates a separate Game series project from a JSON
brief; it never replaces the project currently open. Every imported field can
be edited with the same manual controls, and uploaded media takes priority.

1. Click **Import AI brief**, then **Copy AI prompt**. Replace the idea, games and
   target length before sending the prompt to your AI. The prompt asks the AI to
   browse and verify gameplay sources, keep asset metadata outside the spoken
   script, and use null when a direct logo image is unavailable.
2. Paste its JSON or choose a local `.json` file. **Check brief** validates the
   structure, names, aliases and URL formats and shows a review before creation.
3. Click **Create project**, upload your recorded voiceover, then preview/build.
   The recorded words must match the imported script for accurate captions.

The standard import format is:

```json
{
  "project_name": "My next game video",
  "script": "Exact narration, including opening and closing",
  "games": [
    {
      "exact_name": "Game title",
      "spoken_names": ["Game name exactly as written in the narration"],
      "youtube_gameplay_url": "A complete, verified YouTube video URL",
      "logo_image_url": null
    }
  ]
}
```

Add one entry per game, in narration order. The studio's copied AI prompt uses
these field names. `logo_image_url` may contain a direct image URL or `null`.
The original shorter fields (`name`, `gameplay_url`, and `logo_url`) remain
supported, and the manual editor remains available. If both names for a field
are supplied, their values must match; conflicting names or links are rejected.

Replace the example gameplay placeholder with a real video URL. JSON code
fences are accepted. Only the `script` field supplies narration; additional
metadata is ignored. This import currently automates game-series metadata;
other subjects continue to use the flexible manual section editor.

Review checks the JSON and URL formats locally. During preparation, new
uncached gameplay sources from a brief are checked for availability using
metadata before any footage download starts. Availability cannot guarantee
that the footage shows the right game: use the review's **View gameplay** links
to inspect it. Existing clips and cached sources retain the original reuse
behavior. Downloading still extracts only the required gameplay sections.

`logo_image_url` accepts a direct PNG/JPG/WEBP (or other Pillow-readable raster image)
link from a public website. Preparation validates the actual image and converts
it to PNG. An invalid, unavailable or oversized logo produces a warning and
continues the video; upload a logo or correct its URL to replace it. Logos are
cached by URL, changed URLs refresh generated logos, and manual images are
preserved. Direct logo links need no IGDB credentials. The game editor also has
an image URL field for manually entered projects. Backgrounds, caption styling,
preview/build and command-line workflows remain available.

Verify the import alongside the studio and pipeline:

```powershell
python -m unittest -v test_ai_brief.py test_video_studio.py test_pipeline.py test_prepare_assets.py test_caption_alignment.py
```
