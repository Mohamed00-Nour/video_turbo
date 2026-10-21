const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {bundle}=require('../node_modules/@remotion/bundler');
const {openBrowser,selectComposition,renderStill}=require('../node_modules/@remotion/renderer');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'output/pc-tips-review/windows10');
const note='لو Filter Keys شغالة، اقفلها. لو مقفولة أصلاً، سيبها؛ الإعداد ده مش سبب المشكلة عندك.';
const cases={
 settings:{surface:'settings',title:'Keyboard',path:['Settings','Ease of Access','Keyboard'],rows:[{label:'Use the On-Screen Keyboard',value:'Off'},{label:'Use Sticky Keys',value:'Off'},{label:'Use Toggle Keys',value:'Off'},{label:'Use Filter Keys',value:'On'}],focus:3,action:'toggle_off',keys:[],note},
 home:{surface:'settings',title:'Windows Settings',path:['Settings'],rows:[{label:'System',value:'Display, sound, notifications, power'},{label:'Devices',value:'Bluetooth, printers, mouse'},{label:'Ease of Access',value:'Narrator, magnifier, high contrast'},{label:'Privacy',value:'Location, camera, microphone'}],focus:2,action:'select',keys:[],note:'افتح Ease of Access من Settings.'},
 mouse:{surface:'settings',title:'Mouse',path:['Settings','Devices','Mouse'],rows:[{label:'Select your primary button',value:'Left'}],before:'Right',options:['Left','Right'],focus:0,action:'choose',keys:[],note:'غيّر Select your primary button من Right إلى Left.'},
 clipboard:{surface:'clipboard',title:'Clipboard',path:['Clipboard'],rows:[{label:'First copied text',value:''},{label:'Second copied text',value:''}],focus:0,action:'shortcut',keys:['Win','V'],note:'اضغط Win + V عشان تشوف سجل النسخ.'},
 desktop:{surface:'desktop',title:'Start shortcut menu',path:['Taskbar','Start'],rows:[{label:'Start',value:''},{label:'Task Manager',value:''},{label:'Settings',value:''},{label:'File Explorer',value:''}],focus:0,action:'context_menu',keys:['Left click'],note:'كليك شمال بيفتح قائمة الاختصارات؟ دي المشكلة اللي هنحلها.'},
 explorer:{surface:'explorer',title:'Documents',path:['This PC','Documents'],rows:[{label:'Example.txt',value:''},{label:'Open',value:''},{label:'Edit',value:''},{label:'Print',value:''}],focus:0,action:'context_menu',keys:['Right click'],note:'كليك يمين على الملف عشان تفتح القائمة.'},
 notepad:{surface:'notepad',title:'Notepad',path:['Notepad'],rows:[{label:'A sample sentence in Notepad.',value:''},{label:'The result remains visible.',value:''}],focus:0,action:'result',keys:[],note:'اتأكد إن النتيجة ظاهرة.'},
 task_manager:{surface:'task_manager',title:'Startup',path:['Task Manager','Startup'],rows:[{label:'Example app',value:'Disabled'},{label:'Another app',value:'Enabled'}],focus:0,action:'toggle_off',keys:[],note:'اقفل تشغيل التطبيق مع بداية ويندوز.'},
 control_panel:{surface:'control_panel',title:'Ease of Access Center',path:['Control Panel','Ease of Access','Ease of Access Center'],rows:[{label:'Make the keyboard easier to use',value:''},{label:'Make the mouse easier to use',value:''}],focus:0,action:'select',keys:[],note:'افتح إعدادات الكيبورد.'},
 start:{surface:'start',title:'Start',path:['Start'],rows:[{label:'Notepad',value:''},{label:'Settings',value:''}],focus:0,action:'shortcut',keys:['Ctrl','Esc'],note:'افتح القائمة من زر Start.'},
};
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const serveUrl=await bundle({entryPoint:path.join(__dirname,'../src/PcWalkthrough.tsx')});
 const browser=await openBrowser('chrome',{logLevel:'error'});
 try{
  for(const [name,scene] of Object.entries(cases)){
   const inputProps={os:'Windows 10',phase:name==='desktop'?'problem':'solution',frames:90,scenes:[scene]};
   const composition=await selectComposition({serveUrl,id:'PcWalkthrough',inputProps,puppeteerInstance:browser,logLevel:'error'});
   assert.equal(composition.durationInFrames,90);assert.equal(composition.width,1024);assert.equal(composition.height,960);
   for(const frame of ['settings','mouse','clipboard','desktop','explorer'].includes(name)?[0,45,60,89]:[60]){
    await renderStill({serveUrl,composition,inputProps,frame,puppeteerInstance:browser,output:path.join(out,name+'-'+frame+'.png'),logLevel:'error'});
   }
   console.log('Verified Windows 10 '+name+' frames.');
  }
  // The renderer itself refuses incompatible saved props, even if invoked outside Python.
  await assert.rejects(()=>selectComposition({serveUrl,id:'PcWalkthrough',inputProps:{os:'Windows 11',frames:90,scenes:[cases.settings]},puppeteerInstance:browser,logLevel:'error'}),/Windows 10 only/);
  console.log('Passed: Windows 10 surfaces, bounded layout, before/click/after frames, duration, and Windows 11 rejection.');
 }finally{await browser.close({silent:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
