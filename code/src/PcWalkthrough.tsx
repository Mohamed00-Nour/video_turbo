import React from 'react';
import {AbsoluteFill, Composition, Easing, Img, interpolate, registerRoot, useCurrentFrame, useVideoConfig} from 'remotion';
import './font.css';
import windows10Wallpaper from './assets/windows10-desktop.jpg';

type Surface = 'settings'|'explorer'|'clipboard'|'notepad'|'desktop'|'start'|'task_manager'|'control_panel'|'windows';
type WindowState = {app:'notepad'|'calculator';placement:'floating'|'left'|'right';text:string};
type Scene = {
 surface: Surface; title: string; path: string[]; rows: {label: string; value: string}[];
 focus: number; action: 'select'|'toggle_on'|'toggle_off'|'shortcut'|'result'|'context_menu'|'choose'|'activate_window'|'snap_left'|'snap_right'|'calculate';
 keys: string[]; note: string; before?: string; options?: string[];
 windows?:WindowState[];active_window?:number;snap_assist?:boolean;transparency?:''|'on'|'off';
};
type Props = {os: string; phase?: 'problem'|'solution'; frames: number; scenes: Scene[]};
const blue='#0078d7';
const clamp={extrapolateLeft:'clamp' as const,extrapolateRight:'clamp' as const};
const Logo:React.FC<{size?:number}>=({size=22})=><svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M1 4.2 10.2 3v8H1zm10.5-1.4L23 1.2V11H11.5zM1 12.5h9.2v8L1 19.2zm10.5 0H23v10.3l-11.5-1.6z"/></svg>;
const Glyph:React.FC<{code:number;size?:number}>=({code,size=22})=><span aria-hidden="true" style={{fontFamily:'Segoe MDL2 Assets',fontSize:size,lineHeight:1}}>{String.fromCharCode(code)}</span>;
const Folder:React.FC<{size?:number}>=({size=24})=><svg width={size} height={size} viewBox="0 0 28 24" aria-hidden="true"><path d="M1 4h10l3 3h13v16H1z" fill="#e4ab36"/><path d="M1 9h26l-2 14H1z" fill="#ffd36a"/></svg>;
const Toggle:React.FC<{on:boolean;amount:number}>=({on,amount})=><div data-win10-toggle={on?'on':'off'} style={{display:'flex',alignItems:'center',gap:12,marginTop:9,fontSize:18}}>
 <div style={{width:44,height:20,borderRadius:12,boxSizing:'border-box',border:'2px solid '+(on?blue:'#333'),background:on?blue:'white',position:'relative'}}>
  <div style={{position:'absolute',top:3,left:3+amount*24,width:10,height:10,borderRadius:'50%',background:on?'white':'#333'}}/>
 </div><span>{on?'On':'Off'}</span>
</div>;
const Titlebar:React.FC<{title:string;settings?:boolean}>=({title,settings})=><div data-win10-titlebar style={{height:38,display:'flex',alignItems:'center',background:'white',fontSize:16}}>
 <span style={{width:46,textAlign:'center'}}>{settings?<Glyph code={0xe72b} size={16}/>:<Glyph code={0xe8a5} size={17}/>}</span>
 <span>{title}</span><div style={{marginLeft:'auto',height:'100%',display:'flex',alignItems:'center'}}>
  {[0xe921,0xe922,0xe8bb].map(code=><span key={code} style={{width:46,textAlign:'center'}}><Glyph code={code} size={12}/></span>)}
 </div>
</div>;
const Window:React.FC<{title:string;settings?:boolean;children:React.ReactNode}>=({title,settings,children})=><div style={{position:'absolute',left:34,top:26,width:906,height:612,background:'white',border:'1px solid #777',boxShadow:'0 10px 24px #0006',overflow:'hidden'}}>
 <Titlebar title={title} settings={settings}/>{children}
</div>;

