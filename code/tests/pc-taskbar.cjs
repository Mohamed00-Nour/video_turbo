const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),Module=require('node:module');
const React=require('../node_modules/react');
const {renderToStaticMarkup}=require('../node_modules/react-dom/server');
const {build}=require('../node_modules/esbuild');
const {bundle}=require('../node_modules/@remotion/bundler');
const {openBrowser,selectComposition,renderStill}=require('../node_modules/@remotion/renderer');
const out=path.resolve(__dirname,'../../output/pc-tips-review/taskbar');
const desktop=state=>({surface:'desktop',title:'Desktop',path:['Desktop'],rows:[{label:'Recycle Bin',value:''}],
 focus:0,action:'move_pointer',keys:[],note:'Move away from the taskbar and check the result.',taskbar_auto_hide:state});
const toggle={surface:'settings',title:'Taskbar',path:['Settings','Personalization','Taskbar'],
 rows:[{label:'Automatically hide the taskbar in desktop mode',value:'Off'}],focus:0,action:'toggle_off',
 keys:[],note:'Turn off auto-hide in desktop mode.',taskbar_auto_hide:'on'};
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const built=await build({entryPoints:[path.join(__dirname,'../src/PcWalkthrough.tsx')],
  bundle:true,platform:'node',packages:'external',write:false,loader:{'.css':'empty','.jpg':'dataurl'}});
 const mod=new Module(path.join(__dirname,'taskbar-check.cjs'));
 mod.filename=path.join(__dirname,'taskbar-check.cjs');mod.paths=module.paths;
 const remotion=require('../node_modules/remotion');
 let frame=0;
 const originalRequire=mod.require.bind(mod);
 mod.require=id=>id==='remotion'?{...remotion,useCurrentFrame:()=>frame,
  useVideoConfig:()=>({durationInFrames:150,fps:30}),registerRoot:()=>{},
  AbsoluteFill:props=>React.createElement('div',props),Img:props=>React.createElement('img',props)}:originalRequire(id);
 mod._compile(built.outputFiles[0].text,mod.filename);
 const browser=await openBrowser('chrome',{logLevel:'error'});
 try{
  const page=await browser.newPage({context:()=>null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
  await page.setViewport({width:1024,height:960,deviceScaleFactor:1});
  async function inspect(scene,at){
   frame=at;
   const html=renderToStaticMarkup(React.createElement(mod.exports.PcWalkthrough,{os:'Windows 10',frames:150,scenes:[scene]}));
   await page.goto({url:'data:text/html;charset=utf-8,'+encodeURIComponent('<body style="margin:0">'+html+'</body>'),timeout:30000});
   return page.evaluate(()=>{
    const desktop=document.querySelector('[data-win10-desktop]').getBoundingClientRect();
    const bar=document.querySelector('[data-win10-taskbar]'),bounds=bar.getBoundingClientRect();
    const cursor=document.querySelector('[data-win10-cursor]');
    return {visible:Math.min(bounds.bottom,desktop.bottom-1)-Math.max(bounds.top,desktop.top+1),
     offset:parseFloat(getComputedStyle(bar).bottom),state:bar.getAttribute('data-auto-hide'),
     cursor:cursor?{x:parseFloat(cursor.style.left),y:parseFloat(cursor.style.top)}:null,
     toggles:[...document.querySelectorAll('[data-win10-toggle]')].map(el=>el.getAttribute('data-win10-toggle'))};
   });
  }
  for(const at of [0,18,27,32,36,60,120,149]){
   const before=await inspect(desktop('on'),at),after=await inspect(desktop('off'),at);
   assert.deepEqual(before.cursor,after.cursor,'The same pointer movement must be repeated');
   assert.equal(after.visible,48,'The final taskbar must remain fully visible');
   if(at===0){assert.equal(before.visible,48);assert.equal(before.cursor.y,704);}
   if(at===18)assert(before.cursor.y>340&&before.cursor.y<704,'The pointer must move through the desktop');
   if(at===32)assert(before.visible>2&&before.visible<48,'The taskbar must slide through intermediate positions');
   if(at>=36){assert.equal(before.visible,2);assert.equal(after.cursor.y,340);}
  }
  // Every frame of the final three-second hold retains the pointer and taskbar state.
  for(frame=60;frame<150;frame++){
   const html=renderToStaticMarkup(React.createElement(mod.exports.PcWalkthrough,{os:'Windows 10',frames:150,scenes:[desktop('off')]}));
   assert.match(html,/data-win10-taskbar[^>]*bottom:0/);
   assert.match(html,/data-win10-cursor[^>]*top:340px/);
  }
  const toggleBefore=await inspect(toggle,30),toggleAfter=await inspect(toggle,120);
  assert.deepEqual(toggleBefore.toggles,['on']);assert.deepEqual(toggleAfter.toggles,['off']);
  assert.equal(toggleBefore.visible,2);assert.equal(toggleAfter.visible,48);
  const serveUrl=await bundle({entryPoint:path.join(__dirname,'../src/PcWalkthrough.tsx')});
  for(const [name,scene,at] of [['problem-start',desktop('on'),0],['problem-hidden',desktop('on'),120],
   ['toggle-on',toggle,30],['toggle-off',toggle,120],['result-start',desktop('off'),0],['result-held',desktop('off'),149]]){
   const inputProps={os:'Windows 10',phase:name.startsWith('problem')?'problem':'solution',frames:150,scenes:[scene]};
   const composition=await selectComposition({serveUrl,id:'PcWalkthrough',inputProps,puppeteerInstance:browser,logLevel:'error'});
   await renderStill({serveUrl,composition,inputProps,frame:at,puppeteerInstance:browser,output:path.join(out,name+'.png'),logLevel:'error'});
   console.log('Verified '+name+'.');
  }
  const short=await selectComposition({serveUrl,id:'PcWalkthrough',inputProps:{os:'Windows 10',frames:90,scenes:[desktop('off')]},puppeteerInstance:browser,logLevel:'error'});
  assert.equal(short.durationInFrames,150,'External callers must also reserve the full result hold');
  fs.writeFileSync(path.join(out,'preview-props.json'),JSON.stringify({os:'Windows 10',frames:450,scenes:[desktop('on'),toggle,desktop('off')]},null,2));
  console.log('Passed: repeated cursor motion, real taskbar sliding, documented toggle, and a continuous three-second final hold.');
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
