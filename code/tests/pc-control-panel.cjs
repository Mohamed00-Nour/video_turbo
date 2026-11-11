const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),Module=require('node:module');
const React=require('../node_modules/react'),{renderToStaticMarkup}=require('../node_modules/react-dom/server');
const {build}=require('../node_modules/esbuild'),{bundle}=require('../node_modules/@remotion/bundler');
const {openBrowser,selectComposition,renderStill}=require('../node_modules/@remotion/renderer');
const out=path.resolve(__dirname,'../../output/pc-tips-review/control-panel');
const scene=(action,view,value,before='',options=[])=>({surface:'control_panel',title:'Control Panel',
 path:['Control Panel'],rows:[{label:'View by:',value}],focus:0,action,keys:[],before,options,
 control_panel_view:view,note:'Open the menu and show the actual view change.'});
const options=['Category','Large icons','Small icons'];
const cases={category:scene('result','Category','Category'),open:scene('open_dropdown','Category','Category','Category',options),
 choose:scene('choose','Category','Large icons','Category',options),result:scene('result','Large icons','Large icons'),
 small:scene('result','Small icons','Small icons')};
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const source=fs.readFileSync(path.join(__dirname,'../src/PcWalkthrough.tsx'),'utf8')
  .replace('const ControlPanel:','export const ControlPanel:').replace('const Settings:','export const Settings:');
 const built=await build({stdin:{contents:source,resolveDir:path.join(__dirname,'../src'),loader:'tsx'},
  bundle:true,platform:'node',packages:'external',write:false,loader:{'.css':'empty','.jpg':'dataurl'}});
 const mod=new Module(path.join(__dirname,'control-panel-check.cjs'));mod.filename=path.join(__dirname,'control-panel-check.cjs');mod.paths=module.paths;
 mod._compile(built.outputFiles[0].text,mod.filename);
 const browser=await openBrowser('chrome',{logLevel:'error'});
 try{
  const page=await browser.newPage({context:()=>null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
  await page.setViewport({width:1024,height:960,deviceScaleFactor:1});
  async function inspect(value,progress){
   const html=renderToStaticMarkup(React.createElement(mod.exports.ControlPanel,{scene:value,progress}));
   await page.goto({url:'data:text/html;charset=utf-8,'+encodeURIComponent('<body style="margin:0;font-family:Arial">'+html+'</body>'),timeout:30000});
   return page.evaluate(()=>({view:document.querySelector('[data-control-panel-view]').getAttribute('data-control-panel-view'),
    menu:[...document.querySelectorAll('[data-control-panel-option]')].map(el=>el.getAttribute('data-control-panel-option')),
    categories:[...document.querySelectorAll('[data-control-panel-category]')].map(el=>el.getAttribute('data-control-panel-category')),
    applets:[...document.querySelectorAll('[data-control-panel-applet]')].map(el=>el.getAttribute('data-control-panel-applet')),
    bounds:[...document.querySelectorAll('[data-control-panel-category], [data-control-panel-applet]')].map(el=>{const r=el.getBoundingClientRect();return {right:r.right,bottom:r.bottom};}),
    iconSize:document.querySelector('[data-control-panel-applet] span span')?.style.fontSize}));
  }
  const category=await inspect(cases.category,.9);assert.equal(category.view,'Category');assert.equal(category.categories.length,8);assert.equal(category.applets.length,0);
  assert.deepEqual((await inspect(cases.open,.2)).menu,[]);
  const opened=await inspect(cases.open,.9);assert.equal(opened.view,'Category');assert.equal(opened.categories.length,8);assert.deepEqual(opened.menu,options);
  const choosing=await inspect(cases.choose,.3);assert.equal(choosing.view,'Category');assert.deepEqual(choosing.menu,options);
  const chosen=await inspect(cases.choose,.9),result=await inspect(cases.result,.9);
  assert.equal(chosen.view,'Large icons');assert.equal(chosen.categories.length,0);assert.deepEqual(chosen.menu,[]);
  assert.equal(chosen.applets.length,36);assert.deepEqual(chosen.applets,[...chosen.applets].sort());assert.deepEqual(result.applets,chosen.applets);
  assert(chosen.applets.includes('Mouse'));assert(chosen.applets.includes('Programs and Features'));
  for(const bounds of [...category.bounds,...chosen.bounds]){assert(bounds.right<=941);assert(bounds.bottom<=639);}
  assert.notEqual((await inspect(cases.small,.9)).iconSize,chosen.iconSize);
  const mouse={surface:'settings',title:'Mouse',path:['Settings','Devices','Mouse'],rows:[{label:'Select your primary button',value:'Right'}],
   focus:0,action:'open_dropdown',before:'Right',options:['Left','Right'],keys:[],note:'Open the menu without selecting.'};
  const settings=renderToStaticMarkup(React.createElement(mod.exports.Settings,{scene:mouse,progress:.9,acted:true}));
  assert.match(settings,/>Left</);assert.match(settings,/>Right</);
  const serveUrl=await bundle({entryPoint:path.join(__dirname,'../src/PcWalkthrough.tsx')});
  for(const [name,value,at] of [['category',cases.category,120],['menu-open',cases.open,120],['choose-before',cases.choose,45],['choose-after',cases.choose,120],['result',cases.result,149],['settings-menu-open',mouse,120]]){
   const inputProps={os:'Windows 10',phase:name==='category'?'problem':'solution',frames:150,scenes:[value]};
   const composition=await selectComposition({serveUrl,id:'PcWalkthrough',inputProps,puppeteerInstance:browser,logLevel:'error'});
   await renderStill({serveUrl,composition,inputProps,frame:at,puppeteerInstance:browser,output:path.join(out,name+'.png'),logLevel:'error'});
   console.log('Verified '+name+'.');
  }
  console.log('Passed: eight actual categories, a held View by menu, selection changing to 36 alphabetical applets, persistent final view and Settings open-menu support.');
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
