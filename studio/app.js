'use strict';
const $ = id => document.getElementById(id);
const state = { token: '', projects: [], project: null, selected: 0, dirty: false, job: null, finished: '', busy: false, timer: null, brief: null, publishingJob: null, projectMenu: '', deletingProject: '' };
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const url = (file, id = state.project?.id) => '/media?id=' + encodeURIComponent(id) + '&file=' + encodeURIComponent(file);
function toast(message, error = false) { $('toast').textContent = message; $('toast').classList.toggle('error', error); $('toast').hidden = false; clearTimeout(state.timer); state.timer = setTimeout(() => $('toast').hidden = true, error ? 9000 : 3500); }
async function api(path, data, options = {}) {
  const result = await fetch(path, {...options,...(data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Studio-Token':state.token}, body:JSON.stringify(data)})});
  const payload = await result.json(); if (!result.ok) { const error = new Error(payload.error || 'Request failed.'); error.status = result.status; throw error; } return payload;
}
async function attempt(fn) { try { await fn(); } catch (error) { toast(error.message, true); } }
function dirty() { state.dirty = true; $('save-state').textContent = 'Unsaved changes'; window.VideoTurboAI?.update(state.project); }
function listProjects() {
 $('project-count').textContent = state.projects.length;
 $('projects').innerHTML = state.projects.map(p => `<div class="project-row ${p.id === state.project?.id ? 'active' : ''}"><div class="project-row-heading"><button type="button" class="project-open" data-project="${esc(p.id)}" title="${esc(p.name)}" ${p.id === state.project?.id ? 'aria-current="true"' : ''}><span dir="auto">${esc(p.name)}</span></button><button type="button" class="project-menu-toggle" data-project-menu="${esc(p.id)}" aria-label="Project actions for ${esc(p.name)}" title="Edit or delete project" aria-expanded="${state.projectMenu === p.id}" aria-controls="project-actions-${esc(p.id)}"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg></button></div><div class="project-row-actions" id="project-actions-${esc(p.id)}" ${state.projectMenu === p.id ? '' : 'hidden'}><button type="button" data-project-edit="${esc(p.id)}">Edit project</button><button type="button" class="project-delete" data-project-delete="${esc(p.id)}">Delete project</button></div></div>`).join('') || '<p class="projects-empty">Your videos will appear here.</p>';
}
async function refreshState() { const data = await api('/api/state'); state.token = data.token; state.projects = data.projects; state.job = data.job; state.publishingJob = data.publishing_job; listProjects(); const select = $('preset'); select.querySelectorAll('[data-custom]').forEach(e => e.remove()); for (const preset of data.presets) { const option = document.createElement('option'); option.value = preset; option.textContent = preset + ' · saved layout'; option.dataset.custom = '1'; select.append(option); } showJob(); }
function install(project) { state.project = project; state.selected = 0; state.dirty = false; $('empty').hidden = true; $('workspace').hidden = false; $('project-name').textContent = project.editor.name || 'Untitled video'; $('project-path').textContent = project.path; $('save-state').textContent = 'Saved locally'; $('script').value = project.editor.script || ''; window.VideoTurboAI?.update(project); updateMedia(); renderSections(); layoutPreview(); listProjects(); lockControls(); }
async function openProject(id) { if (state.project?.id === id) return true; if (state.dirty && !confirm('Discard unsaved changes and open another project?')) return false; install(await api('/api/project?id=' + encodeURIComponent(id))); return true; }
async function editProject(id) {
 if (!await openProject(id)) return;
 state.projectMenu = ''; listProjects(); lockControls();
 $('project-edit-name').value = state.project.editor.name;
 $('project-edit-error').hidden = true; $('project-edit-dialog').showModal();
 $('project-edit-name').focus(); $('project-edit-name').select();
}
function deleteProjectDialog(id) {
 const project = state.projects.find(p => p.id === id); if (!project) return;
 state.deletingProject = id; state.projectMenu = ''; listProjects(); lockControls();
 $('project-delete-name').textContent = project.name;
 $('project-delete-note').textContent = (project.managed ? 'This removes the project from Studio and moves its files to Studio’s trash folder. You can recover them from output/deleted_projects.' : 'This removes the project from Studio. The original folder and files stay on your computer.') + (state.project?.id === id && state.dirty ? ' Unsaved changes to this project will be discarded.' : '');
 $('project-delete-error').hidden = true; $('project-delete-dialog').showModal(); $('project-delete-cancel').focus();
}
function clearProject() {
 state.project = null; state.selected = 0; state.dirty = false;
 $('voice-player').pause(); $('final-player').pause(); $('workspace').hidden = true; $('workflow-summary').hidden = true; $('empty').hidden = false;
 $('project-name').textContent = 'Your next great video starts here.'; $('project-path').textContent = 'Bring your story to life, one section at a time.'; $('save-state').textContent = 'Local workspace';
 window.VideoTurboAI?.update(null); window.VideoTurboPublishing?.update(null);
}
function updateOverview() {
 const project = state.project;
 $('workflow-summary').hidden = !project;
 if (!project) return;
 $('overview-voice').textContent = project.voiceover ? 'Ready' : 'Add audio';
 $('overview-voice-note').textContent = project.voiceover ? (project.voice_settings?.generated_current ? 'ElevenLabs voiceover' : 'Recording added') : 'The start of your story';
 $('overview-words').textContent = (project.editor.script || '').trim().split(/\s+/).filter(Boolean).length;
 $('overview-sections').textContent = (project.editor.mode === 'games' ? project.editor.games : project.editor.sections).length;
 $('overview-media').textContent = project.media.length;
}
function updateMedia() {
 const p = state.project; $('voice-name').textContent = p.voiceover || 'MP3, WAV, M4A, FLAC'; $('music-name').textContent = p.music ? 'Music added · MP3' : 'MP3 · mixed below your voice'; $('background-name').textContent = p.background ? 'Custom background added' : 'MP4 · replaces the main background';
 $('media-library').innerHTML = p.media.map(m => `<span class="media-chip" title="${esc(m.path)}">${m.kind === 'video' ? '▷' : '▧'} ${esc(m.name)}</span>`).join('');
 const audio = $('voice-player'); audio.hidden = !p.voiceover; if (p.voiceover) { const src = url(p.voiceover); if (audio.getAttribute('src') !== src) audio.src = src; }
 updateOverview();
 window.VideoTurboPublishing?.update(p); window.VideoTurboReference?.update(p); window.VideoTurboVoice?.update(p);
 $('download').hidden = !p.final; $('download').href = url('output/final.mp4'); $('download').setAttribute('download', (p.editor.name || 'video') + '.mp4');
}
function options(selected, kind = '') { return '<option value="">Choose media…</option>' + state.project.media.filter(m => !kind || m.kind === kind).map(m => `<option value="${esc(m.path)}" ${m.path === selected ? 'selected' : ''}>${esc(m.name)}</option>`).join(''); }
const input = (label,key,value,extra='') => `<label class="field">${label}<input data-field="${key}" value="${esc(value)}" ${extra}></label>`;
const select = (label,key,values,value) => `<label class="field">${label}<select data-field="${key}">${values.map(([v,t]) => `<option value="${v}" ${v === value ? 'selected' : ''}>${t}</option>`).join('')}</select></label>`;
function renderSections() {
 const editor = state.project.editor, games = editor.mode === 'games', items = games ? editor.games : editor.sections;
 $('sections-heading').textContent = games ? 'Your game list' : 'Build your sections'; $('save-preset').hidden = games; $('add-section').textContent = games ? '＋ Add game' : '＋ Add section'; $('section-hint').textContent = games ? 'Choose YouTube gameplay or uploaded MP4 clips. Game names in your script determine the timing.' : 'Reorder sections, then choose a start time or phrase. Empty start fields share the remaining time evenly.';
 $('sections').innerHTML = items.map((s,i) => `<article class="section ${i === state.selected ? 'selected' : ''}" data-index="${i}"><div class="section-top"><button type="button" class="section-title" data-action="select" aria-expanded="${i === state.selected}" aria-controls="section-body-${i}"><span class="section-index">${String(i + 1).padStart(2,'0')}</span><span>${esc(s.title || 'Untitled section')}</span></button><div class="section-controls"><button class="quiet" data-action="up" title="Move earlier" ${i === 0 ? 'disabled' : ''}>↑</button><button class="quiet" data-action="down" title="Move later" ${i === items.length - 1 ? 'disabled' : ''}>↓</button><button class="quiet" data-action="remove" title="Remove section">×</button></div></div><div class="section-body" id="section-body-${i}" ${i !== state.selected ? 'hidden' : ''}><div class="section-fields">${input('Section name','title',s.title || '')}${games ? input('Folder name','folder',s.folder || '') : select('Layout','layout',[['background','Background only'],['single','One clip / screenshot'],['split','Two stacked clips / screenshots'],['title','Title card'],...(state.project.reference_style?.analysis ? [['reference_style','Reference style']] : [])],s.layout || 'single')}
 ${games ? `${input('YouTube gameplay URL','url',s.url || '', 'placeholder="https://youtu.be/…"')}${input('Spoken game names (comma separated)','spoken_names',(s.spoken_names || []).join(', '),'dir="auto"')}<label class="field">Top clip <select data-field="top">${options(s.top,'video')}</select></label><label class="field">Bottom clip <select data-field="bottom">${options(s.bottom,'video')}</select></label><label class="field">Uploaded logo (optional)<select data-field="logo">${options(s.logo,'image')}</select></label>${input('Or download logo from image URL','logo_url',s.logo_url || '', 'placeholder="https://…/logo.png"')}<label class="check"><input data-field="captions_global" type="checkbox" ${editor.captions !== false ? 'checked' : ''}> Captions during game clips</label>` : `
 ${s.layout === 'reference_style' ? `${select('Scene composition','variant',[['hero','Floating object'],['card','Framed image'],['collage','Layered collage'],['type','Expressive typography'],['device','Phone story'],['compare','Two ideas'],['metric','Key figure'],['steps','Three details']],s.variant || 'card')}${input('Emphasized text','emphasis',s.emphasis || '', 'dir="auto"')}${select('Scene background','scene_tone',[['base','Original palette'],['contrast','Contrasting neutral'],['accent','Accent color']],s.scene_tone || 'base')}${select('Backdrop','backdrop',[['clean','Clean'],['grid','Fine grid'],['orbits','Curved lines'],['spotlight','Soft spotlight'],['diagonal','Diagonal shadows']],s.backdrop || 'clean')}${select('Graphic theme','motif',[['none','None'],['warning','Warning'],['connection','Connection'],['privacy','Privacy'],['protection','Protection'],['energy','Energy'],['share','Share']],s.motif || 'none')}${select('Image presentation','media_treatment',[['photo','Framed photography'],['cutout','Transparent cutout'],['multiply','Blend white product background']],s.media_treatment || 'photo')}${input('Short supporting details (separate with |)','details',(s.details || []).join(' | '),'dir="auto"')}` : ''}
  ${['single','split','reference_style'].includes(s.layout) ? `<label class="field">Main clip or screenshot<select data-field="media">${options(s.media)}</select></label>` : ''}
 ${['split','reference_style'].includes(s.layout) ? `<label class="field">Second clip or screenshot<select data-field="secondary_media">${options(s.secondary_media)}</select></label>` : ''}
 ${input('Start at second (optional)','start_seconds',s.start_seconds ?? '', 'type="number" min="0" step="0.1" placeholder="Automatic"')}
 ${input('Or start when these words are spoken','start_phrase',s.start_phrase || '', 'dir="auto" placeholder="Phrase from your script"')}
 ${input('On-screen label (optional)','label',s.label || '', 'dir="auto"')}
 ${select('Background','background',[['gta_background.mp4','Main / GTA'],['roblox.mp4','Roblox'],['fortnite.mp4','Fortnite']],s.background || 'gta_background.mp4')}
 <label class="check"><input data-field="captions" type="checkbox" ${s.captions !== false ? 'checked' : ''}> Show captions</label>
 `}</div>${!games ? `<details class="advanced"><summary>Framing & highlight</summary><div class="section-fields">${select('Media framing','fit',[['contain','Show entire recording'],['cover','Fill the card']],s.fit || 'contain')}${input('Caption height (0–1)','caption_y',s.caption_y ?? .76,'type="number" min="0" max="1" step="0.01"')}${input('Clip start offset (seconds)','offset_seconds',s.offset_seconds ?? 0,'type="number" min="0" step="0.1"')}${input('End zoom (1–1.5)','zoom',s.zoom ?? 1.04,'type="number" min="1" max="1.5" step="0.01"')}<label class="check wide"><input data-field="highlight_enabled" type="checkbox" ${s.highlight ? 'checked' : ''}> Highlight an area of the main media card</label>${s.highlight ? ['x','y','width','height'].map(key => input('Highlight '+ key +' (%)','highlight.'+key,s.highlight[key],'type="number" min="0" max="100" step="1"')).join('') : ''}</div><p class="hint">Highlight coordinates are percentages of the media card. Start timing refers to the voiceover; clip offset selects the footage inside your recording.</p></details>` : ''}</div></article>`).join(''); updateOverview(); lockControls();
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
 if(s.layout === 'reference_style') {
  const r=state.project.reference_style?.analysis;
  if(r){
   $('preview-bg').hidden=true;
   const path=s.media,media=state.project.media.find(m=>m.path===path);
   content=`<div class="reference-layout-preview" style="background:${esc(r.background)};color:${esc(r.ink)}" dir="auto"><strong>${esc(s.title)}</strong><em style="color:${esc(r.accent)}">${esc(s.emphasis)}</em>${media?(media.kind==='image'?`<img src="${url(path)}" alt="">`:`<video src="${url(path)}" muted autoplay loop playsinline></video>`):''}</div>`;
  }
 } else $('preview-bg').hidden=false;
 $('preview-content').innerHTML = content;
 $('preview-caption').style.top = ((game ? .6276 : s.caption_y ?? .76) * 100) + '%';
 $('preview-caption').hidden = game ? state.project.editor.captions === false : s.captions === false;
 $('preview-caption').textContent = (state.project.editor.script || '').split(/\s+/).find(Boolean) || 'Your caption';
 $('preview-note').textContent = 'Layout preview; render a frame for exact captions, transitions and timing.';
}
function lockControls() { const studioBusy = !state.token || state.busy || ['running','cancelling'].includes(state.job?.status); const busy = studioBusy || state.publishingJob?.status === 'running'; document.querySelectorAll('button,input,select,textarea').forEach(e => { if (e.id !== 'cancel' && e.id !== 'theme-toggle') e.disabled = busy; }); document.querySelectorAll('[data-action="up"],[data-action="down"]').forEach(e => { const i = Number(e.closest('[data-index]').dataset.index), len = (state.project?.editor.mode === 'games' ? state.project.editor.games : state.project?.editor.sections)?.length || 0; e.disabled = busy || e.dataset.action === 'up' && i === 0 || e.dataset.action === 'down' && i === len - 1; }); $('publish-nav').disabled = studioBusy || !state.project?.final; $('publish-nav').title = state.project?.final ? 'Prepare your social posts' : 'Build your video to start publishing'; $('cancel').disabled = state.job?.status !== 'running'; $('brief-create').disabled = busy || !state.brief; window.VideoTurboPublishing?.lock(studioBusy); const preparing = state.job?.action === 'ai_prepare' && state.job?.status === 'running' && state.job?.project === state.project?.id; if (preparing) $('voice-input').disabled = !state.token || state.busy || state.publishingJob?.status === 'running'; window.VideoTurboAI?.lock(busy); window.VideoTurboReference?.lock(busy); window.VideoTurboVoice?.lock(busy); window.VideoTurboAnalytics?.lock(Boolean(state.token)); }
async function save() { if (!state.project) return; state.project.editor.script = $('script').value; const selectedIndex = state.selected; const p = await api('/api/save',{id:state.project.id,editor:state.project.editor}); state.project = p; state.selected = selectedIndex; state.dirty = false; $('save-state').textContent = 'Saved locally'; updateMedia(); renderSections(); await refreshState(); }
async function upload(input, role) { if (!state.project || !input.files.length) return; if (state.project.ai_workflow?.auto_build && state.dirty) await save(); state.busy = true; lockControls(); const editor = state.project.editor; try { for (const file of input.files) { toast('Uploading '+file.name+'…'); const response = await fetch('/api/upload?id='+state.project.id+'&name='+encodeURIComponent(file.name)+'&role='+role,{method:'POST',headers:{'X-Studio-Token':state.token},body:file}); const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Upload failed.'); state.project = data.project; if (!(role === 'voice' && data.project.ai_workflow?.auto_build)) state.project.editor = editor; } updateMedia(); renderSections(); layoutPreview(); if (!(role === 'voice' && state.project.ai_workflow?.auto_build)) dirty(); else { window.VideoTurboAI?.update(state.project); await refreshState(); } toast(role === 'voice' ? 'Voiceover added.' : 'Media added. Choose it in your section.'); } finally { state.busy = false; input.value = ''; lockControls(); } }
async function start(action) { await save(); await window.VideoTurboVoice?.saveSelection(); const at = Number($('preview-at').value); if (action === 'preview' && (!Number.isFinite(at) || at < 0)) throw new Error('Choose a valid preview time.'); state.job = await api('/api/start',{id:state.project.id,action,at}); showJob(); }
function showJob() {
 const job = state.job; $('job-panel').hidden = !job; lockControls(); if (!job) return;
 $('job-stage').textContent = job.error || job.stage; $('job-percent').textContent = Math.round(job.progress)+'%'; $('progress').value = job.progress;
 const seconds = Math.floor((job.finished || Date.now()/1000) - job.started); $('job-time').textContent = Math.floor(seconds/60)+'m '+seconds%60+'s'; $('logs').textContent = job.logs.join('\n'); $('cancel').hidden = !['running','cancelling'].includes(job.status);
 if (['complete','failed','cancelled'].includes(job.status) && state.finished !== job.id) { state.finished = job.id; if (job.status === 'complete' && state.project?.id === job.project) attempt(async()=> { const p = await api('/api/project?id='+job.project); if (job.action === 'voice_generate') { install(p); toast('Voiceover ready. Play it below your script, or build your video.'); return; } if ((job.action.startsWith('ai_') || job.action === 'reference_plan' || job.next_action === 'reference_plan')) { install(p); toast((job.action === 'reference_plan' || job.next_action === 'reference_plan') ? 'Reference analyzed. Your new scenes are ready to edit or build.' : job.action === 'ai_script' ? 'Your script is ready. Review and approve it before assets start.' : 'Assets are ready. Add your voiceover to build automatically.'); return; } state.project = p; window.VideoTurboAI?.update(p); updateMedia(); if(job.action.startsWith('voice_'))renderSections(); if (job.action === 'preview') { $('live-preview').hidden = true; $('final-player').hidden = true; $('rendered-preview').src = url('output/studio_preview.png')+'&v='+Date.now(); $('rendered-preview').hidden = false; $('preview-mode').textContent = 'Rendered frame'; $('preview-note').textContent = 'Exact frame at '+$('preview-at').value+' seconds.'; } else { $('live-preview').hidden = true; $('rendered-preview').hidden = true; $('final-player').src = url('output/final.mp4')+'&v='+Date.now(); $('final-player').hidden = false; $('preview-mode').textContent = 'Finished video'; $('preview-note').textContent = 'Your video is ready. Play it here or download it.'; } $('layout-preview').hidden = false; toast(job.action === 'preview' ? 'Preview ready.' : 'Video complete.'); }); else if (job.status === 'failed') toast(job.error || 'Build failed; check the log.',true); }
}
$('script').addEventListener('input',()=>{state.project.editor.script=$('script').value; dirty(); window.VideoTurboAI?.update(state.project); updateOverview(); layoutPreview();});
$('projects').addEventListener('click',e=>{
 e.stopPropagation();
 const menu=e.target.closest('[data-project-menu]'),edit=e.target.closest('[data-project-edit]'),remove=e.target.closest('[data-project-delete]'),open=e.target.closest('[data-project]');
 if(menu){const id=menu.dataset.projectMenu;state.projectMenu=state.projectMenu===id?'':id;listProjects();lockControls();$('projects').querySelector(`[data-project-menu="${id}"]`)?.focus();}
 else if(edit) attempt(()=>editProject(edit.dataset.projectEdit));
 else if(remove) deleteProjectDialog(remove.dataset.projectDelete);
 else if(open) {state.projectMenu='';listProjects();lockControls();attempt(()=>openProject(open.dataset.project));}
});
document.addEventListener('keydown',e=>{if(e.key==='Escape' && state.projectMenu){const id=state.projectMenu;state.projectMenu='';listProjects();lockControls();$('projects').querySelector(`[data-project-menu="${id}"]`)?.focus();}});
document.addEventListener('click',e=>{if(state.projectMenu && !e.target.closest('#projects')){state.projectMenu='';listProjects();lockControls();}});
$('project-edit-cancel').onclick=()=>$('project-edit-dialog').close();
$('project-delete-cancel').onclick=()=>$('project-delete-dialog').close();
$('project-edit-form').onsubmit=async e=>{
 e.preventDefault();if(state.busy)return;state.busy=true;lockControls();$('project-edit-error').hidden=true;
 try{const p=await api('/api/project/rename',{id:state.project.id,name:$('project-edit-name').value});state.project.editor.name=p.editor.name;$('project-name').textContent=p.editor.name;await refreshState();$('project-edit-dialog').close();toast('Project updated. Edit its script and media in the workspace.');}
 catch(error){$('project-edit-error').textContent=error.message;$('project-edit-error').hidden=false;}
 finally{state.busy=false;lockControls();}
};
$('project-delete-form').onsubmit=async e=>{
 e.preventDefault();if(state.busy)return;state.busy=true;lockControls();$('project-delete-error').hidden=true;
 try{const result=await api('/api/project/delete',{id:state.deletingProject,confirmed:true});if(state.project?.id===result.deleted)clearProject();await refreshState();$('project-delete-dialog').close();toast(result.files_moved?'Project deleted. Files kept in Studio’s trash folder.':'Project removed from Studio. Original files kept.');}
 catch(error){$('project-delete-error').textContent=error.message;$('project-delete-error').hidden=false;}
 finally{state.busy=false;lockControls();}
};
$('sections').addEventListener('click',e=>{ const button=e.target.closest('[data-action]'); if(!button)return; const i=Number(button.closest('[data-index]').dataset.index); const items=state.project.editor.mode==='games'?state.project.editor.games:state.project.editor.sections; const action=button.dataset.action; state.selected=i; if(action==='up'||action==='down'){const other=i+(action==='up'?-1:1);[items[i],items[other]]=[items[other],items[i]];state.selected=other;dirty();} if(action==='remove'){if(items.length===1)return toast('Keep at least one section.',true);items.splice(i,1);state.selected=Math.min(i,items.length-1);dirty();} renderSections();layoutPreview(); $('sections').querySelector('[data-index="'+state.selected+'"] [data-action="select"]')?.focus({preventScroll:true}); });
$('sections').addEventListener('change',e=>{ const target=e.target,key=target.dataset.field;if(!key)return;const i=Number(target.closest('[data-index]').dataset.index);const editor=state.project.editor, s=(editor.mode==='games'?editor.games:editor.sections)[i]; let value=target.type==='checkbox'?target.checked:target.type==='number'?(target.value===''?null:Number(target.value)):target.value;if(key==='spoken_names')value=value.split(',').map(v=>v.trim()).filter(Boolean);if(key==='details')value=value.split('|').map(v=>v.trim()).filter(Boolean);if(key==='captions_global')editor.captions=value;else if(key==='highlight_enabled')s.highlight=value?{x:20,y:20,width:50,height:30}:null;else if(key.startsWith('highlight.'))s.highlight[key.split('.')[1]]=value;else s[key]=value;if(key==='layout' && value==='reference_style')s.variant ||= 'card';state.selected=i;dirty();if(['layout','highlight_enabled'].includes(key))renderSections();layoutPreview(); });
$('add-section').onclick=()=>{const editor=state.project.editor,items=editor.mode==='games'?editor.games:editor.sections;items.push(editor.mode==='games'?{title:'New game',folder:String(items.length+1).padStart(2,'0')+'_game',spoken_names:[]}:{title:'New section',layout:'single',caption_y:.76});state.selected=items.length-1;dirty();renderSections();layoutPreview();};
for(const [id,role] of [['voice-input','voice'],['music-input','music'],['background-input','background'],['media-input','media']])$(id).onchange=()=>attempt(()=>upload($(id),role));
$('save').onclick=()=>attempt(async()=>{await save();toast('Project saved.');});$('build').onclick=()=>attempt(()=>start('build'));$('render-preview').onclick=()=>attempt(()=>start('preview'));$('layout-preview').onclick=layoutPreview;$('cancel').onclick=()=>attempt(async()=>{await api('/api/cancel',{});state.job=await api('/api/job');showJob();});
function createDialog(){ $('create-dialog').showModal(); window.VideoTurboAI?.openCreation(); $('new-name').focus(); }$('new-project').onclick=createDialog;$('empty-create').onclick=createDialog;$('close-dialog').onclick=()=>$('create-dialog').close();
$('create-form').onsubmit=e=>{e.preventDefault();attempt(async()=>{if(state.dirty&&!confirm('Discard unsaved changes and create a project?'))return;if ($('new-workflow').value === 'ai') return window.VideoTurboAI.create(); const p=await api('/api/create',{name:$('new-name').value,preset:$('preset').value,voice_source:$('new-voice-source').value});$('create-dialog').close();await refreshState();install(p);});};
$('import-project').onclick=()=>attempt(async()=>{const path=prompt('Paste the path of an existing video project folder:');if(!path)return;if(state.dirty&&!confirm('Discard unsaved changes and open this folder?'))return;const p=await api('/api/import',{path});await refreshState();install(p);});
$('save-preset').onclick=()=>attempt(async()=>{const name=prompt('Name this reusable layout preset:');if(!name)return;await api('/api/preset',{name,sections:state.project.editor.sections});await refreshState();toast('Layout saved. Choose it when creating a new video.');});
const aiBriefPrompt = `Write a video script in Egyptian Arabic for this idea: [REPLACE WITH MY IDEA AND GAMES].
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
$('copy-brief-prompt').onclick = () => attempt(async () => { await navigator.clipboard.writeText(aiBriefPrompt); toast('AI prompt copied. Replace the idea and games before sending it.'); });
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
 try { const project = await api('/api/brief/import', {brief:$('brief-text').value,voice_source:$('brief-voice-source').value}); $('brief-dialog').close(); await refreshState(); install(project); toast('Brief imported. Choose your voiceover, then prepare assets or build.'); }
 finally { state.busy = false; lockControls(); }
}); };
$('publish-nav').onclick = () => window.VideoTurboPublishing?.open();
document.querySelectorAll('[data-view]').forEach(link => link.addEventListener('click', () => {
 document.querySelectorAll('[data-view]').forEach(item => item.classList.toggle('active', item === link));
}));
$('preview-bg').onerror=()=>{$('preview-note').textContent='This background is unavailable. Upload a main background or choose another one.';};
window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue='';}});
window.addEventListener('DOMContentLoaded',()=>{ window.VideoTurboAI?.configure({api,toast,getState:()=>state,install,refreshState,showJob,save,lockControls}); window.VideoTurboVoice?.configure({api,toast,getState:()=>state,install,refreshState,showJob,save,lockControls,mediaUrl:url}); window.VideoTurboReference?.configure({api,toast,getState:()=>state,install,refreshState,showJob,save,lockControls,mediaUrl:url}); window.VideoTurboPublishing?.configure({api,toast,mediaUrl:url}); window.VideoTurboPublishing?.update(state.project); window.VideoTurboAnalytics?.configure({api,openPublishing:async(id,platform)=>{if(!await openProject(id))return false;await window.VideoTurboPublishing?.openSetup(platform);return true;}}); lockControls(); });
lockControls();attempt(refreshState);setInterval(()=>attempt(async()=>{const [renderJob,publishJob]=await Promise.all([api('/api/job'),api('/api/publishing/job')]);state.job=renderJob;state.publishingJob=publishJob;showJob(); await window.VideoTurboAI?.poll(); await window.VideoTurboReference?.poll();}),2000);
