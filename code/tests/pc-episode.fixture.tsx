import React from 'react';
import {AbsoluteFill, Composition, interpolate, registerRoot, useCurrentFrame, useVideoConfig} from 'remotion';
import '../src/font.css';

const cyan='#0078d4', ink='#20252d', muted='#616a75';
const clamp={extrapolateLeft:'clamp' as const,extrapolateRight:'clamp' as const};
const Gear=({size=60}:{size?:number})=><svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
 <g stroke="currentColor" strokeWidth="6">{Array.from({length:8},(_,i)=><path key={i} transform={'rotate('+i*45+' 32 32)'} d="M32 5V14"/>)}<circle cx="32" cy="32" r="19"/><circle cx="32" cy="32" r="7"/></g>
</svg>;
const Access=()=> <svg width="45" height="45" viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round"><circle cx="32" cy="12" r="5"/><path d="M12 25Q32 32 52 25M32 27V42M32 42L20 58M32 42L44 58"/></svg>;
const Cursor=({x,y,click=false}:{x:number;y:number;click?:boolean})=><div style={{position:'absolute',left:x,top:y,zIndex:20}}>
 {click&&<div style={{position:'absolute',width:64,height:64,left:-23,top:-23,border:'4px solid #0078d488',borderRadius:'50%',background:'#0078d41c'}}/>}
 <svg width="40" height="50" viewBox="0 0 40 50"><path d="M4 2L4 38L14 29L22 46L30 42L22 25L37 24Z" fill="#fff" stroke="#102236" strokeWidth="3"/></svg>
</div>;
const Toggle=({on}:{on:boolean})=><div style={{display:'flex',alignItems:'center',gap:16,fontSize:27}}><span>{on?'On':'Off'}</span><div style={{width:70,height:35,borderRadius:24,background:on?cyan:'#eceef1',border:'2px solid '+(on?cyan:'#858d99'),padding:5,boxSizing:'border-box'}}><div style={{width:21,height:21,borderRadius:'50%',background:on?'#fff':'#616a75',marginLeft:on?32:0}}/></div></div>;
const Tag=()=> <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',fontSize:23,letterSpacing:1,color:'#e0f5ff',padding:'0 6px 24px'}}><span>WINDOWS 11</span><span dir="rtl" style={{fontFamily:'Lalezar',fontSize:32,letterSpacing:0}}>شرح توضيحي</span></div>;
const WindowShell:React.FC<{children:React.ReactNode}>=({children})=><div style={{position:'relative',background:'#f5f6f8',borderRadius:22,color:ink,overflow:'hidden',boxShadow:'0 20px 35px #0005',border:'2px solid #ffffff55'}}>
 <div style={{height:58,display:'flex',alignItems:'center',padding:'0 26px',fontSize:21,gap:15,borderBottom:'1px solid #e4e7ec'}}><span style={{color:cyan}}>⚙</span><span>Settings</span><span style={{marginLeft:'auto',color:'#78818e',letterSpacing:25}}>– □ ×</span></div>{children}