function windowBounds(window:WindowState){
 if(window.placement!=='floating')return {left:window.placement==='left'?0:487,top:0,width:487,height:680};
 return window.app==='notepad'?{left:80,top:70,width:650,height:500}:{left:90,top:125,width:420,height:520};
}
const calculatorKeys=['%','CE','C','\u232b','1/x','x\u00b2','\u221ax','\u00f7','7','8','9','\u00d7','4','5','6','\u2212','1','2','3','+','\u00b1','0','.','='];
const CalculatorContent:React.FC<{scene:Scene;window:WindowState;progress:number}>=({scene,window,progress})=>{
 const calculating=scene.action==='calculate';
 const input=(scene.before||'').replace(/\s/g,'');
 const sequence=[...input,'='];
 const count=calculating?Math.floor(interpolate(progress,[.12,.78],[0,sequence.length],clamp)):0;
 const typed=sequence.slice(0,count).join(''),complete=typed.endsWith('=');
 const currentKey=calculating&&count>0&&progress<.85?sequence[Math.min(count-1,sequence.length-1)]:'';
 const display=calculating?(complete?window.text:(typed.split('+').at(-1)||typed.split('+')[0]||'0')):window.text;
 const expression=calculating&&typed.includes('+')?(complete?input+' =':input.split('+')[0]+' +'):'';
 return <div style={{height:'calc(100% - 38px)',display:'flex',flexDirection:'column',background:'#e6e6e6'}}>
  <div style={{padding:'8px 14px',fontSize:23,display:'flex',alignItems:'center',gap:18}}><Glyph code={0xe700} size={20}/>Standard <span style={{marginLeft:'auto'}}><Glyph code={0xe81c} size={20}/></span></div>
  <div data-calculator-expression style={{height:25,paddingRight:20,textAlign:'right',fontSize:17,color:'#555'}}>{expression}</div>
  <div data-calculator-display style={{height:68,padding:'0 18px',fontSize:48,fontWeight:600,textAlign:'right'}}>{display}</div>
  <div style={{display:'flex',justifyContent:'space-around',padding:'10px 0',fontSize:15}}>{['MC','MR','M+','M\u2212','MS','M\u2304'].map(x=><span key={x}>{x}</span>)}</div>
  <div style={{flex:1,minHeight:0,padding:4,display:'grid',gridTemplateColumns:'repeat(4,1fr)',gridTemplateRows:'repeat(6,1fr)',gap:3}}>
   {calculatorKeys.map(key=><div data-calculator-key={key} key={key} style={{display:'grid',placeItems:'center',fontSize:24,background:currentKey===key?'#b4d9f4':key==='='?'#8cbce0':/^\d$/.test(key)?'#fafafa':'#f0f0f0',boxShadow:currentKey===key?'inset 0 0 0 2px #0078d7':undefined}}>{key}</div>)}
  </div>
 </div>;
};
const WindowLayout:React.FC<{scene:Scene;progress:number;acted:boolean}>=({scene,progress,acted})=>{
 const active=scene.action==='result'?scene.active_window||0:acted?scene.focus:scene.active_window||0;
 const snap=scene.action==='snap_left'||scene.action==='snap_right';
 return <>
  {(scene.windows||[]).map((window,i)=>{
   const start=windowBounds(window),end=snap&&i===scene.focus?windowBounds({...window,placement:scene.action==='snap_left'?'left':'right'}):start;
   return <div key={window.app} data-app-window={window.app} data-active-window={i===active} style={{position:'absolute',boxSizing:'border-box',
    left:interpolate(progress,[.52,.72],[start.left,end.left],clamp),top:interpolate(progress,[.52,.72],[start.top,end.top],clamp),
    width:interpolate(progress,[.52,.72],[start.width,end.width],clamp),height:interpolate(progress,[.52,.72],[start.height,end.height],clamp),
    background:'white',border:'1px solid '+(i===active?'#0078d7':'#888'),boxShadow:'0 6px 16px #0005',overflow:'hidden',zIndex:i===active?2:1}}>
    <Titlebar title={window.app==='notepad'?'Untitled - Notepad':'Calculator'}/>
    {window.app==='notepad'?<>
     <div style={{display:'flex',gap:18,fontSize:16,padding:'2px 10px 5px',borderBottom:'1px solid #ddd'}}>{['File','Edit','Format','View','Help'].map(x=><span key={x}>{x}</span>)}</div>
     <div data-notepad-document style={{padding:'15px 24px',fontFamily:'Consolas,monospace',fontSize:29,lineHeight:1.5,whiteSpace:'pre-wrap'}}>{window.text}</div>
     <div style={{position:'absolute',bottom:0,left:0,right:0,padding:'4px 10px',background:'#f0f0f0',borderTop:'1px solid #ddd',fontSize:13,textAlign:'right'}}>{'100%\u3000Windows (CRLF)\u3000UTF-8'}</div>
    </>:<CalculatorContent scene={scene} window={window} progress={progress}/>}
   </div>;
  })}
  {snap&&scene.snap_assist&&progress>=.72&&progress<.88&&<div data-snap-assist style={{position:'absolute',left:scene.action==='snap_left'?487:0,top:0,width:487,height:680,background:'#15202fd9',zIndex:4,display:'grid',placeItems:'center'}}>
   <div style={{width:310,background:'#e6e6e6',boxShadow:'0 5px 18px #0008'}}><Titlebar title={scene.windows?.[1-scene.focus].app==='calculator'?'Calculator':'Untitled - Notepad'}/><div style={{height:180,display:'grid',placeItems:'center',fontSize:35}}>{scene.windows?.[1-scene.focus].text}</div></div>
  </div>}
 </>;
};

