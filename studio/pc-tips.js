(() => {
 'use strict';
 const $=id=>document.getElementById(id);
 let app,busy=false,polling=false,options=null,lastStatus='',lastModeKey='';
 const status={
  writing_script:['Choosing an idea and writing your episode','AI picks a fresh tip in your chosen type, checks official sources, and writes a fast Egyptian Arabic script.',0],
  awaiting_review:['Your script is ready','Review the script below, then continue production. Keep a problem line before the solution lines.',0],
  preparing:['Preparing your episode','Saved assets are reused. The setup changes for every part.',1],
  awaiting_runner:['The recording runner is waiting','Choose Animated walkthrough below, or use a dedicated Windows test session for real recording. You can also upload a real screen recording.',2],
  animating:['Creating the animated walkthrough','Rendering the Windows 10 desktop and tutorial screens with a visible animation label. No desktop recording is needed.',2],
  recording:['Recording the real steps','The Windows runner verifies each result and removes AI response time from the captured actions.',2],
  awaiting_recording:['Add your screen recording','Follow the recording checklist below: problem first, then solution steps and the visible result.',2],
  generating_voice:['Generating your narration','Using the voice and model selected in Voice & script below.',3],
  awaiting_voice_setup:['Set up your narration voice once','Open ElevenLabs settings in Voice & script, save your default voice and model, then continue production.',3],
  awaiting_voice:['Your script is ready to record','Copy or download the script, then upload your voiceover below. Production resumes when it arrives.',3],
  ready:['Assets and narration are ready','Continuing to caption alignment and rendering.',4],
  rendering:['Editing your episode','Assembling the numbered intro, tutorial visuals, and synchronized captions.',4],
  checking:['Checking your video','Reviewing sampled frames, caption readability, episode number, and export format.',5],
  complete:['Your episode is ready','The vertical video, cover, source list, and post caption have been saved.',7],
  failed:['A production step needs attention','Your episode number, script, and completed assets are saved. Fix the issue, then continue.',0],
  cancelled:['Production cancelled','Your episode is saved. Continue when ready.',0],
  interrupted:['Production interrupted','Studio stopped before production finished. Your saved episode can continue.',0],
 };
 function error(message) { $('pc-create-error').textContent=message||'';$('pc-create-error').hidden=!message; }
 function lock(blocked=false) {
  if(!app)return;
  const state=app.getState(),working=blocked||busy||state.busy||!state.token||['running','cancelling'].includes(state.job?.status)||state.publishingJob?.status==='running';
  for(const control of $('pc-dialog').querySelectorAll('button,input,textarea,select'))control.disabled=working;
  $('pc-new').disabled=working;
  for(const control of $('pc-panel').querySelectorAll('button,input,select'))control.disabled=working;
  const p=state.project;
  $('pc-copy-script').disabled=$('pc-download-script').disabled=working||!p?.editor.script;
  $('pc-continue').disabled=working||!p?.pc_tips;
  $('pc-demo-input').disabled=working;
 }
 async function action(fn) {
  if(busy)return;
  busy=true;app.getState().busy=true;app.lockControls();error('');
  try{await fn();}catch(e){error(e.message);$('pc-error').textContent=e.message;$('pc-error').hidden=false;app.toast(e.message,true);}
  finally{busy=false;app.getState().busy=false;app.lockControls();}
 }
 async function subscriptionOptions() {
  const value=await app.api('/api/pc-tips/settings');
  if(value.routing_policy!=='google-first-v1'||(!Array.isArray(value.categories)||!value.recording_modes?.includes('illustrated')||!value.problem_first))throw new Error('Relaunch Studio to load Google-first production and quality fallbacks.');
  return value;
 }
 async function loadOptions() {
  options=await subscriptionOptions();
  $('pc-next').textContent='Next: Part '+String(options.next_part).padStart(2,'0')+' · '+options.next_theme.name+' setup';
  $('pc-name').placeholder='Automatic: PC Tips & Tricks — Part '+String(options.next_part).padStart(2,'0');
  $('pc-google-model').value=options.google_model;$('pc-google-cli-path').value=options.google_cli_path||'';
  $('pc-script-model').value=options.script_model;$('pc-cli-path').value=options.cli_path||'';
  $('pc-runner').checked=options.runner_enabled;
  const selected=$('pc-category').value;
  $('pc-category').replaceChildren(...options.categories.map(row=>{const option=document.createElement('option');option.value=row.id;option.textContent=row.name;return option;}));
  $('pc-category').value=options.categories.some(row=>row.id===selected)?selected:'auto';
  $('pc-voice').value=options.voice_source;$('pc-visual').value=options.recording_mode==='illustrated'?'illustrated':'real';$('pc-recording').value=options.recording_mode==='illustrated'?'automatic':options.recording_mode;$('pc-auto').checked=options.auto_produce;
  updateChoice();

  $('pc-connection').textContent=options.google_installed?
   'Antigravity found. Google / Gemini is first; ChatGPT is the fallback after errors or quality rejection.':
   'Antigravity was not found. Set its executable below to use Google first. ChatGPT can continue as the fallback.';
  if(!options.google_installed)$('pc-settings').open=true;
 }
 function recordingChoice(prefix='pc') {
  return $(prefix+'-visual').value==='illustrated'?'illustrated':$(prefix+'-recording').value;
 }
 function showVisualChoice(prefix='pc') {
  const illustrated=$(prefix+'-visual').value==='illustrated';
  $(prefix+'-recording-field').hidden=illustrated;
  $(prefix+'-visual-note').textContent=illustrated?
   'AI simulates the Windows 10 desktop, Settings and menus with a visible animation label. Shows the problem before the solution. No recording session needed.':
   'Uses real Windows 10 footage. Automatic capture needs a dedicated test desktop; the setting does not create one. AI provides a recording checklist: show the problem first, then follow the correct Windows 10 steps and show the result.';
 }
 function episodeChoice() {
  showVisualChoice('pc-episode');
  $('pc-recording-upload').hidden=$('pc-episode-visual').value==='illustrated';
  const saved=app?.getState().project?.pc_tips;
  if(saved) {
   const changed=recordingChoice('pc-episode')!==(saved.visual_source==='illustrated'?'illustrated':saved.recording_mode);
   $('pc-continue').hidden=saved.status==='complete'&&!saved.stale&&!saved.voice_stale&&!saved.render_stale&&!saved.windows_stale&&!saved.animation_stale&&!app.getState().dirty&&!changed&&!!saved.plan?.problem;
   if(changed)$('pc-episode-visual-note').textContent+=' Click Continue production to apply this choice to this episode.';
  }
 }
 function updateChoice() {
  showVisualChoice();
  $('pc-category-note').textContent=options?.categories.find(row=>row.id===$('pc-category').value)?.description||'AI picks a fresh tip.';
  const missing=[];
  if($('pc-voice').value==='elevenlabs'&&!options?.voice_ready)missing.push('Set your ElevenLabs voice once in Voice settings.');
  if(recordingChoice()==='automatic'&&!$('pc-runner').checked)missing.push('Enable your Windows recording session once below.');
  if($('pc-voice').value==='upload')missing.push('Production will wait for your voice recording.');
  if(recordingChoice()==='upload')missing.push('Production will wait for your screen recording.');
  if(!$('pc-auto').checked)missing.push('The script will pause for your review.');
  $('pc-automation-note').textContent=missing.join(' ')||'Uses your saved settings for automatic production.';
 }
 async function saveOptions() {
  if(options?.routing_policy!=='google-first-v1')throw new Error('Relaunch Studio to load Google-first production.');
  const result=await app.api('/api/pc-tips/settings',{google_model:$('pc-google-model').value,google_cli_path:$('pc-google-cli-path').value.trim(),script_model:$('pc-script-model').value,cli_path:$('pc-cli-path').value.trim(),runner_enabled:$('pc-runner').checked,
   voice_source:$('pc-voice').value,recording_mode:recordingChoice(),auto_produce:$('pc-auto').checked});
  options={...options,...result};updateChoice();$('pc-settings-feedback').textContent='Options saved. No generation request was made.';
 }
 async function apply(result) {
  app.getState().job=result.job;
  await app.refreshState();app.install(result.project);app.showJob();
 }
 function captureRows(saved) {
  if(!saved?.plan)return [];
  return [...(saved.plan.problem?[{...saved.plan.problem,problem:true}]:[]),...saved.plan.steps];
 }
 function captureText(saved) {
  return ['Record: problem → solution → result.',...captureRows(saved).map((shot,i)=>
   (i+1)+'. '+(shot.problem?'PROBLEM · ':'')+shot.title+' ['+shot.os+']\n'+
   (shot.capture_instructions||[shot.goal]).map((line,n)=>'  '+(n+1)+') '+line).join('\n')+'\n  Visible result: '+shot.verification),
   'Finish by repeating the opening action to show the successful result. Hold it for 2–3 seconds.'].join('\n\n');
 }
 function updateCaptureGuide(saved) {
  $('pc-capture-list').replaceChildren();
  $('pc-copy-capture').disabled=!saved?.plan;
  $('pc-capture-note').textContent=!saved?.plan?'Your exact recording steps will appear after the script is drafted.':
   !saved.plan.problem?'This older episode needs a problem opening. Continue production to generate its complete recording guide.':
   'Record these steps on a Windows 10 desktop. '+saved.plan.requirements.join(' · ');
  for(const shot of captureRows(saved)) {
   const item=document.createElement('li'),heading=document.createElement('strong'),actions=document.createElement('ol'),result=document.createElement('p');
   heading.textContent=(shot.problem?'Problem first · ':'')+shot.title+' · '+shot.os;heading.dir='auto';
   for(const instruction of shot.capture_instructions||[shot.goal]){const action=document.createElement('li');action.textContent=instruction;action.dir='auto';actions.append(action);}
   result.textContent='Show: '+shot.verification;result.dir='auto';
   item.append(heading,actions,result);$('pc-capture-list').append(item);
  }
 }
 function update(project) {
  const saved=project?.pc_tips;
  $('pc-panel').hidden=!saved||!Object.keys(saved).length;
  if($('pc-panel').hidden)return;
  $('pc-heading').textContent='Part '+String(saved.part).padStart(2,'0')+(saved.plan?' · '+saved.plan.topic:'');
  $('pc-theme').textContent=saved.theme.name;
  const modeKey=project.id+':'+saved.recording_mode+':'+saved.visual_source;
  if(modeKey!==lastModeKey) {
   lastModeKey=modeKey;
   $('pc-episode-visual').value=saved.visual_source==='illustrated'||saved.recording_mode==='illustrated'?'illustrated':'real';
   $('pc-episode-recording').value=saved.recording_mode==='upload'?'upload':'automatic';
  }
  const [heading,note,progress]=status[saved.status]||['Episode saved','Continue production when ready.',0];
  $('pc-status').textContent=heading;$('pc-note').textContent=saved.windows_stale?'This episode needs Windows 10 instructions. Continue to research and update its script and visuals. Previous files are kept; uploaded narration must be recorded again.':saved.animation_stale?'Continue production to rebuild this episode with the updated Windows 10 simulation.':saved.stale?'Your script has changed. Save it before continuing production.':saved.voice_stale||saved.render_stale?'Your audio, media, or scene settings changed. Continue production to update the export.':note;
  $('pc-error').textContent=saved.error||'';$('pc-error').hidden=!saved.error;
  $('pc-progress').querySelectorAll('li').forEach((item,i)=>{item.classList.toggle('done',i<progress);item.classList.toggle('current',i===progress);if(i===progress)item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');});
  $('pc-continue').textContent=saved.windows_stale?'Update to Windows 10 & rebuild':saved.animation_stale?'Rebuild Windows 10 animation':saved.plan&&!saved.plan.problem?'Add problem opening & rebuild':saved.status==='awaiting_review'?'Use script & produce episode':['failed','cancelled','interrupted'].includes(saved.status)?'Retry production':'Continue production';
  $('pc-continue').hidden=saved.status==='complete'&&!saved.stale&&!saved.voice_stale&&!saved.render_stale&&!saved.windows_stale&&!saved.animation_stale&&!app.getState().dirty&&!!saved.plan?.problem;
  $('pc-shots').replaceChildren();$('pc-sources').replaceChildren();
  if(saved.plan) {
   $('pc-os').textContent=saved.plan.os+(saved.plan.requirements.length?' · '+saved.plan.requirements.join(' · '):'');
   for(const step of [...(saved.plan.problem?[saved.plan.problem]:[]),...saved.plan.steps]) {
    const item=document.createElement('li'),title=document.createElement('strong'),goal=document.createElement('p'),verification=document.createElement('small');
    title.textContent=step.title;title.dir='auto';goal.textContent=step.goal;verification.textContent='Check: '+step.verification;
    item.append(title,goal,verification);$('pc-shots').append(item);
   }
   for(const source of saved.plan.sources) {
    const item=document.createElement('li'),link=document.createElement('a');link.href=source.url;link.textContent=source.title;link.target='_blank';link.rel='noopener noreferrer';item.append(link);$('pc-sources').append(item);
   }
  }
  updateCaptureGuide(saved);
  episodeChoice();
  $('pc-package').hidden=saved.status!=='complete'||saved.windows_stale||saved.animation_stale;$('pc-cover').href=app.mediaUrl('output/cover.jpg');
  lock();
 }
 function download(text,name) {
  const source=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'})),a=document.createElement('a');
  a.href=source;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(source),1000);
 }
 function open(settingsOnly=false){
  error('');$('pc-settings-feedback').textContent='';$('pc-dialog').dataset.settingsOnly=String(settingsOnly);
  $('pc-create-heading').textContent=settingsOnly?'PC series settings':'PC Tips & Tricks · Windows 10';
  $('pc-creation-fields').hidden=settingsOnly;$('pc-name-field').hidden=settingsOnly;
  $('pc-create').textContent=settingsOnly?'Save settings':'Generate video';
  $('pc-category').required=!settingsOnly;$('pc-name').value='';
  $('pc-production').open=settingsOnly;
  if(settingsOnly)$('pc-settings').open=true;
  $('pc-dialog').showModal();loadOptions().then(()=>(settingsOnly?$('pc-voice'):$('pc-category')).focus()).catch(e=>error(e.message));
 }
 for(const id of ['pc-category','pc-voice','pc-visual','pc-recording','pc-runner','pc-auto'])$(id).addEventListener('change',updateChoice);
 for(const id of ['pc-episode-visual','pc-episode-recording'])$(id).addEventListener('change',episodeChoice);
 $('pc-new').onclick=()=>open();
 $('pc-options').onclick=()=>open(true);
 $('pc-close').onclick=()=>$('pc-dialog').close();
 $('pc-save-settings').onclick=()=>action(saveOptions);
 $('pc-check-connection').onclick=()=>action(async()=>{
  await saveOptions();
  $('pc-settings-feedback').textContent='Checking Google first, then the connected fallback...';
  const result=await app.api('/api/pc-tips/check',{});
  $('pc-connection').textContent=result.message;$('pc-settings-feedback').textContent='Connection checked using your included subscription allowance.';
 });
 $('pc-form').onsubmit=e=>{e.preventDefault();if($('pc-dialog').dataset.settingsOnly==='true'){action(async()=>{await saveOptions();$('pc-dialog').close();app.toast('Series settings saved.');});return;}action(async()=>{
  if(app.getState().dirty&&!confirm('Discard unsaved changes and create an episode?'))return;
  await saveOptions();
  const result=await app.api('/api/pc-tips/create',{name:$('pc-name').value,category:$('pc-category').value,
   recording_mode:recordingChoice(),voice_source:$('pc-voice').value,auto_produce:$('pc-auto').checked});
  $('pc-dialog').close();await apply(result);app.toast('AI is choosing your next tip and producing the episode.');
 });};
 $('pc-continue').onclick=()=>action(async()=>{
  await subscriptionOptions();
  await app.save();await window.VideoTurboVoice?.saveSelection();
  await apply(await app.api('/api/pc-tips/start',{id:app.getState().project.id,recording_mode:recordingChoice('pc-episode'),add_problem:true}));
 });
 $('pc-copy-capture').onclick=()=>action(async()=>{await navigator.clipboard.writeText(captureText(app.getState().project?.pc_tips));app.toast('Recording steps copied.');});
 $('pc-copy-script').onclick=()=>action(async()=>{await navigator.clipboard.writeText($('script').value);app.toast('Script copied.');});
 $('pc-download-script').onclick=()=>download($('script').value,'pc-tips-part-'+app.getState().project.pc_tips.part+'-script.txt');
 $('pc-copy-post').onclick=()=>action(async()=>{await navigator.clipboard.writeText(app.getState().project.pc_tips.plan.post_caption);app.toast('Post caption copied.');});
 $('pc-demo-input').onchange=()=>action(async()=>{
  const input=$('pc-demo-input'),file=input.files[0];if(!file)return;
  try{
   await app.save();
   const state=app.getState(),response=await fetch('/api/upload?id='+encodeURIComponent(state.project.id)+'&role=pc_demo&name='+encodeURIComponent(file.name),
    {method:'POST',headers:{'X-Studio-Token':state.token},body:file});
   const result=await response.json();if(!response.ok)throw new Error(result.error||'Recording upload failed.');
   await app.refreshState();app.install(result.project);app.showJob();app.toast('Screen recording saved.');
  }finally{input.value='';}
 });
 window.VideoTurboPcTips={
  configure(value){app=value;},
  update,lock,
  async poll(){
   const state=app.getState();if(!state.project?.pc_tips||!Object.keys(state.project.pc_tips).length||polling||state.dirty||busy||state.busy)return;
   polling=true;
   try{
    const id=state.project.id,latest=await app.api('/api/project?id='+encodeURIComponent(id)),key=id+':'+latest.pc_tips.status+':'+latest.pc_tips.error+':'+JSON.stringify([latest.pc_tips.stale,latest.pc_tips.voice_stale,latest.pc_tips.render_stale,latest.pc_tips.windows_stale,latest.pc_tips.animation_stale,latest.final]);
    if(state.project?.id===id&&!state.dirty&&!busy&&!state.busy){
     if(key!==lastStatus){lastStatus=key;app.install(latest);}else{state.project.pc_tips=latest.pc_tips;update(state.project);}
    }
   }finally{polling=false;}
  },
 };
})();
