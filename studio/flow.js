(() => {
 'use strict';
 const $=id=>document.getElementById(id);
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let app,working=false,lastScenes='',draftKey='';
 function creation(){
  const workflow=$('reference-workflow').value;
  return {workflow,idea:workflow==='flow' && $('flow-story-source').value==='idea'?$('flow-idea').value.trim():''};
 }
 function syncCreation(){
  const flow=$('reference-workflow').value==='flow',idea=flow && $('flow-story-source').value==='idea';
  $('reference-assets-note').textContent=flow?'Optional subject references for the storyboard. Supply these same images in Flow when generating.':'The selected AI uses these first and researches assets when needed.';
  $('reference-voice-source-note').textContent=idea?'Approve the script first, then add your recording or choose an ElevenLabs voice in the project.':'Upload your recording, or generate it from your script with ElevenLabs. Choose the voice in the project before analysis.';
  $('flow-creation-note').hidden=!flow;$('flow-story-source-field').hidden=!flow;
  $('flow-idea-field').hidden=!idea;$('flow-idea').required=idea;
  $('reference-script-field').hidden=idea;$('reference-script').required=!idea;
  const upload=$('reference-voice-source').value==='upload';
  $('reference-voice-upload').hidden=!upload || idea;$('reference-voice').required=upload && !idea;
 }
 async function action(fn){
  if(!app || working || app.getState().busy)return;
  working=true;app.getState().busy=true;$('flow-error').hidden=true;app.lockControls();
  try{await fn();}catch(error){$('flow-error').textContent=error.message;$('flow-error').hidden=false;app.toast(error.message,true);}
  finally{working=false;app.getState().busy=false;app.lockControls();}
 }
 function update(project){
  const ref=project?.reference_style,flow=ref?.workflow==='flow';
  $('flow-workspace').hidden=!flow;
  if(!flow){lastScenes='';draftKey='';return;}
  const hasScript=Boolean(project.editor.script.trim()),plan=ref.flow_plan,clips=ref.flow_clips || {};
  const ready=['ready','complete','render_failed'].includes(ref.status) && !ref.stale;
  const step=!hasScript?0:!plan || ref.stale?1:ready?3:2;
  $('flow-steps').innerHTML=['Review script','Plan scenes','Generate & import','Final edit'].map((label,index)=>
   '<li'+(index===step?' aria-current="step"':'')+'><span>'+String(index+1)+'</span>'+label+'</li>').join('');
  $('flow-script-review').hidden=ref.status!=='script_review';
  if(ref.status==='script_review'){
   const key=project.id+ref.draft_script;
   if(key!==draftKey){draftKey=key;$('flow-draft').value=ref.draft_script || '';}
   $('flow-draft-summary').textContent=ref.draft_summary || '';
  }
  $('flow-storyboard').hidden=!plan;
  if(!plan)return;
  $('flow-visual-bible').textContent=ref.flow_visual_direction ?? plan.visual_bible;
  const scenes=ref.flow_scenes || [];
  $('flow-clip-count').textContent=Object.keys(clips).length+' / '+scenes.length+' scene clips imported'+(ref.stale?' · Storyboard needs an update':'');
  const key=project.id+ref.plan_hash+JSON.stringify(clips);
  if(key===lastScenes)return;lastScenes=key;
  $('flow-scenes').innerHTML=scenes.map((scene,index)=>{
   const clip=clips[scene.id],end=Number(scene.start_seconds)+scene.duration_seconds;
   return '<article class="flow-scene" data-flow-scene="'+esc(scene.id)+'"><div class="flow-scene-heading"><div><span class="eyebrow">SCENE '+String(index+1).padStart(2,'0')+'</span><h4 dir="auto">'+esc(scene.title)+'</h4></div><span class="badge">'+(clip?'Clip imported':'Needs a clip')+'</span></div>'+
    '<p class="hint">'+Number(scene.start_seconds).toFixed(2)+'–'+end.toFixed(2)+'s · '+scene.duration_seconds.toFixed(2)+'s in your video · Generate '+scene.generation_seconds+'s · '+(scene.transition==='fade'?'Fade through black':'Cut')+'</p>'+
    '<p class="flow-continuity" dir="auto">'+esc(scene.continuity)+'</p>'+
    ['image','motion'].map(kind=>'<details><summary>'+(kind==='image'?'1. Create the scene image':'2. Animate in Flow')+'</summary><label class="field">'+(kind==='image'?'Scene image prompt':'Motion prompt')+'<textarea readonly rows="5" dir="auto" id="flow-'+scene.id+'-'+kind+'">'+esc(scene[kind+'_prompt'])+'</textarea></label><button type="button" class="outline small" data-flow-copy="'+kind+'">Copy '+kind+' prompt</button></details>').join('')+
    (clip?'<video controls muted playsinline preload="metadata" aria-label="Imported clip for scene '+(index+1)+'" src="'+esc(app.mediaUrl(clip.file,project.id))+'"></video><p class="hint">'+Number(clip.duration_seconds).toFixed(2)+'s source · '+Number(clip.width)+' × '+Number(clip.height)+(clip.width>=clip.height?' · Landscape clip; final edit crops to vertical':'')+'</p><div class="flow-trim"><label class="field">Start clip at second<input type="number" min="0" step="0.01" data-flow-offset value="'+Number(clip.offset_seconds || 0)+'"></label><button type="button" class="outline small" data-flow-trim>Apply trim</button></div>':'')+
    '<label class="field flow-import">'+(clip?'Replace Flow clip':'3. Import downloaded Flow clip')+'<input type="file" data-flow-import accept="video/mp4,video/webm,video/quicktime,.mkv"><small>Choose this scene’s downloaded clip. Previous takes stay in your media library.</small></label></article>';
  }).join('');
 }
 function lock(blocked){
  if(!app)return;
  const ref=app.getState().project?.reference_style;
  const busy=blocked || working;
  if(ref?.workflow==='flow'){
   $('add-section').disabled=true;
   for(const control of document.querySelectorAll('#sections [data-action="up"],#sections [data-action="down"],#sections [data-action="remove"],#sections [data-field="layout"],#sections [data-field="start_seconds"],#sections [data-field="start_phrase"]'))control.disabled=true;
  }
  const available=ref?.workflow==='flow' && Boolean(ref.flow_plan) && !ref.stale;
  for(const control of $('flow-workspace').querySelectorAll('button,input,textarea')){
   control.disabled=busy || (control.id!=='flow-draft' && control.id!=='flow-approve-script' && !available);
  }
  $('flow-build').disabled=busy || !available || !['ready','complete','render_failed'].includes(ref?.status);
 }
 $('reference-workflow').onchange=syncCreation;
 $('flow-story-source').onchange=syncCreation;
 $('reference-voice-source').addEventListener('change',syncCreation);
 $('flow-approve-script').onclick=()=>action(async()=>{
  const project=app.getState().project;
  const result=await app.api('/api/reference/flow/approve',{id:project.id,script:$('flow-draft').value});
  app.install(result);app.toast('Script approved. Add your voiceover, then prepare the Flow storyboard.');
 });
 $('flow-copy-bible').onclick=()=>action(async()=>{
  await navigator.clipboard.writeText(app.getState().project.reference_style.flow_visual_direction ?? app.getState().project.reference_style.flow_plan.visual_bible);app.toast('Shared visual direction copied.');
 });
 $('flow-download-pack').onclick=()=>action(async()=>{
  if(app.getState().dirty)await app.save();
  const pack=await app.api('/api/reference/flow/pack?id='+encodeURIComponent(app.getState().project.id));
  const link=document.createElement('a'),url=URL.createObjectURL(new Blob([pack.text],{type:'text/markdown;charset=utf-8'}));
  link.href=url;link.download=pack.filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
 });
 $('flow-scenes').addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  const card=button.closest('[data-flow-scene]'),scene=card.dataset.flowScene;
  if(button.dataset.flowCopy)action(async()=>{
   await navigator.clipboard.writeText($('flow-'+scene+'-'+button.dataset.flowCopy).value);app.toast('Flow '+button.dataset.flowCopy+' prompt copied.');
  });
  else if(button.hasAttribute('data-flow-trim'))action(async()=>{
   if(app.getState().dirty)await app.save();
   const p=app.getState().project,r=p.reference_style;
   const result=await app.api('/api/reference/flow/clip',{id:p.id,scene,file:r.flow_clips[scene].file,
    offset_seconds:Number(card.querySelector('[data-flow-offset]').value),plan_hash:r.plan_hash});
   app.install(result);app.toast('Clip trim saved.');
  });
 });
 $('flow-scenes').addEventListener('change',event=>{
  const input=event.target;if(!input.hasAttribute('data-flow-import') || !input.files[0])return;
  const file=input.files[0],scene=input.closest('[data-flow-scene]').dataset.flowScene;
  action(async()=>{
   if(file.size>4*1024**3)throw new Error('Choose a clip up to 4 GB.');
   if(app.getState().dirty)await app.save();
   const p=app.getState().project,r=p.reference_style;
   app.toast('Importing Flow clip...');
   const response=await fetch('/api/upload?id='+encodeURIComponent(p.id)+'&role=flow_clip&scene='+encodeURIComponent(scene)+'&plan_hash='+encodeURIComponent(r.plan_hash)+'&name='+encodeURIComponent(file.name),
    {method:'POST',headers:{'X-Studio-Token':app.getState().token},body:file});
   const result=await response.json();if(!response.ok)throw new Error(result.error || 'Clip import failed.');
   app.install(result.project);app.toast('Flow clip imported. Review its preview and trim point.');
  }).finally(()=>{input.value='';});
 });
 $('flow-build').onclick=()=>action(async()=>{
  await app.save();await window.VideoTurboVoice?.saveSelection();
  app.getState().job=await app.api('/api/start',{id:app.getState().project.id,action:'build'});app.showJob();
 });
 window.VideoTurboFlow={configure(options){app=options;syncCreation();},creation,syncCreation,update,lock};
})();
