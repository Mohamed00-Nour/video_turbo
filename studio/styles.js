(() => {
 'use strict';
 // Style Library: saved style breakdowns, their editor, and the picker in "Create from a reference".
 const $=id=>document.getElementById(id);
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const PALETTE=['background','background_end','contrast_background','ink','accent','muted'];
 const LIVE=['queued','analyzing'];
 const STATUS={awaiting_upload:'Needs a video',awaiting_analysis:'Ready to analyze',queued:'Queued',analyzing:'Analyzing',ready:'Ready',failed:'Needs attention',cancelled:'Cancelled',interrupted:'Interrupted'};
 let app,library={styles:[],fields:[],categories:{},layout_choices:{},layout_labels:{},layout_categories:{},max_styles:2,providers:{}};
 let editing='',working=false,timer=null,selected=[],mix={},providerReady=false;
 const reference=()=>window.VideoTurboReference;
 const live=style=>LIVE.includes(style.status);
 const usable=style=>Boolean(style.profile) && !live(style);
 function message(id,text){$(id).textContent=text;$(id).hidden=!text;}

 async function load(){
  library=await app.api('/api/styles');
  render();renderPicker();schedule();
 }
 function schedule(){
  clearTimeout(timer);
  if(library.styles.some(live) && ($('style-library-dialog').open || $('reference-dialog').open))timer=setTimeout(()=>load().catch(()=>{}),2500);
 }
 function refresh(result){if(result?.styles){library=result;render();renderPicker();schedule();}}
 async function action(fn,errorId='style-library-error'){
  if(working || app.getState().busy)return;
  working=true;app.lockControls();message(errorId,'');
  try{await fn();}catch(error){message(errorId,error.message);app.toast(error.message,true);}
  finally{working=false;app.lockControls();}
 }
 async function upload(id,file,role){
  const response=await fetch('/api/styles/upload?id='+encodeURIComponent(id)+'&name='+encodeURIComponent(file.name)+'&role='+role,
   {method:'POST',headers:{'X-Studio-Token':app.getState().token},body:file});
  const result=await response.json();if(!response.ok)throw new Error(result.error || 'Upload failed.');
  return result.style;
 }

 // Analysis provider shared by new styles and "Analyze again".
 async function fillProvider(refresh=false){
  const provider=$('style-provider').value,api=reference();
  $('style-model-label').textContent=api?.modelLabel(provider) || 'Model';
  const settings=(!refresh && api?.settings()) || await app.api('/api/reference/settings');
  const saved=settings?.providers?.[provider];
  const preferred=saved?.model ?? (api?.blankDefault(provider)?'':undefined);
  providerReady=Boolean(saved?.installed);
  if(!providerReady){$('style-model').replaceChildren(new Option('Local CLI not found',''));$('style-model-status').textContent='The '+(api?.providerName(provider) || provider)+' CLI was not found. Install it and sign in, or choose another provider.';app.lockControls();return;}
  return api.loadModels('style-model',provider,preferred,refresh);
 }
 function analysisChoice(){
  if(!reference()?.modelReady('style-model'))throw new Error('Choose an available model for the style analysis.');
  return {provider:$('style-provider').value,model:$('style-model').value};
 }

 function swatches(profile){
  const a=profile?.analysis;if(!a)return '';
  return `<div class="reference-palette" aria-label="Style colors">${PALETTE.filter(k=>a[k]).map(k=>`<span class="reference-swatch"><i style="background:${esc(a[k])}" aria-hidden="true"></i>${esc(a[k])}</span>`).join('')}</div>`;
 }
 function breakdown(profile){
  const a=profile.analysis,l=profile.layouts,join=rows=>rows.join(', ');
  const rows=[['Fonts',a.heading_font+(a.italic?', italic':'')],
   ['Motion',a.entrance+' entrance, floats '+a.float_amplitude+'px, corners '+a.card_radius],
   ['Transitions',a.transition+'; between scenes: '+join(l.transition_style)],
   ['Captions',(a.caption_style==='word'?'word by word':'short phrases')+' at '+Math.round(a.caption_y*100)+'% height'],
   ['Layouts',join(l.variants)+'; backdrops: '+join(l.backdrops)]];
  return `<dl class="style-breakdown">${rows.map(([k,v])=>`<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>`;
 }
 function preview(style){
  if(style.thumbnail)return `<img class="style-thumb" src="/api/styles/thumbnail?id=${esc(style.id)}&v=${esc(style.updated)}" alt="">`;
  const a=style.profile?.analysis;
  if(!a)return '<div class="style-thumb style-thumb-empty style-thumb-missing" aria-hidden="true">No preview yet</div>';
  return `<div class="style-thumb style-thumb-empty" aria-hidden="true" style="background:linear-gradient(160deg,${esc(a.background)},${esc(a.background_end)});color:${esc(a.ink)}">Aa</div>`;
 }
 function card(style){
  const job=style.job,profile=style.profile;
  const by=style.provider?(library.providers[style.provider] || style.provider)+(style.model?' ('+style.model+')':''):'';
  const actions=[
   profile && !live(style)?`<button type="button" class="outline small" data-style-action="edit">${editing===style.id?'Close editor':'Edit'}</button>`:'',
   style.has_source && !live(style)?`<button type="button" class="quiet small" data-style-action="analyze">${profile?'Analyze again':'Analyze'}</button>`:'',
   !style.has_source && !live(style)?`<label class="quiet small style-upload">Upload reference video<input type="file" data-style-upload accept="video/mp4,video/webm,video/quicktime,.mkv"></label>`:'',
   job?`<button type="button" class="quiet small" data-style-action="cancel" data-job="${esc(job.id)}" ${job.status==='cancelling'?'disabled':''}>Cancel analysis</button>`:'',
   !live(style)?`<button type="button" class="quiet small danger" data-style-action="delete">Delete</button>`:'',
  ].join('');
  return `<article class="style-card" data-style="${esc(style.id)}">${preview(style)}<div class="style-body">
   <div class="style-title"><h3 dir="auto">${esc(style.name)}</h3><span class="badge">${esc(STATUS[style.status] || style.status)}</span></div>
   ${job?`<p class="hint" role="status">${esc(job.stage)}</p><progress max="100" value="${Number(job.progress)||0}" aria-label="Analysis progress"></progress>`:''}
   ${style.error?`<p class="brief-error" role="alert">${esc(style.error)}</p>`:''}
   ${profile?`<p class="hint" dir="auto">${esc(profile.analysis.summary)}</p>${swatches(profile)}${breakdown(profile)}${profile.layouts.notes?`<details><summary>Style notes</summary><p dir="auto">${esc(profile.layouts.notes)}</p></details>`:''}`:''}
   ${by || style.origin==='project'?`<p class="style-meta">${style.origin==='project'?'Saved from a project':(profile?'Analyzed by ':'Will be analyzed by ')+esc(by)}${style.edited?' · edited':''}${style.screens?' · '+style.screens+' screenshot'+(style.screens>1?'s':''):''}</p>`:''}
   <div class="style-actions">${actions}</div>
   ${editing===style.id && profile?editor(style):''}</div></article>`;
 }
 function render(){
  $('style-list').innerHTML=library.styles.length?library.styles.map(card).join(''):'<p class="hint">No saved styles yet. Add a reference video above to create your first style.</p>';
  app?.lockControls();
 }

 // Editor: every category value of the breakdown can be changed.
 function input(field,value){
  const optional=field.optional?`<label class="style-include"><input type="checkbox" data-include="${field.key}" ${value!==undefined?'checked':''}> Use</label>`:'';
  const attrs=`data-field="${field.key}"`;
  let control;
  if(field.type==='color')control=`<input type="color" ${attrs} value="${esc(value || '#888888')}">`;
  else if(field.type==='bool')control=`<input type="checkbox" ${attrs} ${value?'checked':''}>`;
  else if(field.type==='choice')control=`<select ${attrs}>${field.choices.map(choice=>`<option value="${esc(choice)}" ${choice===value?'selected':''}>${esc(choice)}</option>`).join('')}</select>`;
  else control=`<input type="number" ${attrs} min="${field.min}" max="${field.max}" step="${field.step}" value="${esc(value ?? field.min)}" required>`;
  return `<label class="field style-field style-field-${field.type}"><span>${esc(field.label)}</span><span class="style-control">${control}${optional}</span></label>`;
 }
 function editor(style){
  const a=style.profile.analysis,l=style.profile.layouts;
  const groups=Object.entries(library.categories).map(([category,title])=>{
   const fields=library.fields.filter(field=>field.category===category).map(field=>input(field,a[field.key])).join('');
   const lists=Object.entries(library.layout_categories).filter(([,owner])=>owner===category).map(([key])=>
    `<fieldset class="style-multi"><legend>${esc(library.layout_labels[key])}</legend>${library.layout_choices[key].map(choice=>
     `<label><input type="checkbox" data-layout="${key}" value="${esc(choice)}" ${l[key].includes(choice)?'checked':''}> ${esc(choice)}</label>`).join('')}</fieldset>`).join('');
   return `<fieldset class="style-group"><legend>${esc(title)}</legend>${fields}${lists}</fieldset>`;
  }).join('');
  return `<form class="style-editor" data-editor="${esc(style.id)}">
   <label class="field">Style name<input data-name value="${esc(style.name)}" maxlength="80" required dir="auto"></label>
   <label class="field">Summary<textarea data-summary rows="2" maxlength="2000" required dir="auto">${esc(a.summary)}</textarea></label>
   ${groups}
   <label class="field">Style notes<textarea data-notes rows="2" maxlength="2000" dir="auto">${esc(l.notes)}</textarea></label>
   <div class="dialog-actions"><button type="button" class="quiet" data-style-action="edit">Cancel</button><button class="primary">Save style</button></div></form>`;
 }
 function readEditor(form,style){
  const analysis={...style.profile.analysis,summary:form.querySelector('[data-summary]').value.trim()};
  for(const field of library.fields){
   const control=form.querySelector(`[data-field="${field.key}"]`),include=form.querySelector(`[data-include="${field.key}"]`);
   if(include && !include.checked){delete analysis[field.key];continue;}
   analysis[field.key]=field.type==='number'?Number(control.value):field.type==='bool'?control.checked:control.value;
  }
  const layouts={notes:form.querySelector('[data-notes]').value};
  for(const key of Object.keys(library.layout_choices)){
   const before=style.profile.layouts[key] || [];
   const chosen=[...form.querySelectorAll(`[data-layout="${key}"]:checked`)].map(box=>box.value);
   // Keep the analysed preference order; newly ticked options go last.
   layouts[key]=chosen.sort((x,y)=>(before.includes(x)?before.indexOf(x):99)-(before.includes(y)?before.indexOf(y):99));
   if(!layouts[key].length)throw new Error('Choose at least one option for '+library.layout_labels[key].toLowerCase()+'.');
  }
  return {id:style.id,name:form.querySelector('[data-name]').value,profile:{analysis,layouts}};
 }

 $('style-list').addEventListener('click',event=>{
  const button=event.target.closest('[data-style-action]');if(!button)return;
  const id=button.closest('[data-style]').dataset.style,style=library.styles.find(row=>row.id===id),kind=button.dataset.styleAction;
  if(kind==='edit'){editing=editing===id?'':id;render();return;}
  if(kind==='analyze')action(async()=>{refresh(await app.api('/api/styles/analyze',{id,...analysisChoice()}));app.toast('Analyzing "'+style.name+'". You can keep working.');});
  if(kind==='cancel')action(async()=>{await app.api('/api/cancel',{job_id:button.dataset.job});await load();});
  if(kind==='delete' && confirm('Delete the style "'+style.name+'"? Videos already made with it keep their copy.'))
   action(async()=>{refresh(await app.api('/api/styles/delete',{id,confirmed:true}));app.toast('Style deleted.');});
 });
 $('style-list').addEventListener('change',event=>{
  const picker=event.target.closest('[data-style-upload]');if(!picker || !picker.files[0])return;
  const id=picker.closest('[data-style]').dataset.style;
  action(async()=>{await upload(id,picker.files[0],'reference');await load();app.toast('Reference video added. Click Analyze to break down the style.');});
 });
 $('style-list').addEventListener('submit',event=>{
  const form=event.target.closest('[data-editor]');if(!form)return;
  event.preventDefault();
  const style=library.styles.find(row=>row.id===form.dataset.editor);
  action(async()=>{const values=readEditor(form,style);editing='';refresh(await app.api('/api/styles/update',values));app.toast('Style saved.');});
 });
 $('style-add-form').onsubmit=event=>{event.preventDefault();action(async()=>{
  const file=$('style-file').files[0],screens=[...$('style-screens').files];
  if(!file)throw new Error('Choose a reference video.');
  if(screens.length>6)throw new Error('Add up to 6 screenshots.');
  if([file,...screens].some(item=>item.size>4*1024**3))throw new Error('Choose media files up to 4 GB each.');
  const choice=analysisChoice();
  const created=await app.api('/api/styles/create',{name:$('style-name').value,...choice});
  app.toast('Uploading '+file.name+'...');
  await upload(created.style.id,file,'reference');
  for(const screen of screens)await upload(created.style.id,screen,'screen');
  refresh(await app.api('/api/styles/analyze',{id:created.style.id}));
  $('style-add-form').reset();$('style-add').open=false;
  app.toast('Analyzing your style. You can keep working while it runs.');
 },'style-add-error');};
 $('style-provider').onchange=()=>fillProvider().catch(error=>message('style-library-error',error.message));
 $('style-model').onchange=()=>app.lockControls();
 $('style-model-refresh').onclick=()=>fillProvider(true).catch(error=>message('style-library-error',error.message));
 $('styles-open').onclick=()=>open();
 $('style-library-close').onclick=()=>$('style-library-dialog').close();
 $('style-library-dialog').addEventListener('close',()=>{renderPicker();schedule();});
 async function open(){
  editing='';message('style-library-error','');$('style-library-dialog').showModal();
  try{await load();await fillProvider();}catch(error){message('style-library-error',error.message || 'This Studio server needs an update. Relaunch Video Turbo.');}
 }

 // Picker inside "Create from a reference" (Video Turbo animation only).
 function names(){return selected.map(id=>library.styles.find(row=>row.id===id)?.name || 'Style');}
 function renderPicker(){
  const ready=library.styles.filter(usable);
  selected=selected.filter(id=>ready.some(row=>row.id===id));
  const full=selected.length>=library.max_styles;
  $('reference-style-options').innerHTML=ready.length?ready.map(style=>{
   const index=selected.indexOf(style.id),a=style.profile.analysis;
   return `<label class="style-option ${index>=0?'selected':''}"><input type="checkbox" value="${esc(style.id)}" ${index>=0?'checked':''} ${index<0 && full?'disabled':''}>
    <span class="style-option-colors" aria-hidden="true">${['background','ink','accent'].map(k=>`<i style="background:${esc(a[k])}"></i>`).join('')}</span>
    <span dir="auto">${esc(style.name)}</span>${index>=0 && selected.length>1?`<b class="badge">Style ${'AB'[index]}</b>`:''}</label>`;
  }).join(''):'<p class="hint">No saved styles yet. Open the style library to add one.</p>';
  const [first,second]=names();
  $('reference-style-mix-rows').innerHTML=Object.entries(library.categories).map(([key,title])=>`<label class="field">${esc(title)}<select data-mix="${key}">
   <option value="mix" ${(mix[key] || 'mix')==='mix'?'selected':''}>AI mix</option><option value="a" ${mix[key]==='a'?'selected':''}>Style A · ${esc(first)}</option><option value="b" ${mix[key]==='b'?'selected':''}>Style B · ${esc(second)}</option></select></label>`).join('');
  $('reference-style-mix').hidden=selected.length<2;
  syncCreation();
 }
 function syncCreation(){
  const animation=$('reference-workflow').value==='reference',using=animation && selected.length>0;
  $('reference-style-picker').hidden=!animation;
  $('reference-file-field').hidden=using;$('reference-file').required=!using;
  $('reference-style-hint').textContent=!using?'Choose up to 2 saved styles, or leave empty and upload a one-off reference video below.':
   selected.length>1?'Two styles chosen. Choose how to combine them below.':'This saved style will be applied to your new video.';
 }
 $('reference-style-options').addEventListener('change',event=>{
  const box=event.target.closest('input[type="checkbox"]');if(!box)return;
  selected=box.checked?[...selected,box.value].slice(0,library.max_styles):selected.filter(id=>id!==box.value);
  renderPicker();
 });
 $('reference-style-mix-rows').addEventListener('change',event=>{const row=event.target.closest('[data-mix]');if(row)mix[row.dataset.mix]=row.value;});
 $('reference-workflow').addEventListener('change',syncCreation);
 $('reference-style-library').onclick=()=>open();

 window.VideoTurboStyles={
  configure(options){app=options;load().catch(()=>{});},
  refresh,
  async openCreation(){
   selected=[];mix={};
   try{
    await load();
    // Saved styles belong to Video Turbo animation; start there when some are ready.
    if(library.styles.some(usable)){$('reference-workflow').value='reference';window.VideoTurboFlow?.syncCreation();}
   }catch{library.styles=[];}
   renderPicker();
  },
  syncCreation,
  selection(){
   if($('reference-workflow').value!=='reference' || !selected.length)return {styles:[],mix:{}};
   return {styles:[...selected],mix:selected.length>1?Object.fromEntries(Object.keys(library.categories).map(key=>[key,mix[key] || 'mix'])):{}};
  },
  mixSummary(choice,styles){
   if(!styles || styles.length<2 || !choice)return '';
   const fixed=Object.entries(choice).filter(([,value])=>value!=='mix');
   if(!fixed.length)return 'AI mixes every category.';
   return fixed.map(([key,value])=>(library.categories[key] || key)+' from '+(value==='a'?'A':'B')).join(', ')+'; AI mixes the rest.';
  },
  lock(busy){
   if(!app)return;
   const stop=busy || working;
   for(const element of document.querySelectorAll('#style-library-dialog button, #style-library-dialog input, #style-library-dialog select, #style-library-dialog textarea')){
    if(element.id==='style-library-close')continue;
    element.disabled=stop;
   }
   const needsModel=!providerReady || !reference()?.modelReady('style-model');
   $('style-add-submit').disabled=stop || needsModel;
   $('style-model').disabled=stop || !providerReady || Boolean(reference()?.modelLoading('style-model'));
   document.querySelectorAll('[data-style-action="analyze"]').forEach(button=>{button.disabled=stop || needsModel;});
  },
 };
})();
