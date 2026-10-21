
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const {bundle}=require('../node_modules/@remotion/bundler');
const {openBrowser,selectComposition,renderStill}=require('../node_modules/@remotion/renderer');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'output/pc-tips-review'),publicDir=path.join(out,'public');
(async()=>{
 fs.mkdirSync(publicDir,{recursive:true});
 execFileSync('python',['-c',"from PIL import Image,ImageDraw; from pathlib import Path; p=Path(r'"+publicDir+"'); im=Image.new('RGB',(1024,1536),'#172b42'); d=ImageDraw.Draw(im); d.rectangle((180,350,850,880),fill='#06121c',outline='#66e1ff',width=8); d.rectangle((510,880,530,1030),fill='#667788'); d.rectangle((100,1030,930,1070),fill='#8b6850'); im.save(p/'setup.png')"]);
 execFileSync('ffmpeg',['-y','-v','error','-f','lavfi','-i','testsrc2=s=1280x720:r=30:d=1','-an','-c:v','libx264','-pix_fmt','yuv420p',path.join(publicDir,'screen.mp4')]);
 const serveUrl=await bundle({entryPoint:path.join(__dirname,'pc-tips.fixture.tsx'),publicDir,outDir:path.join(out,'bundle')});
 const browser=await openBrowser('chrome',{logLevel:'error'});
 try{
  for(const [id,frames] of [['PcIntroFixture',[0,20,59]],['PcDemoFixture',[0,45,89]]]){
   const composition=await selectComposition({serveUrl,id,puppeteerInstance:browser,logLevel:'error'});
   assert.equal(composition.width,1080);assert.equal(composition.height,1920);
   for(const frame of frames)await renderStill({serveUrl,composition,frame,puppeteerInstance:browser,output:path.join(out,id+'-'+frame+'.png'),scale:.5,logLevel:'error'});
  }
  const page=await browser.newPage({context:()=>null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
  await page.setViewport({width:1440,height:1100,deviceScaleFactor:1});
  await page.goto({url:'http://127.0.0.1:8772',timeout:30000});
  await page.evaluate(async()=>{
   for(let i=0;i<100&&!document.getElementById('pc-new');i++)await new Promise(r=>setTimeout(r,50));
   document.getElementById('pc-new').click();
   for(let i=0;i<100&&!document.getElementById('pc-script-model').value;i++)await new Promise(r=>setTimeout(r,50));
  });
  let ui=await page.evaluate(()=>({open:document.getElementById('pc-dialog').open,next:document.getElementById('pc-next').textContent,
   googleModel:document.getElementById('pc-google-model').value,model:document.getElementById('pc-script-model').value,auto:document.getElementById('pc-auto').checked,
   visual:document.getElementById('pc-visual').value,modes:Array.from(document.getElementById('pc-visual').options).map(o=>o.textContent),realMethodHidden:document.getElementById('pc-recording-field').hidden,
   category:document.getElementById('pc-category').value,types:Array.from(document.getElementById('pc-category').options).map(o=>o.value),
   noIdea:!document.getElementById('pc-idea'),voice:document.getElementById('pc-voice').value,recording:document.getElementById('pc-recording').value,
   preferencesClosed:!document.getElementById('pc-production').open,runner:document.getElementById('pc-runner').checked,noApiKey:!document.getElementById('pc-api-key'),connection:document.getElementById('pc-connection').textContent,width:document.documentElement.scrollWidth,viewport:innerWidth}));
  assert(ui.open);assert(ui.next.includes('Part'));assert.equal(ui.model,'gpt-6.1-sol');assert.equal(ui.googleModel,'gemini-3.8-flash-high');assert.equal(ui.auto,true);assert.equal(ui.runner,false);assert.equal(ui.noApiKey,true);assert(ui.connection.includes('ChatGPT'));assert(ui.width<=ui.viewport);
  assert.equal(ui.visual,'illustrated');assert.equal(ui.modes.length,2);assert(ui.realMethodHidden);
  assert(ui.noIdea);assert.equal(ui.category,'auto');assert.equal(ui.types.length,6);assert.equal(ui.voice,'elevenlabs');assert.equal(ui.recording,'automatic');assert(ui.preferencesClosed);
  const screenshot=await page._client().send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,'studio-dialog.png'),Buffer.from((screenshot.value || screenshot).data,'base64'));
  await page.setViewport({width:375,height:812,deviceScaleFactor:1});
  const mobile=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth,dialog:document.getElementById('pc-dialog').getBoundingClientRect().width}));
  assert(mobile.width<=mobile.viewport);assert(mobile.dialog<=mobile.viewport);
  const small=await page._client().send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,'studio-mobile.png'),Buffer.from((small.value || small).data,'base64'));
  const googleSettings=await page.evaluate(()=>{
   document.getElementById('pc-settings').open=true;
   document.getElementById('pc-google-model').scrollIntoView({block:'center'});
   return {width:document.documentElement.scrollWidth,viewport:innerWidth,policy:document.getElementById('pc-settings').textContent,
    google:document.getElementById('pc-google-model').value,fallback:document.getElementById('pc-script-model').value};
  });
  assert(googleSettings.width<=googleSettings.viewport);assert(googleSettings.policy.includes('Google first:'));assert(googleSettings.policy.includes('Flow is not connected'));
  const settingsShot=await page._client().send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,'google-settings-mobile.png'),Buffer.from((settingsShot.value||settingsShot).data,'base64'));
  await page.evaluate(()=>{document.getElementById('pc-settings').open=false;});
  const submitted=await page.evaluate(async()=>{
   const actualFetch=window.fetch;let captured=null;
   window.fetch=async(input,options)=>{
    if(String(input).includes('/api/pc-tips/create')){captured=JSON.parse(options.body);return new Response(JSON.stringify({error:'UI test intercepted generation'}),{status:400,headers:{'Content-Type':'application/json'}});}
    return actualFetch(input,options);
   };
   try{
    const type=document.getElementById('pc-category');type.value='performance';type.dispatchEvent(new Event('change'));
    document.getElementById('pc-form').requestSubmit();
    for(let i=0;i<100&&!captured;i++)await new Promise(r=>setTimeout(r,25));
    return captured;
   }finally{window.fetch=actualFetch;}
  });
  assert(submitted);assert.equal(submitted.recording_mode,'illustrated');assert.equal(submitted.category,'performance');assert(!('idea' in submitted));assert.equal(submitted.name,'');assert.equal(submitted.auto_produce,true);
  const realOptions=await page.evaluate(()=>{
   const visual=document.getElementById('pc-visual');visual.value='real';visual.dispatchEvent(new Event('change'));
   return {methodHidden:document.getElementById('pc-recording-field').hidden,methods:Array.from(document.getElementById('pc-recording').options).map(o=>o.value),
    note:document.getElementById('pc-visual-note').textContent,automation:document.getElementById('pc-automation-note').textContent};
  });
  assert(!realOptions.methodHidden);assert.deepEqual(realOptions.methods,['automatic','upload']);assert(realOptions.note.includes('dedicated'));assert(realOptions.automation.includes('Windows recording'));
  await page._client().send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await page.setViewport({width:812,height:375,deviceScaleFactor:1});
  const landscape=await page.evaluate(()=>{
   document.documentElement.dataset.theme='dark';document.documentElement.style.fontSize='200%';
   const button=document.getElementById('pc-create');button.scrollIntoView({block:'center'});
   const rect=button.getBoundingClientRect(),dialog=document.getElementById('pc-dialog').getBoundingClientRect();
   const color=value=>value.match(/[0-9.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4);}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
   const foreground=color(getComputedStyle(document.getElementById('pc-category-note')).color),background=color(getComputedStyle(document.getElementById('pc-dialog')).backgroundColor);
   return {width:document.documentElement.scrollWidth,viewport:innerWidth,dialogWidth:dialog.width,buttonVisible:rect.top>=dialog.top&&rect.bottom<=dialog.bottom,reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches,hintContrast:(Math.max(foreground,background)+.05)/(Math.min(foreground,background)+.05)};
  });
  assert(landscape.width<=landscape.viewport);assert(landscape.dialogWidth<=landscape.viewport);assert(landscape.buttonVisible);assert(landscape.reducedMotion);assert(landscape.hintContrast>=4.5);
  const episode=await page.evaluate(async()=>{
   document.getElementById('pc-dialog').close();
   const project={id:'episode-mode-fixture',editor:{script:'A saved tutorial'},pc_tips:{part:2,theme:{name:'Bright minimal'},recording_mode:'automatic',status:'awaiting_runner',error:'',
    plan:{os:'Windows 10 & 11',requirements:['Use a test document'],sources:[],
     problem:{title:'Left click opens a menu',os:'Windows 10 & 11',narration:'The symptom',goal:'Click a test document',
      capture_instructions:['اضغط كليك شمال على الملف التجريبي.','ثبّت قائمة الاختصارات اللي ظهرت لمدة ثلاث ثواني.'],verification:'A context menu is visible'},
     steps:[{title:'Windows 10 fix',os:'Windows 10',goal:'Settings > Devices > Mouse',capture_instructions:['افتح Settings > Devices > Mouse.'],verification:'Left is selected'},
      {title:'Windows 11 fix',os:'Windows 11',goal:'Settings > Bluetooth & devices > Mouse',capture_instructions:['افتح Settings > Bluetooth & devices > Mouse.'],verification:'Left click selects normally'}]}}};
   const state={token:'fixture',project,dirty:false,busy:false,job:null};
   let captured=null;
   const saveVoice=window.VideoTurboVoice.saveSelection;
   window.VideoTurboVoice.saveSelection=async()=>{};
   window.VideoTurboPcTips.configure({getState:()=>state,save:async()=>{},refreshState:async()=>{},
    api:async(route,value)=>{
     if(route==='/api/pc-tips/start'){captured=value;return {project,job:{status:'complete'}};}
     return (await fetch(route)).json();
    },
    install:()=>{},showJob:()=>{},toast:()=>{},lockControls:()=>window.VideoTurboPcTips.lock(),mediaUrl:file=>file
   });
   try{
    window.VideoTurboPcTips.update(project);
    const visual=document.getElementById('pc-episode-visual');
    const startedReal=visual.value==='real'&&!document.getElementById('pc-episode-recording-field').hidden;
    const checklist=Array.from(document.querySelectorAll('#pc-capture-list>li')).map(item=>item.textContent);
    visual.value='illustrated';visual.dispatchEvent(new Event('change'));
    const uploadHidden=document.getElementById('pc-recording-upload').hidden;
    document.getElementById('pc-continue').click();
    for(let i=0;i<100&&!captured;i++)await new Promise(r=>setTimeout(r,25));
    return {startedReal,uploadHidden,captured,checklist};
   }finally{window.VideoTurboVoice.saveSelection=saveVoice;}
  });
  assert(episode.checklist[0].includes('Left click opens a menu'));assert(episode.checklist[1].includes('Settings > Devices > Mouse'));assert(episode.checklist[2].includes('Bluetooth & devices'));
  assert(episode.startedReal);assert(episode.uploadHidden);assert.equal(episode.captured.recording_mode,'illustrated');
  await page.setViewport({width:1440,height:1100,deviceScaleFactor:1});
  await page.evaluate(()=>{
   document.documentElement.style.fontSize='';
   document.getElementById('workspace').hidden=false;document.getElementById('empty').hidden=true;
   const visual=document.getElementById('pc-episode-visual');visual.value='real';visual.dispatchEvent(new Event('change'));
   document.getElementById('pc-capture-guide').scrollIntoView({block:'start'});
  });
  const guideShot=await page._client().send('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,'recording-guide.png'),Buffer.from((guideShot.value||guideShot).data,'base64'));
  await page.setViewport({width:375,height:812,deviceScaleFactor:1});
  const guideLayout=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth,visible:!document.getElementById('pc-recording-upload').hidden}));
  assert(guideLayout.width<=guideLayout.viewport);assert(guideLayout.visible);
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({status:'passed',ui,mobile,googleSettings,submitted,realOptions,landscape,episode,guideLayout},null,2));
  console.log('Passed: intro and tutorial frame renders, last-frame playback, automatic type-only submission, saved production defaults, and desktop/mobile overflow checks.');
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