function settingsNavigation(scene:Scene){
 const group=scene.path.find(item=>['Ease of Access','System','Devices','Personalization','Privacy','Apps','Update & Security','Time & Language','Network & Internet','Gaming','Accounts'].includes(item))||'System';
 const pages:Record<string,string[]>={
  'Ease of Access':['Display','Mouse pointer','Text cursor','Magnifier','Color filters','High contrast','Narrator','Audio','Closed captions','Speech','Keyboard','Mouse','Eye control'],
  'System':['Display','Sound','Notifications & actions','Focus assist','Power & sleep','Storage','Tablet','Multitasking','Projecting to this PC','Shared experiences','Clipboard','Remote Desktop','About'],
  'Devices':['Bluetooth & other devices','Printers & scanners','Mouse','Typing','Pen & Windows Ink','AutoPlay','USB'],
  'Personalization':['Background','Colors','Lock screen','Themes','Fonts','Start','Taskbar'],
  'Privacy':['General','Speech','Inking & typing personalization','Diagnostics & feedback','Activity history','Location','Camera','Microphone'],
  'Apps':['Apps & features','Default apps','Offline maps','Apps for websites','Video playback','Startup'],
  'Update & Security':['Windows Update','Delivery Optimization','Windows Security','Backup','Troubleshoot','Recovery','Activation','Find my device','For developers'],
  'Time & Language':['Date & time','Region','Language','Speech'],
  'Network & Internet':['Status','Wi-Fi','Ethernet','Dial-up','VPN','Airplane mode','Mobile hotspot','Proxy'],
  'Gaming':['Xbox Game Bar','Captures','Game Mode'],
  'Accounts':['Your info','Email & accounts','Sign-in options','Access work or school','Family & other users','Sync your settings'],
 };
 const page=scene.path.at(-1)||scene.title,all=pages[group];
 const position=all.findIndex(item=>item.toLowerCase()===page.toLowerCase());
 return {group,page,pages:all.slice(position>7?position-6:0,position>7?position+3:9)};
}

const Settings:React.FC<{scene:Scene;acted:boolean;progress:number}>=({scene,acted,progress})=>{
 const {group,page,pages}=settingsNavigation(scene),home=scene.title==='Windows Settings'||scene.path.length===1;
 const toggle=scene.action==='toggle_on'||scene.action==='toggle_off';
 const amount=interpolate(progress,[.5,.57],[scene.action==='toggle_off'?1:0,scene.action==='toggle_on'?1:0],clamp);
 if(home)return <Window title="Settings" settings><div style={{textAlign:'center',fontSize:30,margin:'30px 0 20px'}}>Windows Settings</div>
  <div style={{width:360,margin:'0 auto 38px',border:'2px solid #888',padding:'7px 12px',fontSize:18,color:'#666'}}>Find a setting <span style={{float:'right'}}>⌕</span></div>
  <div style={{padding:'0 46px',display:'grid',gridTemplateColumns:'1fr 1fr',gap:'22px 34px'}}>{scene.rows.map((row,i)=><div key={i} style={{display:'flex',gap:18,minHeight:92,padding:10,background:i===scene.focus&&progress>.4?'#e5e5e5':'transparent'}}>
   <span style={{color:blue}}><Glyph code={row.label==='Ease of Access'?0xe776:row.label==='Devices'?0xe772:row.label==='Privacy'?0xe72e:0xe770} size={32}/></span>
   <div><div style={{fontSize:22}}>{row.label}</div><div style={{fontSize:16,color:'#555',marginTop:7}}>{row.value}</div></div>
  </div>)}</div></Window>;
 return <Window title="Settings" settings>
  <aside data-win10-sidebar style={{position:'absolute',left:0,top:38,bottom:0,width:250,background:'#e6e6e6'}}>
   <div style={{padding:'17px 18px',display:'flex',alignItems:'center',gap:18,fontSize:18}}><Glyph code={0xe80f} size={18}/>Home</div>
   <div style={{margin:'7px 16px 22px',padding:'7px 10px',border:'1px solid #888',background:'white',color:'#666',fontSize:17}}>Find a setting <span style={{float:'right'}}>⌕</span></div>
   <div style={{padding:'0 18px 15px',fontSize:20,fontWeight:600}}>{group}</div>
   {pages.map((item,i)=><div key={item} style={{position:'relative',height:40,display:'flex',alignItems:'center',gap:15,paddingLeft:18,fontSize:16,background:item.toLowerCase()===page.toLowerCase()?'#d4d4d4':'transparent'}}>
    {item.toLowerCase()===page.toLowerCase()&&<span style={{position:'absolute',left:0,height:22,width:4,background:blue}}/>}
    <Glyph code={({Keyboard:0xe765,Mouse:0xe962,Clipboard:0xe77f,'Bluetooth & other devices':0xe702,'Printers & scanners':0xe749,Typing:0xe765,'Pen & Windows Ink':0xe70f,AutoPlay:0xe768,USB:0xe88e,Display:0xe7f4,Audio:0xe767,Narrator:0xe8f4,Speech:0xe720,'Color filters':0xe790,'High contrast':0xe793} as Record<string,number>)[item]||0xe8a5} size={18}/>{item}
   </div>)}
  </aside>
  <div style={{position:'absolute',left:274,top:62,right:26,bottom:0,overflow:'hidden'}}>
   <h1 style={{fontWeight:400,fontSize:32,lineHeight:1.2,margin:'0 0 30px'}}>{page}</h1>
   {scene.rows.map((row,i)=>{
    const active=i===scene.focus,choose=active&&scene.action==='choose',dropdown=choose||['Left','Right'].includes(row.value),on=active&&toggle?(scene.action==='toggle_on'?acted:!acted):row.value.toLowerCase()==='on';
    return <div key={i} data-win10-row={i} style={{height:106,boxSizing:'border-box',padding:'8px 0',background:active&&progress>.4&&progress<.58?'#f3f3f3':'transparent'}}>
     <div style={{fontSize:21,lineHeight:1.25,fontWeight:toggle?600:400,maxWidth:560}}>{row.label}</div>
     {dropdown?<div style={{position:'relative',marginTop:10,width:220,fontSize:18}}><div style={{height:32,border:'2px solid #888',padding:'3px 10px',boxSizing:'border-box'}}>{choose&&!acted?scene.before:row.value}<span style={{float:'right'}}>⌄</span></div>
      {choose&&progress>.28&&!acted&&<div style={{position:'absolute',top:-(scene.options||[]).indexOf(scene.before||'')*34,left:0,right:0,zIndex:3,border:'1px solid #777',background:'#f2f2f2',boxShadow:'0 4px 9px #0003'}}>{(scene.options||[]).map((option,n)=><div key={n} style={{height:34,boxSizing:'border-box',padding:'5px 10px',background:option===row.value&&progress>.4?'#cce8ff':'transparent'}}>{option}</div>)}</div>}
     </div>:active&&toggle||/^(on|off)$/i.test(row.value)?<Toggle on={on} amount={active&&toggle?amount:on?1:0}/>:<div style={{marginTop:10,fontSize:18,color:scene.action==='select'?blue:'#555'}}>{row.value}</div>}
    </div>;
   })}
  </div><span style={{position:'absolute',right:5,top:130,height:170,width:3,background:'#b6b6b6'}}/>
 </Window>;
};

