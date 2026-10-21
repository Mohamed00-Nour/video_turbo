const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {openBrowser}=require('../node_modules/@remotion/renderer');
(async()=>{
 const browser=await openBrowser('chrome',{logLevel:'error'});
 try{
  const page=await browser.newPage({context:()=>null,logLevel:'error',indent:false,pageIndex:0,onBrowserLog:null,onLog:()=>{}});
  await page.setViewport({width:1440,height:1100,deviceScaleFactor:1});
  await page.goto({url:'http://127.0.0.1:8766',timeout:30000});
  const result=await page.evaluate(async()=>{
   for(let i=0;i<100&&document.getElementById('pc-new').disabled;i++)await new Promise(r=>setTimeout(r,50));
   document.getElementById('pc-new').click();
   for(let i=0;i<100&&!document.getElementById('pc-script-model').value;i++)await new Promise(r=>setTimeout(r,50));
   const state=await (await fetch('/api/state')).json();
   const headers={'X-Studio-Token':state.token};
   const settings=await (await fetch('/api/pc-tips/settings',{headers})).json();
   const legacy=[];
   for(const row of state.projects||[]){
    const project=await (await fetch('/api/project?id='+encodeURIComponent(row.id),{headers})).json();
    if(project.pc_tips?.plan)legacy.push({id:project.id,windows_stale:project.pc_tips.windows_stale});
   }
   return {open:document.getElementById('pc-dialog').open,title:document.getElementById('pc-create-heading').textContent,
    visuals:[...document.getElementById('pc-visual').options].map(row=>row.textContent),note:document.getElementById('pc-visual-note').textContent,
    target:settings.target_os,style:settings.walkthrough_style,legacy};
  });
  assert(result.open);assert(result.title.includes('Windows 10'));assert.equal(result.target,'Windows 10');
  assert(result.visuals.every(label=>label.includes('Windows 10')));assert(result.note.includes('Windows 10'));
  assert(result.legacy.length>=1);assert(result.legacy.every(row=>row.windows_stale));
  const screenshot=await page._client().send('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync(path.resolve(__dirname,'../../output/pc-tips-review/windows10/studio.png'),Buffer.from((screenshot.value||screenshot).data,'base64'));
  await page.setViewport({width:375,height:812,deviceScaleFactor:1});
  const small=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth,dialog:document.getElementById('pc-dialog').getBoundingClientRect().width}));
  assert(small.width<=small.viewport);assert(small.dialog<=small.viewport);
  await page.evaluate(()=>document.getElementById('pc-close').click());
  console.log('Passed: Windows 10 Studio labels, server targeting, legacy conversion flags, and mobile dialog layout. No production request was made.');
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
