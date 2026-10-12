(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels = {youtube:'YouTube',instagram:'Instagram',tiktok:'TikTok',facebook:'Facebook profile',facebook_page:'Facebook Page'};
  const uploaders = {youtube:'https://studio.youtube.com/',instagram:'https://www.instagram.com/',tiktok:'https://www.tiktok.com/tiktokstudio/upload',facebook:'https://www.facebook.com/reels/create'};
  const terminal = new Set(['complete','failed','cancelled','interrupted']);
  const view = {project:null,data:null,api:null,toast:()=>{},mediaUrl:null,studioBusy:false,busy:false,dirty:false,timer:null,polling:false,loading:false,loadedId:'',pending:{},lastCompleted:''};
  const dialog = $('publish-dialog');
  if (!dialog) return;

  $('publish-panel').innerHTML = `
    <div class="publish-heading"><div><div class="eyebrow">YOUR VIDEO, YOUR CHANNELS</div><h2 id="publish-heading">Publish your video</h2><p class="hint" id="publish-project-name"></p></div><button type="button" class="quiet publish-close" id="publish-close" aria-label="Close publishing">&times;</button></div>
    <div class="publish-grid"><div>
      <label class="field">Video title<input id="publish-title" maxlength="100" dir="auto" placeholder="A title for YouTube or your Facebook Page"></label><span class="publish-title-counter" id="publish-title-counter">0 / 100</span>
      <label class="field">Description / caption<textarea id="publish-description" rows="5" maxlength="5000" dir="auto" placeholder="Tell viewers what this video is about"></textarea></label>
      <label class="field">Hashtags<input id="publish-hashtags" dir="auto" placeholder="#gaming #العاب"></label>
      <div class="publish-draft-footer"><span id="publish-draft-state">Saved with this project</span><button type="button" class="outline small" id="publish-save">Save posting details</button></div>
      <p class="hint">Your caption and hashtags are used for each destination. YouTube and Facebook Pages also use the title.</p>
    </div><aside class="publish-preview-column"><video id="publish-preview" class="publish-preview" controls playsinline preload="metadata"></video><div><a id="publish-download" class="outline full" download>Download finished video</a><p class="hint" id="publish-video-state">Checking the finished video...</p></div></aside></div>
    <div class="publish-platforms">
      <article class="publish-card"><div class="publish-card-heading"><h3><span class="publish-platform-icon">YT</span>YouTube</h3><span class="publish-status" id="publish-youtube-status">Not connected</span></div><p class="hint" id="publish-youtube-account">Connect your YouTube channel for direct uploads.</p><div class="publish-card-actions"><button type="button" class="outline small" data-connect="youtube">Connect channel</button><button type="button" class="quiet small" data-disconnect="youtube" hidden>Disconnect</button><button type="button" class="quiet small" data-setup="youtube">Account setup</button></div></article>
      <article class="publish-card"><div class="publish-card-heading"><h3><span class="publish-platform-icon">IG</span>Instagram</h3><span class="publish-status" id="publish-instagram-status">Not connected</span></div><p class="hint" id="publish-instagram-account">Connect your Professional account to publish Reels.</p><div class="publish-card-actions"><button type="button" class="outline small" data-connect="instagram">Connect account</button><button type="button" class="quiet small" data-disconnect="instagram" hidden>Disconnect</button><button type="button" class="quiet small" data-setup="instagram">Account setup</button><button type="button" class="quiet small" data-uploader="instagram">Open Instagram</button><button type="button" class="quiet small" data-copy>Copy caption</button><button type="button" class="quiet small" data-mark="instagram">Mark published</button></div><p class="hint">Posting inside Instagram lets you choose your linked Facebook profile. Direct API publishing does not guarantee Facebook sharing.</p><div data-manual-form="instagram" hidden></div></article>
      <article class="publish-card"><div class="publish-card-heading"><h3><span class="publish-platform-icon">FB</span>Facebook Page</h3><span class="publish-status" id="publish-facebook_page-status">Not connected</span></div><p class="hint" id="publish-facebook_page-account">Connect a Page you manage for automatic Reel publishing.</p><div class="publish-card-actions"><button type="button" class="outline small" data-setup="facebook_page">Connect Page / account setup</button><button type="button" class="quiet small" data-disconnect="facebook_page" hidden>Disconnect Page</button></div><p class="hint">Uploads the finished MP4 directly to your Page. Your personal Facebook profile remains a separate destination.</p></article>
      <article class="publish-card"><div class="publish-card-heading"><h3><span class="publish-platform-icon">TT</span>TikTok</h3><span class="publish-status">Assisted upload</span></div><p class="hint">Download your video, copy the caption and finish publishing in TikTok.</p><div class="publish-card-actions"><button type="button" class="outline small" data-uploader="tiktok">Open uploader</button><button type="button" class="quiet small" data-copy>Copy caption</button><button type="button" class="quiet small" data-mark="tiktok">Mark published</button></div><div data-manual-form="tiktok" hidden></div></article>
      <article class="publish-card"><div class="publish-card-heading"><h3><span class="publish-platform-icon">FB</span>Facebook profile</h3><span class="publish-status">Assisted upload</span></div><p class="hint">Publish through Instagram's Share to Facebook option, or upload the video on Facebook.</p><div class="publish-card-actions"><button type="button" class="outline small" data-uploader="facebook">Open Facebook</button><button type="button" class="quiet small" data-copy>Copy caption</button><button type="button" class="quiet small" data-mark="facebook">Mark published</button></div><div data-manual-form="facebook" hidden></div></article>
    </div>
    <div class="publish-submit-area"><h3>Direct upload</h3><div class="publish-options"><label class="field">Destination<select id="publish-platform"><option value="youtube">YouTube</option><option value="instagram">Instagram Reel</option><option value="facebook_page">Facebook Page Reel</option></select></label><label class="field" id="publish-privacy-field">YouTube visibility<select id="publish-privacy"><option value="private">Private</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></label></div>
      <div id="publish-youtube-options"><label class="check"><input type="checkbox" id="publish-kids">This video is made for kids</label><p class="hint">Leave this unchecked only if the video is not made for kids. Review your audience choice before uploading.</p></div>
      <div id="publish-instagram-options" hidden><label class="check"><input type="checkbox" id="publish-feed" checked>Also show this Reel on my Instagram feed</label><label class="field">Public HTTPS link to this finished MP4<input id="publish-instagram-url" type="url" placeholder="https://your-host.example/final.mp4" autocomplete="off"></label><p class="hint">Instagram must be able to fetch the MP4 from a public HTTPS address. A file on your computer cannot be used as this link. Assisted upload above works with your local file.</p></div>
      <div id="publish-facebook_page-options" hidden><p class="hint">Publishes a Reel on the connected Facebook Page using this finished MP4, caption and hashtags. No public video link is needed.</p></div>
      <label class="check publish-review"><input type="checkbox" id="publish-reviewed">I watched the finished video and reviewed the destination, caption and publishing settings.</label><div class="publish-submit-row"><p class="hint" id="publish-requirements">Connect an account, then review your video.</p><button type="button" class="primary" id="publish-submit">Upload to YouTube</button></div>
    </div>
    <div id="publish-error" class="publish-error" role="alert" hidden></div><div id="publish-feedback" class="publish-feedback" role="status" hidden></div>
    <div id="publish-job" class="publish-job" hidden><div class="publish-job-top"><strong id="publish-job-stage"></strong><span id="publish-job-percent"></span></div><progress id="publish-job-progress" max="100" value="0"></progress><p id="publish-job-detail"></p><a id="publish-job-link" class="outline full" target="_blank" rel="noopener noreferrer" hidden>Open uploaded video</a></div>
    <section class="publish-history"><h3>Posting history</h3><ul id="publish-history-list" class="publish-history-list"></ul></section>
    <details class="publish-setup" id="publish-setup"><summary>Connect accounts and configure API access</summary><p class="hint">Set up your own API apps once. Credentials are stored on this computer. Blank secret fields keep your saved values.</p><div class="publish-setup-grid">
      <section class="publish-setup-card" id="publish-youtube-setup"><h3>YouTube account setup</h3><p class="hint">Create a Google OAuth client for a Desktop app and enable the YouTube Data API. Add your Google account as a test user while the app is in testing.</p><a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer" class="outline small">Open Google API credentials</a><label class="field">OAuth client ID<input id="publish-youtube-id" autocomplete="off" spellcheck="false"></label><label class="field">OAuth client secret<input id="publish-youtube-secret" type="password" autocomplete="new-password" placeholder="Paste a secret, or leave blank to keep it"></label><div class="publish-form-buttons"><button type="button" class="outline small" data-save-settings="youtube">Save YouTube setup</button></div><p id="publish-youtube-configured" class="publish-setup-status"></p><p class="hint">Sign-in returns to <code id="publish-youtube-redirect"></code>.</p><details class="publish-callback"><summary>Finish sign-in manually</summary><label class="field">Completed browser redirect URL<input type="password" autocomplete="off" id="publish-youtube-callback" placeholder="Paste the complete redirect URL"></label><button type="button" class="outline small full" data-finish="youtube">Complete connection</button></details></section>
      <section class="publish-setup-card" id="publish-instagram-setup"><h3>Instagram account setup</h3><p class="hint">Configure a Meta app with Instagram Login and publishing permissions for your Professional account.</p><a href="https://developers.facebook.com/apps/" target="_blank" rel="noopener noreferrer" class="outline small">Open Meta apps</a><label class="field">Instagram app ID<input id="publish-instagram-id" autocomplete="off" spellcheck="false"></label><label class="field">Instagram app secret<input id="publish-instagram-secret" type="password" autocomplete="new-password" placeholder="Paste a secret, or leave blank to keep it"></label><label class="field">Registered HTTPS redirect URI<input id="publish-instagram-redirect-input" type="url" placeholder="https://your-site.example/callback" autocomplete="off"></label><div class="publish-form-buttons"><button type="button" class="outline small" data-save-settings="instagram">Save Instagram setup</button></div><p id="publish-instagram-configured" class="publish-setup-status"></p><details class="publish-callback"><summary>Finish sign-in manually</summary><p class="hint">After authorizing Instagram, copy the complete final URL from your browser's address bar and paste it here.</p><label class="field">Completed browser redirect URL<input type="password" autocomplete="off" id="publish-instagram-callback" placeholder="Paste the complete redirect URL"></label><button type="button" class="outline small full" data-finish="instagram">Complete connection</button></details><details class="publish-callback"><summary>Connect with an Instagram access token instead</summary><p class="hint">Use a token issued for your own Instagram Professional account with publishing permissions. It is sent only to your local Studio and never shown after saving.</p><label class="field">Instagram access token<input id="publish-instagram-token" type="password" autocomplete="off" placeholder="Paste your access token"></label><button type="button" class="outline small full" id="publish-token-connect">Connect token</button></details></section>
      <section class="publish-setup-card" id="publish-facebook_page-setup"><h3>Facebook Page account setup</h3><p class="hint">Connect the Page you manage with your Facebook profile. The token identifies the Page; its name appears above before you publish.</p><a href="https://developers.facebook.com/tools/explorer/" target="_blank" rel="noopener noreferrer" class="outline small">Open Meta Graph API Explorer</a><details class="publish-callback"><summary>How to get a Page access token</summary><ol class="hint"><li>In your Meta app, enable the Page publishing use case: <strong>Manage everything on your Page</strong>.</li><li>In Graph API Explorer, select that app and get a <strong>User Access Token</strong> with <code>pages_show_list</code>, <code>pages_read_engagement</code> and <code>pages_manage_posts</code>. For a Page in a business portfolio, also request <code>business_management</code> to list its Pages. Generate a new token after adding permissions and authorize the intended business and Page.</li><li>Open <strong>User or Page</strong> and select your Page under <strong>Page Access Tokens</strong>. Alternatively, run <code>GET me/accounts?fields=id,name,access_token,tasks</code> with the user token and copy the access token belonging to your Page.</li><li>Paste that Page token below. Its Page ID is detected automatically.</li></ol></details><label class="field">Page ID (optional check)<input id="publish-facebook_page-id" inputmode="numeric" autocomplete="off" placeholder="Detected from the Page access token"></label><label class="field">Facebook Page access token<input id="publish-facebook_page-token" type="password" autocomplete="off" placeholder="Paste the token issued for your Page"></label><div class="publish-form-buttons"><button type="button" class="outline small" id="publish-facebook_page-connect">Connect Page</button></div><p class="hint">Use a Page token with publishing permissions. Reconnect here if Meta expires or revokes access.</p></section>
    </div></details>`;

  function secureLink(value) {
    try { const parsed = new URL(value); return parsed.protocol === 'https:' ? parsed.href : ''; } catch (_) { return ''; }
  }
  function sameProject() { return view.data && view.loadedId === view.project?.id; }
  function runningJob() { return view.data?.job && !terminal.has(view.data.job.status); }
  function reviewedReset() { $('publish-reviewed').checked = false; lock(); }
  function draftChanged() { view.dirty = true; $('publish-draft-state').textContent = 'Unsaved posting details'; reviewedReset(); }
  function draft() {
    return {title:$('publish-title').value.trim(),description:$('publish-description').value,hashtags:$('publish-hashtags').value.trim(),youtube_privacy:$('publish-privacy').value,made_for_kids:$('publish-kids').checked,instagram_share_to_feed:$('publish-feed').checked,instagram_video_url:$('publish-instagram-url').value.trim(),facebook_page_id:view.data?.accounts?.facebook_page?.page_id || ''};
  }
  function caption() { const value = draft(); const tags = value.hashtags.split(/\s+/).map(tag=>tag.replace(/^,+|,+$/g,'').replace(/^#+/,'')).filter(Boolean).map(tag=>'#'+tag).join(' '); return [value.description.trim(),tags].filter(Boolean).join('\n\n'); }
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
    $('publish-facebook_page-status').textContent = page.connected ? 'Connected' : 'Setup needed';
    $('publish-facebook_page-status').classList.toggle('connected',Boolean(page.connected));
    $('publish-facebook_page-account').textContent = page.connected ? page.name + ' - Page ID ' + page.page_id : 'Connect a Page you manage for automatic Reel publishing.';
    dialog.querySelector('[data-disconnect="facebook_page"]').hidden = !page.connected;
    $('publish-youtube-redirect').textContent = view.data?.accounts?.youtube?.redirect_uri || window.location.origin + '/api/publishing/callback/youtube';
  }
  function renderHistory() {
    const history = view.data?.history || [];
    $('publish-history-list').innerHTML = history.length ? history.slice().reverse().map(entry => {
      const link = secureLink(entry.url); const stamp = Number(entry.finished || entry.created || entry.started || 0);
      const date = stamp ? new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(new Date(stamp < 1e12 ? stamp*1000 : stamp)) : '';
      const status = entry.status === 'complete' ? (entry.platform === 'youtube' ? 'Uploaded' : 'Published') : entry.status === 'manual' || entry.status === 'published' ? 'Marked published' : entry.status || '';
      return `<li class="publish-history-item"><div><strong>${esc(labels[entry.platform] || entry.platform)}${entry.destination_name ? ' - ' + esc(entry.destination_name) : ''} &middot; ${esc(status)}</strong><small dir="auto">${esc(entry.title || view.project?.editor?.name || '')}</small><small>${esc(date)}${entry.error ? ' - ' + esc(entry.error) : ''}</small></div>${entry.platform === 'facebook_page' && ['failed','interrupted'].includes(entry.status) && entry.remote_id ? `<button type="button" class="outline small" data-verify-facebook="${esc(entry.id)}">Check existing upload</button>` : ''}${link ? `<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">Open post &nearr;</a>` : ''}</li>`;
    }).join('') : '<li class="publish-empty">Uploads and posts you mark as published will appear here.</li>';
  }
  function renderJob() {
    const job = view.data?.job; const relevant = job && job.project === view.project?.id;
    $('publish-job').hidden = !relevant;
    if (!relevant) return;
    const progress = Math.max(0,Math.min(100,Number(job.progress) || 0));
    $('publish-job-stage').textContent = job.stage || (terminal.has(job.status) ? job.status : 'Uploading');
    $('publish-job-percent').textContent = Math.round(progress) + '%'; $('publish-job-progress').value = progress;
    $('publish-job-detail').textContent = job.error || job.warning || (job.status === 'complete' ? 'The upload finished successfully.' : 'You may close this panel. Keep Studio running until the upload finishes.');
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
    $('publish-privacy-field').hidden = platform !== 'youtube'; $('publish-youtube-options').hidden = platform !== 'youtube'; $('publish-instagram-options').hidden = platform !== 'instagram';
    $('publish-facebook_page-options').hidden = platform !== 'facebook_page';
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
    let reason = !sameProject() ? 'Loading publishing details...' : !view.data.video?.ready ? 'Build your video first.' : uploading ? 'An upload is already running. Wait for it to finish.' : !account?.connected ? 'Connect your ' + labels[platform] + ' account first.' : platform === 'youtube' && !$('publish-title').value.trim() ? 'Add a video title.' : platform === 'instagram' && !secureLink($('publish-instagram-url').value) ? 'Provide a public HTTPS link to the finished MP4, or use assisted upload.' : !$('publish-reviewed').checked ? 'Watch your video, then confirm the review above.' : platform === 'youtube' ? 'Visibility: ' + $('publish-privacy').selectedOptions[0].textContent + '. Upload starts when you click.' : platform === 'facebook_page' ? 'Publishes to ' + account.name + ' when you click.' : 'Your Reel will be published when you click.';
    $('publish-requirements').textContent = reason;
    $('publish-submit').disabled = blocked || uploading || !sameProject() || !view.data?.video?.ready || !account?.connected || !$('publish-reviewed').checked || platform === 'youtube' && !$('publish-title').value.trim() || platform === 'instagram' && !secureLink($('publish-instagram-url').value);
    for (const item of dialog.querySelectorAll('[data-connect]')) item.disabled = blocked || !view.data?.accounts?.[item.dataset.connect]?.configured;
    for (const item of dialog.querySelectorAll('[data-disconnect],[data-save-settings],#publish-token-connect,#publish-facebook_page-connect,[data-verify-facebook]')) item.disabled = blocked || uploading;
    for (const item of dialog.querySelectorAll('[data-uploader],[data-copy],[data-mark]')) item.disabled = blocked || !view.data?.video?.ready;
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
      view.data = data; view.loadedId = id;
      if (initial) { loadDraft(data.draft); loadSetup(); }
      else if ((previousSignature && previousSignature !== data.video?.signature) || (previousPage && previousPage !== data.accounts?.facebook_page?.page_id)) reviewedReset();
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
    await view.api('/api/publishing/save',{id:view.project.id,draft:draft()});
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
  async function copyCaption() {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(caption());
    else { const temporary = document.createElement('textarea'); temporary.value = caption(); dialog.append(temporary); temporary.select(); const copied = document.execCommand('copy'); temporary.remove(); if (!copied) throw new Error('Copy the caption from its field above.'); }
    feedback('Caption and hashtags copied. Paste them into your platform uploader.');
  }
  function showManual(platform) {
    const target = dialog.querySelector('[data-manual-form="' + platform + '"]');
    target.className = 'publish-manual-form'; target.hidden = false;
    target.innerHTML = `<p class="hint">After publishing on ${esc(labels[platform])}, record it here. This button only updates your local history.</p><label class="field">Post link (optional)<input type="url" data-post-url="${platform}" placeholder="https://..."></label><div class="publish-card-actions"><button type="button" class="outline small" data-mark-finish="${platform}">Mark as published</button><button type="button" class="quiet small" data-mark-cancel="${platform}">Cancel</button></div>`;
    lock(); target.querySelector('input').focus();
  }
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
    if (!token) throw new Error('Paste a Facebook Page access token first.');
    try {
      await view.api('/api/publishing/token',{platform:'facebook_page',access_token:token,page_id:$('publish-facebook_page-id').value.trim()});
      await refresh(); $('publish-facebook_page-id').value = view.data.accounts.facebook_page.page_id;
      reviewedReset(); feedback('Connected Facebook Page: ' + view.data.accounts.facebook_page.name + '.');
    } finally { input.value = ''; }
  });
  dialog.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button || button.disabled) return;
    const {connect:connectPlatform,disconnect,setup,saveSettings,finish,uploader,copy,mark,markFinish,markCancel,verifyFacebook} = button.dataset;
    if (connectPlatform) action(()=>connect(connectPlatform));
    else if (verifyFacebook) action(async()=> {
      const result = await view.api('/api/publishing/verify-facebook',{id:view.project.id,job_id:verifyFacebook});
      await refresh(); reviewedReset(); feedback(result.message);
    });
    else if (disconnect) action(async()=> { await view.api('/api/publishing/disconnect',{platform:disconnect}); delete view.pending[disconnect]; await refresh(); reviewedReset(); feedback(labels[disconnect] + ' disconnected.'); });
    else if (setup) { $('publish-setup').open = true; $('publish-' + setup + '-setup').scrollIntoView({behavior:'smooth',block:'nearest'}); $('publish-' + setup + '-id').focus(); }
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
    else if (copy !== undefined) action(copyCaption);
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
      if (view.project?.id !== project?.id) { view.data = null; view.loadedId = ''; view.dirty = false; view.pending = {}; if (dialog.open) dialog.close(); }
      view.project = project; updateVideo(); lock();
    },
    lock,
  };
  optionsChanged(); lock();
})();
