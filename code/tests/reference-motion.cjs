// Browser regression checks using synthetic scenes only. No accepted project is rendered.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'output/reference-motion-check');
const {bundle}=require('../node_modules/@remotion/bundler');
const {openBrowser,selectComposition,renderStill}=require('../node_modules/@remotion/renderer');
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const publicDir=path.join(out,'fixture-public'),fonts=path.join(publicDir,'reference-fonts');
 fs.mkdirSync(fonts,{recursive:true});
 for(const name of ['ibm-plex-sans-arabic-700.woff2','Amiri-Bold.ttf']) fs.copyFileSync(path.join(root,'studio/ui-fonts',name),path.join(fonts,name));
 const placeholder=path.join(out,'fixture-default-timeline.json');
 fs.writeFileSync(placeholder,JSON.stringify({blocks:[],words:[],captionsInGameBlocks:true,totalFrames:1,fps:30}));
 const serveUrl=await bundle({entryPoint:path.join(__dirname,'reference-motion.fixture.tsx'),publicDir,outDir:path.join(out,'bundle'),
   webpackOverride:config=>({...config,resolve:{...config.resolve,alias:{...config.resolve?.alias,'./timeline.json$':placeholder}}})});
 const browser=await openBrowser('chrome',{logLevel:'error'});
 const records=new Map(),svg=[];
 const onBrowserLog=log=>{
   if(log.text.startsWith('REFERENCE_CHECK:')){const r=JSON.parse(log.text.slice('REFERENCE_CHECK:'.length));records.set((r.legacy?'legacy-':'')+r.frame,r);}
   if(log.text.startsWith('SVG_CHECK:')) svg.push(JSON.parse(log.text.slice('SVG_CHECK:'.length)));
 };
 try{
  const composition=await selectComposition({serveUrl,id:'MotionFixture',puppeteerInstance:browser,logLevel:'error'});
  assert.equal(composition.durationInFrames,330);
  for(const frame of [0,45,60,89,90,91,95,101,102,179,180,185,191,192,270,273,277,329]){
   await renderStill({serveUrl,composition,frame,puppeteerInstance:browser,output:path.join(out,`motion-${frame}.png`),scale:.25,logLevel:'error',dumpBrowserLogs:false,onBrowserLog});
  }
  for(const frame of [0,45,60,89]) assert.deepEqual(records.get(String(frame)).scenes.map(s=>s.start),[0]);
  for(const frame of [90,91,95,101]) assert.deepEqual(records.get(String(frame)).scenes.map(s=>s.start),[0,90]);
  assert.deepEqual(records.get('102').scenes.map(s=>s.start),[90]);
  for(const frame of [180,185,191]) assert.deepEqual(records.get(String(frame)).scenes.map(s=>s.start),[90,180]);
  assert.deepEqual(records.get('192').scenes.map(s=>s.start),[180]);
  assert.deepEqual(records.get('277').scenes.map(s=>s.start),[270]);
  assert.deepEqual(records.get('329').scenes.map(s=>s.start),[270]);
  assert.equal(records.get('90').scenes[1].opacity,0);
  assert.equal(records.get('101').scenes[1].opacity,1);
  assert(records.get('95').scenes[1].opacity>0 && records.get('95').scenes[1].opacity<1);
  assert(records.get('180').scenes[1].clip.includes('100%'));
  assert(records.get('191').scenes[1].clip.includes('0%'));
  for(const frame of [90,95,180,185]){
   const scenes=records.get(String(frame)).scenes;
   assert.equal(scenes[0].line,scenes[1].line,'Background motion must not reset at a handoff');
   assert.equal(scenes[0].opacity,1,'The outgoing scene must cover the frame under the incoming scene');
  }
  for(const frame of [90,91,95,101]){
   const scenes=records.get(String(frame)).scenes;
   assert(scenes.filter(s=>s.headlineOpacity*s.opacity>.15).length<=1,'Avoid overprinting two headings during a handoff');
  }
  assert(records.get('101').scenes[0].headlineFont.includes('Arial'),'English headings need the matching sans fallback');
  assert.notEqual(records.get('45').scenes[0].line,records.get('60').scenes[0].line);
  assert.notDeepEqual(records.get('45').scenes[0].depth,records.get('60').scenes[0].depth);
  const english=records.get('95').english;
  assert.equal(english.length,1,'Only one global caption overlay should be visible');
  assert.equal(english[0].text,'Juice Jacking');
  assert.equal(english[0].direction,'ltr');assert.equal(english[0].parentDirection,'rtl');
  assert(english[0].words[0].x<english[0].words[1].x,'English words must remain in reading order');
  assert(english[0].width<=910,'Caption phrase should fit within the safe area');
  const first=fs.readFileSync(path.join(out,'motion-95.png'));
  await renderStill({serveUrl,composition,frame:95,puppeteerInstance:browser,output:path.join(out,'repeat-95.png'),scale:.25,logLevel:'error',dumpBrowserLogs:false,onBrowserLog});
  assert.deepEqual(first,fs.readFileSync(path.join(out,'repeat-95.png')),'Frame output must be deterministic');
  const legacy=await selectComposition({serveUrl,id:'LegacyFixture',puppeteerInstance:browser,logLevel:'error'});
  await renderStill({serveUrl,composition:legacy,frame:95,puppeteerInstance:browser,output:path.join(out,'legacy.png'),scale:.25,logLevel:'error',dumpBrowserLogs:false,onBrowserLog});
  assert.equal(records.get('legacy-95').scenes.length,0,'An existing v2 plan must keep the original scene renderer');
  const caption=await selectComposition({serveUrl,id:'SvgCaptionFixture',puppeteerInstance:browser,logLevel:'error'});
  for(const frame of [5,20]) await renderStill({serveUrl,composition:caption,frame,puppeteerInstance:browser,output:path.join(out,`svg-caption-${frame}.png`),scale:.25,logLevel:'error',dumpBrowserLogs:false,onBrowserLog});
  assert(svg.some(r=>r.text==='USB-C' && r.direction==='ltr'));
  assert(svg.some(r=>r.text==='\u0628\u064a\u0627\u0646\u0627\u062a\u0643' && r.direction==='rtl'));
  fs.writeFileSync(path.join(out,'browser-checks.json'),JSON.stringify({status:'passed',syntheticOnly:true,checks:[...records.values()],svg},null,2));
  console.log('Passed browser checks: continuous depth motion, narration-safe handoffs, English captions, legacy compatibility and deterministic frames.');
 }finally{await browser.close({silent:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
