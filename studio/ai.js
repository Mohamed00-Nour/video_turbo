(() => {
 'use strict';
 const $ = id=>document.getElementById(id);
 let app,settings,busy=false,polling=false,lastStatus='';
 const connectionResults = {};
 let seriesList=[],seriesLoaded=false,seriesRequest=null;
 const seriesDrafts = {};
 const phases = {
  awaiting_assets:['Your script and game list are ready','Click Prepare assets, then upload a recording or choose ElevenLabs below. Studio builds when the assets and voiceover are ready.'],
  writing_script:['Writing your script','The script comes first. Assets will wait until you approve it.'],
  awaiting_review:['Your script is ready to review','Edit the spoken script below, then approve it. You can copy or download it for recording.'],
  finding_sources:['Finding gameplay and logos','Your script is approved. Studio is finding asset sources. Your selected voiceover source will be used when the assets are ready.'],
  preparing_assets:['Preparing your assets','Gameplay clips and logos are being prepared. ElevenLabs can generate your selected voiceover after this step.'],
  assets_ready:['Assets ready','Upload a voiceover, or choose an ElevenLabs voice and generate it below. Studio will align the audio and build your video.'],
  rendering:['Building your video','Your assets and voiceover are ready. Studio is aligning captions and rendering the finished MP4.'],
  complete:['Your video is ready','Preview the finished video, then open Publishing when you are ready to post.'],
  failed:['A step needs attention','Your project and script are saved. Check the message below and retry the step.'],
  cancelled:['AI workflow cancelled','Your script is saved. Retry when you are ready to continue.'],
  interrupted:['Workflow interrupted','Your script is saved. Retry the interrupted step after restarting Studio.'],
 };
 function creationMode() {
  const ai=$('new-workflow').value==='ai';
  $('create-ai-fields').hidden=!ai; $('create-manual-fields').hidden=ai;
  $('ai-idea').required=ai; $('ai-language').required=ai;
  lock(false);
 }
 function connection() {
  const info=settings?.providers?.[$('ai-provider').value];
  $('ai-model').value=info?.model || '';
  $('ai-api-key').value='';
  $('ai-key-link').href=info?.key_url || 'https://aistudio.google.com/apikey';
  $('ai-connection-state').textContent=info?.configured ? 'API key saved for '+info.name+'. Blank keeps your saved key. Connection has not been tested.' : 'Save an API key for '+(info?.name || 'your provider')+' before creating an AI project.';
  const result=connectionResults[$('ai-provider').value];
  connectionFeedback(result?.message,result?.kind);
  if(info && !info.configured) $('ai-settings').open=true;
  lock(false);
 }
 async function loadSettings() {
  settings=await app.api('/api/ai/settings');
  $('ai-provider').value=settings.default;
  connection();
 }
 function selectedSeries() {return seriesList.find(series=>series.id===$('ai-series').value);}
 function seriesValues() {
  return {name:$('ai-series-name').value,platform:$('ai-series-platform').value,instructions:$('ai-series-instructions').value,
   language:$('ai-series-language').value,reference_script:$('ai-series-reference').value};
 }
 function seriesFeedback(message,kind='') {
  const feedback=$('ai-series-feedback');
  feedback.textContent=message || '';feedback.dataset.state=kind;feedback.hidden=!message;
 }
 function seriesSelection() {
  const id=$('ai-series').value,series=selectedSeries(),draft=seriesDrafts[id];
  const editing=id==='__new__' || Boolean(series);
  $('ai-series-settings').hidden=!editing;
  $('ai-idea-label').textContent=editing ? 'This episode\u2019s idea' : 'Your video idea';
  $('ai-idea').placeholder=editing ? 'Create one more episode with new games, or describe this episode\u2019s topic.' : 'Three free games for a low-end PC. Explain what makes each fun.';
  $('ai-series-context').textContent=series ? series.episodes.length+' approved episode'+(series.episodes.length===1?'':'s')+'. Saved instructions'+(series.reference_script ? ', reference script' : '')+' and game history are included in each new episode.' : editing ? 'Save your initial prompt as series instructions. Each episode will use this structure.' : 'Choose a series to reuse its structure, or create a standalone video.';
  $('ai-series-context').dataset.state='';
  if(editing) {
   const values=draft || series || {name:'',platform:'pc',instructions:'',language:$('ai-language').value || 'Egyptian Arabic',reference_script:''};
   for(const [key,field] of [['name','name'],['platform','platform'],['instructions','instructions'],['language','language'],['reference_script','reference']]) $('ai-series-'+field).value=values[key];
   $('ai-language').value=values.language;
   const episodes=series?.episodes || [];
   $('ai-series-history').hidden=!episodes.length;
   $('ai-series-episodes').replaceChildren();
   for(const episode of episodes.slice(-10).reverse()) {
    const item=document.createElement('li'),name=document.createElement('strong'),games=document.createElement('span');
    name.textContent=episode.name;games.textContent=episode.games.join(', ');name.dir=games.dir='auto';
    item.append(name,games);$('ai-series-episodes').append(item);
   }
   if(id==='__new__') $('ai-series-settings').open=true;
  }
  seriesFeedback(draft ? 'Unsaved series settings. Save them below, or create an episode to save them automatically.' : '');
  lock(false);
 }
 function seriesOptions(selected=$('ai-series').value) {
  const select=$('ai-series');select.replaceChildren();
  for(const series of [{id:'',name:'Standalone video (no series)'},...seriesList,...(selected==='__new__'?[{id:'__new__',name:'New series (unsaved)'}]:[])]) {
   const option=document.createElement('option');option.value=series.id;option.textContent=series.name;select.append(option);
  }
  select.value=seriesList.some(series=>series.id===selected) || selected==='__new__' ? selected : '';
 }
 function loadSeries() {
  if(seriesRequest) return seriesRequest;
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
  $('ai-series-context').textContent='Loading saved series...';$('ai-series-context').dataset.state='';
  $('ai-series-retry').hidden=true;
  const request=(async()=>{
   try {
    const result=await app.api('/api/ai/series',undefined,{signal:controller.signal});
    const language=$('ai-language').value;
    seriesList=result.series;seriesLoaded=true;seriesOptions();seriesSelection();
    $('ai-language').value=language;
   } catch(e) {
    seriesLoaded=false;
    const outdated=e.status===404 || e.message==='Page not found.';
    $('ai-series-context').textContent=outdated ? 'Studio is running an older version. Restart Studio, then retry loading series. Standalone videos remain available.' :
     e.name==='AbortError' ? 'Loading saved series timed out. Check that Studio is running, then retry.' : 'Could not load saved series. '+e.message+' Check that Studio is running, then retry.';
    $('ai-series-context').dataset.state='error';$('ai-series-retry').hidden=false;
   } finally {clearTimeout(timer);}
  })();
  seriesRequest=request;lock(false);
  return request.finally(()=>{seriesRequest=null;lock(false);});
 }
 async function saveSeries() {
  const id=$('ai-series').value;
  if(!id) return;
  const values=seriesValues(),button=$('ai-series-save');
  button.textContent='Saving series...';seriesFeedback('Saving your series settings...','pending');
  try {
   const result=await app.api('/api/ai/series',{id:id==='__new__'?'':id,...values});
   seriesList=result.series;delete seriesDrafts[id];
   const saved=id==='__new__' ? seriesList[seriesList.length-1].id : id;
   seriesOptions(saved);seriesSelection();
   seriesFeedback('Series saved. New episodes will use these instructions.','success');
  } catch(e) {seriesFeedback(e.message,'error');throw e;}
  finally {button.textContent='Save series';}
 }
 function error(message) { $('ai-create-error').textContent=message || ''; $('ai-create-error').hidden=!message; }
 function connectionFeedback(message,kind='') {
  const feedback=$('ai-connection-feedback');
  feedback.textContent=message || '';feedback.dataset.state=kind;feedback.hidden=!message;
 }
 function lock(blocked) {
  if(!app) return;
  const state=app.getState();
  const working=blocked || busy || state.busy || !state.token || ['running','cancelling'].includes(state.job?.status) || state.publishingJob?.status==='running';
  const ai=$('new-workflow').value==='ai';
  $('create-submit').disabled=working || ai && (!settings?.providers?.[$('ai-provider').value]?.configured || Boolean($('ai-series').value) && !seriesLoaded);
  for(const control of $('create-ai-fields').querySelectorAll('input,textarea,select,button')) control.disabled=working || !ai;
  $('ai-series').disabled=working || !ai || !seriesLoaded;
  $('ai-series-new').disabled=working || !ai || !seriesLoaded;
  $('ai-series-retry').disabled=working || !ai || Boolean(seriesRequest);
  for(const id of ['ai-approve','ai-retry','ai-prepare-assets']) $(id).disabled=working;
  for(const id of ['ai-copy-script','ai-download-script']) $(id).disabled=!state.project?.editor?.script;
  $('close-dialog').disabled=busy;
 }
 function update(project) {
  const workflow=project?.ai_workflow;
  $('ai-workflow').hidden=!workflow || !Object.keys(workflow).length;
  if($('ai-workflow').hidden) return;
  const imported=workflow.source==='import';
  const changed=Boolean(workflow.approved_script && workflow.approved_script!==$('script').value.trim()) || imported && app.getState().dirty;
  $('ai-workflow-heading').textContent=imported ? 'Prepare assets and your voiceover.' : 'Script first. Your voice next.';
  const [title,note]=phases[changed?(imported?'awaiting_assets':'awaiting_review'):workflow.status] || ['AI workflow','Review your script before recording.'];
  $('ai-workflow-status').textContent=title; $('ai-workflow-note').textContent=note;
  const review=workflow.status==='awaiting_review' || changed;
  $('ai-approve').hidden=imported || !review || !workflow.outline;
  $('ai-prepare-assets').hidden=!imported || !changed && !['awaiting_assets','assets_ready','complete'].includes(workflow.status);
  $('ai-prepare-assets').textContent=['assets_ready','complete'].includes(workflow.status) && !changed ? 'Prepare assets again' : 'Prepare assets';
  $('ai-retry').hidden=!['failed','cancelled','interrupted'].includes(workflow.status) || changed;
  $('ai-retry').textContent=workflow.approved_script_hash ? (project.editor.mode==='games' && ['build','preview'].includes(workflow.failed_step) ? 'Retry video build' : 'Retry asset preparation') : 'Retry script generation';
  $('ai-download-brief').hidden=imported || !['preparing_assets','assets_ready','rendering','complete'].includes(workflow.status) || project.editor.mode!=='games';
  $('ai-workflow-error').textContent=workflow.error || ''; $('ai-workflow-error').hidden=!workflow.error;
  $('ai-workflow-series').textContent=workflow.series_context ? 'Series: '+workflow.series_context.name : '';
  $('ai-workflow-series').hidden=!workflow.series_context;
  const progress=imported && (changed || workflow.status==='awaiting_assets') ? 2 : review ? 1 : ['finding_sources','preparing_assets'].includes(workflow.status) ? 2 : workflow.status==='assets_ready' ? 3 : workflow.status==='rendering' ? 4 : workflow.status==='complete' ? 5 : 0;
  $('ai-workflow-steps').querySelectorAll('span').forEach((step,index)=>{step.hidden=imported && index===1;step.textContent=(imported ? ['1 Script','','2 Assets','3 Voiceover','4 Video'] : ['1 Script','2 Approval','3 Assets','4 Voiceover','5 Video'])[index];step.classList.toggle('done',index<progress || index===3 && Boolean(project.voiceover));step.classList.toggle('current',index===progress);});
  lock(false);
 }
 async function action(fn) {
  if(busy || app.getState().busy) return;
  busy=true;app.getState().busy=true;app.lockControls();error('');
  try {await fn();} catch(e) {error(e.message);app.toast(e.message,true);} finally {busy=false;app.getState().busy=false;app.lockControls();}
 }
 function download(text,name,type) {
  const source=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');
  a.href=source;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(source),1000);
 }
 async function apply(result) {
  app.getState().job=result.job; $('create-dialog').close();
  await app.refreshState();app.install(result.project);app.showJob();
 }
 $('new-workflow').onchange=creationMode;
 $('ai-provider').onchange=()=>{error('');connection();};
 $('ai-series').onchange=seriesSelection;
 $('ai-series-retry').onclick=()=>loadSeries();
 $('ai-series-new').onclick=()=>{seriesOptions('__new__');seriesSelection();$('ai-series-name').focus();};
 for(const id of ['ai-series-name','ai-series-platform','ai-series-instructions','ai-series-language','ai-series-reference']) $(id).oninput=()=>{
  seriesDrafts[$('ai-series').value]=seriesValues();
  if(id==='ai-series-language') $('ai-language').value=$(id).value;
  seriesFeedback('Unsaved series settings. Save them below, or create an episode to save them automatically.');
 };
 $('ai-series-save').onclick=()=>action(saveSeries);
 for(const id of ['ai-model','ai-api-key']) $(id).oninput=()=>{
  delete connectionResults[$('ai-provider').value];connectionFeedback();
 };
 $('ai-save-settings').onclick=()=>action(async()=>{
  const provider=$('ai-provider').value,button=$('ai-save-settings');
  delete connectionResults[provider];$('ai-settings').open=true;
  button.textContent='Saving...';connectionFeedback('Saving your AI settings...','pending');
  try {
   settings=await app.api('/api/ai/settings',{provider,model:$('ai-model').value,api_key:$('ai-api-key').value});
   connection();
   connectionResults[provider]={message:'AI settings saved for '+settings.providers[provider].name+'. Your API key is stored on this computer. Connection has not been tested.',kind:'success'};
  } catch(e) {
   connectionResults[provider]={message:'AI settings were not saved. '+e.message,kind:'error'};
  } finally {
   $('ai-api-key').value='';button.textContent='Save AI connection';
   const result=connectionResults[provider];connectionFeedback(result?.message,result?.kind);
  }
 });
 $('ai-approve').onclick=()=>action(async()=>{
  await app.save();await window.VideoTurboVoice?.saveSelection();
  const result=await app.api('/api/ai/approve',{id:app.getState().project.id,script:$('script').value,approved:true});
  await apply(result);app.toast('Script approved. Prepare your voiceover while Studio prepares the assets.');
 });
 $('ai-prepare-assets').onclick=()=>action(async()=>{
  await app.save();await window.VideoTurboVoice?.saveSelection();
  await apply(await app.api('/api/brief/prepare',{id:app.getState().project.id}));
  app.toast('Preparing assets. Studio will use your selected voiceover source when ready.');
 });
 $('ai-retry').onclick=()=>action(async()=>{
  const state=app.getState();
  if(state.project.editor.mode==='games' && state.project.ai_workflow.approved_script_hash && ['build','preview'].includes(state.project.ai_workflow.failed_step)) {
   await app.save();state.job=await app.api('/api/start',{id:state.project.id,action:'build'});app.showJob();return;
  }
  if(state.project.ai_workflow.source==='import') await app.save();
  await apply(await app.api(state.project.ai_workflow.source==='import' ? '/api/brief/prepare' : '/api/ai/retry',{id:state.project.id}));
 });
 $('ai-copy-script').onclick=()=>action(async()=>{await navigator.clipboard.writeText($('script').value);app.toast('Script copied for recording.');});
 $('ai-download-script').onclick=()=>download($('script').value,'voiceover-script.txt','text/plain;charset=utf-8');
 $('ai-download-brief').onclick=()=>action(async()=>{const brief=await app.api('/api/ai/brief?id='+encodeURIComponent(app.getState().project.id));download(JSON.stringify(brief,null,2),'video-turbo-brief.json','application/json');});
 window.VideoTurboAI={
  configure(value) {app=value;loadSettings().catch(e=>error(e.message));loadSeries();},
  openCreation() {creationMode();if(!settings) loadSettings().catch(e=>error(e.message));else connection();loadSeries();},
  async create() {await action(async()=>{
   const language=$('ai-language').value;
   if($('ai-series').value==='__new__' || seriesDrafts[$('ai-series').value]) await saveSeries();
   const result=await app.api('/api/ai/create',{name:$('new-name').value,provider:$('ai-provider').value,idea:$('ai-idea').value,language,series_id:$('ai-series').value,voice_source:$('new-voice-source').value});
   await apply(result);app.toast('Writing your script first. Assets wait for your approval.');
  });},
  update,lock,
  async poll() {
   const state=app.getState(),project=state.project;
   if(!project?.ai_workflow || !Object.keys(project.ai_workflow).length || polling) return;
   polling=true;
   try {
    const workflow=await app.api('/api/ai/workflow?id='+encodeURIComponent(project.id));
    if(state.project?.id!==project.id) return;
    const key=project.id+':'+workflow.status;
    if(key!==lastStatus && !state.dirty && !state.busy && !busy) {
     const latest=await app.api('/api/project?id='+encodeURIComponent(project.id));
     if(state.project?.id===project.id && !state.dirty) {app.install(latest);lastStatus=key;}
    } else {state.project.ai_workflow=workflow;update(state.project);}
   } finally {polling=false;}
  },
 };
})();