const Notepad:React.FC<{scene:Scene;empty?:boolean}>=({scene,empty})=><Window title="Untitled - Notepad">
 <div style={{display:'flex',gap:22,fontSize:17,padding:'2px 10px 5px',borderBottom:'1px solid #ddd'}}>{['File','Edit','Format','View','Help'].map(x=><span key={x}>{x}</span>)}</div>
 <div style={{padding:'12px 14px',fontFamily:'Consolas,monospace',fontSize:25,lineHeight:1.65,whiteSpace:'pre-wrap'}}>
  {!empty&&scene.rows.map((row,i)=><div key={i}>{row.label}</div>)}<span style={{display:'inline-block',height:28,borderLeft:'2px solid #333',verticalAlign:'middle'}}/>
 </div>
 <div style={{position:'absolute',bottom:0,left:0,right:0,height:25,borderTop:'1px solid #ddd',background:'#f0f0f0',fontSize:14,textAlign:'right',padding:'3px 18px',boxSizing:'border-box'}}>Ln 1, Col 1　　100%　　Windows (CRLF)　　UTF-8</div>
</Window>;
const Explorer:React.FC<{scene:Scene;acted:boolean;progress:number}>=({scene,acted,progress})=><Window title={scene.path.at(-1)||'File Explorer'}>
 <div style={{height:29,display:'flex',gap:28,alignItems:'center',borderBottom:'1px solid #ddd',fontSize:16}}><span style={{background:'#0067b8',color:'white',padding:'5px 20px'}}>File</span>{['Home','Share','View'].map(x=><span key={x}>{x}</span>)}</div>
 <div style={{height:67,background:'#f5f6f7',borderBottom:'1px solid #ccc',display:'flex',alignItems:'center',gap:29,padding:'0 20px',fontSize:16}}>
  <span style={{textAlign:'center'}}><Glyph code={0xe77f} size={25}/><br/>Paste</span><span>Copy</span><span>Cut</span><span style={{borderLeft:'1px solid #ccc',height:40}}/><span><Folder/><br/>New folder</span><span>Properties</span>
 </div>
 <div style={{height:42,display:'flex',gap:18,alignItems:'center',padding:'0 15px',fontSize:17}}><span style={{color:'#777'}}>←　→　↑</span><div style={{flex:1,border:'1px solid #ccc',padding:'4px 8px'}}><Folder size={16}/>　{scene.path.filter(x=>!['File Explorer','Explorer'].includes(x)).join('　›　')||'This PC'}</div><div style={{border:'1px solid #ccc',padding:'4px 10px',color:'#777'}}>Search</div></div>
 <aside style={{position:'absolute',top:176,bottom:25,width:192,borderRight:'1px solid #ddd',paddingTop:12}}>{['Quick access','Desktop','Downloads','Documents','Pictures','This PC','Network'].map((x,i)=><div key={x} style={{fontSize:17,padding:'10px 20px',background:i===0?'#e5f3ff':'white'}}> {i>0&&i<5?<Folder size={18}/>:<Glyph code={0xe8a5} size={18}/>}　{x}</div>)}</aside>
 <div style={{marginLeft:210,marginRight:15}}><div style={{display:'flex',fontSize:16,color:'#666',borderBottom:'1px solid #eee',height:35,alignItems:'center'}}><span style={{flex:1}}>Name</span><span style={{width:190}}>Date modified</span><span style={{width:100}}>Type</span></div>
  {scene.rows.map((row,i)=>scene.action==='context_menu'&&i!==scene.focus?null:<div key={i} data-win10-row={i} style={{height:48,display:'flex',alignItems:'center',gap:10,fontSize:19,background:i===scene.focus&&progress>.4?'#cce8ff':'white',outline:i===scene.focus&&acted?'1px solid #99d1ff':'none'}}>
   {scene.action.startsWith('toggle')?<span style={{width:16,height:16,border:'1px solid #555',background:(scene.action==='toggle_on'?acted:!acted)?blue:'white',color:'white',fontSize:14,textAlign:'center'}}>✓</span>:<Glyph code={0xe8a5} size={21}/>}
   <span style={{flex:1}}>{row.label}</span><span style={{fontSize:16,color:'#666',width:290}}>{row.value}</span>
  </div>)}
 </div><div style={{position:'absolute',bottom:0,height:25,left:0,right:0,borderTop:'1px solid #eee',fontSize:14,padding:'3px 16px'}}>{scene.action==='context_menu'?1:scene.rows.length} items</div>
