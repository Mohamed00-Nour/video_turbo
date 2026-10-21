const path=require('node:path'),fs=require('node:fs');
const {bundle}=require('@remotion/bundler');
const {openBrowser,selectComposition,renderMedia,renderStill}=require('@remotion/renderer');
(async()=>{
 const manifestPath=path.resolve(process.argv[2]),folder=path.dirname(manifestPath);
 const manifest=JSON.parse(fs.readFileSync(manifestPath,'utf8'));
 if(!Array.isArray(manifest.steps)||manifest.steps.some(step=>step.os!=='Windows 10'))throw Error('Animated tutorials require Windows 10 steps.');
 const url=await bundle({entryPoint:path.join(__dirname,'src/PcWalkthrough.tsx')});
 const browser=await openBrowser('chrome',{logLevel:'error'});
 try{
  for(let i=0;i<manifest.steps.length;i++){
   const step=manifest.steps[i],target=path.resolve(folder,step.file);
   if(path.dirname(target)!==folder||!/^animated-step-[a-z0-9-]+\.mp4$/.test(step.file))throw Error('Invalid walkthrough output path');
   if(fs.existsSync(target)&&fs.statSync(target).size>0){console.log('[PC TIPS] Reusing animated step '+(i+1));continue;}
   const inputProps={os:step.os,phase:step.phase||'solution',frames:step.frames,scenes:step.scenes};
   const composition=await selectComposition({serveUrl:url,id:'PcWalkthrough',inputProps,puppeteerInstance:browser,logLevel:'error'});
   const preview=target.replace(/\.mp4$/,'.png');
   await renderStill({serveUrl:url,composition,inputProps,frame:Math.floor(step.frames*.7),
    puppeteerInstance:browser,output:preview,scale:.75,logLevel:'error'});
   const pending=target.replace(/\.mp4$/,'.pending.mp4');
   try{
    await renderMedia({serveUrl:url,composition,inputProps,codec:'h264',crf:18,concurrency:2,
     puppeteerInstance:browser,outputLocation:pending,logLevel:'error'});
    fs.renameSync(pending,target);
   }finally{if(fs.existsSync(pending))fs.unlinkSync(pending);}
   console.log('[PC TIPS] Animated step '+(i+1)+' of '+manifest.steps.length+' ready.');
  }
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
