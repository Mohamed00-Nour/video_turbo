'use strict';
const $ = id => document.getElementById(id);
const state = { token: '', projects: [], project: null, selected: 0, dirty: false, job: null, finished: '', busy: false, timer: null, brief: null };
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const url = (file, id = state.project?.id) => '/media?id=' + encodeURIComponent(id) + '&file=' + encodeURIComponent(file);
function toast(message, error = false) { $('toast').textContent = message; $('toast').classList.toggle('error', error); $('toast').hidden = false; clearTimeout(state.timer); state.timer = setTimeout(() => $('toast').hidden = true, error ? 9000 : 3500); }
async function api(path, data) {
  const result = await fetch(path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Studio-Token':state.token}, body:JSON.stringify(data)});
  const payload = await result.json(); if (!result.ok) throw new Error(payload.error || 'Request failed.'); return payload;
}
async function attempt(fn) { try { await fn(); } catch (error) { toast(error.message, true); } }
function dirty() { state.dirty = true; $('save-state').textContent = 'Unsaved changes'; }
function listProjects() { $('projects').innerHTML = state.projects.map(p => `<button data-project="${esc(p.id)}" class="${p.id === state.project?.id ? 'active' : ''}">${esc(p.name)}</button>`).join(''); }
async function refreshState() { const data = await api('/api/state'); state.token = data.token; state.projects = data.projects; state.job = data.job; listProjects(); const select = $('preset'); select.querySelectorAll('[data-custom]').forEach(e => e.remove()); for (const preset of data.presets) { const option = document.createElement('option'); option.value = preset; option.textContent = preset + ' · saved layout'; option.dataset.custom = '1'; select.append(option); } showJob(); }
function install(project) { state.project = project; state.selected = 0; state.dirty = false; $('empty').hidden = true; $('workspace').hidden = false; $('project-name').textContent = project.editor.name || 'Untitled video'; $('project-path').textContent = project.path; $('save-state').textContent = 'Saved locally'; $('script').value = project.editor.script || ''; updateMedia(); renderSections(); layoutPreview(); listProjects(); lockControls(); }
async function openProject(id) { if (state.dirty && !confirm('Discard unsaved changes and open another project?')) return; install(await api('/api/project?id=' + encodeURIComponent(id))); }
function updateMedia() {
 const p = state.project; $('voice-name').textContent = p.voiceover || 'MP3, WAV, M4A, FLAC'; $('music-name').textContent = p.music ? 'Music added · MP3' : 'MP3 · mixed below your voice'; $('background-name').textContent = p.background ? 'Custom background added' : 'MP4 · replaces the main background';
 $('media-library').innerHTML = p.media.map(m => `<span class="media-chip" title="${esc(m.path)}">${m.kind === 'video' ? '▷' : '▧'} ${esc(m.name)}</span>`).join('');
 const audio = $('voice-player'); audio.hidden = !p.voiceover; if (p.voiceover) { const src = url(p.voiceover); if (audio.getAttribute('src') !== src) audio.src = src; }
 $('download').hidden = !p.final; $('download').href = url('output/final.mp4'); $('download').setAttribute('download', (p.editor.name || 'video') + '.mp4');
}
function options(selected, kind = '') { return '<option value="">Choose media…</option>' + state.project.media.filter(m => !kind || m.kind === kind).map(m => `<option value="${esc(m.path)}" ${m.path === selected ? 'selected' : ''}>${esc(m.name)}</option>`).join(''); }
const input = (label,key,value,extra='') => `<label class="field">${label}<input data-field="${key}" value="${esc(value)}" ${extra}></label>`;
const select = (label,key,values,value) => `<label class="field">${label}<select data-field="${key}">${values.map(([v,t]) => `<option value="${v}" ${v === value ? 'selected' : ''}>${t}</option>`).join('')}</select></label>`;
function renderSections() {
 const editor = state.project.editor, games = editor.mode === 'games', items = games ? editor.games : editor.sections;
 $('sections-heading').textContent = games ? 'Your game list' : 'Build your sections'; $('save-preset').hidden = games; $('add-section').textContent = games ? '＋ Add game' : '＋ Add section'; $('section-hint').textContent = games ? 'Choose YouTube gameplay or uploaded MP4 clips. Game names in your script determine the timing.' : 'Reorder sections, then choose a start time or phrase. Empty start fields share the remaining time evenly.';
 $('sections').innerHTML = items.map((s,i) => `<article class="section ${i === state.selected ? 'selected' : ''}" data-index="${i}"><div class="section-top"><div class="section-title" data-action="select"><span class="section-index">${String(i + 1).padStart(2,'0')}</span>${esc(s.title || 'Untitled section')}</div><div class="section-controls"><button class="quiet" data-action="up" title="Move earlier" ${i === 0 ? 'disabled' : ''}>↑</button><button class="quiet" data-action="down" title="Move later" ${i === items.length - 1 ? 'disabled' : ''}>↓</button><button class="quiet" data-action="remove" title="Remove section">×</button></div></div><div class="section-fields">${input('Section name','title',s.title || '')}${games ? input('Folder name','folder',s.folder || '') : select('Layout','layout',[['background','Background only'],['single','One clip / screenshot'],['split','Two stacked clips / screenshots'],['title','Title card']],s.layout || 'single')}
 ${games ? `${input('YouTube gameplay URL','url',s.url || '', 'placeholder="https://youtu.be/…"')}${input('Spoken game names (comma separated)','spoken_names',(s.spoken_names || []).join(', '),'dir="auto"')}<label class="field">Top clip <select data-field="top">${options(s.top,'video')}</select></label><label class="field">Bottom clip <select data-field="bottom">${options(s.bottom,'video')}</select></label><label class="field">Uploaded logo (optional)<select data-field="logo">${options(s.logo,'image')}</select></label>${input('Or download logo from image URL','logo_url',s.logo_url || '', 'placeholder="https://…/logo.png"')}<label class="check"><input data-field="captions_global" type="checkbox" ${editor.captions !== false ? 'checked' : ''}> Captions during game clips</label>` : `
 ${['single','split'].includes(s.layout) ? `<label class="field">Main clip or screenshot<select data-field="media">${options(s.media)}</select></label>` : ''}
 ${s.layout === 'split' ? `<label class="field">Second clip or screenshot<select data-field="secondary_media">${options(s.secondary_media)}</select></label>` : ''}
 ${input('Start at second (optional)','start_seconds',s.start_seconds ?? '', 'type="number" min="0" step="0.1" placeholder="Automatic"')}
 ${input('Or start when these words are spoken','start_phrase',s.start_phrase || '', 'dir="auto" placeholder="Phrase from your script"')}
 ${input('On-screen label (optional)','label',s.label || '', 'dir="auto"')}
 ${select('Background','background',[['gta_background.mp4','Main / GTA'],['roblox.mp4','Roblox'],['fortnite.mp4','Fortnite']],s.background || 'gta_background.mp4')}
 <label class="check"><input data-field="captions" type="checkbox" ${s.captions !== false ? 'checked' : ''}> Show captions</label>
 `}</div>${!games ? `<details class="advanced"><summary>Framing & highlight</summary><div class="section-fields">${select('Media framing','fit',[['contain','Show entire recording'],['cover','Fill the card']],s.fit || 'contain')}${input('Caption height (0–1)','caption_y',s.caption_y ?? .76,'type="number" min="0" max="1" step="0.01"')}${input('Clip start offset (seconds)','offset_seconds',s.offset_seconds ?? 0,'type="number" min="0" step="0.1"')}${input('End zoom (1–1.5)','zoom',s.zoom ?? 1.04,'type="number" min="1" max="1.5" step="0.01"')}<label class="check wide"><input data-field="highlight_enabled" type="checkbox" ${s.highlight ? 'checked' : ''}> Highlight an area of the main media card</label>${s.highlight ? ['x','y','width','height'].map(key => input('Highlight '+ key +' (%)','highlight.'+key,s.highlight[key],'type="number" min="0" max="100" step="1"')).join('') : ''}</div><p class="hint">Highlight coordinates are percentages of the media card. Start timing refers to the voiceover; clip offset selects the footage inside your recording.</p></details>` : ''}</article>`).join(''); lockControls();
}
function selected() { const editor = state.project.editor; return (editor.mode === 'games' ? editor.games : editor.sections)[state.selected]; }
function layoutPreview() {
 if (!state.project) return;
 $('rendered-preview').hidden = true; $('final-player').hidden = true; $('final-player').pause(); $('live-preview').hidden = false; $('layout-preview').hidden = true; $('preview-mode').textContent = 'Layout preview';
 const s = selected() || {layout:'background'}, game = state.project.editor.mode === 'games';
 const background = s.background || 'gta_background.mp4', custom = background === 'gta_background.mp4' && state.project.background;
 const src = custom ? url(background) : '/library/' + background;
 const bg = $('preview-bg'); if (bg.getAttribute('src') !== src) { bg.src = src; bg.play().catch(()=>{}); }
 bg.style.filter = !game && s.layout === 'background' ? '' : 'blur(1px) brightness(.7)';
 const makeCard = (path,top,height,primary=true) => { const media = state.project.media.find(m => m.path === path); return `<div class="media-card" style="top:${top}%;height:${height}%">${media ? media.kind === 'image' ? `<img src="${url(path)}" style="object-fit:${s.fit || 'contain'}">` : `<video src="${url(path)}" muted loop autoplay playsinline style="object-fit:${s.fit || 'contain'}"></video>` : '<div class="media-placeholder">Choose a clip or screenshot</div>'}${primary && s.highlight ? `<div class="highlight" style="left:${Number(s.highlight.x)}%;top:${Number(s.highlight.y)}%;width:${Number(s.highlight.width)}%;height:${Number(s.highlight.height)}%"></div>` : ''}</div>`; };
 let content = '';
 if (game) { const folder = s.folder || ''; content = makeCard(s.top || `games/${folder}/top.mp4`,11.46,25) + makeCard(s.bottom || `games/${folder}/bottom.mp4`,67.7,25,false); }
 else if (s.layout === 'single') content = makeCard(s.media,16.67,52.08);
 else if (s.layout === 'split') content = makeCard(s.media,11.46,25) + makeCard(s.secondary_media,55.73,25,false);
 else if (s.layout === 'title') content = `<div class="title-card" dir="auto">${esc(s.title)}</div>`;
 if (s.label) content += `<div class="preview-label" dir="auto" ${s.layout === 'split' ? 'style="top:40.6%"' : ''}>${esc(s.label)}</div>`;
 $('preview-content').innerHTML = content;
 $('preview-caption').style.top = ((game ? .6276 : s.caption_y ?? .76) * 100) + '%';
 $('preview-caption').hidden = game ? state.project.editor.captions === false : s.captions === false;
 $('preview-caption').textContent = (state.project.editor.script || '').split(/\s+/).find(Boolean) || 'Your caption';
 $('preview-note').textContent = 'Layout preview; render a frame for exact captions, transitions and timing.';
}
function lockControls() { const busy = !state.token || state.busy || ['running','cancelling'].includes(state.job?.status); document.querySelectorAll('button,input,select,textarea').forEach(e => { if (e.id !== 'cancel') e.disabled = busy; }); document.querySelectorAll('[data-action="up"],[data-action="down"]').forEach(e => { const i = Number(e.closest('[data-index]').dataset.index), len = (state.project?.editor.mode === 'games' ? state.project.editor.games : state.project?.editor.sections)?.length || 0; e.disabled = busy || e.dataset.action === 'up' && i === 0 || e.dataset.action === 'down' && i === len - 1; }); $('cancel').disabled = state.job?.status !== 'running'; $('brief-create').disabled = busy || !state.brief; }
async function save() { if (!state.project) return; state.project.editor.script = $('script').value; const selectedIndex = state.selected; const p = await api('/api/save',{id:state.project.id,editor:state.project.editor}); state.project = p; state.selected = selectedIndex; state.dirty = false; $('save-state').textContent = 'Saved locally'; updateMedia(); renderSections(); await refreshState(); }
async function upload(input, role) { if (!state.project || !input.files.length) return; state.busy = true; lockControls(); const editor = state.project.editor; try { for (const file of input.files) { toast('Uploading '+file.name+'…'); const response = await fetch('/api/upload?id='+state.project.id+'&name='+encodeURIComponent(file.name)+'&role='+role,{method:'POST',headers:{'X-Studio-Token':state.token},body:file}); const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Upload failed.'); state.project = data.project; state.project.editor = editor; } updateMedia(); renderSections(); layoutPreview(); dirty(); toast('Media added. Choose it in your section.'); } finally { state.busy = false; input.value = ''; lockControls(); } }
async function start(action) { await save(); const at = Number($('preview-at').value); if (action === 'preview' && (!Number.isFinite(at) || at < 0)) throw new Error('Choose a valid preview time.'); state.job = await api('/api/start',{id:state.project.id,action,at}); showJob(); }
function showJob() {
 const job = state.job; $('job-panel').hidden = !job; lockControls(); if (!job) return;
 $('job-stage').textContent = job.error || job.stage; $('job-percent').textContent = Math.round(job.progress)+'%'; $('progress').value = job.progress;
 const seconds = Math.floor((job.finished || Date.now()/1000) - job.started); $('job-time').textContent = Math.floor(seconds/60)+'m '+seconds%60+'s'; $('logs').textContent = job.logs.join('\n'); $('cancel').hidden = !['running','cancelling'].includes(job.status);
 if (['complete','failed','cancelled'].includes(job.status) && state.finished !== job.id) { state.finished = job.id; if (job.status === 'complete' && state.project?.id === job.project) attempt(async()=> { const p = await api('/api/project?id='+job.project); state.project = p; updateMedia(); if (job.action === 'preview') { $('live-preview').hidden = true; $('final-player').hidden = true; $('rendered-preview').src = url('output/studio_preview.png')+'&v='+Date.now(); $('rendered-preview').hidden = false; $('preview-mode').textContent = 'Rendered frame'; $('preview-note').textContent = 'Exact frame at '+$('preview-at').value+' seconds.'; } else { $('live-preview').hidden = true; $('rendered-preview').hidden = true; $('final-player').src = url('output/final.mp4')+'&v='+Date.now(); $('final-player').hidden = false; $('preview-mode').textContent = 'Finished video'; $('preview-note').textContent = 'Your video is ready. Play it here or download it.'; } $('layout-preview').hidden = false; toast(job.action === 'preview' ? 'Preview ready.' : 'Video complete.'); }); else if (job.status === 'failed') toast(job.error || 'Build failed; check the log.',true); }
}
$('script').addEventListener('input',()=>{state.project.editor.script=$('script').value; dirty(); layoutPreview();});
$('projects').addEventListener('click',e=>{ const button=e.target.closest('[data-project]'); if(button) attempt(()=>openProject(button.dataset.project)); });
$('sections').addEventListener('click',e=>{ const button=e.target.closest('[data-action]'); if(!button)return; const i=Number(button.closest('[data-index]').dataset.index); const items=state.project.editor.mode==='games'?state.project.editor.games:state.project.editor.sections; const action=button.dataset.action; state.selected=i; if(action==='up'||action==='down'){const other=i+(action==='up'?-1:1);[items[i],items[other]]=[items[other],items[i]];state.selected=other;dirty();} if(action==='remove'){if(items.length===1)return toast('Keep at least one section.',true);items.splice(i,1);state.selected=Math.min(i,items.length-1);dirty();} renderSections();layoutPreview(); });
$('sections').addEventListener('change',e=>{ const target=e.target,key=target.dataset.field;if(!key)return;const i=Number(target.closest('[data-index]').dataset.index);const editor=state.project.editor, s=(editor.mode==='games'?editor.games:editor.sections)[i]; let value=target.type==='checkbox'?target.checked:target.type==='number'?(target.value===''?null:Number(target.value)):target.value;if(key==='spoken_names')value=value.split(',').map(v=>v.trim()).filter(Boolean);if(key==='captions_global')editor.captions=value;else if(key==='highlight_enabled')s.highlight=value?{x:20,y:20,width:50,height:30}:null;else if(key.startsWith('highlight.'))s.highlight[key.split('.')[1]]=value;else s[key]=value;state.selected=i;dirty();if(['layout','highlight_enabled'].includes(key))renderSections();layoutPreview(); });
$('add-section').onclick=()=>{const editor=state.project.editor,items=editor.mode==='games'?editor.games:editor.sections;items.push(editor.mode==='games'?{title:'New game',folder:String(items.length+1).padStart(2,'0')+'_game',spoken_names:[]}:{title:'New section',layout:'single',caption_y:.76});state.selected=items.length-1;dirty();renderSections();layoutPreview();};
for(const [id,role] of [['voice-input','voice'],['music-input','music'],['background-input','background'],['media-input','media']])$(id).onchange=()=>attempt(()=>upload($(id),role));
$('save').onclick=()=>attempt(async()=>{await save();toast('Project saved.');});$('build').onclick=()=>attempt(()=>start('build'));$('render-preview').onclick=()=>attempt(()=>start('preview'));$('layout-preview').onclick=layoutPreview;$('cancel').onclick=()=>attempt(async()=>{await api('/api/cancel',{});state.job=await api('/api/job');showJob();});
function createDialog(){ $('create-dialog').showModal();$('new-name').focus(); }$('new-project').onclick=createDialog;$('empty-create').onclick=createDialog;$('close-dialog').onclick=()=>$('create-dialog').close();
$('create-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{if(state.dirty&&!confirm('Discard unsaved changes and create a project?'))return;const p=await api('/api/create',{name:$('new-name').value,preset:$('preset').value});$('create-dialog').close();await refreshState();install(p);});};
$('import-project').onclick=()=>attempt(async()=>{const path=prompt('Paste the path of an existing video project folder:');if(!path)return;if(state.dirty&&!confirm('Discard unsaved changes and open this folder?'))return;const p=await api('/api/import',{path});await refreshState();install(p);});
$('save-preset').onclick=()=>attempt(async()=>{const name=prompt('Name this reusable layout preset:');if(!name)return;await api('/api/preset',{name,sections:state.project.editor.sections});await refreshState();toast('Layout saved. Choose it when creating a new video.');});
const aiBriefPrompt = `Write a short video script in Egyptian Arabic for this idea: [REPLACE WITH MY IDEA, GAMES AND TARGET LENGTH].
Return one JSON object for Video Turbo, with this structure:
{
  "project_name": "Short project title",
  "script": "Complete narration, with an opening, games in order and a closing",
  "games": [
    {
      "exact_name": "Exact game title",
      "spoken_names": ["Game name exactly as written and pronounced in the narration"],
      "youtube_gameplay_url": "A verified YouTube gameplay video URL",
      "logo_image_url": null
    }
  ]
}
Use web browsing to find and open each gameplay source. Choose real footage of the correct game, preferably without commentary, face cameras or long menus. Use complete individual video links, never placeholders or playlist-only URLs. Supply a direct PNG, JPG or WEBP logo link from an official or reputable source when available; otherwise use null. Do not invent URLs or claim to have verified a source you could not open. If browsing is unavailable, ask me for gameplay links before producing the final brief.
Keep URLs, asset metadata, headings and stage directions outside the script. The script must contain only the words I will record. List the games in narration order and include the Egyptian Arabic spellings or English names used in the script in spoken_names. Escape JSON correctly and output JSON only.`;
$('brief-prompt').textContent = aiBriefPrompt;
function resetBrief() { state.brief = null; $('brief-review').hidden = true; $('brief-error').hidden = true; lockControls(); }
$('import-brief').onclick = () => { resetBrief(); $('brief-dialog').showModal(); $('brief-text').focus(); };
$('close-brief').onclick = () => $('brief-dialog').close();
$('brief-text').oninput = resetBrief;
$('brief-file').onchange = () => attempt(async () => { const file = $('brief-file').files[0]; if (!file) return; if (file.size > 1024 * 1024) throw new Error('Use a JSON brief below 1 MB.'); $('brief-text').value = await file.text(); $('brief-file').value = ''; resetBrief(); });
$('copy-brief-prompt').onclick = () => attempt(async () => { await navigator.clipboard.writeText(aiBriefPrompt); toast('AI prompt copied. Replace the idea and target length before sending it.'); });
async function checkBrief() {
 resetBrief(); state.busy = true; lockControls();
 try {
  const parsed = await api('/api/brief/validate', {brief:$('brief-text').value});
  state.brief = parsed; const editor = parsed.editor;
  const words = editor.script.split(/\s+/).filter(Boolean).length;
  $('brief-review').innerHTML = `<h3>${esc(editor.name)}</h3><span class="muted">${editor.games.length} games · ${words} script words · new project</span><ul class="brief-games">${editor.games.map(game => `<li><strong dir="auto">${esc(game.title)}</strong><a href="${esc(game.url)}" target="_blank" rel="noopener noreferrer">View gameplay ↗</a><small dir="auto">Spoken names: ${game.spoken_names.map(esc).join(', ')}</small><small>${game.logo_url ? 'Logo link included' : 'Logo optional; no link supplied'}</small></li>`).join('')}</ul><p class="hint">The JSON and link formats are valid. Preparation checks new gameplay sources before downloading. Review footage yourself to confirm it matches your game.</p>`;
  $('brief-review').hidden = false;
 } catch (error) { $('brief-error').textContent = error.message; $('brief-error').hidden = false; }
 finally { state.busy = false; lockControls(); }
}
$('check-brief').onclick = checkBrief;
$('brief-form').onsubmit = event => { event.preventDefault(); attempt(async () => {
 if (!state.brief) return checkBrief();
 if (state.dirty && !confirm('Discard unsaved changes and create a project from this brief?')) return;
 state.busy = true; lockControls();
 try { const project = await api('/api/brief/import', {brief:$('brief-text').value}); $('brief-dialog').close(); await refreshState(); install(project); toast('Brief imported. Upload your voiceover, then preview or build.'); }
 finally { state.busy = false; lockControls(); }
}); };
$('preview-bg').onerror=()=>{$('preview-note').textContent='This background is unavailable. Upload a main background or choose another one.';};
window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue='';}});
lockControls();attempt(refreshState);setInterval(()=>attempt(async()=>{state.job=await api('/api/job');showJob();}),2000);