</Window>;
const TaskManager:React.FC<{scene:Scene;acted:boolean}>=({scene,acted})=><Window title="Task Manager">
 <div style={{fontSize:16,padding:'2px 12px 9px'}}>File　 Options　 View</div>
 <div style={{display:'flex',fontSize:16,borderBottom:'1px solid #aaa',gap:0}}>{['Processes','Performance','App history','Startup','Users','Details','Services'].map(x=><span key={x} style={{padding:'7px 10px',border:'1px solid #bbb',borderBottom:0,background:scene.path.includes(x)?'white':'#eee'}}>{x}</span>)}</div>
 <div style={{margin:20,fontSize:18}}><div style={{padding:'12px',borderBottom:'1px solid #aaa',background:'#f4f4f4'}}>Name <span style={{float:'right'}}>Status</span></div>{scene.rows.map((row,i)=><div key={i} style={{height:56,padding:'10px 12px',boxSizing:'border-box',background:i===scene.focus?'#d9edff':'white',borderBottom:'1px solid #eee'}}>{row.label}<span style={{float:'right'}}>{acted?row.value:scene.action==='toggle_off'&&i===scene.focus?'Enabled':row.value}</span></div>)}</div>
</Window>;
const ControlPanel:React.FC<{scene:Scene;progress:number}>=({scene,progress})=><Window title="Control Panel">
 <div style={{padding:'10px 22px',borderBlock:'1px solid #ddd',fontSize:17}}>←　↑　{scene.path.join('　›　')}</div>
 <div style={{display:'flex'}}><aside style={{width:205,padding:24,color:'#0066bb',fontSize:17}}>Control Panel Home</aside><main style={{flex:1,padding:'25px 20px'}}><h1 style={{margin:'0 0 30px',fontSize:27,fontWeight:400,color:'#006600'}}>{scene.title}</h1>{scene.rows.map((row,i)=><div key={i} style={{padding:'14px 8px',fontSize:21,color:'#0066bb',background:i===scene.focus&&progress>.4?'#e5f3ff':'white'}}>{row.label}<div style={{fontSize:17,color:'#555',marginTop:5}}>{row.value}</div></div>)}</main></div>
</Window>;

