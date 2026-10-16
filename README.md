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
falls back to 20-second clips. After adding the voiceover, generated clips are
adjusted to the recording: when a cached starter clip covers the required section,
Studio trims it locally and preserves the starter cache, avoiding a second gameplay
download. Longer sections, changed sources or missing/broken cache files can still
require downloading footage. A failed preparation exits with a nonzero status.

For IGDB logo downloads, provide `IGDB_CLIENT_ID` and `IGDB_CLIENT_SECRET` as environment variables. Keep credentials out of committed configuration files.

## Build

```powershell
python build_video.py --project "G:\A Steady\Anti-vids\game 5" --no-preview
```

If Chrome times out while starting, the build or preview retries once with
verbose browser diagnostics. Other render failures stop immediately. If both
startup attempts time out, the job reports the browser error in its log.

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


## Automatic AI projects

**New video** defaults to **AI script & assets**, using **Google Gemini**.
OpenAI and Anthropic Claude are also available in the provider selector. Choose
**Manual layout** for the existing editor, or **Import JSON brief** to keep the
manual JSON workflow.

1. In the creation dialog, open **AI connection settings**, get an API key from
   the selected provider, paste it, and click **Save AI connection**. Model IDs
   can be changed if your account uses another compatible model. A message below
   the save button shows saving, success, or a save error. Saving stores the key
   locally; it does not verify the key or model with the provider. Saved keys are
   protected with Windows DPAPI for your Windows account; responses never return
   them to the browser. This uses the provider API and its quota or billing.
2. Enter a project name, game-series video idea and script language/dialect,
   then click **Create project**. The script has no fixed target length; the
   finished video follows the duration of your recorded voiceover.
3. Studio generates and saves the spoken script first. **No gameplay research,
   asset download or rendering starts before script approval.** Edit the script
   in **Voice & script**, and copy or download it for recording.
4. Click **Approve script & prepare assets**. Studio researches gameplay and
   optional logo sources, validates the JSON brief, saves `ai_brief.json`, and
   starts the existing asset preparer in the background. **Download JSON brief**
   exports the generated brief. Source availability is checked by preparation;
   AI-selected footage still needs your visual review for relevance.
5. Record and upload the voiceover while assets prepare. Uploading voiceover is
   allowed for that project during preparation; other project changes remain
   locked. Starter clips are prepared without reading the voiceover, avoiding
   a race with recording uploads. Final preparation uses the real recording to
   calculate clip lengths and caption timing.
6. When assets and voiceover are both ready, Studio automatically starts one
   video build. Review its finished MP4 and publish using the platform cards.
   Social publishing remains an explicit action.

Changing the approved script clears approval. Failed or interrupted AI steps
keep the project and script; use the visible retry action after resolving the
provider or source problem. Cancellation never automatically starts the next
step. Settings and workflow checkpoints are local, under `output/ai/` and each
project's `ai_workflow.json`; API keys are excluded from project exports.

To keep a repeatable format, choose **New series** in the creation dialog. Give
it a name such as **PC games** or **Mobile games**, choose its game platform and
default dialect, and paste your initial writing prompt into **Series
instructions**. You can paste a reference script too. Click **Save series**, or
create the first episode to save the settings automatically.

For later episodes, select that series and enter **Create one more episode** or
a specific topic in **This episode's idea**. Each series keeps its own
instructions, reference script and approved game history. Approving a script
saves it as the latest reference; successful asset research updates the game
list to the actual approved brief. Earlier game names and summaries of the ten
most recent approved episodes help the AI avoid repetition. You can inspect
recent episodes and edit the series instructions or reference in **Series
instructions & reference**. Changes apply to new episodes; retries use the
context saved when their project was created.

Choose **Standalone video (no series)** for a single video. It sends only that
video's idea and dialect and does not read or update series memory. Series are
saved locally in `output/ai/series.json`; the selected series context is sent
with script requests to the chosen provider. This is independent of ChatGPT
chat history and works with any of the supported providers.

