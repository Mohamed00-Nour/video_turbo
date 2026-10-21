const path=require('node:path');
const {bundle}=require('../node_modules/@remotion/bundler');
const {openBrowser,selectComposition,renderStill}=require('../node_modules/@remotion/renderer');
(async()=>{
 const root=path.resolve(__dirname,'../..');
 const serveUrl=await bundle({entryPoint:path.join(__dirname,'../src/index.ts'),publicDir:path.join(__dirname,'../public')});
 const browser=await openBrowser('chrome',{logLevel:'error'});
 try{
  const composition=await selectComposition({serveUrl,id:'MainVideo',puppeteerInstance:browser,logLevel:'error'});
  for(const frame of [30,160,400,650,880])await renderStill({serveUrl,composition,frame,puppeteerInstance:browser,output:path.join(root,'output/pc-live-review/final-frame-'+frame+'.png'),scale:.5,logLevel:'error'});
  console.log('Final composition review frames ready: '+composition.durationInFrames+' frames');
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});