const StartMenu:React.FC<{scene:Scene;progress:number;transparent:boolean}>=({scene,progress,transparent})=><div data-win10-start data-transparency={transparent?'on':'off'} style={{position:'absolute',left:0,bottom:48,width:660,height:555,display:'flex',background:transparent?'rgba(37,37,37,.72)':'#252525',backdropFilter:transparent?'blur(18px)':'none',color:'white',boxShadow:'4px -4px 12px #0004'}}>
    <aside style={{width:54,display:'flex',flexDirection:'column',alignItems:'center',gap:30,paddingTop:22}}><Glyph code={0xe700}/><div style={{flex:1}}/><Glyph code={0xe77b}/><Glyph code={0xe713}/><Glyph code={0xe7e8}/><div/></aside>
    <div style={{width:250,padding:'24px 12px'}}><div style={{fontSize:17,marginBottom:20}}>Recently added</div>{scene.rows.map((row,i)=><div key={i} style={{height:53,display:'flex',alignItems:'center',gap:12,fontSize:19,background:i===scene.focus&&progress>.4?'#444':'transparent'}}><Glyph code={0xe8a5}/>{row.label}</div>)}</div>
    <div style={{flex:1,padding:'24px 16px'}}><div style={{fontSize:17,marginBottom:20}}>Productivity</div><div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:5}}>{['Mail','Calendar','Photos','Microsoft Store'].map((x,i)=><div key={x} style={{height:100,background:i===2?'#456f86':'#0063b1',fontSize:14,padding:10,display:'flex',flexDirection:'column',justifyContent:'space-between'}}><Glyph code={i===0?0xe715:i===1?0xe787:0xe8a5} size={30}/>{x}</div>)}</div></div>
</div>;

