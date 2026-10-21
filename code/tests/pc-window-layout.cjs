const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),Module=require('node:module');
const React=require('../node_modules/react');
const {renderToStaticMarkup}=require('../node_modules/react-dom/server');
const {build}=require('../node_modules/esbuild');
const {bundle}=require('../node_modules/@remotion/bundler');
const {openBrowser,selectComposition,renderStill}=require('../node_modules/@remotion/renderer');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'output/pc-tips-review/snapping');
const windows=(left='floating',right='floating',display='0')=>[
 {app:'notepad',placement:left,text:'125 + 75'},
 {app:'calculator',placement:right,text:display},
];
const scene=(action,items,focus=0,active=0,extra={})=>({
 surface:'windows',title:'Notepad and Calculator',path:['Desktop'],rows:[],focus,action,
 windows:items,active_window:active,keys:[],before:'',options:[],snap_assist:false,
 note:'رتب الشباكين وشوف النتيجة.',...extra,
});
const cases={
 overlap:scene('activate_window',windows(),1,0),
 left:scene('snap_left',windows(),0,0,{keys:['Win','Left'],snap_assist:true}),
 right:scene('snap_right',windows('left'),1,1,{keys:['Win','Right']}),
 addition:scene('calculate',windows('left','right','200'),1,1,{before:'125 + 75'}),
 result:scene('result',windows('left','right','200'),1,1),
};
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 // Inspect the rendered component's DOM to prove spatial effects, occlusion and arithmetic state.
 const source=fs.readFileSync(path.join(__dirname,'../src/PcWalkthrough.tsx'),'utf8')
  .replace('const WindowLayout:','export const WindowLayout:');
 const built=await build({stdin:{contents:source,resolveDir:path.join(__dirname,'../src'),loader:'tsx'},
  bundle:true,platform:'node',packages:'external',write:false,loader:{'.css':'empty','.jpg':'dataurl'}});
 const mod=new Module(path.join(__dirname,'window-layout-check.cjs'));
 mod.filename=path.join(__dirname,'window-layout-check.cjs');mod.paths=module.paths;
 mod._compile(built.outputFiles[0].text,mod.filename);
 const browser=await openBrowser('chrome',{logLevel:'error'});
 try{
  const page=await browser.newPage({context:()=>null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
  async function inspect(value,progress){
   const html=renderToStaticMarkup(React.createElement(mod.exports.WindowLayout,{scene:value,progress,acted:progress>=.52}));
   await page.goto({url:'data:text/html;charset=utf-8,'+encodeURIComponent('<body style="margin:0"><div style="position:relative;width:974px;height:680px">'+html+'</div>'),timeout:30000});
   return page.evaluate(()=>{
    const bounds=selector=>{const r=document.querySelector(selector).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
    const doc=document.querySelector('[data-notepad-document]').getBoundingClientRect();
    return {notepad:bounds('[data-app-window="notepad"]'),calculator:bounds('[data-app-window="calculator"]'),
     active:document.querySelector('[data-active-window="true"]').getAttribute('data-app-window'),
     covering:document.elementFromPoint(doc.x+50,doc.y+30)?.closest('[data-app-window]')?.getAttribute('data-app-window'),
     assist:!!document.querySelector('[data-snap-assist]'),display:document.querySelector('[data-calculator-display]').textContent,
     expression:document.querySelector('[data-calculator-expression]').textContent,
     keys:[...document.querySelectorAll('[data-calculator-key]')].map(el=>el.textContent)};
   });
  }
  const before=await inspect(cases.overlap,.1),after=await inspect(cases.overlap,.9);
  assert(before.keys.includes('\u00f7'));assert(before.keys.includes('\u00d7'));
  assert(before.keys.includes('\u2212'));assert(before.keys.includes('\u232b'));assert(!before.keys.includes('?'));
  assert.equal(before.active,'notepad');assert.equal(before.covering,'notepad');
  assert.equal(after.active,'calculator');assert.equal(after.covering,'calculator');
  const left=await inspect(cases.left,.78),leftDone=await inspect(cases.left,.95);
  assert.equal(left.notepad.x,0);assert.equal(left.notepad.width,487);assert(left.assist);assert(!leftDone.assist);
  const mid=await inspect(cases.right,.62),right=await inspect(cases.right,.95);
  assert(mid.calculator.x>90&&mid.calculator.x<487,'Window moves through intermediate positions');
  assert.equal(right.notepad.x,0);assert.equal(right.calculator.x,487);
  assert.equal(right.notepad.width,487);assert.equal(right.calculator.width,487);
  assert.equal(right.notepad.height,680);assert.equal(right.calculator.height,680);
  assert.equal((await inspect(cases.addition,.05)).display,'0');
  assert.equal((await inspect(cases.addition,.45)).display,'125');
  const sum=await inspect(cases.addition,.95);assert.equal(sum.display,'200');assert.equal(sum.expression,'125+75 =');
  console.log('Passed: actual overlap/occlusion, focus switch, interpolated half-screen snapping, Snap Assist dismissal and Calculator input/result.');
  const serveUrl=await bundle({entryPoint:path.join(__dirname,'../src/PcWalkthrough.tsx')});
  for(const [name,value] of Object.entries(cases)){
   const inputProps={os:'Windows 10',phase:name==='overlap'?'problem':'solution',frames:120,scenes:[value]};
   const composition=await selectComposition({serveUrl,id:'PcWalkthrough',inputProps,puppeteerInstance:browser,logLevel:'error'});
   for(const frame of name==='result'?[114]:[6,48,90,114]){
    await renderStill({serveUrl,composition,inputProps,frame,puppeteerInstance:browser,output:path.join(out,name+'-'+frame+'.png'),logLevel:'error'});
   }
   console.log('Verified '+name+' frames.');
  }
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});


