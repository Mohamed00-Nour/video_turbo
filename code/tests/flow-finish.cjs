const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const {bundle}=require('../node_modules/@remotion/bundler');
const {openBrowser,selectComposition,renderStill}=require('../node_modules/@remotion/renderer');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'output/flow-motion-review/checks');
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const publicDir=path.join(out,'public');fs.mkdirSync(path.join(publicDir,'reference-fonts'),{recursive:true});
 fs.copyFileSync(path.join(root,'studio/ui-fonts/ibm-plex-sans-arabic-700.woff2'),path.join(publicDir,'reference-fonts/ibm-plex-sans-arabic-700.woff2'));
 fs.copyFileSync(path.join(root,'studio/ui-fonts/Amiri-Bold.ttf'),path.join(publicDir,'reference-fonts/Amiri-Bold.ttf'));
 fs.copyFileSync(path.join(root,'studio/ui-fonts/ibm-plex-sans-arabic-400.woff2'),path.join(publicDir,'reference-fonts/ibm-plex-sans-arabic-400.woff2'));
 const displayFont=[path.join(root,'fonts/Bodoni-Italic.ttf'),path.join(process.env.WINDIR || 'C:/Windows','Fonts/BOD_I.TTF'),path.join(root,'studio/ui-fonts/Amiri-Bold.ttf')].find(file=>fs.existsSync(file));
 fs.copyFileSync(displayFont,path.join(publicDir,'reference-fonts/Bodoni-Italic.ttf'));
 execFileSync('ffmpeg',['-y','-v','error','-f','lavfi','-i','color=c=0xeee2f5:s=160x284:r=30:d=1','-an','-c:v','libx264','-pix_fmt','yuv420p',path.join(publicDir,'fixture.mp4')]);
 const serveUrl=await bundle({entryPoint:path.join(__dirname,'flow-finish.fixture.tsx'),publicDir,outDir:path.join(out,'bundle')});
 const browser=await openBrowser('chrome',{logLevel:'error'});
 const records=new Map();
 const onBrowserLog=log=>{if(log.text.startsWith('FLOW_CHECK:')){const r=JSON.parse(log.text.slice(11));records.set(r.disabled?'disabled-'+r.frame:r.different?'other-'+r.frame:r.unanalysed?'neutral-'+r.frame:r.frame,r);}};
 try{
  const composition=await selectComposition({serveUrl,id:'FlowFixture',puppeteerInstance:browser,logLevel:'error'});
  const render=async(frame,name=`frame-${frame}.png`)=>renderStill({serveUrl,composition,frame,puppeteerInstance:browser,output:path.join(out,name),scale:.25,logLevel:'error',dumpBrowserLogs:false,onBrowserLog});
  for(const frame of [0,2,6,14,29,30,34,38,39,59,60,64,68,69,89])await render(frame);
  assert.equal(composition.durationInFrames,90);
  assert(records.get(14).caption,'Captions must remain alongside display type');
  assert(records.get(14).headline.opacity>.99,'Display headline must settle into view');
  assert(records.get(2).headline.opacity<records.get(14).headline.opacity);
  assert.notEqual(records.get(2).headline.blur,records.get(14).headline.blur);
  for(const record of records.values()){
    assert.equal(record.corners.length,2);
    assert(record.corners.every(c=>c.opacity>.4),'Both defocused corners must be visible');
  }
  assert.deepEqual(records.get(29).scenes.map(s=>s.start),[0]);
  for(const frame of [30,34,38]){
    const scenes=records.get(frame).scenes;
    assert.deepEqual(scenes.map(s=>s.start),[0,30]);
    assert.equal(scenes[0].held,'true');assert.equal(scenes[0].opacity,1);
  }
  assert.equal(records.get(30).scenes[1].opacity,0);
  assert(records.get(34).scenes[1].opacity>0 && records.get(34).scenes[1].opacity<1);
  assert.equal(records.get(38).scenes[1].opacity,1);
  assert.deepEqual(records.get(39).scenes.map(s=>s.start),[30]);
  assert.deepEqual(records.get(89).scenes.map(s=>s.start),[60]);
  assert.notDeepEqual(records.get(29).depth,records.get(30).depth);
  for(const r of records.values())assert.equal(r.depth.length,3);
  assert(records.get(2).caption.opacity<records.get(6).caption.opacity);
  assert.notEqual(records.get(0).caption.blur,records.get(6).caption.blur);
  const english=records.get(38).caption.english.find(e=>e.text.includes('Juice'));
  assert.equal(english.text,'Juice Jacking');assert(english.positions[0]<english.positions[1]);
  const first=fs.readFileSync(path.join(out,'frame-34.png'));await render(34,'repeat.png');
  assert.deepEqual(first,fs.readFileSync(path.join(out,'repeat.png')));
  const disabled=await selectComposition({serveUrl,id:'DisabledFlow',puppeteerInstance:browser,logLevel:'error'});
  await renderStill({serveUrl,composition:disabled,frame:34,puppeteerInstance:browser,output:path.join(out,'disabled.png'),scale:.25,logLevel:'error',dumpBrowserLogs:false,onBrowserLog});
  assert.equal(records.get('disabled-34').scenes.length,0);assert.equal(records.get('disabled-34').depth.length,0);assert.equal(records.get('disabled-34').caption,null);assert.equal(records.get('disabled-34').headline,null);
  for(const id of ['OtherReference','UnanalysedReference']){
    const other=await selectComposition({serveUrl,id,puppeteerInstance:browser,logLevel:'error'});
    await renderStill({serveUrl,composition:other,frame:38,puppeteerInstance:browser,output:path.join(out,id+'.png'),scale:.25,logLevel:'error',dumpBrowserLogs:false,onBrowserLog});
  }
  const other=records.get('other-38');
  assert.equal(other.depth.length,0);assert.equal(other.corners.length,0);
  assert(!other.headline.font.includes('FlowDisplay'));assert.equal(other.headline.fontStyle,'normal');
  assert.equal(other.headline.blur,'blur(0px)');assert.equal(other.headline.color,'rgb(255, 255, 255)');
  assert.equal(other.scenes.length,1,'A reference using cuts must have no inherited blur dissolve');
  assert.equal(records.get('neutral-38').depth.length,0);assert.equal(records.get('neutral-38').headline,null);
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({status:'passed',records:[...records.values()]},null,2));
  console.log('Passed: exact duration, held outgoing tails, continuous depth, animated captions, English order, deterministic frames, finishing opt-out, separate headline animation, retained captions, prominent reference-specific corner shapes, different-reference typography, and neutral defaults.');
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