export const PcWalkthrough:React.FC<Props>=({os,scenes,phase='solution'})=>{
 const frame=useCurrentFrame(),{durationInFrames}=useVideoConfig();
 if(os!=='Windows 10')throw new Error('PcWalkthrough supports Windows 10 only. Update the episode before rendering.');
 const perScene=durationInFrames/scenes.length,index=Math.min(scenes.length-1,Math.floor(frame/perScene));
 const scene=scenes[index],local=frame-index*perScene,progress=local/perScene,acted=progress>=.52;
 const snap=scene.action==='snap_left'||scene.action==='snap_right';
 const isToggle=scene.action.startsWith('toggle'),shortcut=scene.action==='shortcut'||snap,context=scene.action==='context_menu';
 const activeWindow=scene.action==='result'?scene.active_window||0:acted?scene.focus:scene.active_window||0;
 const desktop=scene.surface==='desktop',start=scene.surface==='start',clipboard=scene.surface==='clipboard';
 const changesTransparency=scene.surface==='settings'&&isToggle&&scene.rows[scene.focus]?.label==='Transparency effects';
 const transparent=changesTransparency&&acted?scene.action==='toggle_on':scene.transparency==='on';
 const startTarget=context&&/start/i.test(scene.rows[scene.focus].label),home=scene.surface==='settings'&&(scene.path.length===1||scene.title==='Windows Settings');
 // Targets share the same desktop coordinate space as their actual controls.
 let target={x:385,y:26+62+68+scene.focus*106+24};
 if(isToggle)target={x:34+274+22,y:210+scene.focus*106};
 if(scene.action==='choose')target={x:34+274+105,y:217+scene.focus*106+((scene.options||[]).indexOf(scene.rows[scene.focus].value)-(scene.options||[]).indexOf(scene.before||''))*34};
 if(home)target={x:150+(scene.focus%2)*410,y:247+Math.floor(scene.focus/2)*114};
 if(scene.surface==='explorer')target={x:350,y:26+176+35+(context?0:scene.focus)*48+24};
 if(clipboard)target={x:710,y:170+scene.focus*90};
 if(scene.surface==='notepad')target={x:235,y:115+scene.focus*41};
 if(scene.surface==='task_manager')target={x:330,y:204+scene.focus*56};
 if(scene.surface==='control_panel')target={x:420,y:195+scene.focus*77};
 if(desktop)target={x:49,y:137};
 if(start)target={x:200,y:166+scene.focus*53};
 if(startTarget)target={x:25,y:703};
 if(scene.surface==='windows')target={x:scene.focus===0?434:486,y:703};
 const move=interpolate(progress,[.08,.44],[0,1],{...clamp,easing:Easing.bezier(.25,.1,.25,1)});
 const cursor={x:850+(target.x-850)*move,y:575+(target.y-575)*move};
 const menuItems=startTarget?['Apps and Features','Power Options','Event Viewer','System','Device Manager','Network Connections','Disk Management','Computer Management','Windows PowerShell','Windows PowerShell (Admin)','Task Manager','Settings','File Explorer','Search','Run','Shut down or sign out','Desktop'].map(label=>({label,value:''})):scene.rows.filter((_,i)=>i!==scene.focus);
 const menuRowHeight=startTarget?34:43,menuHeight=menuItems.length*menuRowHeight+14;
 const menuTop=startTarget?680-menuHeight:Math.min(target.y+16,655-menuHeight);
 const menuLeft=startTarget?0:Math.min(target.x+10,650);
 return <AbsoluteFill data-windows-version="10" style={{background:'#10161f',fontFamily:'Segoe UI,Arial,sans-serif',color:'#161616'}}>
  <div style={{position:'absolute',top:27,left:26,right:26,display:'flex',alignItems:'center',gap:13,color:'#f2f5f9',fontSize:23}}><Logo size={25}/><span>Windows 10</span><span style={{marginLeft:'auto',fontSize:18,letterSpacing:1,color:'#bfc8d2'}}>ANIMATED WALKTHROUGH</span></div>
  <div data-win10-desktop style={{position:'absolute',left:24,right:24,top:88,height:728,overflow:'hidden',background:'radial-gradient(ellipse at 75% 42%,#169be0 0%,#087bb8 26%,#005693 55%,#003b71 100%)',border:'1px solid #526273'}}>
   <Img src={windows10Wallpaper} style={{position:'absolute',inset:0,width:'100%',height:680,objectFit:'cover'}}/>
   <div style={{position:'absolute',left:12,top:17,width:78,textAlign:'center',color:'white',fontSize:15,textShadow:'1px 1px 2px #000'}}><Glyph code={0xe74d} size={36}/><div style={{marginTop:8}}>Recycle Bin</div></div>
   {desktop&&!startTarget&&<div style={{position:'absolute',left:12,top:105,width:100,textAlign:'center',color:'white',fontSize:16}}><Glyph code={0xe8a5} size={38}/><div>{scene.rows[scene.focus].label}</div></div>}
   {scene.surface==='windows'&&<WindowLayout scene={scene} progress={progress} acted={acted}/>}
   {scene.surface==='settings'&&<Settings scene={scene} acted={acted} progress={progress}/>}
   {scene.surface==='explorer'&&<Explorer scene={scene} acted={acted} progress={progress}/>}
   {(scene.surface==='notepad'||clipboard)&&<Notepad scene={clipboard&&acted&&scene.action==='select'?{...scene,rows:[scene.rows[scene.focus]]}:scene} empty={clipboard&&(!acted||scene.action!=='select')}/>}
   {scene.surface==='task_manager'&&<TaskManager scene={scene} acted={acted}/>}
   {scene.surface==='control_panel'&&<ControlPanel scene={scene} progress={progress}/>}
   {clipboard&&(!shortcut||acted)&&!(acted&&scene.action==='select')&&<div data-win10-clipboard style={{position:'absolute',left:586,top:95,width:346,boxSizing:'border-box',background:'#f2f2f2',border:'1px solid #888',boxShadow:'0 5px 16px #0005',padding:16}}>
    <div style={{fontSize:22,fontWeight:600,marginBottom:16}}>Clipboard <span style={{float:'right',fontSize:16,fontWeight:400,color:'#555'}}>Clear all</span></div>
    {scene.rows.map((row,i)=><div key={i} style={{position:'relative',background:'white',border:'1px solid '+(i===scene.focus?'#777':'#ccc'),minHeight:66,marginBottom:12,padding:'12px 24px 12px 12px',fontSize:19,boxSizing:'border-box'}}>{row.label}<span style={{position:'absolute',right:8,top:2}}>···</span>{row.value&&<div style={{fontSize:16,color:'#555'}}>{row.value}</div>}</div>)}
   </div>}
   {start&&(!shortcut||acted)&&<StartMenu scene={scene} progress={progress} transparent={transparent}/>}
   <div data-win10-taskbar data-transparency={transparent?'on':'off'} style={{position:'absolute',bottom:0,left:0,right:0,height:48,background:transparent?'rgba(25,25,25,.78)':'#191919',backdropFilter:transparent?'blur(18px)':'none',color:'white',display:'flex',alignItems:'center',fontSize:15}}>
    <span data-win10-start-button style={{height:48,width:50,display:'grid',placeItems:'center',background:startTarget&&progress>.4?'#414141':'transparent'}}><Logo size={22}/></span>
    <div style={{height:48,width:245,boxSizing:'border-box',background:'#f4f4f4',color:'#444',display:'flex',alignItems:'center',gap:15,padding:'0 15px',fontSize:17}}><Glyph code={0xe721} size={19}/>Type here to search</div>
    <span style={{padding:'0 19px'}}><Glyph code={0xe7c4}/></span><span style={{height:48,display:'grid',placeItems:'center',width:53,borderBottom:scene.surface==='explorer'?'3px solid #76b9ed':'3px solid transparent',boxSizing:'border-box'}}><Folder size={25}/></span>
    {scene.surface==='windows'?(scene.windows||[]).map((window,i)=><span data-window-taskbar={window.app} key={window.app} style={{width:52,height:48,display:'grid',placeItems:'center',boxSizing:'border-box',borderBottom:'3px solid #76b9ed',background:i===activeWindow?'#444':'transparent',color:'#9cdcff'}}><Glyph code={window.app==='calculator'?0xe8ef:0xe8a5} size={24}/></span>):<span style={{width:52,textAlign:'center',color:'#59b9ff'}}><Glyph code={scene.surface==='settings'?0xe713:0xe8a5} size={24}/></span>}
    <div style={{marginLeft:'auto',display:'flex',gap:15,alignItems:'center',height:'100%',paddingRight:16}}><Glyph code={0xe70e} size={15}/><Glyph code={0xe839} size={17}/><Glyph code={0xe767} size={18}/><span>ENG</span><span style={{textAlign:'center',fontSize:13,lineHeight:1.4}}>10:10 AM<br/>10/19/2026</span><Glyph code={0xe91c} size={20}/></div><span style={{height:48,width:5,borderLeft:'1px solid #777'}}/>
   </div>
   {context&&acted&&<div data-win10-context-menu style={{position:'absolute',left:menuLeft,top:menuTop,width:290,padding:'7px 0',background:startTarget?'#282828':'#f2f2f2',color:startTarget?'white':'#161616',border:'1px solid #777',boxShadow:'3px 4px 10px #0005',fontSize:19}}>
    {menuItems.map((row,i)=><div key={i} style={{height:menuRowHeight,display:'flex',alignItems:'center',paddingLeft:26,fontSize:startTarget?17:19,borderTop:startTarget&&['Task Manager','Shut down or sign out','Desktop'].includes(row.label)?'1px solid #555':undefined}}>{row.label}</div>)}
   </div>}
   {!shortcut&&scene.action!=='result'&&scene.action!=='calculate'&&<div data-win10-cursor style={{position:'absolute',left:cursor.x,top:cursor.y,zIndex:5,pointerEvents:'none'}}>
    {progress>=.5&&progress<.64&&<div style={{position:'absolute',left:-13,top:-13,width:32,height:32,border:'2px solid #ffbb00',borderRadius:'50%',scale:String(interpolate(progress,[.5,.64],[.5,1.3],clamp)),opacity:interpolate(progress,[.5,.64],[1,0],clamp)}}/>}
    <svg width="25" height="32" viewBox="0 0 25 32"><path d="M2 1v24l6-6 5 11 5-2-5-10h9z" fill="white" stroke="#111" strokeWidth="1.5"/></svg>
   </div>}
  </div>
  {shortcut&&<div data-shortcut-keys style={{position:'absolute',top:28,left:410,display:'flex',gap:9,alignItems:'center',color:'white',fontSize:18}}>{(snap&&scene.snap_assist&&progress>=.84?['Esc']:scene.keys).map((key,i)=><React.Fragment key={i}>{i>0&&<span>+</span>}<span style={{padding:'7px 15px',background:acted?'#0067b8':'#282828',border:'1px solid #999',borderBottomWidth:3}}>{key}</span></React.Fragment>)}</div>}
  <div style={{position:'absolute',top:834,left:30,right:30,display:'flex',alignItems:'center',gap:15,color:'#bbc5d1',fontSize:17}}>
   <span>{scene.path.join(' › ')}</span><span style={{marginLeft:'auto',whiteSpace:'nowrap'}}>{index+1} / {scenes.length}</span>
  </div>
  <div dir="rtl" style={{position:'absolute',top:871,left:30,right:30,color:phase==='problem'?'#ffd48a':'#eff7ff',fontFamily:'Lalezar,Arial,sans-serif',fontSize:31,lineHeight:1.15,textAlign:'center'}}>{phase==='problem'?'المشكلة قبل الحل · ':''}{scene.note}</div>
  <div style={{position:'absolute',bottom:6,left:30,right:30,fontSize:12,color:'#a1adbb',textAlign:'center'}}>Windows 10 simulation · Animated illustration, not a screen recording</div>
 </AbsoluteFill>;
};

registerRoot(()=><Composition id="PcWalkthrough" component={PcWalkthrough} fps={30} width={1024} height={960}
 durationInFrames={240} calculateMetadata={({props})=>{
  if(props.os!=='Windows 10')throw new Error('PcWalkthrough supports Windows 10 only. Update the episode before rendering.');
  return {durationInFrames:props.frames};
 }}
 defaultProps={{os:'Windows 10',frames:240,scenes:[{
  surface:'settings',title:'Keyboard',path:['Settings','Ease of Access','Keyboard'],
  rows:[{label:'Use the On-Screen Keyboard',value:'Off'},{label:'Use Sticky Keys',value:'Off'},
   {label:'Use Toggle Keys',value:'Off'},{label:'Use Filter Keys',value:'On'}],
  focus:3,action:'toggle_off',keys:[],note:'لو Filter Keys شغالة، اقفلها. لو مقفولة أصلاً، سيبها.'
 }]}}/>);
