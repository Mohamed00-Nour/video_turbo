(() => {
 'use strict';
 const $=id=>document.getElementById(id);
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let app, busy=false, polling=false, lastKey='', connectionSettings=null, currentProvider='antigravity';
 const providerDrafts={};
 const creationDrafts={};
 let creationProvider='codex';
 const providerName=key=>key==='codex'?'Codex / ChatGPT':key==='claude'?'Claude':'Antigravity Gemini';
 // Codex and Claude accept a blank model: the client then uses its own configured default.
 const blankDefault=key=>key==='codex' || key==='claude';
 // claude-opus-5-5 -> Claude Opus 5.5; other model IDs are shown as returned.
 const modelName=id=>{const m=/^claude-([a-z]+)-(\d+)-(\d+)/.exec(id || '');return m?'Claude '+m[1][0].toUpperCase()+m[1].slice(1)+' '+m[2]+'.'+m[3]:id;};
 const modelLabel=key=>key==='codex'?'Codex model':key==='claude'?'Claude model':'Gemini model';
 const modelStates={};
 const modelRequests={};
 const modelCatalogs={};
 function modelValue(id){const state=modelStates[id];return state && (state.loading || !state.ids) ? state.preferred : $(id).value;}
 function requireModel(id){
  if(!modelStates[id]?.ready)throw new Error('Choose an available model. Refresh models if the list could not be loaded.');
  return $(id).value;
 }
 async function loadModels(id,provider,preferred,refresh=false){
  const state={provider,preferred,loading:true,ready:false};modelStates[id]=state;
  const control=$(id),status=$(id+'-status');
  control.replaceChildren(new Option('Loading available models...',''));
  status.textContent='Loading models from '+providerName(provider)+'...';app.lockControls();
  try{
   const cached=modelCatalogs[provider];
   let result;
   if(!refresh && cached && Date.now()-cached.fetchedAt<60000){result=cached.result;}
   else{
    if(refresh || !modelRequests[provider]){
     const request=app.api('/api/reference/models?provider='+encodeURIComponent(provider));
     modelRequests[provider]=request;
     request.finally(()=>{if(modelRequests[provider]===request)delete modelRequests[provider];}).catch(()=>{});
    }
    result=await modelRequests[provider];
    modelCatalogs[provider]={result,fetchedAt:Date.now()};
   }
   if(modelStates[id]!==state)return;
   const rows=result.models || [];
   state.ids=new Set(rows.map(row=>row.id));if(blankDefault(provider))state.ids.add('');
   control.replaceChildren();
   if(blankDefault(provider))control.add(new Option(provider==='claude'?'Use my Claude default model':'Use configured Codex default',''));
   rows.forEach(row=>control.add(new Option(row.name,row.id)));
   const desired=preferred ?? (blankDefault(provider)?'':rows.find(row=>row.is_default)?.id || rows[0]?.id);
   const available=(blankDefault(provider) && desired==='') || rows.some(row=>row.id===desired);
   if(!available && desired){
    const missing=new Option('Saved model unavailable: '+desired,desired);missing.disabled=true;control.add(missing,0);
   }
   control.value=desired;
   state.ready=available;state.loading=false;
   status.textContent=available?(provider==='claude'?'Signed in to Claude. Each choice uses the newest model of that family.':rows.length+' models returned by '+providerName(provider)+'.'): 'Your saved model is unavailable. Choose a model from the list.';
  }catch(error){
   if(modelStates[id]!==state)return;
   state.loading=false;control.replaceChildren(new Option('Models unavailable',''));
   status.textContent=error.message || 'Could not load models. Refresh to retry.';
  }finally{if(modelStates[id]===state)app.lockControls();}
 }

 function message(id,text){$(id).textContent=text;$(id).hidden=!text;}
 function update(project){
  const ref=project?.reference_style;
  window.VideoTurboFlow?.update(project);
  $('reference-panel').hidden=!ref || !Object.keys(ref).length;
  if($('reference-panel').hidden)return;
  const usedModel=ref.model_id || ref.draft_metadata?.model || '';
  $('reference-provider-badge').textContent=usedModel?modelName(usedModel):providerName(ref.analysis?ref.provider:$('reference-provider').value);
  $('reference-provider-badge').title=usedModel?'Model that produced the current script or scene plan: '+usedModel:'Provider that produced the current saved style analysis';
  const state=app.getState();
  const active=state.job?.project===project.id && ['running','cancelling'].includes(state.job.status);
  const recreating=window.VideoTurboRecreate?.drafting(project);
  $('reference-build').hidden=ref.workflow==='flow' || recreating;
  $('reference-plan').textContent=ref.workflow==='flow' ? (!project.editor.script.trim()?'Analyze reference & draft script':'Prepare Flow storyboard') : recreating ? (ref.status==='script_review'?'Draft the script again':'Analyze source & draft script') : 'Analyze & plan scenes';
  $('reference-status').textContent=active ? state.job.stage : ref.workflow!=='flow' && ref.stale && ref.analysis ? 'Your inputs changed. Analyze again to adapt the scenes to the current reference and recording.' : (ref.workflow==='flow' ? (ref.stale && ref.flow_plan ? 'Your inputs changed. Prepare the Flow storyboard again before importing or building.' : ({awaiting_inputs:'Add your reference, spoken script and voiceover, then prepare your Flow storyboard.',script_review:'Review and approve the script draft below, then add your voiceover.',awaiting_clips:'Storyboard ready. Generate your scenes in Flow and import each clip below.',ready:'All Flow clips are imported. Review the scenes, then build your final video.',complete:'Your Flow video is ready.',failed:'Flow preparation needs attention. Check the message and retry.',render_failed:'Your Flow clips are saved. Check the build log and retry.',cancelled:'Cancelled. Your saved storyboard and clips are kept.'}[ref.status] || 'Prepare your Flow storyboard when your inputs are ready.')) : ({awaiting_inputs:'Reference project ready. Check your files below, then analyze the style.',ready:'Style analyzed and scenes prepared. Edit the scenes below or build your video.',complete:'Your reference-style video is ready.',render_failed:'The scene plan is ready. Check the build log and retry Build video.',failed:'Analysis or building needs attention. Your files are saved; check the message and retry.',cancelled:'Cancelled. Your files are saved; analyze again when ready.',interrupted:'Analysis was interrupted. Your files are saved; retry analysis.'}[ref.status] || 'Ready to analyze your reference.'));
  if(recreating && !active)$('reference-status').textContent=ref.status==='script_review'?'Review and approve your new script below, then add your voiceover.':ref.status==='failed'?'Drafting needs attention. Check the message below, then click Analyze source & draft script to retry.':ref.status==='interrupted'?'Drafting was interrupted. Click Analyze source & draft script to retry.':window.VideoTurboRecreate?.hasSource(project)?'Your source video is ready. Click Analyze source & draft script to write your new script.':'Add your source video, then draft your new script from its idea.';
  window.VideoTurboRecreate?.update(project);
  message('reference-project-error',ref.error || '');
  const library=ref.library_styles || [];
  $('reference-source').hidden=library.length>0;
  $('reference-library-summary').hidden=!library.length;
  if(library.length){
   const parts=window.VideoTurboStyles?.mixSummary(ref.style_mix || {},library) || '';
   $('reference-library-summary').textContent=(library.length>1?'Saved styles: ':'Saved style: ')+library.map((row,i)=>(library.length>1?'ABC'[i]+' · ':'')+row.name).join(' + ')+(parts?'. '+parts:'.');
  }
  $('reference-save-style').hidden=!ref.analysis || ref.workflow==='flow';
  const custom=ref.scene_mode==='custom',drawn=ref.custom_scenes;
  $('reference-scenes-box').hidden=ref.workflow==='flow' || Boolean(recreating);
  if(document.activeElement!==$('reference-scene-mode-panel'))$('reference-scene-mode-panel').value=custom?'custom':'templates';
  $('reference-draw').hidden=!custom || !ref.analysis;
  $('reference-draw').textContent=drawn?'Draw scenes again with Claude':'Draw scenes with Claude';
  const total=(drawn?.passed?.length || 0)+(drawn?.failed?.length || 0);
  $('reference-scenes-status').textContent=!custom?'Scenes use the built-in templates.':!drawn?(ref.analysis?'Click Draw scenes with Claude, or Analyze & plan scenes to plan and draw in one step.':'Analyze & plan scenes will also have Claude draw every scene.'):
   'Claude drew '+drawn.passed.length+' of '+total+' scenes'+(drawn.model?' ('+modelName(drawn.model)+')':'')+'.'+(drawn.failed?.length?' '+drawn.failed.join(', ')+' use templates because the version Claude drew did not pass the checks.':'');
  const player=$('reference-player');player.hidden=!ref.reference_file;
  if(ref.sampled)player.poster=app.mediaUrl('reference/frames/frame-0001.jpg',project.id);
  if(ref.reference_file){const src=app.mediaUrl(ref.reference_file,project.id);if(player.getAttribute('src')!==src)player.src=src;}
  $('reference-analysis').hidden=!ref.analysis;
  if(ref.analysis){
   const s=ref.analysis;$('reference-style-name').textContent=s.name;$('reference-style-summary').textContent=s.summary;
   $('reference-palette').innerHTML=['background','background_end',...(s.contrast_background?['contrast_background']:[]),'ink','accent','muted'].map(k=>`<span class="reference-swatch"><i style="background:${esc(s[k])}" aria-hidden="true"></i>${esc(s[k])}</span>`).join('');
   $('reference-observations').innerHTML=(s.observations || []).map(o=>`<li><strong>${Number(o.time_seconds).toFixed(2)}s</strong> ${esc(o.detail)}</li>`).join('');
  }
 }
 function fillConnection(){
  const provider=$('reference-provider').value;
  const config=providerDrafts[provider] || connectionSettings?.providers?.[provider] || {};
  currentProvider=provider;
  const preferred=config.model ?? (blankDefault(provider)?'':'gemini-3.8-flash-medium');
  $('reference-cli').value=config.cli_path || '';
  $('reference-model-label').textContent=modelLabel(provider);
  $('reference-cli-label').textContent=provider==='codex'?'Codex CLI path (optional)':provider==='claude'?'Claude CLI path (optional)':'Antigravity CLI path (optional)';
  $('reference-cli').placeholder='Automatically detected '+(provider==='codex'?'codex':provider==='claude'?'claude':'agy')+' executable';
  const found=connectionSettings?.providers?.[provider]?.installed;
  $('reference-connection-status').textContent=found?'Local '+providerName(provider)+' CLI found. Check the connection to verify access.':'Local CLI not found. Install it or enter its executable path.';
  update(app.getState().project);
  return loadModels('reference-model',provider,preferred);
 }
 async function connection(){
  connectionSettings=await app.api('/api/reference/settings');
  $('reference-provider').value=connectionSettings.provider || 'antigravity';
  fillConnection();
 }
 async function saveConnection(){
  const provider=$('reference-provider').value;
  providerDrafts[provider]={cli_path:$('reference-cli').value,model:requireModel('reference-model')};
  connectionSettings=await app.api('/api/reference/settings',{provider,...providerDrafts[provider]});
 }
 async function action(fn,errorId='reference-project-error'){
  if(busy || app.getState().busy)return;
  busy=true;app.getState().busy=true;app.lockControls();message(errorId,'');
  try{await fn();}catch(e){message(errorId,e.message);app.toast(e.message,true);}finally{busy=false;app.getState().busy=false;app.lockControls();}
 }
 async function upload(file,role){
  const p=app.getState().project;
  const response=await fetch('/api/upload?id='+p.id+'&name='+encodeURIComponent(file.name)+'&role='+role,{method:'POST',headers:{'X-Studio-Token':app.getState().token},body:file});
  const result=await response.json();if(!response.ok)throw new Error(result.error || 'Upload failed.');
  app.install(result.project);
 }
 function fillCreationConnection(refresh=false){
  const provider=$('reference-create-provider').value;
  const config=creationDrafts[provider] || providerDrafts[provider] || connectionSettings?.providers?.[provider] || {};
  creationProvider=provider;
  const preferred=config.model ?? (blankDefault(provider)?'':'gemini-3.8-flash-medium');
  $('reference-create-model-label').textContent=modelLabel(provider);
  $('reference-create-model').required=provider==='antigravity';
  const found=connectionSettings?.providers?.[provider]?.installed;
  $('reference-create-connection-status').textContent=found?'Local '+providerName(provider)+' CLI found. Uses its saved sign-in.':'Local CLI not found. Install it or set its path under Local AI connection in the project.';
  return loadModels('reference-create-model',provider,preferred,refresh);
 }
 async function applyCreationProvider(){
  requireModel('reference-create-model');
  providerDrafts[currentProvider]={cli_path:$('reference-cli').value,model:modelValue('reference-model')};
  const provider=$('reference-create-provider').value;
  const config=providerDrafts[provider] || connectionSettings?.providers?.[provider] || {};
  providerDrafts[provider]={cli_path:config.cli_path || '',model:modelValue('reference-create-model')};
  creationDrafts[provider]={...providerDrafts[provider]};
  $('reference-provider').value=provider;await fillConnection();await saveConnection();
  return provider;
 }
 async function open(){
  $('reference-form').reset();window.VideoTurboVoice?.sync();window.VideoTurboStyles?.openCreation();window.VideoTurboFlow?.syncCreation();window.VideoTurboRecreate?.syncCreation();syncSceneMode();message('reference-create-error','');$('reference-dialog').showModal();$('reference-name').focus();
  try{
   connectionSettings=await app.api('/api/reference/settings');
   $('reference-create-provider').value=$('reference-provider').value || connectionSettings.provider || 'codex';
   fillCreationConnection(true);app.lockControls();
  }catch(e){message('reference-create-error','This Studio server needs an update. Relaunch Video Turbo and use the updated window.');}
 }
 async function start(build){
  await app.save();
  await window.VideoTurboVoice?.saveSelection();
  await saveConnection();
  const result=await app.api('/api/reference/start',{id:app.getState().project.id,build,provider:$('reference-provider').value});
  app.getState().job=result.job;app.install(result.project);app.showJob();
 }
 function syncSceneMode(){
  const animation=$('reference-workflow').value==='reference',custom=animation && $('reference-scene-mode').value==='custom';
  $('reference-scene-mode-field').hidden=!animation;$('reference-scene-mode-note').hidden=!custom;
 }
 $('reference-workflow').addEventListener('change',syncSceneMode);
 $('reference-scene-mode').onchange=()=>{
  syncSceneMode();
  if($('reference-scene-mode').value==='custom' && $('reference-create-provider').value!=='claude'){
   creationDrafts[creationProvider]={model:modelValue('reference-create-model')};
   $('reference-create-provider').value='claude';fillCreationConnection();
   app.toast('Claude is now the AI provider, since it draws the scenes.');
  }
 };
 $('reference-new').onclick=open;
 $('reference-close').onclick=()=>$('reference-dialog').close();
 $('reference-form').onsubmit=e=>{e.preventDefault();action(async()=>{
  const flow=window.VideoTurboFlow?.creation() || {workflow:'reference',idea:''};
  const recreating=window.VideoTurboRecreate?.creation() || null;
  const drafting=(flow.workflow==='flow' && $('flow-story-source').value==='idea') || Boolean(recreating);
  if(flow.workflow==='flow' && drafting && !flow.idea)throw new Error('Describe your video idea first.');
  const library=flow.workflow==='reference' ? (window.VideoTurboStyles?.selection() || {styles:[],mix:{}}) : {styles:[],mix:{}};
  const files=[...(library.styles.length?[]:[['reference',$('reference-file').files[0]]]),...(recreating?.file?[['source',recreating.file]]:[]),...($('reference-voice-source').value==='upload' && !drafting?[['voice',$('reference-voice').files[0]]]:[]),...Array.from($('reference-assets').files).map(f=>['media',f])];
  if(files.some(([,f])=>!f || f.size>4*1024**3))throw new Error('Choose supported media files up to 4 GB each.');
  if(app.getState().dirty)await app.save();
  const provider=await applyCreationProvider();
  const project=await app.api('/api/reference/create',{provider,voice_source:$('reference-voice-source').value,name:$('reference-name').value,script:drafting?'':$('reference-script').value,...flow,instructions:$('reference-instructions').value,styles:library.styles,style_mix:library.mix,...(recreating?{recreate:recreating.options}:{}),scene_mode:flow.workflow==='reference'?$('reference-scene-mode').value:'templates'});
  app.install(project);$('reference-dialog').close();await app.refreshState();
  for(const [role,file] of files){app.toast('Uploading '+file.name+'...');await upload(file,role);}
  if(recreating){
   const match=app.getState().project?.reference_style?.recreate?.source_matches_style;
   if(match){app.toast('Project created. The source video is the same file as your style "'+match+'", so drafting has not started. Check the source, then click Analyze source & draft script.',true);await connection();return;}
   // Every input for the draft is ready, so start it now; the script still waits for approval.
   try{
    const result=await app.api('/api/reference/start',{id:project.id,build:false,provider});
    app.getState().job=result.job;app.install(result.project);app.showJob();await connection();
    app.toast('Project created. Drafting your new script from the source video.');
   }catch(error){app.toast('Project created, but drafting could not start: '+error.message+' Click Analyze source & draft script to retry.',true);}
   return;
  }
  await connection();app.toast(flow.workflow==='flow'?'Flow project ready. Analyze the reference to prepare your script or storyboard.':recreating?'Project ready. Click Analyze source & draft script.':library.styles.length?'Project ready. Click Analyze & plan scenes to apply your saved styles.':'Reference project ready. Analyze the style to prepare your new scenes.');
 },'reference-create-error');};
 $('reference-create-provider').onchange=()=>{
  if($('reference-create-provider').value!=='claude' && $('reference-scene-mode').value==='custom'){$('reference-scene-mode').value='templates';syncSceneMode();}
  creationDrafts[creationProvider]={model:modelValue('reference-create-model')};
  fillCreationConnection();
 };
 $('reference-create-check').onclick=()=>action(async()=>{
  const provider=await applyCreationProvider();
  $('reference-create-connection-status').textContent='Checking '+providerName(provider)+'...';
  const result=await app.api('/api/reference/check',{});
  $('reference-create-connection-status').textContent='Connected to '+providerName(result.provider)+' ('+(result.model || 'configured default model')+').';
 },'reference-create-error');
 $('reference-create-model').onchange=()=>{
  const state=modelStates['reference-create-model'];if(state)state.ready=Boolean(state.ids?.has($('reference-create-model').value));
  app.lockControls();
 };
 $('reference-model').onchange=()=>{
  const state=modelStates['reference-model'];if(state)state.ready=Boolean(state.ids?.has($('reference-model').value));
  app.lockControls();
 };
 $('reference-create-model-refresh').onclick=()=>loadModels('reference-create-model',$('reference-create-provider').value,modelValue('reference-create-model'),true);
 $('reference-model-refresh').onclick=()=>loadModels('reference-model',$('reference-provider').value,modelValue('reference-model'),true);
 $('reference-replace').onchange=()=>action(async()=>{const f=$('reference-replace').files[0];if(f)await upload(f,'reference');$('reference-replace').value='';});
 $('reference-plan').onclick=()=>action(()=>start(false));
 $('reference-scene-mode-panel').onchange=()=>action(async()=>{
  const p=app.getState().project;if(app.getState().dirty)await app.save();
  app.install(await app.api('/api/reference/scene-mode',{id:p.id,mode:$('reference-scene-mode-panel').value}));
 });
 $('reference-draw').onclick=()=>action(async()=>{
  if(app.getState().dirty)await app.save();
  const result=await app.api('/api/reference/draw-scenes',{id:app.getState().project.id});
  app.getState().job=result.job;app.install(result.project);app.showJob();
  app.toast('Claude is drawing your scenes. This takes several minutes.');
 });
 $('reference-save-style').onclick=()=>action(async()=>{
  const result=await app.api('/api/styles/from-project',{id:app.getState().project.id});
  window.VideoTurboStyles?.refresh(result);
  app.toast('Saved "'+result.style.name+'" to your style library.');
 });
 $('reference-build').onclick=()=>action(()=>start(true));
 $('reference-provider').onchange=()=>{
  providerDrafts[currentProvider]={cli_path:$('reference-cli').value,model:modelValue('reference-model')};
  fillConnection();
  $('reference-connection-status').textContent='Selected '+providerName($('reference-provider').value)+'. Analyze, check the connection, or save to use this provider.';
 };
 $('reference-save-connection').onclick=()=>action(async()=>{await saveConnection();$('reference-connection-status').textContent='Connection settings saved. Check the connection next.';});
 $('reference-check-connection').onclick=()=>action(async()=>{await saveConnection();$('reference-connection-status').textContent='Checking '+providerName($('reference-provider').value)+'...';const r=await app.api('/api/reference/check',{});$('reference-connection-status').textContent='Connected to '+providerName(r.provider)+' ('+(r.model || 'configured default model')+').';});
 window.VideoTurboReference={
  configure(options){app=options;window.VideoTurboFlow?.configure(options);connection().catch(e=>{$('reference-connection-status').textContent=e.message;});},update,
  // Shared with the Style Library dialog.
  loadModels,providerName,modelLabel,blankDefault,
  modelValue,
  modelReady:id=>Boolean(modelStates[id]?.ready),
  modelLoading:id=>Boolean(modelStates[id]?.loading),
  settings:()=>connectionSettings,
  lock(working){
   if(!app)return;
   $('reference-create').disabled=working || busy || !connectionSettings?.providers || !modelStates['reference-create-model']?.ready;
   $('reference-create-check').disabled=working || busy || !connectionSettings?.providers || !modelStates['reference-create-model']?.ready;
   for(const id of ['reference-model','reference-create-model'])$(id).disabled=working || busy || Boolean(modelStates[id]?.loading);
   $('reference-create-model-refresh').disabled=working || busy || Boolean(modelStates['reference-create-model']?.loading);
   $('reference-model-refresh').disabled=working || busy || Boolean(modelStates['reference-model']?.loading);
   for(const id of ['reference-save-connection','reference-check-connection'])$(id).disabled=working || busy || !modelStates['reference-model']?.ready;
   $('reference-save-style').disabled=working || busy;
   for(const id of ['reference-scene-mode-panel','reference-draw'])$(id).disabled=working || busy;
   const p=app.getState().project,r=p?.reference_style,ready=Boolean((r?.reference_file || r?.library_styles?.length) && ((r.workflow==='flow' && r.idea && !p?.editor?.script?.trim()) || (window.VideoTurboRecreate?.drafting(p) && window.VideoTurboRecreate?.hasSource(p)) || ((p?.voiceover || window.VideoTurboVoice?.canGenerate()) && p?.editor?.script?.trim())));
   for(const id of ['reference-plan','reference-build'])$(id).disabled=working || busy || !ready || !modelStates['reference-model']?.ready;
   if(r && Object.keys(r).length && (r.stale || !['ready','complete','render_failed'].includes(r.status))){$('build').disabled=true;$('render-preview').disabled=true;}
   window.VideoTurboFlow?.lock(working || busy);
  },
  async poll(){
   const state=app.getState(),p=state.project;
   if(!p?.reference_style || !Object.keys(p.reference_style).length || polling || state.busy || state.dirty)return;
   polling=true;
   try{const latest=await app.api('/api/project?id='+p.id);if(state.project?.id!==p.id || state.dirty)return;const key=p.id+JSON.stringify(latest.reference_style);if(key!==lastKey){lastKey=key;app.install(latest);}}finally{polling=false;}
  }
 };
})();
