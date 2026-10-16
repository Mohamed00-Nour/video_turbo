import React from 'react';

export const Glyph: React.FC<{kind?: string; color?: string; size?: number}> = ({kind='shield',color='currentColor',size=64}) => {
  const paths: Record<string, React.ReactNode> = {
    shield: <><path d="M32 5 53 14v17c0 14-21 26-21 26S11 45 11 31V14Z"/><path d="m22 31 7 7 14-15"/></>,
    lock: <><rect x="15" y="27" width="34" height="29" rx="6"/><path d="M22 27V17a10 10 0 0 1 20 0v10m-10 12v7"/></>,
    image: <><rect x="8" y="10" width="48" height="44" rx="7"/><circle cx="23" cy="24" r="5"/><path d="m10 46 14-12 9 8 11-15 10 12"/></>,
    message: <><path d="M12 10h40v34H31L18 54V44h-6Z"/><path d="M21 22h22M21 31h16"/></>,
    bank: <><path d="M7 23 32 8l25 15H7Zm5 32h40M16 29v18m16-18v18m16-18v18"/></>,
    energy: <path d="m36 5-22 31h16l-3 23 23-32H34Z"/>,
    usb: <><path d="M21 30V12h22v18m-26 0h30v25H17Z"/><path d="M27 14v8m10-8v8M24 38h16m-8 0v9"/></>,
    share: <><circle cx="45" cy="12" r="7"/><circle cx="17" cy="32" r="7"/><circle cx="45" cy="52" r="7"/><path d="m23 28 16-12M23 36l16 12"/></>,
    warning: <><path d="m32 7 26 47H6Z"/><path d="M32 23v14m0 7v2"/></>,
    connection: <><path d="M24 23H14a10 10 0 0 0 0 20h12m12 0h12a10 10 0 0 0 0-20H38M20 33h24"/></>,
    check: <path d="m12 32 13 13 27-28"/>,
  };
  return <svg width={size} height={size} viewBox="0 0 64 64" fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[kind] || paths.shield}</svg>;
};

export const Phone: React.FC<{accent: string; ink: string; paper: string; progress: number; motif?: string; details: string[]; reveals: number[]}> = ({accent,ink,paper,progress,motif,details,reveals}) => {
  const warning=motif==='warning' || motif==='privacy';
  return <div style={{position:'relative',width:400,height:790,borderRadius:68,padding:13,background:'linear-gradient(120deg,#eeeeef 0%,#55565a 15%,#111215 40%,#77787c 80%,#ddd 100%)',boxShadow:'0 40px 90px #0005, inset 0 0 0 2px #ffffff60'}}>
    <div style={{position:'absolute',left:-4,top:170,width:5,height:70,borderRadius:4,background:'#666'}}/>
    <div style={{position:'absolute',right:-4,top:220,width:5,height:95,borderRadius:4,background:'#888'}}/>
    <div style={{height:'100%',overflow:'hidden',border:'4px solid #101114',borderRadius:57,background:paper,position:'relative',color:ink}}>
      <div style={{position:'absolute',top:13,left:124,width:124,height:30,borderRadius:20,background:'#101114',zIndex:3}}/>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'20px 28px 0',fontSize:17,fontWeight:700}}><span>9:41</span><span style={{display:'flex',gap:5,alignItems:'end'}}>{[7,10,13,16].map((h,i)=><i key={i} style={{height:h,width:4,background:ink,borderRadius:1}}/>)}</span></div>
      <div style={{position:'absolute',top:120,left:0,right:0,textAlign:'center'}}>
        <div style={{display:'inline-flex',width:116,height:116,borderRadius:35,alignItems:'center',justifyContent:'center',color:accent,background:accent+'14',border:'1px solid '+accent+'25'}}><Glyph kind={warning?'lock':motif==='energy'?'energy':'shield'} size={68}/></div>
        <div style={{fontSize:25,fontWeight:700,marginTop:25,letterSpacing:2}}>{warning?'USB / DATA':'USB'}</div>
      </div>
      <div style={{position:'absolute',top:355,left:27,right:27,display:'grid',gap:17}}>
        {(details.length?details:['••••••','••••••','••••••']).slice(0,3).map((label,i)=><div key={i} dir="auto" style={{display:'flex',alignItems:'center',gap:15,padding:'17px 16px',borderRadius:18,border:'1px solid '+ink+'14',background:ink+'05',fontSize:23,fontWeight:700,opacity:motif==='privacy'?(reveals[i] || 0):1}}><Glyph kind={motif==='privacy'?['image','message','bank'][i]:motif==='share'?'share':motif==='energy'?'energy':'usb'} size={32}/><span>{label}</span><span style={{marginInlineStart:'auto',width:8,height:8,borderRadius:8,background:accent,opacity:progress>i*.15?1:.25}}/></div>)}
      </div>
      {details.length<2 && <div style={{position:'absolute',left:70,right:70,top:525,height:150,opacity:.7}}>
        <svg width="100%" height="100%" viewBox="0 0 240 150" fill="none" stroke={ink} strokeWidth="2" aria-hidden="true">
          <rect x="48" y="12" width="140" height="70" rx="15" opacity=".45"/><path d="M190 35h9v24h-9" opacity=".45"/>
          {[0,1,2,3].map(i=><rect key={i} x={58+i*31} y="23" width="23" height="48" rx="5" fill={accent} stroke="none" opacity={.2+.8*Math.max(0,Math.min(1,progress*5-i*.4))}/>)}
          <path d="M119 85v23m-45 25h90m-45-25-12 12m12-12 12 12" stroke={accent} strokeLinecap="round"/>
        </svg>
      </div>}
      {warning && <div style={{position:'absolute',left:0,right:0,top:130+Math.max(0,Math.min(1,progress))*520,height:3,background:accent,boxShadow:`0 0 30px 5px ${accent}55`}}/>}
      <div style={{position:'absolute',bottom:18,left:124,width:124,height:5,borderRadius:4,background:ink+'aa'}}/>
    </div>
  </div>;
};
