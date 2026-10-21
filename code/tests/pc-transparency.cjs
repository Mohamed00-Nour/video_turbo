const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),Module=require('node:module');
const React=require('../node_modules/react');
const {renderToStaticMarkup}=require('../node_modules/react-dom/server');
const {build}=require('../node_modules/esbuild');
const {bundle}=require('../node_modules/@remotion/bundler');
const {openBrowser,selectComposition,renderStill}=require('../node_modules/@remotion/renderer');
const out=path.resolve(__dirname,'../../output/pc-tips-review/transparency');
const apps=[{label:'Notepad',value:''},{label:'Settings',value:''}];
const start=state=>({surface:'start',title:'Start',path:['Start'],rows:apps,focus:0,action:'shortcut',
 keys:['Ctrl','Esc'],note:'Open the same Start menu and inspect its background.',transparency:state});
const toggle={surface:'settings',title:'Colors',path:['Settings','Personalization','Colors'],
 rows:[{label:'Transparency effects',value:'Off'}],focus:0,action:'toggle_off',keys:[],
 note:'Turn off the acrylic transparency effect.',transparency:'on'};
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const source=fs.readFileSync(path.join(__dirname,'../src/PcWalkthrough.tsx'),'utf8').replace('const StartMenu:','export const StartMenu:');
 const built=await build({stdin:{contents:source,resolveDir:path.join(__dirname,'../src'),loader:'tsx'},
  bundle:true,platform:'node',packages:'external',write:false,loader:{'.css':'empty','.jpg':'dataurl'}});
 const mod=new Module(path.join(__dirname,'transparency-check.cjs'));
 mod.filename=path.join(__dirname,'transparency-check.cjs');mod.paths=module.paths;
 mod._compile(built.outputFiles[0].text,mod.filename);
 const browser=await openBrowser('chrome',{logLevel:'error'});
 try{
  const page=await browser.newPage({context:()=>null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
  async function inspect(transparent){
   const html=renderToStaticMarkup(React.createElement(mod.exports.StartMenu,{scene:start(transparent?'on':'off'),progress:.9,transparent}));
   await page.goto({url:'data:text/html;charset=utf-8,'+encodeURIComponent('<div style="position:relative;width:974px;height:680px;background:linear-gradient(90deg,#005693,#169be0)">'+html+'</div>'),timeout:30000});
   return page.evaluate(()=>{const el=document.querySelector('[data-win10-start]'),style=getComputedStyle(el);return {
    background:style.backgroundColor,blur:style.backdropFilter,text:el.textContent,opacity:style.opacity,
    width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height};});
  }
  const before=await inspect(true),after=await inspect(false);
  assert.match(before.background,/rgba/);assert.match(before.blur,/blur\(18px\)/);
  assert.equal(after.background,'rgb(37, 37, 37)');assert.equal(after.blur,'none');
  assert.equal(before.text,after.text);assert.equal(before.opacity,'1');assert.equal(after.opacity,'1');
  assert.equal(before.width,after.width);assert.equal(before.height,after.height);
  const serveUrl=await bundle({entryPoint:path.join(__dirname,'../src/PcWalkthrough.tsx')});
  const cases={'start-on':start('on'),'start-off':start('off'),'toggle-before':toggle,'toggle-after':toggle};
  for(const [name,scene] of Object.entries(cases)){
   const inputProps={os:'Windows 10',phase:name==='start-on'?'problem':'solution',frames:120,scenes:[scene]};
   const composition=await selectComposition({serveUrl,id:'PcWalkthrough',inputProps,puppeteerInstance:browser,logLevel:'error'});
   await renderStill({serveUrl,composition,inputProps,frame:name==='toggle-before'?30:100,
    puppeteerInstance:browser,output:path.join(out,name+'.png'),logLevel:'error'});
   console.log('Verified '+name+'.');
  }
  assert.notDeepEqual(fs.readFileSync(path.join(out,'start-on.png')),fs.readFileSync(path.join(out,'start-off.png')));
  fs.writeFileSync(path.join(out,'preview-props.json'),JSON.stringify({os:'Windows 10',frames:360,scenes:[start('on'),toggle,start('off')]},null,2));
  console.log('Passed: real acrylic blur/translucency becomes solid, identical Start contents and layout, visible Settings before/after frames.');
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
