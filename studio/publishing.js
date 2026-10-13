(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels = {youtube:'YouTube',instagram:'Instagram',tiktok:'TikTok',facebook:'Facebook profile',facebook_page:'Facebook Page'};
  const uploaders = {youtube:'https://studio.youtube.com/',instagram:'https://www.instagram.com/',tiktok:'https://www.tiktok.com/tiktokstudio/upload',facebook:'https://www.facebook.com/reels/create'};
  const terminal = new Set(['complete','failed','cancelled','interrupted']);
  const view = {project:null,data:null,api:null,toast:()=>{},mediaUrl:null,studioBusy:false,busy:false,dirty:false,timer:null,polling:false,loading:false,loadedId:'',pending:{},lastCompleted:'',lastFailed:'',overrides:{}};
  const dialog = $('publish-dialog');
  if (!dialog) return;

  $('publish-panel').innerHTML = `
    <div class="publish-heading"><div><div class="eyebrow">YOUR VIDEO, YOUR CHANNELS</div><h2 id="publish-heading">Publish your video</h2><p class="hint" id="publish-project-name"></p></div><button type="button" class="quiet publish-close" id="publish-close" aria-label="Close publishing">&times;</button></div>
    <div class="publish-body"><div class="publish-main">
<section class="publish-shared"><div class="shared-card-heading"><span class="shared-icon" aria-hidden="true">↗</span><div><h3>Shared posting details</h3><p class="hint">Write it once. Every platform starts here.</p></div><span class="shared-badge">MASTER</span></div>
<label class="field">Video title<input id="publish-title" maxlength="100" dir="auto" placeholder="Give your video a great title"></label><span class="publish-title-counter" id="publish-title-counter">0 / 100</span>
<label class="field">Description / caption<textarea id="publish-description" rows="4" maxlength="5000" dir="auto" placeholder="Tell viewers what this video is about"></textarea></label>
<label class="field">Hashtags<input id="publish-hashtags" maxlength="1500" dir="auto" placeholder="#gaming #العاب"></label>
<div class="publish-draft-footer"><span id="publish-draft-state" role="status">Saved with this project</span><button type="button" class="outline small" id="publish-save">Save posting details</button></div>
<p class="hint shared-explainer">Edit any field in a platform card to customize it. Untouched fields keep following these shared details.</p></section>
<div class="platform-list-heading"><h3>Your platforms</h3><span class="muted">5 destinations · one video</span></div>
<div class="publish-platforms"><details class="publish-card platform-youtube" data-platform-card="youtube" open>
 <summary class="publish-card-heading"><span class="publish-platform-icon" aria-hidden="true">YT</span><span class="platform-identity"><strong>YouTube</strong><small id="publish-youtube-summary">Using shared posting details</small></span><span class="publish-status" id="publish-youtube-status">Not connected</span><span class="platform-chevron" aria-hidden="true">⌄</span></summary>
 <div class="platform-card-body"><p class="hint" id="publish-youtube-account">Connect your channel for direct uploads.</p><div class="platform-detail-heading"><span class="inheritance-badge" id="publish-youtube-inheritance">Using shared details</span><button type="button" class="quiet small" data-reset-platform="youtube" hidden>Reset all to shared</button></div><div class="platform-fields"><div class="platform-field "><label class="field">Video title<input id="publish-youtube-title" data-post-platform="youtube" data-post-field="title" maxlength="100" dir="auto"></label><div class="field-inheritance"><span data-field-source="youtube:title">Shared</span><button type="button" class="quiet small" data-reset-platform="youtube" data-reset-field="title" hidden>Use shared title</button></div></div><div class="platform-field wide"><label class="field">Description / caption<textarea id="publish-youtube-description" data-post-platform="youtube" data-post-field="description" rows="3" maxlength="5000" dir="auto"></textarea></label><div class="field-inheritance"><span data-field-source="youtube:description">Shared</span><button type="button" class="quiet small" data-reset-platform="youtube" data-reset-field="description" hidden>Use shared description</button></div></div><div class="platform-field "><label class="field">Hashtags<input id="publish-youtube-hashtags" data-post-platform="youtube" data-post-field="hashtags" maxlength="1500" dir="auto"></label><div class="field-inheritance"><span data-field-source="youtube:hashtags">Shared</span><button type="button" class="quiet small" data-reset-platform="youtube" data-reset-field="hashtags" hidden>Use shared hashtags</button></div></div></div><div class="platform-caption-count" id="publish-youtube-caption-count"></div><div id="publish-youtube-options" class="platform-options"><label class="field" id="publish-privacy-field">YouTube visibility<select id="publish-privacy"><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></label><label class="check"><input type="checkbox" id="publish-kids">This video is made for kids</label></div><div class="publish-card-actions"><button type="button" class="outline small" data-connect="youtube">Connect channel</button><button type="button" class="quiet small" data-disconnect="youtube" hidden>Disconnect</button><button type="button" class="quiet small" data-setup="youtube">Account setup</button><button type="button" class="quiet small" data-copy="youtube">Copy caption</button><button type="button" class="primary small platform-upload" data-direct="youtube" aria-controls="publish-submit-area" aria-expanded="false">Review &amp; upload <span aria-hidden="true">↗</span></button></div></div></details><details class="publish-card platform-instagram" data-platform-card="instagram" >
 <summary class="publish-card-heading"><span class="publish-platform-icon" aria-hidden="true">IG</span><span class="platform-identity"><strong>Instagram</strong><small id="publish-instagram-summary">Using shared posting details</small></span><span class="publish-status" id="publish-instagram-status">Not connected</span><span class="platform-chevron" aria-hidden="true">⌄</span></summary>
 <div class="platform-card-body"><p class="hint" id="publish-instagram-account">Connect your Professional account, or use assisted upload.</p><div class="platform-detail-heading"><span class="inheritance-badge" id="publish-instagram-inheritance">Using shared details</span><button type="button" class="quiet small" data-reset-platform="instagram" hidden>Reset all to shared</button></div><div class="platform-fields"><div class="platform-field "><label class="field">Video title<input id="publish-instagram-title" data-post-platform="instagram" data-post-field="title" maxlength="100" dir="auto"></label><div class="field-inheritance"><span data-field-source="instagram:title">Shared</span><button type="button" class="quiet small" data-reset-platform="instagram" data-reset-field="title" hidden>Use shared title</button></div></div><div class="platform-field wide"><label class="field">Description / caption<textarea id="publish-instagram-description" data-post-platform="instagram" data-post-field="description" rows="3" maxlength="5000" dir="auto"></textarea></label><div class="field-inheritance"><span data-field-source="instagram:description">Shared</span><button type="button" class="quiet small" data-reset-platform="instagram" data-reset-field="description" hidden>Use shared description</button></div></div><div class="platform-field "><label class="field">Hashtags<input id="publish-instagram-hashtags" data-post-platform="instagram" data-post-field="hashtags" maxlength="1500" dir="auto"></label><div class="field-inheritance"><span data-field-source="instagram:hashtags">Shared</span><button type="button" class="quiet small" data-reset-platform="instagram" data-reset-field="hashtags" hidden>Use shared hashtags</button></div></div></div><div class="platform-caption-count" id="publish-instagram-caption-count"></div><div id="publish-instagram-options" class="platform-options"><label class="check"><input type="checkbox" id="publish-feed" checked>Also show this Reel on my Instagram feed</label><p class="hint" id="publish-instagram-upload-hint">Connect the professional account linked to your Facebook Page. Studio sends the finished MP4 directly to Instagram.</p><div id="publish-instagram-hosted" hidden><label class="field">Public HTTPS link to this finished MP4<input id="publish-instagram-url" type="url" placeholder="https://your-host.example/final.mp4" autocomplete="off"></label><p class="hint">Your Instagram Login connection uses hosted video links. Connect through your Facebook Page to upload the local MP4 instead.</p></div></div><div class="publish-card-actions"><button type="button" class="outline small" data-instagram-page="true">Connect from Facebook Page</button><button type="button" class="quiet small" data-disconnect="instagram" hidden>Disconnect</button><button type="button" class="quiet small" data-setup="instagram">Account setup</button><button type="button" class="outline small" data-uploader="instagram">Open Instagram</button><button type="button" class="quiet small" data-mark="instagram">Mark published</button><button type="button" class="quiet small" data-copy="instagram">Copy caption</button><button type="button" class="primary small platform-upload" data-direct="instagram" aria-controls="publish-submit-area" aria-expanded="false">Review &amp; upload <span aria-hidden="true">↗</span></button></div><div data-manual-form="instagram" hidden></div></div></details><details class="publish-card platform-facebook_page" data-platform-card="facebook_page" >
 <summary class="publish-card-heading"><span class="publish-platform-icon" aria-hidden="true">f</span><span class="platform-identity"><strong>Facebook Page</strong><small id="publish-facebook_page-summary">Using shared posting details</small></span><span class="publish-status" id="publish-facebook_page-status">Not connected</span><span class="platform-chevron" aria-hidden="true">⌄</span></summary>
 <div class="platform-card-body"><p class="hint" id="publish-facebook_page-account">Connect a Page you manage for direct Reel publishing.</p><div class="platform-detail-heading"><span class="inheritance-badge" id="publish-facebook_page-inheritance">Using shared details</span><button type="button" class="quiet small" data-reset-platform="facebook_page" hidden>Reset all to shared</button></div><div class="platform-fields"><div class="platform-field "><label class="field">Video title<input id="publish-facebook_page-title" data-post-platform="facebook_page" data-post-field="title" maxlength="100" dir="auto"></label><div class="field-inheritance"><span data-field-source="facebook_page:title">Shared</span><button type="button" class="quiet small" data-reset-platform="facebook_page" data-reset-field="title" hidden>Use shared title</button></div></div><div class="platform-field wide"><label class="field">Description / caption<textarea id="publish-facebook_page-description" data-post-platform="facebook_page" data-post-field="description" rows="3" maxlength="5000" dir="auto"></textarea></label><div class="field-inheritance"><span data-field-source="facebook_page:description">Shared</span><button type="button" class="quiet small" data-reset-platform="facebook_page" data-reset-field="description" hidden>Use shared description</button></div></div><div class="platform-field "><label class="field">Hashtags<input id="publish-facebook_page-hashtags" data-post-platform="facebook_page" data-post-field="hashtags" maxlength="1500" dir="auto"></label><div class="field-inheritance"><span data-field-source="facebook_page:hashtags">Shared</span><button type="button" class="quiet small" data-reset-platform="facebook_page" data-reset-field="hashtags" hidden>Use shared hashtags</button></div></div></div><div class="platform-caption-count" id="publish-facebook_page-caption-count"></div><div id="publish-facebook_page-options"><p class="hint">Publishes the local MP4 to your connected Page. No public video link is needed.</p></div><div class="publish-card-actions"><button type="button" class="outline small" data-setup="facebook_page">Connect Page / account setup</button><button type="button" class="quiet small" data-check-account="facebook_page">Check connection</button><button type="button" class="quiet small" data-disconnect="facebook_page" hidden>Disconnect Page</button><button type="button" class="quiet small" data-copy="facebook_page">Copy caption</button><button type="button" class="primary small platform-upload" data-direct="facebook_page" aria-controls="publish-submit-area" aria-expanded="false">Review &amp; upload <span aria-hidden="true">↗</span></button></div></div></details><details class="publish-card platform-tiktok" data-platform-card="tiktok" >
 <summary class="publish-card-heading"><span class="publish-platform-icon" aria-hidden="true">tk</span><span class="platform-identity"><strong>TikTok</strong><small id="publish-tiktok-summary">Using shared posting details</small></span><span class="publish-status" >Assisted upload</span><span class="platform-chevron" aria-hidden="true">⌄</span></summary>
 <div class="platform-card-body"><p class="hint">Download the video and finish publishing in TikTok.</p><div class="platform-detail-heading"><span class="inheritance-badge" id="publish-tiktok-inheritance">Using shared details</span><button type="button" class="quiet small" data-reset-platform="tiktok" hidden>Reset all to shared</button></div><div class="platform-fields"><div class="platform-field "><label class="field">Video title<input id="publish-tiktok-title" data-post-platform="tiktok" data-post-field="title" maxlength="100" dir="auto"></label><div class="field-inheritance"><span data-field-source="tiktok:title">Shared</span><button type="button" class="quiet small" data-reset-platform="tiktok" data-reset-field="title" hidden>Use shared title</button></div></div><div class="platform-field wide"><label class="field">Description / caption<textarea id="publish-tiktok-description" data-post-platform="tiktok" data-post-field="description" rows="3" maxlength="5000" dir="auto"></textarea></label><div class="field-inheritance"><span data-field-source="tiktok:description">Shared</span><button type="button" class="quiet small" data-reset-platform="tiktok" data-reset-field="description" hidden>Use shared description</button></div></div><div class="platform-field "><label class="field">Hashtags<input id="publish-tiktok-hashtags" data-post-platform="tiktok" data-post-field="hashtags" maxlength="1500" dir="auto"></label><div class="field-inheritance"><span data-field-source="tiktok:hashtags">Shared</span><button type="button" class="quiet small" data-reset-platform="tiktok" data-reset-field="hashtags" hidden>Use shared hashtags</button></div></div></div><div class="platform-caption-count" id="publish-tiktok-caption-count"></div><div class="publish-card-actions"><button type="button" class="outline small" data-uploader="tiktok">Open uploader</button><button type="button" class="quiet small" data-mark="tiktok">Mark published</button><button type="button" class="quiet small" data-copy="tiktok">Copy caption</button></div><div data-manual-form="tiktok" hidden></div></div></details><details class="publish-card platform-facebook" data-platform-card="facebook" >
 <summary class="publish-card-heading"><span class="publish-platform-icon" aria-hidden="true">f</span><span class="platform-identity"><strong>Facebook profile</strong><small id="publish-facebook-summary">Using shared posting details</small></span><span class="publish-status" >Assisted upload</span><span class="platform-chevron" aria-hidden="true">⌄</span></summary>
 <div class="platform-card-body"><p class="hint">Upload on Facebook, or share through your linked Instagram account.</p><div class="platform-detail-heading"><span class="inheritance-badge" id="publish-facebook-inheritance">Using shared details</span><button type="button" class="quiet small" data-reset-platform="facebook" hidden>Reset all to shared</button></div><div class="platform-fields"><div class="platform-field "><label class="field">Video title<input id="publish-facebook-title" data-post-platform="facebook" data-post-field="title" maxlength="100" dir="auto"></label><div class="field-inheritance"><span data-field-source="facebook:title">Shared</span><button type="button" class="quiet small" data-reset-platform="facebook" data-reset-field="title" hidden>Use shared title</button></div></div><div class="platform-field wide"><label class="field">Description / caption<textarea id="publish-facebook-description" data-post-platform="facebook" data-post-field="description" rows="3" maxlength="5000" dir="auto"></textarea></label><div class="field-inheritance"><span data-field-source="facebook:description">Shared</span><button type="button" class="quiet small" data-reset-platform="facebook" data-reset-field="description" hidden>Use shared description</button></div></div><div class="platform-field "><label class="field">Hashtags<input id="publish-facebook-hashtags" data-post-platform="facebook" data-post-field="hashtags" maxlength="1500" dir="auto"></label><div class="field-inheritance"><span data-field-source="facebook:hashtags">Shared</span><button type="button" class="quiet small" data-reset-platform="facebook" data-reset-field="hashtags" hidden>Use shared hashtags</button></div></div></div><div class="platform-caption-count" id="publish-facebook-caption-count"></div><div class="publish-card-actions"><button type="button" class="outline small" data-uploader="facebook">Open Facebook profile</button><button type="button" class="quiet small" data-mark="facebook">Mark published</button><button type="button" class="quiet small" data-copy="facebook">Copy caption</button></div><div data-manual-form="facebook" hidden></div></div></details></div>
<div class="publish-submit-area" id="publish-submit-area" role="region" aria-labelledby="publish-review-heading"><div class="review-heading"><h3 id="publish-review-heading">Review & upload</h3><span class="muted">You choose when it goes live</span></div>
<select id="publish-platform" aria-label="Upload destination" hidden><option value="youtube">YouTube</option><option value="instagram">Instagram Reel</option><option value="facebook_page">Facebook Page Reel</option></select>
<div class="publish-selected-post"><strong id="publish-selected-title" dir="auto"></strong><p id="publish-selected-caption" dir="auto"></p></div>
<label class="check publish-review"><input type="checkbox" id="publish-reviewed">I watched the finished video and reviewed this destination, its posting details and publishing settings.</label>
<div class="publish-submit-row"><p class="hint" id="publish-requirements">Connect an account, then review your video.</p><button type="button" class="primary" id="publish-submit">Upload to YouTube</button></div></div>
</div><aside class="publish-preview-column"><div class="publish-preview-sticky"><div class="eyebrow">READY FOR YOUR AUDIENCE</div><h3>The final cut</h3><video id="publish-preview" class="publish-preview" controls playsinline preload="metadata"></video><a id="publish-download" class="outline full" download>Download video</a><p class="hint" id="publish-video-state">Checking the finished video...</p><div class="publish-preview-tip">One video.<br>Every destination.<p>Customize the words for each audience while your video stays the same.</p></div></div></aside></div>
<div id="publish-error" class="publish-error" role="alert" hidden></div><div id="publish-feedback" class="publish-feedback" role="status" hidden></div>
    <div id="publish-job" class="publish-job" hidden><div class="publish-job-top"><strong id="publish-job-stage"></strong><span id="publish-job-percent"></span></div><progress id="publish-job-progress" max="100" value="0"></progress><p id="publish-job-detail"></p><a id="publish-job-link" class="outline full" target="_blank" rel="noopener noreferrer" hidden>Open uploaded video</a></div>
    <section class="publish-history"><h3>Posting history</h3><ul id="publish-history-list" class="publish-history-list"></ul></section>
    <details class="publish-setup" id="publish-setup"><summary>Connect accounts and configure API access</summary><p class="hint">Set up your own API apps once. Credentials are stored on this computer. Blank secret fields keep your saved values.</p><div class="publish-setup-grid">
      <section class="publish-setup-card" id="publish-youtube-setup"><h3>YouTube account setup</h3><p class="hint">Create a Google OAuth client for a Desktop app and enable the YouTube Data API. Add your Google account as a test user while the app is in testing.</p><a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" class="outline small">Open Google API credentials</a><label class="field">OAuth client ID<input id="publish-youtube-id" autocomplete="off" spellcheck="false"></label><label class="field">OAuth client secret<input id="publish-youtube-secret" type="password" autocomplete="new-password" placeholder="Paste a secret, or leave blank to keep it"></label><div class="publish-form-buttons"><button type="button" class="outline small" data-save-settings="youtube">Save YouTube setup</button></div><p id="publish-youtube-configured" class="publish-setup-status"></p><p class="hint">Sign-in returns to <code id="publish-youtube-redirect"></code>.</p><details class="publish-callback"><summary>Finish sign-in manually</summary><label class="field">Completed browser redirect URL<input type="password" autocomplete="off" id="publish-youtube-callback" placeholder="Paste the complete redirect URL"></label><button type="button" class="outline small full" data-finish="youtube">Complete connection</button></details></section>
      <section class="publish-setup-card" id="publish-instagram-setup"><h3>Instagram local uploads</h3><p class="hint">Connect once, then upload every finished MP4 directly from Studio.</p><p id="publish-instagram-page-state" class="publish-setup-status"></p><ol class="hint"><li>Use an Instagram Business or Creator account and link it to your Facebook Page under <strong>Linked accounts</strong>.</li><li>In your Meta app, enable Instagram access through Facebook Login. Request <code>instagram_basic</code>, <code>instagram_content_publish</code> and <code>pages_read_engagement</code> when generating the token. Authorize the intended Instagram account.</li><li>Reconnect the Facebook Page with the updated token, then connect its linked Instagram account below.</li></ol><button type="button" class="outline small full" id="publish-instagram-page-connect" data-instagram-page="true">Connect linked Instagram account</button><details class="publish-callback"><summary>Alternative: Instagram Login with a hosted video</summary><p class="hint">This alternative uses a public HTTPS video link. Configure a Meta app with Instagram Login and publishing permissions.</p><a href="https://developers.facebook.com/apps/" target="_blank" rel="noopener noreferrer" class="outline small">Open Meta apps</a><label class="field">Instagram app ID<input id="publish-instagram-id" autocomplete="off" spellcheck="false"></label><label class="field">Instagram app secret<input id="publish-instagram-secret" type="password" autocomplete="new-password" placeholder="Paste a secret, or leave blank to keep it"></label><label class="field">Registered HTTPS redirect URI<input id="publish-instagram-redirect-input" type="url" placeholder="https://your-site.example/callback" autocomplete="off"></label><div class="publish-form-buttons"><button type="button" class="outline small" data-save-settings="instagram">Save Instagram setup</button></div><button type="button" class="outline small" data-connect="instagram">Connect with Instagram Login</button><p id="publish-instagram-configured" class="publish-setup-status"></p><details class="publish-callback"><summary>Finish sign-in manually</summary><p class="hint">After authorizing Instagram, copy the complete final URL from your browser's address bar and paste it here.</p><label class="field">Completed browser redirect URL<input type="password" autocomplete="off" id="publish-instagram-callback" placeholder="Paste the complete redirect URL"></label><button type="button" class="outline small full" data-finish="instagram">Complete connection</button></details><details class="publish-callback"><summary>Connect with an Instagram access token instead</summary><p class="hint">Use a token issued for your own Instagram Professional account with publishing permissions. It is sent only to your local Studio and never shown after saving.</p><label class="field">Instagram access token<input id="publish-instagram-token" type="password" autocomplete="off" placeholder="Paste your access token"></label><button type="button" class="outline small full" id="publish-token-connect">Connect token</button></details></details></section>
      <section class="publish-setup-card" id="publish-facebook_page-setup"><h3>Facebook Page account setup</h3><p class="hint">Connect the Page you manage with your Facebook profile. The token identifies the Page; its name appears above before you publish.</p><a href="https://developers.facebook.com/tools/explorer/" target="_blank" rel="noopener noreferrer" class="outline small">Open Meta Graph API Explorer</a><details class="publish-callback"><summary>How to get a Page access token</summary><ol class="hint"><li>In your Meta app, enable the Page publishing use case: <strong>Manage everything on your Page</strong>.</li><li>In Graph API Explorer, select that app and get a <strong>User Access Token</strong> with <code>pages_show_list</code>, <code>pages_read_engagement</code> and <code>pages_manage_posts</code>. For a Page in a business portfolio, also request <code>business_management</code> to list its Pages. Generate a new token after adding permissions and authorize the intended business and Page.</li><li>Open <strong>User or Page</strong> and select your Page under <strong>Page Access Tokens</strong>. Alternatively, run <code>GET me/accounts?fields=id,name,access_token,tasks</code> with the user token and copy the access token belonging to your Page.</li><li>Paste that Page token below. Its Page ID is detected automatically.</li></ol></details><label class="field">Page ID (required for a User token managing multiple Pages)<input id="publish-facebook_page-id" inputmode="numeric" autocomplete="off" placeholder="Detected from the Page access token"></label><label class="field">Meta access token<input id="publish-facebook_page-token" type="password" autocomplete="off" placeholder="Paste the Page token, or a User token that can access this Page"></label><div class="publish-form-buttons"><button type="button" class="outline small" id="publish-facebook_page-connect">Connect Page</button></div><p class="hint">Page tokens connect directly. If Graph API Explorer returns a User token, Studio retrieves the token for the Page ID above. Tokens are validated before saving.</p><p class="hint">For Instagram local uploads, also add <code>instagram_basic</code> and <code>instagram_content_publish</code>, authorize the linked Instagram account, and generate a fresh token.</p></section>
    </div></details>`;

  function secureLink(value) {
    try { const parsed = new URL(value); return parsed.protocol === 'https:' ? parsed.href : ''; } catch (_) { return ''; }
  }
  function sameProject() { return view.data && view.loadedId === view.project?.id; }
  function runningJob() { return view.data?.job && !terminal.has(view.data.job.status); }
  function reviewedReset() { $('publish-reviewed').checked = false; lock(); }
  function draftChanged() { renderPlatformDetails(); view.dirty = true; $('publish-draft-state').textContent = 'Unsaved posting details'; reviewedReset(); }
  function draft() {
    return {title:$('publish-title').value.trim(),description:$('publish-description').value,hashtags:$('publish-hashtags').value.trim(),youtube_privacy:$('publish-privacy').value,made_for_kids:$('publish-kids').checked,instagram_share_to_feed:$('publish-feed').checked,instagram_video_url:$('publish-instagram-url').value.trim(),facebook_page_id:view.data?.accounts?.facebook_page?.page_id || '',platform_overrides:view.overrides};
  }
  function postingDetails(platform) {
    const value = draft();
    return {...value, ...view.overrides[platform]};
  }
  function caption(platform) {
    const value = platform ? postingDetails(platform) : draft();
    const tags = value.hashtags.split(/\s+/).map(tag=>tag.replace(/^,+|,+$/g,'').replace(/^#+/,'')).filter(Boolean).map(tag=>'#'+tag).join(' ');
    return [value.description.trim(), tags].filter(Boolean).join('\n\n');
  }
  function renderPlatformDetails() {
    for (const platform of Object.keys(labels)) {
      const value = postingDetails(platform);
      const overrides = view.overrides[platform] || {};
      const count = Object.keys(overrides).length;
      $('publish-' + platform + '-inheritance').textContent = count ? count + ' custom ' + (count === 1 ? 'field' : 'fields') : 'Using shared details';
      $('publish-' + platform + '-summary').textContent = value.title || 'Add a title in shared details';
      for (const field of ['title','description','hashtags']) {
        const custom = Object.prototype.hasOwnProperty.call(overrides,field);
        const input = $('publish-' + platform + '-' + field);
        if (document.activeElement !== input) input.value = value[field];
        dialog.querySelector('[data-field-source="' + platform + ':' + field + '"]').textContent = custom ? 'Customized for ' + labels[platform] : 'Following shared ' + field;
        dialog.querySelector('[data-reset-platform="' + platform + '"][data-reset-field="' + field + '"]').hidden = !custom;
      }
      dialog.querySelector('[data-reset-platform="' + platform + '"]:not([data-reset-field])').hidden = !count;
      const limit = platform === 'youtube' ? 5000 : platform === 'instagram' ? 2200 : 0;
      const length = caption(platform).length;
      const counter = $('publish-' + platform + '-caption-count');
      counter.textContent = length.toLocaleString() + (limit ? ' / ' + limit.toLocaleString() : '') + ' caption characters, including hashtags';
      counter.classList.toggle('error',Boolean(limit && length > limit));
    }
    const platform = $('publish-platform').value;
    $('publish-selected-title').textContent = postingDetails(platform).title || 'Untitled video';
    $('publish-selected-caption').textContent = caption(platform) || 'No caption or hashtags.';
  }
  function feedback(message, error = false) {
    const target = error ? $('publish-error') : $('publish-feedback'); target.textContent = message; target.hidden = !message;
    if (error) $('publish-feedback').hidden = true; else $('publish-error').hidden = true;
  }
  async function action(fn) {
    if (view.busy || view.studioBusy) return;
    view.busy = true; lock(); feedback('');
    try { await fn(); } catch (error) { feedback(error.message || 'Publishing request failed.',true); }
    finally { view.busy = false; lock(); }
  }
  function loadDraft(value = {}) {
    $('publish-title').value = value.title ?? view.project?.editor?.name ?? '';
    $('publish-description').value = value.description ?? '';
    $('publish-hashtags').value = Array.isArray(value.hashtags) ? value.hashtags.join(' ') : value.hashtags ?? '';
    $('publish-privacy').value = value.youtube_privacy || 'private';
    $('publish-kids').checked = value.made_for_kids === true;
    $('publish-feed').checked = value.instagram_share_to_feed !== false;
    $('publish-instagram-url').value = value.instagram_video_url || '';
    $('publish-title-counter').textContent = $('publish-title').value.length + ' / 100';
    view.overrides = JSON.parse(JSON.stringify(value.platform_overrides || {})); renderPlatformDetails();
    view.dirty = false; $('publish-draft-state').textContent = 'Saved with this project'; reviewedReset();
  }
  function loadSetup() {
    for (const platform of ['youtube','instagram']) {
      const account = view.data.accounts?.[platform] || {};
      $('publish-' + platform + '-id').value = account.client_id || '';
      $('publish-' + platform + '-secret').value = '';
    }
    $('publish-instagram-redirect-input').value = view.data.accounts?.instagram?.redirect_uri || '';
    $('publish-facebook_page-id').value = view.data.accounts?.facebook_page?.page_id || '';
    $('publish-facebook_page-token').value = '';
  }
  function updateVideo() {
    const ready = Boolean(view.project?.final && (!view.data || view.data.video?.ready));
    $('publish-open').hidden = !view.project?.final;
    $('publish-project-name').textContent = view.project?.editor?.name || 'Your finished video';
    const source = view.mediaUrl ? view.mediaUrl('output/final.mp4',view.project?.id) : '';
    const video = $('publish-preview');
    video.hidden = !ready;
    if (ready && source && video.getAttribute('src') !== source) video.src = source;
    if (!ready) { video.pause(); video.removeAttribute('src'); }
    const download = $('publish-download'); download.hidden = !ready; download.href = source;
    download.download = (view.project?.editor?.name || 'video') + '.mp4';
    const size = view.data?.video?.size;
    $('publish-video-state').textContent = ready ? 'Finished MP4' + (size ? ' - ' + (size/1024/1024).toFixed(1) + ' MB' : '') : 'Build your video before publishing.';
  }
  function renderAccounts() {
    for (const platform of ['youtube','instagram']) {
      const account = view.data?.accounts?.[platform] || {};
      if (account.connected) delete view.pending[platform];
      const status = $('publish-' + platform + '-status');
      status.textContent = account.connected ? 'Connected' : view.pending[platform] ? 'Waiting for sign-in' : account.configured ? 'Ready to connect' : 'Setup needed';
      status.classList.toggle('connected',Boolean(account.connected));
      $('publish-' + platform + '-account').textContent = account.connected ? account.name || 'Account connected' : platform === 'youtube' ? 'Connect your channel for direct uploads.' : 'Connect your Professional account to publish Reels.';
      document.querySelector('[data-connect="' + platform + '"]').hidden = Boolean(account.connected);
      document.querySelector('[data-disconnect="' + platform + '"]').hidden = !account.connected;
      $('publish-' + platform + '-configured').textContent = account.configured ? 'App settings saved.' + (account.has_secret ? ' A secret is stored; it is not displayed.' : '') : 'Save your API app settings before connecting.';
    }
    const page = view.data?.accounts?.facebook_page || {};
    $('publish-facebook_page-status').textContent = page.needs_reconnect ? 'Reconnect required' : page.connected ? 'Connected' : 'Setup needed';
    $('publish-facebook_page-status').classList.toggle('error',Boolean(page.needs_reconnect));
    $('publish-facebook_page-status').classList.toggle('connected',Boolean(page.connected));
    $('publish-facebook_page-account').textContent = page.needs_reconnect ? (page.name || 'Your Page') + ': the saved access token expired or is invalid. Reconnect with a fresh Page token.' : page.connected ? page.name + ' - Page ID ' + page.page_id : 'Connect a Page you manage for automatic Reel publishing.';
    dialog.querySelector('[data-disconnect="facebook_page"]').hidden = !page.connected && !page.needs_reconnect;
    const instagram = view.data?.accounts?.instagram || {};
    const localInstagram = instagram.upload_mode === 'local';
    const hostedInstagram = instagram.connected && !localInstagram;
    $('publish-instagram-hosted').hidden = !hostedInstagram;
    $('publish-instagram-upload-hint').textContent = localInstagram && instagram.connected ? 'Uploads this finished MP4 directly. No public video link is needed.' : hostedInstagram ? 'Switch to the account linked to your Facebook Page to upload this MP4 directly.' : 'Connect the professional Instagram account linked to your Facebook Page for local MP4 uploads.';
    $('publish-instagram-page-state').textContent = localInstagram && instagram.connected ? instagram.name + ' is connected through ' + instagram.source_page_name + ' for local uploads.' : page.connected ? 'Uses the Instagram account linked to ' + page.name + '.' : 'Connect your Facebook Page first, then connect its linked Instagram account.';
    for (const button of dialog.querySelectorAll('[data-instagram-page]')) button.hidden = localInstagram && instagram.connected && button.id !== 'publish-instagram-page-connect';
    $('publish-instagram-page-connect').textContent = localInstagram && instagram.connected ? 'Check linked Instagram account' : 'Connect linked Instagram account';
    if (localInstagram) {
      $('publish-instagram-status').textContent = instagram.connected ? 'Local upload ready' : 'Reconnect Page';
      $('publish-instagram-account').textContent = instagram.connected ? instagram.name + ' - connected through ' + instagram.source_page_name : 'Reconnect the same Facebook Page to restore this Instagram connection.';
    }
    $('publish-youtube-redirect').textContent = view.data?.accounts?.youtube?.redirect_uri || window.location.origin + '/api/publishing/callback/youtube';
  }
  function renderHistory() {
    const history = view.data?.history || [];
    $('publish-history-list').innerHTML = history.length ? history.slice().reverse().map(entry => {
      const link = secureLink(entry.url); const stamp = Number(entry.finished || entry.created || entry.started || 0);
      const date = stamp ? new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(new Date(stamp < 1e12 ? stamp*1000 : stamp)) : '';
      const status = entry.status === 'complete' ? (entry.platform === 'youtube' ? 'Uploaded' : 'Published') : entry.status === 'manual' || entry.status === 'published' ? 'Marked published' : entry.status || '';
      return `<li class="publish-history-item"><div><strong>${esc(labels[entry.platform] || entry.platform)}${entry.destination_name ? ' - ' + esc(entry.destination_name) : ''} &middot; ${esc(status)}</strong><small dir="auto">${esc(entry.title || view.project?.editor?.name || '')}</small><small>${esc(date)}${entry.error ? ' - ' + esc(entry.error) : ''}</small></div>${entry.platform === 'facebook_page' && ['failed','interrupted'].includes(entry.status) && entry.remote_id ? `<button type="button" class="outline small" data-verify-facebook="${esc(entry.id)}">Check existing upload</button>` : ''}${entry.platform === 'instagram' && entry.instagram_connection_type === 'facebook' && ['failed','interrupted'].includes(entry.status) && entry.container_id ? `<button type="button" class="outline small" data-verify-instagram="${esc(entry.id)}">Check existing upload</button>` : ''}${link ? `<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">Open post &nearr;</a>` : ''}</li>`;
    }).join('') : '<li class="publish-empty">Uploads and posts you mark as published will appear here.</li>';
  }
  function renderJob() {
    const job = view.data?.job; const relevant = job && job.project === view.project?.id;
    $('publish-job').hidden = !relevant;
    if (!relevant) return;
    const card = dialog.querySelector('[data-platform-card="' + job.platform + '"]');
    if (card) { card.querySelector('.platform-card-body').append($('publish-job')); if (!terminal.has(job.status)) card.open = true; }
    const authFailure = (job.platform === 'facebook_page' || job.platform === 'instagram' && job.instagram_connection_type === 'facebook') && ['failed','interrupted'].includes(job.status) && (job.reconnect_required || job.error_code === 190 || /\bcode 190\b/.test(job.error || ''));
    const needsReconnect = authFailure && !view.data?.accounts?.facebook_page?.connected;
    if (['failed','interrupted'].includes(job.status) && view.lastFailed !== job.id) {
      view.lastFailed = job.id; $('publish-feedback').hidden = true;
    }
    let pageRecovery = $('publish-facebook-recovery');
    if (!pageRecovery) {
      pageRecovery = document.createElement('div'); pageRecovery.id = 'publish-facebook-recovery'; pageRecovery.className = 'publish-manual-form';
      pageRecovery.innerHTML = '<p class="hint">Reconnect this Page with a fresh Page access token from Meta Graph API Explorer. Then review the video and try again.</p><button type="button" class="outline small" data-setup="facebook_page">Reconnect Facebook Page</button>';
      $('publish-job').append(pageRecovery);
    }
    pageRecovery.hidden = !needsReconnect;
    if (needsReconnect && job.remote_id && job.publish_attempted) pageRecovery.querySelector('p').textContent = 'Reconnect this Page with a fresh Page access token, then use Check existing upload in posting history before trying again.';
    else if (needsReconnect) pageRecovery.querySelector('p').textContent = 'Facebook rejected the access token. Reconnect this Page with a fresh Page access token from Meta Graph API Explorer, then review the video and retry.';
    const progress = Math.max(0,Math.min(100,Number(job.progress) || 0));
    $('publish-job-stage').textContent = needsReconnect ? 'Reconnect Facebook Page' : authFailure ? 'Previous upload failed' : job.stage || (terminal.has(job.status) ? job.status : 'Uploading');
    $('publish-job-percent').textContent = Math.round(progress) + '%'; $('publish-job-progress').value = progress;
    $('publish-job-detail').textContent = authFailure && !needsReconnect ? 'The Page is connected again. Review the video and posting details before retrying.' : job.error || job.warning || (job.status === 'complete' ? 'The upload finished successfully.' : 'You may close this panel. Keep Studio running until the upload finishes.');
    const link = secureLink(job.url); $('publish-job-link').hidden = !link; if (link) $('publish-job-link').href = link;
    let recovery = $('publish-youtube-recovery');
    if (!recovery) {
      recovery = document.createElement('div'); recovery.id = 'publish-youtube-recovery'; recovery.className = 'publish-manual-form';
      recovery.innerHTML = '<p class="hint">If this video appears in YouTube Studio, check it here before uploading again.</p><label class="field">Existing YouTube video link<input type="url" id="publish-existing-youtube-url" placeholder="https://www.youtube.com/watch?v=..."></label><button type="button" class="outline small" id="publish-verify-youtube">Check existing upload</button>';
      $('publish-job').append(recovery);
      $('publish-verify-youtube').onclick = () => action(async()=> {
        const checked = await view.api('/api/publishing/verify-youtube',{id:view.project.id,job_id:view.data.job.id,url:$('publish-existing-youtube-url').value.trim()});
        await refresh(); feedback(checked.message); reviewedReset();
      });
    }
    recovery.hidden = job.platform !== 'youtube' || !['failed','interrupted'].includes(job.status);

    if (job.status === 'complete' && view.lastCompleted !== job.id) { view.lastCompleted = job.id; view.toast(labels[job.platform] + ' upload finished.'); }
  }
  function optionsChanged() {
    const platform = $('publish-platform').value;
    const card = dialog.querySelector('[data-platform-card="' + platform + '"]');
    const body = card.querySelector('.platform-card-body');
    body.insertBefore($('publish-submit-area'),$('publish-job').parentElement === body ? $('publish-job') : null);
    card.open = true;
    $('publish-review-heading').textContent = 'Review & upload to ' + labels[platform];
    for (const button of dialog.querySelectorAll('[data-direct]')) button.setAttribute('aria-expanded',String(button.dataset.direct === platform));
    renderPlatformDetails();
    $('publish-submit').textContent = platform === 'instagram' ? 'Publish Instagram Reel' : platform === 'facebook_page' ? 'Publish Facebook Page Reel' : 'Upload to YouTube'; reviewedReset();
  }
  function lock(studioBusy) {
    if (typeof studioBusy === 'boolean') view.studioBusy = studioBusy;
    const blocked = view.studioBusy || view.busy || view.loading || !view.api;
    const uploading = Boolean(runningJob());
    dialog.querySelectorAll('button,input,select,textarea').forEach(element => { element.disabled = blocked; });
    $('publish-close').disabled = false;
    $('publish-open').disabled = blocked || !view.project?.final;
    const platform = $('publish-platform').value;
    const account = view.data?.accounts?.[platform];
    const instagramUnconfirmed = platform === 'instagram' && (view.data?.history || []).some(entry => entry.platform === 'instagram' && entry.video_signature === view.data?.video?.signature && (!entry.destination_id || entry.destination_id === account?.user_id) && ['failed','interrupted'].includes(entry.status) && (entry.publish_attempted || entry.processing_status === 'PUBLISHED') && !entry.confirmed_unpublished);
    let reason = !sameProject() ? 'Loading publishing details...' : !view.data.video?.ready ? 'Build your video first.' : uploading ? 'An upload is already running. Wait for it to finish.' : !account?.connected ? 'Connect your ' + labels[platform] + ' account first.' : platform === 'youtube' && !postingDetails(platform).title.trim() ? 'Add a video title.' : platform === 'instagram' && account?.upload_mode !== 'local' && !secureLink($('publish-instagram-url').value) ? 'Provide a public HTTPS link to the finished MP4, or use assisted upload.' : instagramUnconfirmed ? 'Check the existing Instagram upload in posting history before trying again.' : !$('publish-reviewed').checked ? 'Watch your video, then confirm the review above.' : platform === 'youtube' ? 'Visibility: ' + $('publish-privacy').selectedOptions[0].textContent + '. Upload starts when you click.' : platform === 'facebook_page' ? 'Publishes to ' + account.name + ' when you click.' : 'Your Reel will be published when you click.';
    const overLimit = caption(platform).length > (platform === 'instagram' ? 2200 : platform === 'youtube' ? 5000 : Infinity);
    $('publish-requirements').textContent = overLimit ? 'Shorten this platform’s caption or hashtags to fit its character limit.' : reason;
    $('publish-submit').disabled = instagramUnconfirmed || overLimit || blocked || uploading || !sameProject() || !view.data?.video?.ready || !account?.connected || !$('publish-reviewed').checked || platform === 'youtube' && !postingDetails(platform).title.trim() || platform === 'instagram' && account?.upload_mode !== 'local' && !secureLink($('publish-instagram-url').value);
    for (const item of dialog.querySelectorAll('[data-connect]')) item.disabled = blocked || !view.data?.accounts?.[item.dataset.connect]?.configured;
    for (const item of dialog.querySelectorAll('[data-check-account],[data-disconnect],[data-save-settings],#publish-token-connect,#publish-facebook_page-connect,[data-verify-facebook],[data-verify-instagram]')) item.disabled = blocked || uploading;
    for (const item of dialog.querySelectorAll('[data-instagram-page]')) item.disabled = blocked || uploading || !view.data?.accounts?.facebook_page?.connected;
    for (const item of dialog.querySelectorAll('[data-uploader],[data-copy],[data-mark]')) item.disabled = blocked || !view.data?.video?.ready;
    for (const item of dialog.querySelectorAll('[data-direct]')) item.disabled = blocked || uploading || !view.data?.video?.ready;
    if (uploading) for (const item of dialog.querySelectorAll('[data-post-field],[data-reset-platform]')) item.disabled = true;
    if (uploading) for (const item of dialog.querySelectorAll('#publish-title,#publish-description,#publish-hashtags,#publish-privacy,#publish-kids,#publish-feed,#publish-instagram-url,#publish-platform,#publish-save,#publish-reviewed')) item.disabled = true;
  }
  async function refresh(initial = false) {
    if (!view.api || !view.project || view.polling) return;
    const id = view.project.id; view.polling = true;
    try {
      const data = await view.api('/api/publishing?id=' + encodeURIComponent(id));
      if (view.project?.id !== id) return;
      const previousSignature = view.data?.video?.signature;
      const previousPage = view.data?.accounts?.facebook_page?.page_id;
      const previousInstagram = JSON.stringify([view.data?.accounts?.instagram?.user_id,view.data?.accounts?.instagram?.connection_type]);
      view.data = data; view.loadedId = id;
      if (initial) { loadDraft(data.draft); loadSetup(); }
      else if ((previousSignature && previousSignature !== data.video?.signature) || (previousPage && previousPage !== data.accounts?.facebook_page?.page_id) || previousInstagram !== JSON.stringify([data.accounts?.instagram?.user_id,data.accounts?.instagram?.connection_type])) reviewedReset();
      renderAccounts(); renderHistory(); renderJob(); updateVideo(); lock();
    } finally { view.polling = false; }
  }
  function ensurePolling() {
    if (view.timer) return;
    view.timer = setInterval(() => {
      if (!dialog.open && !runningJob() && !Object.keys(view.pending).length) { clearInterval(view.timer); view.timer = null; return; }
      refresh().catch(error => { if (dialog.open) feedback(error.message || 'Cannot refresh publishing status.',true); });
    },2500);
  }
  async function open() {
    if (!view.project?.final || !view.api) return;
    dialog.showModal(); $('final-player')?.pause(); feedback(''); view.loading = true; lock();
    try { await refresh(!sameProject()); ensurePolling(); }
    catch (error) { feedback(error.message || 'Cannot load publishing details.',true); }
    finally { view.loading = false; lock(); }
  }
  async function saveDraft() {
    const saved = await view.api('/api/publishing/save',{id:view.project.id,draft:draft()});
    view.data.draft = saved.draft; loadDraft(saved.draft);
    view.dirty = false; $('publish-draft-state').textContent = 'Saved with this project';
  }
  async function connect(platform) {
    const popup = window.open('about:blank','_blank');
    if (popup) popup.opener = null;
    try {
      const response = await view.api('/api/publishing/connect',{platform});
      const authorization = new URL(response.authorization_url);
      const hosts = new Set(['accounts.google.com','www.facebook.com','facebook.com','www.instagram.com','instagram.com']);
      if (authorization.protocol !== 'https:' || !hosts.has(authorization.hostname)) throw new Error('The service returned an unexpected authorization address.');
      if (!popup) throw new Error('Allow popups for this local Studio, then click Connect again.');
      popup.location.href = authorization.href; view.pending[platform] = true;
      if (response.manual_callback) { $('publish-setup').open = true; $('publish-' + platform + '-setup').querySelector('.publish-callback').open = true; feedback('Finish ' + labels[platform] + ' sign-in, then paste the completed redirect URL below.'); }
      else feedback('Complete sign-in in the new browser tab. This screen will update when connected.');
      renderAccounts(); ensurePolling();
    } catch (error) { if (popup) popup.close(); throw error; }
  }
  async function copyCaption(platform) {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(caption(platform));
    else { const temporary = document.createElement('textarea'); temporary.value = caption(platform); dialog.append(temporary); temporary.select(); const copied = document.execCommand('copy'); temporary.remove(); if (!copied) throw new Error('Copy the caption from its field above.'); }
    feedback(labels[platform] + ' caption and hashtags copied.');
  }
  function showManual(platform) {
    const target = dialog.querySelector('[data-manual-form="' + platform + '"]');
    target.className = 'publish-manual-form'; target.hidden = false;
    target.innerHTML = `<p class="hint">After publishing on ${esc(labels[platform])}, record it here. This button only updates your local history.</p><label class="field">Post link (optional)<input type="url" data-post-url="${platform}" placeholder="https://..."></label><div class="publish-card-actions"><button type="button" class="outline small" data-mark-finish="${platform}">Mark as published</button><button type="button" class="quiet small" data-mark-cancel="${platform}">Cancel</button></div>`;
    lock(); target.querySelector('input').focus();
  }
  dialog.addEventListener('input',event => {
    const {postPlatform,postField} = event.target.dataset;
    if (!postPlatform || !postField) return;
    view.overrides[postPlatform] = {...view.overrides[postPlatform], [postField]:event.target.value};
    draftChanged();
  });
  $('publish-open').addEventListener('click',open);
  $('publish-close').onclick = () => dialog.close();
  dialog.addEventListener('close',()=> { $('publish-preview').pause(); });
  $('publish-title').addEventListener('input',()=> { $('publish-title-counter').textContent = $('publish-title').value.length + ' / 100'; draftChanged(); });
  for (const id of ['publish-description','publish-hashtags','publish-instagram-url']) $(id).addEventListener('input',draftChanged);
  for (const id of ['publish-privacy','publish-kids','publish-feed']) $(id).addEventListener('change',draftChanged);
  $('publish-platform').addEventListener('change',optionsChanged);
  $('publish-reviewed').addEventListener('change',()=>lock());
  $('publish-save').onclick = () => action(async()=> { await saveDraft(); feedback('Posting details saved locally.'); });
  $('publish-submit').onclick = () => action(async()=> {
    const platform = $('publish-platform').value;
    if (!$('publish-reviewed').checked) throw new Error('Review the finished video before uploading.');
    const result = await view.api('/api/publishing/start',{id:view.project.id,platform,draft:draft(),reviewed:true,video_signature:view.data?.video?.signature});
    view.data.job = result.job; view.dirty = false; $('publish-draft-state').textContent = 'Saved with this project'; $('publish-reviewed').checked = false;
    renderJob(); ensurePolling(); feedback(labels[platform] + ' upload started. Keep Studio running.');
  });
  $('publish-token-connect').onclick = () => action(async()=> {
    const input = $('publish-instagram-token'); const token = input.value.trim();
    if (!token) throw new Error('Paste an Instagram access token first.');
    try { await view.api('/api/publishing/token',{platform:'instagram',access_token:token}); await refresh(); feedback('Instagram account connected.'); }
    finally { input.value = ''; }
  });
  $('publish-facebook_page-connect').onclick = () => action(async()=> {
    const input = $('publish-facebook_page-token'); const token = input.value.trim();
    if (!token) throw new Error('Paste the Meta access token first.');
    try {
      await view.api('/api/publishing/token',{platform:'facebook_page',access_token:token,page_id:$('publish-facebook_page-id').value.trim()});
      await refresh(); $('publish-facebook_page-id').value = view.data.accounts.facebook_page.page_id;
      reviewedReset(); feedback('Connected Facebook Page: ' + view.data.accounts.facebook_page.name + '.');
    } finally { input.value = ''; }
  });
  dialog.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button || button.disabled) return;
    const {connect:connectPlatform,disconnect,setup,saveSettings,finish,uploader,copy,mark,markFinish,markCancel,verifyFacebook,verifyInstagram,instagramPage,resetPlatform,resetField,direct,checkAccount} = button.dataset;
    if (resetPlatform) {
      if (resetField) { delete view.overrides[resetPlatform]?.[resetField]; if (!Object.keys(view.overrides[resetPlatform] || {}).length) delete view.overrides[resetPlatform]; }
      else delete view.overrides[resetPlatform];
      draftChanged();
    }
    else if (direct) { $('publish-platform').value = direct; optionsChanged(); $('publish-submit-area').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',block:'nearest'}); $('publish-reviewed').focus(); }
    else if (checkAccount) action(async()=> {
      const result = await view.api('/api/publishing/check-account',{platform:checkAccount});
      await refresh(); reviewedReset(); feedback(result.message,!result.ok);
    });
    else if (instagramPage) action(async()=> {
      const result = await view.api('/api/publishing/instagram-page',{});
      await refresh(); reviewedReset(); feedback(result.message);
    });
    else if (verifyInstagram) action(async()=> {
      const result = await view.api('/api/publishing/verify-instagram',{id:view.project.id,job_id:verifyInstagram});
      await refresh(); reviewedReset(); feedback(result.message);
    });
    else if (connectPlatform) action(()=>connect(connectPlatform));
    else if (verifyFacebook) action(async()=> {
      const result = await view.api('/api/publishing/verify-facebook',{id:view.project.id,job_id:verifyFacebook});
      await refresh(); reviewedReset(); feedback(result.message);
    });
    else if (disconnect) action(async()=> { await view.api('/api/publishing/disconnect',{platform:disconnect}); delete view.pending[disconnect]; await refresh(); reviewedReset(); feedback(labels[disconnect] + ' disconnected.'); });
    else if (setup) {
      $('publish-setup').open = true;
      $('publish-' + setup + '-setup').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',block:'nearest'});
      (setup === 'instagram' ? $('publish-instagram-page-connect') : $('publish-' + setup + (setup === 'facebook_page' ? '-token' : '-id'))).focus({preventScroll:true});
    }
    else if (saveSettings) action(async()=> {
      const secret = $('publish-' + saveSettings + '-secret');
      try { await view.api('/api/publishing/settings',{platform:saveSettings,client_id:$('publish-' + saveSettings + '-id').value.trim(),client_secret:secret.value,redirect_uri:saveSettings === 'instagram' ? $('publish-instagram-redirect-input').value.trim() : ''}); await refresh(); feedback(labels[saveSettings] + ' app settings saved. Click Connect to authorize your account.'); }
      finally { secret.value = ''; }
    });
    else if (finish) action(async()=> {
      const input = $('publish-' + finish + '-callback'); const redirect = input.value.trim();
      if (!redirect) throw new Error('Paste the complete redirect URL from the browser first.');
      try { await view.api('/api/publishing/oauth/finish',{platform:finish,redirect_url:redirect}); delete view.pending[finish]; await refresh(); feedback(labels[finish] + ' connected.'); }
      finally { input.value = ''; }
    });
    else if (uploader) { window.open(uploaders[uploader],'_blank','noopener,noreferrer'); feedback('Download the finished video and paste your caption in ' + labels[uploader] + '.'); }
    else if (copy !== undefined) action(()=>copyCaption(copy));
    else if (mark) showManual(mark);
    else if (markCancel) { dialog.querySelector('[data-manual-form="' + markCancel + '"]').hidden = true; }
    else if (markFinish) action(async()=> {
      const input = dialog.querySelector('[data-post-url="' + markFinish + '"]'); const link = input.value.trim();
      if (link && !secureLink(link)) throw new Error('Use a complete HTTPS post link, or leave it blank.');
      await saveDraft(); await view.api('/api/publishing/mark',{id:view.project.id,platform:markFinish,url:link});
      dialog.querySelector('[data-manual-form="' + markFinish + '"]').hidden = true; await refresh(); feedback(labels[markFinish] + ' marked as published in local history.');
    });
  });
  window.addEventListener('beforeunload',event=> { if (view.dirty) { event.preventDefault(); event.returnValue = ''; } });
  window.VideoTurboPublishing = {
    configure({api,toast,mediaUrl}) { view.api = api; view.toast = toast || (()=>{}); view.mediaUrl = mediaUrl; lock(); },
    update(project) {
      if (view.project?.id !== project?.id) { view.data = null; view.loadedId = ''; view.dirty = false; view.pending = {}; view.overrides = {}; if (dialog.open) dialog.close(); }
      view.project = project; updateVideo(); lock();
    },
    lock,
    open,
  };
  optionsChanged(); lock();
})();