Series are available before generating the first video. If **New series** is
disabled and Studio reports an older server version, close the running Studio
server and launch `start_studio.cmd` again to load the new backend. **Retry
loading series** checks the server again without clearing the video idea.
The launcher detects an older idle server and starts the updated Studio on the
next local port instead of reopening the old backend. Later launches reuse that
updated server. It leaves active generation or publishing jobs alone.

Provider implementations use the official [Gemini Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview),
[OpenAI Responses API](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses),
and [Claude Messages API](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

## Project library actions

Open the three-dot menu beside a project in the left sidebar. **Edit project**
opens its workspace and lets you rename it without discarding unsaved edits.
**Delete project** shows a confirmation and removes the entry from the library.
Projects stored directly in Studio's `projects/` folder are moved to the
recoverable `output/deleted_projects/<project-id>/` folder. Projects opened from
other folders keep their original files. Removed entries stay removed after
restart and automatic discovery; **Open existing folder** can add an external
folder again. Rename and delete are blocked while a build, preparation or upload
is running.

## Optional AI brief import

Both workflows remain available. **New video ? Manual layout** opens the manual editor for any
subject. **Import JSON brief** creates a separate Game series project from a JSON
brief; it never replaces the project currently open. Every imported field can
be edited with the same manual controls, and uploaded media takes priority.

1. Click **Import JSON brief**, then **Copy AI prompt**. Replace the idea and games
   before sending the prompt to your AI. The prompt asks the AI to
   browse and verify gameplay sources, keep asset metadata outside the spoken
   script, and use null when a direct logo image is unavailable.
2. Paste its JSON or choose a local `.json` file. **Check brief** validates the
   structure, names, aliases and URL formats and shows a review before creation.
3. Click **Create project**. Your spoken script and game list are saved, and
   **Prepare assets** is available in **Voice & script**, including on older imports.
4. Click **Prepare assets** to prepare gameplay and logos while you record. No
   voiceover or provider API key is needed for this step. You can upload your
   voiceover while preparation runs; other editing is locked during the job.
5. Studio starts one video build automatically when both assets and voiceover
   are ready, regardless of which finishes first. **Build video** remains available
   for manual builds, including preparing assets as part of a build. The recorded
   words must match the imported script for accurate captions. Editing the script
   or game sources requires fresh preparation before automatic building.

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


## Publishing finished videos

Open a completed project and click **Publish video** beside the download button.
The panel previews `output/final.mp4` and saves a title, caption, hashtags and
posting options for that project. Metadata defaults to the project name and
script. The editor and command-line build workflow remain available.

| Destination | Available workflow |
| --- | --- |
| YouTube | Direct MP4 upload after Google app setup and channel connection; private, unlisted or public visibility. |
| Instagram Professional | Direct local MP4 publishing through the professional account linked to your Facebook Page. Existing Instagram Login connections can still publish from public HTTPS video links. Assisted upload is also available. |
| TikTok | Download the MP4, copy the caption, open TikTok's uploader and finish posting there. |
| Facebook Page | Direct local MP4 upload and confirmed Reel publishing after connecting a Page access token; no public video URL is required. |
| Facebook personal profile | Download the MP4, copy the caption, open Facebook's Reel creator and finish posting there. |

For a direct upload, open the platform card and click **Review & upload**.
The review controls appear inside that card with its posting details selected.
Watch the preview, check the review box, then click **Upload to YouTube**,
**Publish Instagram Reel** or **Publish Facebook Page Reel** in the card.
Each click starts one upload, and its progress appears in that platform card.
To start several destinations together, use **Publish to multiple platforms**:
select connected YouTube, Instagram and/or Facebook Page accounts, review the
posting details and settings shown for each, check the review box, then click
**Publish selected platforms**. The selection is validated before any upload
starts. Each platform uploads independently; one failure does not stop the
others. You can also start another platform while an upload is running.
Account changes and video editing stay locked until all uploads finish.
TikTok and Facebook profiles continue to use the assisted upload controls.
Switching destinations or changing posting options or the finished file clears
the review. A completed upload of the same file to the same platform
is blocked to prevent duplicate posts. Facebook Page uploads track the connected
Page ID, so publishing the same video to a different Page is allowed.

Progress and publishing history appear in the panel. Keep the Studio process
running until the upload finishes; closing the panel is fine. YouTube recovers
transient connection failures by querying the existing upload session. Uploads
use 1 MiB chunks; status queries retry network failures and transient server
errors up to five times before reporting a safe error reason. A Studio
restart marks an unfinished attempt as interrupted. After an interrupted or
uncertain attempt, check the platform before retrying, since a remote upload
may have succeeded even when its response was lost. If the video appears in
YouTube Studio, paste its video link into **Check existing upload** in the job
panel. This makes read-only API checks and updates the local history only after
YouTube confirms processing is complete and the channel, title and file size
match. While YouTube is still processing, it asks you to wait rather than marking
the attempt successful. It never uploads another copy.

Facebook Page and local Instagram uploads automatically retry interrupted
transfers up to three attempts, waiting one and then two seconds before retrying.
A retry starts a new upload session before publication; progress shows the retry
number. If the finished file changes, the retry stops for a new review. Expired
tokens, permission errors and TLS certificate failures do not trigger retries.

If the connection drops after the publish request, Studio checks the existing
video/container up to three times using reads only. Confirmed publication marks
the job complete. An unconfirmed publish remains blocked from creating a new
copy. **Check existing upload** also retries interrupted status reads. When a
failed transfer is safe to restart, posting history offers **Retry upload**;
this opens the review controls before another upload starts. Retry counts and
publication checkpoints remain saved after a Studio restart.

Assisted uploads have **Copy caption**, **Open uploader** and **Mark published**
controls. Marking a post only records its optional post link in local history;
it does not upload anything. When posting inside Instagram, you can use your
existing **Share to Facebook** option. Instagram API publishing does not
guarantee that this native sharing setting applies.

### Connect YouTube

1. Create/select a project in [Google Cloud Console](https://console.cloud.google.com/).
   Enable **YouTube Data API v3** and configure the OAuth consent screen. If the
   app is in testing, add your Google account as a test user.
2. Create an OAuth client with application type **Desktop app**. Copy its client
   ID and client secret into **Account setup > YouTube**, then save.
3. Click **Connect channel**, select your Google account/channel and grant the
   requested upload/read permissions. Google returns to the local Studio
   callback displayed in the panel, and the connected channel name appears.
4. Try a **Private** upload first and inspect it in YouTube Studio before
   uploading publicly. Upload completion does not mean YouTube has finished
   processing the video.

The connection uses the installed-app loopback callback, OAuth state and PKCE.
Saved refresh tokens renew access where available. Google app testing status,
permissions and quota can require reconnecting or completing further Google
setup. See [Google's installed-app OAuth guide](https://developers.google.com/identity/protocols/oauth2/native-app)
and [YouTube upload documentation](https://developers.google.com/youtube/v3/docs/videos/insert).

### Connect Instagram

Your Instagram account must be **Professional** (Business or Creator). For
local MP4 uploads, link it to the Facebook Page you connected in Studio.

1. Enable Instagram access through **Facebook Login for Business** in your
   Meta app and authorize your professional Instagram account.
2. When generating the Facebook token, include `instagram_basic`,
   `instagram_content_publish`, and `pages_read_engagement`, in addition to
   the permissions needed for Facebook Page publishing. Adding permissions
   requires generating a fresh token; an existing token does not gain them.
3. Reconnect the Facebook Page with the updated token in **Account setup**.
4. In the Instagram card, click **Connect from Facebook Page**. Studio reads
   the linked account and its publishing eligibility before saving the connection.

After this one-time setup, Studio sends each finished MP4 directly to Meta.
The public video URL field is hidden. Review the local video, caption, hashtags,
and feed-sharing setting, then click **Publish Instagram Reel**. The Facebook
Page token remains protected in the local credential vault; Instagram references
that connection so refreshing the Page token also updates local Instagram access.

Studio saves the media container before transferring the file and records the
publish attempt before submitting it. If publication is uncertain, use
**Check existing upload** in posting history. This sends only a status request
and prevents a duplicate publish. Reconnect the original account to check its
previous uploads. **Also show this Reel on my Instagram feed** controls the
Instagram feed; it does not publish another copy to Facebook.

The setup panel also retains **Alternative: Instagram Login with a hosted
video**. This uses `instagram_business_basic` and
`instagram_business_content_publish`, an Instagram access token or OAuth
connection, and a public HTTPS URL for the finished MP4. Existing connections
continue to use that method until you connect through the Facebook Page.
Studio does not publicly host your video. Assisted download/copy/open Instagram
publishing remains available.

See [Meta's official local Instagram upload sample](https://github.com/fbsamples/reels_publishing_apis/tree/main/insta_reels_publishing_api_sample)
for the container/upload/publish flow, and [Meta's content publishing guide](https://developers.facebook.com/docs/instagram-platform/content-publishing/)
for account roles, permissions, and app review requirements.

### Connect a Facebook Page

Facebook Page publishing uses a **Page access token** issued by your Meta app.
The Instagram token cannot authorize publishing to a Facebook Page. Your
Facebook personal profile remains available through assisted upload.

1. In [Meta apps](https://developers.facebook.com/apps/), add the **Manage
   everything on your Page** use case. If your current Instagram app cannot
   add that use case, create a separate app for Page publishing.
2. Open [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
   and select the Page publishing app. Authorize your Facebook account with
   `pages_show_list`, `pages_read_engagement` and `pages_manage_posts`, granting
   access to the Page you want to connect. For a Page in a business portfolio,
   also request `business_management` to list its Pages. Generate a new user
   token after adding permissions and authorize the intended business and Page.
   Your account needs permission to create content on that Page. During app
   development, use an account with the appropriate app role; publishing for
   other users may require App Review.
3. Extend the **User Access Token before requesting the Page token**. Open
   [Meta Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/),
   inspect the User token, and select **Extend Access Token** if available.
   Otherwise follow [Meta's long-lived token exchange guide](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived/).
   Copy the resulting long-lived User token back into Graph API Explorer.
4. With that **long-lived User token**, run
   `GET me/accounts?fields=id,name,access_token,tasks` and copy the
   **access_token for the intended Page** from the response. Check this Page
   token in the debugger before saving it. A Page token obtained from a
   temporary User token can expire within hours. Studio validates and stores
   pasted tokens; it does not extend temporary Meta tokens.
5. In Studio, open a completed project > **Publish video** > **Facebook Page**
   > **Connect Page / account setup**. Paste the Page token and click **Connect
   Page**. Studio detects its numeric Page ID and displays the Page name. The
   optional Page ID field checks that the token belongs to that exact Page.
6. Select **Facebook Page Reel**, confirm the displayed Page and posting
   details, review the final video, then click **Publish Facebook Page Reel**.
   Studio streams the local MP4 directly to Meta and waits for the publishing
   phase to complete before recording success. No Cloudflare link is needed.

Studio stores the video ID before requesting publication. If the finish response
is lost or Studio restarts, it blocks another upload of the same file to that
Page until the existing attempt is checked. Click **Check existing upload** on
its history entry: this only reads the video's status and checks Page ownership.
A confirmed published Reel updates history; ongoing processing asks you to wait.
A confirmed failed upload permits a new reviewed attempt. Upload and publication
requests are not repeated after a publish may have reached Meta. A confirmed
success remains successful if the later permalink lookup fails; a link using the confirmed video ID is shown.

Page tokens derived from long-lived User tokens have no fixed expiration date,
but Meta can still invalidate their access. Reconnect in account setup when
required. Instagram linked to the same Page automatically reuses the replacement
Page token; it does not need a separate reconnect unless the linked account or
Page changes.
See [Meta's Page Reel publishing sample](https://github.com/fbsamples/reels_publishing_apis/tree/main/fb_reels_publishing_api_sample)
for the upload protocol and required Page permissions.

### Local storage and verification

Publishing drafts, history, job state and account connections live in
`output/publishing/`, which is excluded from Git. On Windows, app secrets and
account tokens are protected with DPAPI for the Windows user that connected
them. On other systems, the credential file uses restricted local file
permissions. The browser receives account names and connection status, never
stored tokens or app secrets. Disconnect removes the saved account connection.

The publishing checks simulate provider responses and use temporary projects;
they do not upload to real accounts:

```powershell
python -m unittest -v test_publishing.py test_facebook_publishing.py
```

## Studio themes and platform posting details

The workspace uses a warm ivory, charcoal and yellow light theme and a matching
dark theme. Use the theme switch in the top bar; your choice is remembered on
this browser. The project overview shows real voiceover, script, section and
media counts. Section cards expand individually to keep the editor focused.

In **Publish video**, the first card contains shared title, description and
hashtags. Every platform inherits these values. Open a platform card and edit
a field to customize only that field for that destination. Other fields keep
following the shared details. **Use shared** clears a field override; **Reset
all to shared** clears that platform's overrides. Save posting details to keep
the shared text and all overrides with the project.

YouTube, Instagram and Facebook Page direct uploads use the selected card's
resolved posting details. Caption counts include hashtags and show the existing
YouTube and Instagram limits. Assisted-upload caption copying and local posting
history also use the relevant platform card. Review the selected destination
and its final text before starting an upload.

The interface uses locally bundled Source Sans 3 and IBM Plex Sans Arabic fonts. Font
licenses are included under `studio/ui-fonts/`.

If Facebook rejects a Page token with code 190, Studio marks the connection as
**Reconnect required** and stops further uploads with that token. **Check
connection** performs only a Page identity read. Generate a fresh **Page access
token** in Meta Graph API Explorer, paste it into the Facebook Page account
setup, and select **Connect Page**. After reconnecting, review the destination
and posting details again before uploading. If a failed upload already has a
remote video ID and may have reached publishing, check that existing upload
in posting history before creating another copy.

Facebook Page connection also accepts a User token with access to the intended
Page. If Meta identifies the token as a User token, Studio reads the managed
Pages, matches the entered Page ID, and validates the returned Page token before
saving. Multiple Pages require an explicit Page ID; Studio never selects another
Page when the intended one is unavailable. Connection errors include Meta's
field or permission explanation with tokens and provider URLs redacted.


## Views dashboard

Open **Analytics** in the Studio top bar to see saved views for videos published
through Video Turbo to YouTube, Instagram and Facebook Pages. Select a video
and choose **7 days** or **30 days** to inspect its growth. The chart appears
after four saved samples; the recorded-count table is available from the first
sample. Combined views sum reported platform counts, including repeat viewers
across platforms; each card shows how many posts have available data.

**Refresh views** reads statistics without uploading or modifying a post.
Studio also refreshes every 15 minutes while its process runs. Refreshes run in
the background and remain available during video builds and platform uploads.
Manual refreshes have a one-minute cooldown. Saved counts and history live in
`output/analytics.sqlite3`, excluded from Git. History starts at the first
successful refresh; Studio cannot reconstruct earlier daily view counts.

YouTube reuses the connected channel's access and refresh tokens. Linked
Instagram accounts need `instagram_manage_insights` and
`pages_read_engagement` on the Facebook connection; Instagram Login needs
`instagram_business_manage_insights`. Facebook Page statistics require Page
read access (`pages_read_engagement`); Insights access additionally uses
`read_insights`. If access expires or permissions are missing, the dashboard
shows an account setup link and retains the last successful count. Reconnect
with the required access in **Publishing > Account setup**, then refresh views.
TikTok and personal Facebook profile uploads are outside this first version.

Analytics tests use simulated provider responses and temporary storage:

```powershell
python -m unittest -v test_analytics.py
```