</div>;
const Step:React.FC<{step:number}>=({step})=>{
 const frame=useCurrentFrame(),{fps,durationInFrames}=useVideoConfig();
 const reveal=interpolate(frame,[0,.4*fps],[0,1],clamp);
 const end=frame/Math.max(1,durationInFrames-1);
 const clicked=frame>fps*2.5;
 const off=frame>fps*2.3;
 const pulse=.3+.35*Math.sin(frame/fps*5);
 return <AbsoluteFill style={{background:'linear-gradient(140deg,#172c40,#0c1826)',padding:38,fontFamily:'Arial,sans-serif'}}>
 <Tag/><div style={{opacity:reveal,translate:'0 '+(1-reveal)*18+'px'}}>
 {step===1?<div style={{height:760,background:'#f5f6f8',border:'2px solid #fff8',borderRadius:24,padding:38,color:ink,boxShadow:'0 24px 45px #0005'}}>
  <div style={{height:64,borderBottom:'3px solid '+cyan,background:'#fff',borderRadius:8,padding:'15px 20px',fontSize:27,color:muted}}>Search for apps, settings, and documents</div>
  <div style={{marginTop:40,display:'flex',justifyContent:'space-between',fontSize:28,fontWeight:700}}><span>Pinned</span><span style={{fontSize:22,color:muted}}>All apps ›</span></div>
  <div style={{display:'flex',gap:24,marginTop:36}}>
   <div style={{width:250,height:196,background:'#e3f0ff',border:'4px solid '+cyan,borderRadius:15,display:'flex',flexDirection:'column',justifyContent:'center',alignItems:'center',gap:22,boxShadow:'0 0 0 '+(4+pulse*9)+'px #0078d414'}}><Gear size={72}/><b style={{fontSize:32}}>Settings</b></div>
   <div style={{width:250,height:196,background:'#fff',borderRadius:15,display:'flex',flexDirection:'column',justifyContent:'center',alignItems:'center',gap:22}}><span style={{fontSize:72,color:'#dcaa26'}}>▰</span><span style={{fontSize:30}}>File Explorer</span></div>
   <div style={{width:250,height:196,background:'#fff',borderRadius:15,display:'flex',flexDirection:'column',justifyContent:'center',alignItems:'center',gap:22}}><span style={{fontSize:72,color:'#4a9ad8'}}>▤</span><span style={{fontSize:30}}>Notepad</span></div>
  </div>
  <div dir="rtl" style={{fontFamily:'Lalezar',fontSize:57,textAlign:'center',marginTop:66}}>افتح الإعدادات</div>
  <div style={{display:'flex',justifyContent:'center',gap:15,marginTop:20,color:cyan,fontSize:31,fontWeight:700}}><span>Start</span><span>›</span><span>Settings</span></div>
  <Cursor x={interpolate(frame,[0,2*fps],[690,160],clamp)} y={interpolate(frame,[0,2*fps],[630,375],clamp)} click={clicked&&frame<fps*3.2}/>
 </div>:<WindowShell>
  <div style={{height:702,padding:'35px 30px',position:'relative'}}>
   <div style={{fontSize:39,fontWeight:700,letterSpacing:-1,marginBottom:30}}>{step===2?'Accessibility':'Accessibility  ›  Visual effects'}</div>
   {step===2?<>
    <div style={{display:'flex',gap:22}}>
     <div style={{width:248,paddingTop:15}}>
      <div style={{color:muted,fontSize:24,padding:'23px 15px'}}>System</div>
      <div style={{color:muted,fontSize:24,padding:'23px 15px'}}>Personalization</div>
      <div style={{color:muted,fontSize:24,padding:'23px 15px'}}>Apps</div>
      <div style={{fontSize:25,padding:'20px 13px',borderLeft:'6px solid '+cyan,borderRadius:6,background:'#dfeeff',fontWeight:700}}>Accessibility</div>
     </div>
     <div style={{flex:1}}>
      <div style={{fontSize:23,color:muted,marginBottom:18}}>Vision</div>
      <div style={{padding:'27px 25px',background:'#fff',border:'1px solid #dce0e6',borderRadius:12,fontSize:29}}>Text size <span style={{float:'right'}}>›</span></div>
      <div style={{padding:'25px 23px',marginTop:14,background:'#e7f2ff',border:'3px solid '+cyan,borderRadius:12,display:'flex',gap:17,alignItems:'center'}}>
       <Access/><div><b style={{fontSize:30}}>Visual effects</b><div style={{fontSize:21,color:muted,marginTop:8,lineHeight:1.35}}>Scroll bars, transparency,<br/>animations</div></div><span style={{marginLeft:'auto',fontSize:32}}>›</span>
      </div>
      <div style={{padding:'27px 25px',marginTop:14,background:'#fff',border:'1px solid #dce0e6',borderRadius:12,fontSize:29}}>Mouse pointer and touch</div>
     </div>
    </div>
    <div dir="rtl" style={{fontFamily:'Lalezar',fontSize:44,color:cyan,textAlign:'center',marginTop:55}}>إمكانية الوصول ← التأثيرات المرئية</div>
    <Cursor x={interpolate(frame,[0,2.2*fps],[170,660],clamp)} y={interpolate(frame,[0,2.2*fps],[410,310],clamp)} click={clicked&&frame<fps*3.3}/>
   </>:<>
    <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'28px 24px',background:'#fff',border:'1px solid #dce0e6',borderRadius:12,fontSize:28}}><span>Always show scrollbars</span><Toggle on={false}/></div>
    <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'28px 24px',marginTop:14,background:'#fff',border:'1px solid #dce0e6',borderRadius:12,fontSize:28}}><span>Transparency effects</span><Toggle on/></div>
    <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'29px 23px',marginTop:14,background:'#e7f2ff',border:'3px solid '+cyan,borderRadius:12,fontSize:30,fontWeight:700}}><span>Animation effects</span><Toggle on={!off}/></div>
    <div dir="rtl" style={{fontFamily:'Lalezar',fontSize:54,color:cyan,textAlign:'center',marginTop:33}}>Animation effects ← Off</div>
    <div style={{marginTop:15,display:'flex',gap:18}}>
     <div style={{flex:1,height:125,border:'2px solid #d2dbe5',borderRadius:12,padding:15,background:'#e6e9ef',position:'relative'}}>
      <span style={{fontSize:20,color:muted}}>ANIMATION ON</span>
      <div style={{position:'absolute',top:52,left:28,width:90,height:55,background:'#fff',border:'3px solid #889ab1',borderRadius:7,translate:Math.sin(frame/fps*1.8)*23+23+'px 0'}}><div style={{height:11,background:'#aebdd1'}}/></div>
     </div>
     <div style={{flex:1,height:125,border:'2px solid #0078d455',borderRadius:12,padding:15,background:'#e3f0ff',position:'relative'}}>
      <span style={{fontSize:20,color:cyan}}>ANIMATION OFF</span>
      <div style={{position:'absolute',top:52,left:48,width:90,height:55,background:'#fff',border:'3px solid '+cyan,borderRadius:7}}><div style={{height:11,background:cyan}}/></div>
     </div>
    </div>
    <Cursor x={interpolate(frame,[0,1.9*fps],[665,798],clamp)} y={interpolate(frame,[0,1.9*fps],[465,346],clamp)} click={frame>fps*2&&frame<fps*2.8}/>
   </>}
  </div>
 </WindowShell>}
 </div>
 <div dir="rtl" style={{position:'absolute',bottom:20,left:38,right:38,fontFamily:'Lalezar',color:'#b8d8ec',fontSize:27,textAlign:'center'}}>توضيح الخطوات · راجع أسماء الخيارات في نسخة ويندوز عندك</div>
 </AbsoluteFill>;
};
const One=()=> <Step step={1}/>;
const Two=()=> <Step step={2}/>;
const Three=()=> <Step step={3}/>;
registerRoot(()=> <>
 <Composition id="PcStep1" component={One} durationInFrames={240} fps={30} width={1024} height={960}/>
 <Composition id="PcStep2" component={Two} durationInFrames={270} fps={30} width={1024} height={960}/>
 <Composition id="PcStep3" component={Three} durationInFrames={390} fps={30} width={1024} height={960}/>
</>);
