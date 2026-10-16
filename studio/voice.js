(() => {
 'use strict';
 const $=id=>document.getElementById(id);
 let app, settings=null, catalog=null, loading=false, working=false, selectedProject='', generationStamp='';
 const message=(id,text)=>{$(id).textContent=text || '';$(id).hidden=!text;};
 const chosen=()=>({source:$('voice-source').value,voice_id:$('voice-id').value,model_id:$('voice-model').value,
  stability:Number($('voice-stability').value),similarity_boost:Number($('voice-similarity').value),speed:Number($('voice-speed').value)});
 function fillSelect(id,rows,preferred){
  const control=$(id);control.replaceChildren();
  if(!rows?.length){control.add(new Option(settings?.configured?'Load your voices and models':'Connect ElevenLabs first',''));return;}
  rows.forEach(row=>control.add(new Option(row.name+(row.category?` (${row.category})`:''),row.id)));
  if(preferred && !rows.some(row=>row.id===preferred)){
   const missing=new Option('Saved selection unavailable: '+preferred,preferred);missing.disabled=true;control.add(missing,0);
  }
  control.value=preferred || rows[0].id;
 }
 function fillCatalog(){
  const p=app.getState().project, saved=p?.voice_settings || {}, defaults=settings?.defaults || {};
  const voices=catalog?.voices,models=catalog?.models;
  const defaultModel=defaults.model_id || models?.find(row=>row.id==='eleven_multilingual_v2')?.id;
  fillSelect('voice-default-id',voices,defaults.voice_id);
  fillSelect('voice-default-model',models,defaultModel);
  fillSelect('voice-id',voices,saved.voice_id || defaults.voice_id);
  fillSelect('voice-model',models,saved.model_id || defaultModel);
  status();app.lockControls();
 }
 function status(){
  if(!app)return;
  const state=app.getState(),p=state.project,model=catalog?.models.find(row=>row.id===$('voice-model').value);
  const characters=Array.from($('script').value.trim()).length;
  $('voice-elevenlabs').hidden=$('voice-source').value!=='elevenlabs';
  $('voice-label').hidden=$('voice-source').value==='elevenlabs';
  $('voice-character-count').textContent=characters.toLocaleString()+' script characters'+(model?' / '+model.limit.toLocaleString()+' per request for '+model.name:'')+'.';
  $('voice-speed-field').hidden=['eleven_v3','eleven_v4'].includes($('voice-model').value);
  $('voice-stability').step=$('voice-model').value==='eleven_v3'?'0.5':'0.05';
  const ref=p?.reference_style;
  const generated=p?.voice_settings?.generated,current=p?.voice_settings?.generated_current;
  const changed=Boolean(generated && (p.voice_settings.stale || state.dirty));
  $('voice-audio-status').textContent=current?(changed?'The script or voice settings changed. Generate the current voiceover before building.':`Saved voiceover: ${generated.voice_name} / ${generated.model_name}, ${Number(generated.duration).toFixed(1)} seconds.`):'Generate your voiceover, then listen to it in the audio player below.';
  $('voice-regenerate').hidden=!current;
  $('voice-build').textContent=ref && Object.keys(ref).length?'Generate voiceover, analyze & build':'Generate voiceover & build';
  $('voice-connection-status').textContent=loading?'Loading ElevenLabs voices and models...':!settings?.configured?'Connect your ElevenLabs account in Voice settings first.':catalog?catalog.voices.length+' voices and '+catalog.models.length+' speech models loaded.':'API key saved. Refresh to load your voices and models.';
  const upload=$('reference-voice-source').value==='upload';
  $('reference-voice-upload').hidden=!upload;$('reference-voice').required=upload;
 }
 function lock(blocked){
  if(!app)return;
  const state=app.getState(),busy=blocked || working || state.busy || !state.token || ['running','cancelling'].includes(state.job?.status) || state.publishingJob?.status==='running';
  const config=chosen(),model=catalog?.models.find(row=>row.id===config.model_id),voice=catalog?.voices.find(row=>row.id===config.voice_id);
  const wf=state.project?.ai_workflow;
  const unapproved=wf && Object.keys(wf).length && wf.source!=='import' && (!wf.approved_script_hash || ['writing_script','awaiting_review'].includes(wf.status));
  const ready=Boolean(settings?.configured && model && voice && $('script').value.trim() && Array.from($('script').value.trim()).length<=model.limit && !unapproved);
  for(const id of ['voice-generate','voice-build','voice-regenerate'])$(id).disabled=busy || loading || !ready;
  if(unapproved && config.source==='elevenlabs')$('voice-audio-status').textContent='Review and approve the AI script before generating speech.';
  for(const id of ['voice-id','voice-model','voice-default-id','voice-default-model'])$(id).disabled=busy || loading || !catalog;
  for(const id of ['voice-connect','voice-settings-refresh','voice-settings-save','voice-refresh'])$(id).disabled=busy || loading || (id!=='voice-connect' && !settings?.configured) || (id==='voice-settings-save' && !catalog);
  $('voice-settings-close').disabled=working || loading;
 }
 async function action(fn,errorId='voice-error'){
  if(working || app.getState().busy)return;
  working=true;app.getState().busy=true;app.lockControls();message(errorId,'');
  try{await fn();}catch(error){message(errorId,error.message);app.toast(error.message,true);}
  finally{working=false;app.getState().busy=false;status();app.lockControls();}
 }
 async function loadCatalog(refresh=false){
  if(loading)return;
  loading=true;message('voice-settings-status','Loading ElevenLabs voices and models...');$('voice-settings-dialog').setAttribute('aria-busy','true');status();app.lockControls();
  try{
   catalog=await app.api('/api/voice/catalog'+(refresh?'?refresh=1':''));
   fillCatalog();message('voice-settings-status','Connected. Your account voices and speech models are ready. Saving settings does not generate speech.');
  }catch(error){catalog=null;fillCatalog();throw error;}
  finally{loading=false;$('voice-settings-dialog').setAttribute('aria-busy','false');status();app.lockControls();}
 }
 async function openSettings(){
  message('voice-settings-error','');$('voice-api-key').value='';$('voice-settings-dialog').showModal();$('voice-api-key').focus();
  try{
   settings=await app.api('/api/voice/settings');
   message('voice-settings-status',settings.configured?'API key saved. Load your voices or choose your default voice below.':'Add your API key after subscribing and creating your voice clone.');
   if(settings.configured && !catalog)await loadCatalog();else fillCatalog();
  }catch(error){message('voice-settings-error',error.message);}
 }
 async function saveSelection(){
  const state=app.getState();if(!state.project)return;
  const result=await app.api('/api/voice/project',{id:state.project.id,settings:chosen()});
  state.project.voice_settings=result.voice_settings;
 }
 async function generate(build=false,force=false){
  await app.save();await saveSelection();
  const result=await app.api('/api/voice/start',{id:app.getState().project.id,build,force});
  app.getState().job=result.job;app.install(result.project);app.showJob();
 }
 function update(project){
  if(!app || !project)return;
  if(selectedProject!==project.id){
   selectedProject=project.id;
   const saved=project.voice_settings || {};
   $('voice-source').value=saved.source || 'upload';
   $('voice-stability').value=saved.stability ?? .5;$('voice-similarity').value=saved.similarity_boost ?? .75;$('voice-speed').value=saved.speed ?? 1;
   fillCatalog();
   if(settings?.configured && !catalog && $('voice-source').value==='elevenlabs')action(()=>loadCatalog());
  }
  const stamp=project.voice_settings?.generated?.created;
  if(stamp && generationStamp!==stamp){
   generationStamp=stamp;$('voice-player').src=app.mediaUrl(project.voiceover,project.id)+'&v='+stamp;
  }
  status();
 }
 $('voice-connection-open').onclick=openSettings;$('voice-setup').onclick=openSettings;
 $('voice-settings-close').onclick=()=>$('voice-settings-dialog').close();
 $('voice-settings-dialog').addEventListener('close',()=>{$('voice-api-key').value='';});
 $('voice-connect').onclick=()=>action(async()=>{
  try{settings=await app.api('/api/voice/settings',{api_key:$('voice-api-key').value});catalog=null;await loadCatalog(true);}
  finally{$('voice-api-key').value='';}
 },'voice-settings-error');
 $('voice-settings-form').onsubmit=event=>{event.preventDefault();action(async()=>{
  const defaults={...settings.defaults,source:'elevenlabs',voice_id:$('voice-default-id').value,model_id:$('voice-default-model').value};
  settings=await app.api('/api/voice/settings',{defaults});
  fillCatalog();message('voice-settings-status','Default voice saved for new projects.');
 },'voice-settings-error');};
 $('voice-settings-refresh').onclick=()=>action(()=>loadCatalog(true),'voice-settings-error');
 $('voice-refresh').onclick=()=>action(async()=>{await saveSelection();await loadCatalog(true);});
 $('voice-source').onchange=()=>action(async()=>{status();await saveSelection();if($('voice-source').value==='elevenlabs' && settings?.configured && !catalog){await loadCatalog();await saveSelection();}app.getState().project.voice_settings.source=$('voice-source').value;});
 for(const id of ['voice-id','voice-model','voice-stability','voice-similarity','voice-speed'])$(id).onchange=()=>action(async()=>{
  if(id==='voice-model' && $('voice-model').value==='eleven_v3')$('voice-stability').value=.5;
  if(['eleven_v3','eleven_v4'].includes($('voice-model').value))$('voice-speed').value=1;
  await saveSelection();status();
 });
 $('script').addEventListener('input',()=>{status();app.lockControls();});
 $('reference-voice-source').onchange=status;
 $('voice-generate').onclick=()=>action(()=>generate());
 $('voice-build').onclick=()=>action(()=>generate(true));
 $('voice-regenerate').onclick=()=>action(()=>generate(false,true));
 window.VideoTurboVoice={
  configure(value){app=value;app.api('/api/voice/settings').then(result=>{settings=result;fillCatalog();if(app.getState().project)update(app.getState().project);}).catch(error=>message('voice-error',error.message));},
  update,lock,saveSelection,sync:status,
  canGenerate(){return $('voice-source').value==='elevenlabs' && Boolean(settings?.configured && !loading && catalog?.voices.some(v=>v.id===$('voice-id').value) && catalog?.models.some(m=>m.id===$('voice-model').value));},
  async setSource(source){$('voice-source').value=source;status();await saveSelection();},
 };
})();
