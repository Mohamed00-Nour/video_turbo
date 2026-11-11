(() => {
 'use strict';
 // Recreate a video's idea: creation fields, the source breakdown and the script approval step.
 const $=id=>document.getElementById(id);
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const WORDS_PER_SECOND=2.4;
 let app,working=false,draftKey='';
 const chosen=()=>$('reference-workflow').value==='reference' && $('reference-story-source').value==='recreate';

 function syncCreation(){
  window.VideoTurboFlow?.syncCreation();
  const animation=$('reference-workflow').value==='reference',on=chosen();
  $('reference-story-source-field').hidden=!animation;
  $('recreate-fields').hidden=!on;
  if(!animation)return;
  $('reference-script-field').hidden=on;$('reference-script').required=!on;
  const upload=$('reference-voice-source').value==='upload';
  $('reference-voice-upload').hidden=!upload || on;$('reference-voice').required=upload && !on;
  if(on)$('reference-voice-source-note').textContent='Approve your new script first. Then record it, or generate it with ElevenLabs in the project.';
 }
 function creation(){
  if(!chosen())return null;
  const file=$('recreate-file').files[0],url=$('recreate-url').value.trim(),seconds=$('recreate-seconds').value;
  if(!file && !url)throw new Error('Add the source video or its YouTube link.');
  if(!window.VideoTurboStyles?.selection().styles.length)throw new Error('Choose at least one saved style for the recreated video.');
  return {file,options:{url:file?'':url,language:$('recreate-language').value.trim(),target_seconds:seconds===''?null:Number(seconds)}};
 }

 function count(){
  const words=$('recreate-draft').value.trim().split(/\s+/).filter(Boolean).length;
  $('recreate-draft-count').textContent=words+' words, about '+Math.round(words/WORDS_PER_SECOND)+' seconds when spoken.';
 }
 function update(project){
  const ref=project?.reference_style,source=ref?.recreate;
  $('recreate-panel').hidden=!source;
  if(!source)return;
  $('recreate-source-name').textContent=source.source_file?'Source video: '+source.source_file.split('/').pop():source.source_url?'Source link: '+source.source_url:'Add the source video to recreate.';
  const breakdown=source.breakdown;
  $('recreate-breakdown').hidden=!breakdown;
  if(breakdown){
   $('recreate-summary').textContent=(breakdown.title?breakdown.title+'. ':'')+breakdown.summary;
   $('recreate-points').innerHTML=breakdown.points.map(point=>`<li><strong>${Number(point.time_seconds).toFixed(0)}s</strong> <bdi>${esc(point.idea)}</bdi><span>Shows: <bdi>${esc(point.visual)}</bdi></span></li>`).join('');
   $('recreate-notes').hidden=!source.notes;$('recreate-notes').textContent=source.notes?'Check before recording: '+source.notes:'';
   if(ref.status==='script_review')$('recreate-breakdown').open=true;
  }
  const review=ref.status==='script_review';
  $('recreate-review').hidden=!review;
  if(review){
   const key=project.id+'|'+(ref.draft_script || '');
   if(key!==draftKey){draftKey=key;$('recreate-draft').value=ref.draft_script || '';}
   count();
  }
 }
 async function action(fn){
  if(!app || working || app.getState().busy)return;
  working=true;app.getState().busy=true;app.lockControls();
  try{await fn();}catch(error){app.toast(error.message,true);}finally{working=false;app.getState().busy=false;app.lockControls();}
 }
 $('recreate-draft').addEventListener('input',()=>{count();app?.lockControls();});
 $('recreate-approve').onclick=()=>action(async()=>{
  const project=await app.api('/api/reference/recreate/approve',{id:app.getState().project.id,script:$('recreate-draft').value});
  app.install(project);app.toast('Script approved. Add your voiceover, then click Analyze & plan scenes.');
 });
 $('recreate-replace').onchange=()=>action(async()=>{
  const file=$('recreate-replace').files[0];$('recreate-replace').value='';if(!file)return;
  const p=app.getState().project;
  const response=await fetch('/api/upload?id='+p.id+'&name='+encodeURIComponent(file.name)+'&role=source',{method:'POST',headers:{'X-Studio-Token':app.getState().token},body:file});
  const result=await response.json();if(!response.ok)throw new Error(result.error || 'Upload failed.');
  app.install(result.project);app.toast('Source video replaced.');
 });
 for(const id of ['reference-story-source','reference-workflow','reference-voice-source'])$(id).addEventListener('change',syncCreation);

 window.VideoTurboRecreate={
  configure(options){app=options;syncCreation();},
  syncCreation,creation,update,
  drafting:project=>Boolean(project?.reference_style?.recreate && !project.editor.script.trim()),
  hasSource:project=>Boolean(project?.reference_style?.recreate?.source_file || project?.reference_style?.recreate?.source_url),
  lock(busy){
   if(!app)return;
   $('recreate-approve').disabled=busy || working || !$('recreate-draft').value.trim();
   $('recreate-replace').disabled=busy || working;
  },
 };
})();
