const path=require('node:path'),fs=require('node:fs');
const {bundle}=require('../node_modules/@remotion/bundler');
const {openBrowser,selectComposition,renderStill,renderMedia}=require('../node_modules/@remotion/renderer');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'output/pc-live-review'),media=path.join(root,'projects/PC Tips  Tricks - Part 01-509530/media/pc-tips');
(async()=>{
 const url=await bundle({entryPoint:path.join(__dirname,'pc-episode.fixture.tsx')});
 const browser=await openBrowser('chrome',{logLevel:'error'});
 try{
  for(let i=1;i<=3;i++){
   const composition=await selectComposition({serveUrl:url,id:'PcStep'+i,puppeteerInstance:browser,logLevel:'error'});
   await renderStill({serveUrl:url,composition,frame:90,puppeteerInstance:browser,output:path.join(out,'step-'+i+'.png'),scale:.75,logLevel:'error'});
   if(!process.argv.includes('--stills-only')){
    console.log('Rendering illustrated step '+i);
    await renderMedia({serveUrl:url,composition,codec:'h264',crf:18,concurrency:2,puppeteerInstance:browser,outputLocation:path.join(media,'illustrated-step-'+i+'.mp4'),logLevel:'error'});
    console.log('Step '+i+' ready');
   }
  }
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});