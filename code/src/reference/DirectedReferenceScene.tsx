import React from 'react';
import {Easing, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {LoopingVideo} from '../LoopingVideo';
import {Glyph, Phone} from './ReferenceGraphics';
import {darkColor, scenePalette} from './visualStyle';
import {MovingBackdrop} from './MovingBackdrop';

const curve=Easing.bezier(.16,1,.3,1);
const clamp={extrapolateLeft:'clamp' as const,extrapolateRight:'clamp' as const,easing:curve};
const icons: Record<string,string>={warning:'warning',connection:'usb',privacy:'lock',protection:'shield',energy:'energy',share:'share',none:'shield'};

export const DirectedReferenceScene: React.FC<{block:any; visibility?:number}> = ({block,visibility=1}) => {
  const rawFrame=useCurrentFrame(),{fps}=useVideoConfig(),s=block.referenceStyle;
  const duration=block.durationFrames,moving=s.renderer_version>=3;
  const frame=moving?Math.min(rawFrame,duration-1):rawFrame;
  const palette=scenePalette(s,block),{background,ink,accent,muted,panel,dark}=palette;
  const variant=block.variant || 'card',motif=block.motif || 'none',details=block.details || [];
  const seconds=(moving?rawFrame:frame)/fps,progress=frame/Math.max(1,duration-1);
  const entrance=Math.max(1,Math.min(Math.round(fps*.32),Math.round(duration*.2)));
  const reveal=(delay=0)=>visibility*interpolate(frame,[delay,delay+entrance],[0,1],clamp);
  const detailReveal=(index:number)=>reveal(block.detailFrames?.[index] ?? index*3+3);
  const float=Math.sin(seconds*Math.PI*2/(s.float_period/fps)+block.startFrame*.013)*Math.min(s.float_amplitude,18);
  const move=reveal(Math.min(4,Math.floor(duration*.08)));
  const title=String(block.title || ''),emphasis=String(block.emphasis || '');
  const at=emphasis?title.indexOf(emphasis):-1;
  const fontBase=s.heading_font==='serif'?'ReferenceAmiri':s.heading_font==='display'?'Lalezar':'ReferencePlex';
  const font=moving?`${fontBase}, ${s.heading_font==='serif'?'Georgia, serif':'Arial, sans-serif'}`:fontBase;
  const sans=moving?'ReferencePlex, Arial, sans-serif':'ReferencePlex';
  const heading=at>=0 ? <>{title.slice(0,at)}<span style={{color:accent,background:block.accent_style==='block'?accent:undefined,...(block.accent_style==='block'?{color:darkColor(accent)?'#fff':'#111',padding:'0 14px',boxDecorationBreak:'clone' as const}:{}),textDecoration:block.accent_style==='underline'?'underline':undefined,textDecorationThickness:5,textUnderlineOffset:16}}>{emphasis}</span>{title.slice(at+emphasis.length)}</> : title;
  const backgroundEnd=block.scene_tone==='base' || !block.scene_tone?s.background_end:background;
  const headlineTop=block.text_position==='center'?620:block.text_position==='bottom'?1250:230;
  const fontSize=variant==='type'?Math.min(148,Math.max(94,180-title.length*2.1)):Math.min(122,Math.max(84,149-title.length*1.65));
  const graphicY=variant==='type'?1080:680;
  const sceneStyle: React.CSSProperties={position:'absolute',inset:0,overflow:'hidden',background:`radial-gradient(ellipse at 50% 40%,${background},${backgroundEnd})`,color:ink,fontFamily:font,fontWeight:700};
  const castShadow=dark?'0 28px 65px #0008':'0 30px 65px #00000024';
  const media=(item:any,style:React.CSSProperties,treatment=block.media_treatment || 'photo',fit=block.fit || 'contain')=>item && <div style={{position:'absolute',...style,opacity:move*(style.opacity as number ?? 1),translate:`0px ${(1-move)*100}px`,scale:.96+.04*move,mixBlendMode:treatment==='multiply'?'multiply':'normal'}}>
    <div style={{width:'100%',height:'100%',position:'relative',overflow:'hidden',borderRadius:treatment==='photo'?s.card_radius:0,
      border:treatment==='photo'?`3px solid ${dark?'#ffffffcc':'#ffffff'}`:undefined,background:treatment==='photo'?panel:'transparent',
      boxShadow:treatment==='photo'?castShadow:undefined,
      filter:treatment==='cutout'?`drop-shadow(0px 24px 26px ${dark?'#0009':'#0003'})`:undefined}}>
      {item.kind==='image'?<Img src={staticFile(item.src)} style={{width:'100%',height:'100%',objectFit:fit}}/>:
        <LoopingVideo src={item.src} durationFrames={item.durationFrames} offsetSeconds={block.offset_seconds || 0} style={{width:'100%',height:'100%',objectFit:fit}}/>}
    </div>
  </div>;
  const icon=icons[motif] || 'shield';
  const tile=(text:string,index:number,x:number,y:number,width=300)=> <div key={index} dir="auto" style={{position:'absolute',left:x,top:y+(1-detailReveal(index))*44,width,padding:'26px 22px',borderRadius:26,background:panel,border:`1px solid ${ink}16`,boxShadow:castShadow,color:ink,display:'flex',alignItems:'center',gap:18,opacity:detailReveal(index),rotate:`${index%2===0?-3:3}deg`,fontFamily:sans,fontSize:42,lineHeight:1.4}}><span style={{color:accent,display:'flex'}}><Glyph kind={motif==='privacy'?['image','message','bank'][index%3]:index===0?icon:'check'} size={48}/></span><span>{text}</span></div>;

  return <div style={sceneStyle}>
    <style>{`@font-face{font-family:ReferencePlex;src:url('${staticFile('reference-fonts/ibm-plex-sans-arabic-700.woff2')}');font-weight:700;font-style:normal;}@font-face{font-family:ReferenceAmiri;src:url('${staticFile('reference-fonts/Amiri-Bold.ttf')}');font-weight:700;}`}</style>
    {moving ? <MovingBackdrop block={block} frame={rawFrame} fps={fps} ink={ink} accent={accent} dark={dark}/> : <>
    {(block.backdrop==='grid' || variant==='device') && <div style={{position:'absolute',inset:-100,opacity:s.grid_opacity ?? .1,backgroundImage:`linear-gradient(${ink} 1px,transparent 1px),linear-gradient(90deg,${ink} 1px,transparent 1px)`,backgroundSize:'172px 172px',translate:`${progress*-14}px ${progress*20}px`,maskImage:'radial-gradient(ellipse at center,#000 20%,transparent 80%)'}}/>}
    {block.backdrop==='diagonal' && <div style={{position:'absolute',inset:-300,rotate:'-33deg',background:`repeating-linear-gradient(90deg,transparent 0px,transparent 180px,${ink}0a 183px,transparent 240px)`,filter:'blur(12px)'}}/>}
    {(s.ribbon || block.backdrop==='orbits') && <svg width="1080" height="1920" viewBox="0 0 1080 1920" style={{position:'absolute',inset:0,opacity:.42}}>
      <path d="M-90 1740C1050 1860 1250 900 700 730S-180 950 90 480S1220 110 1170-130" fill="none" stroke={block.scene_tone==='contrast'?accent:ink} strokeWidth={s.ribbon_width ?? 2} strokeDasharray="3700" strokeDashoffset={80-progress*100}/>
      {block.backdrop==='orbits' && <ellipse cx="540" cy="1080" rx="510" ry="400" fill="none" stroke={ink} strokeWidth="1" opacity=".28"/>}
    </svg>}
    {block.backdrop==='spotlight' && <div style={{position:'absolute',left:-220,top:430,width:1500,height:1300,background:`radial-gradient(ellipse,${dark?accent+'12':'#ffffff'} 0%,transparent 63%)`}}/>}
    </>}
    <div style={{position:'absolute',left:75,top:90,width:42,height:5,borderRadius:3,background:accent,opacity:.8}}/>
    {block.label && <div dir="auto" style={{position:'absolute',left:85,right:85,top:130,color:muted,fontFamily:sans,fontSize:32,textAlign:'center',letterSpacing:/[\u0600-\u06ff]/.test(block.label)?0:2,opacity:reveal()}}>{block.label}</div>}
    <div data-reference-headline="true" dir="auto" style={{position:'absolute',left:90,right:90,top:headlineTop,textAlign:'center',fontFamily:font,fontSize,fontWeight:700,fontStyle:s.italic?'italic':'normal',lineHeight:1.28,letterSpacing:'-.025em',textWrap:'balance',opacity:reveal(),translate:`0px ${(1-reveal())*42}px`,zIndex:5}}>
      {heading}
      {emphasis && at<0 && variant!=='metric' && <div style={{color:accent,marginTop:8,fontSize:Math.min(152,fontSize*1.2)}}>{emphasis}</div>}
    </div>

    {variant==='hero' && <>
      <div style={{position:'absolute',left:250,top:1430,width:580,height:50,borderRadius:'50%',background:'#000',filter:'blur(28px)',opacity:(dark?.22:.12)*visibility,scale:.8+move*.2}}/>
      {media(block.media,{left:100,top:graphicY+float,width:880,height:740,rotate:`${-5+progress*8}deg`},block.media_treatment || 'cutout')}
    </>}
    {variant==='card' && <>
      {(block.media_treatment || 'photo')==='photo' && <div style={{position:'absolute',left:180,top:graphicY+36,width:760,height:690,borderRadius:s.card_radius,background:accent,opacity:.15*visibility,rotate:'6deg'}}/>}
      {media(block.media,{left:110,top:graphicY+float,width:860,height:700,rotate:`${-4+progress*5}deg`})}
    </>}
    {variant==='collage' && <>
      {media(block.secondary_media || block.media,{left:300,top:graphicY+185-float,width:690,height:570,rotate:`${9-progress*3}deg`,opacity:.9})}
      {media(block.media,{left:70,top:graphicY+float,width:700,height:570,rotate:`${-8+progress*4}deg`})}
    </>}
    {variant==='type' && <>
      {motif!=='none' && <div style={{position:'absolute',left:400,top:1080+float,width:280,height:280,borderRadius:80,color:accent,background:accent+'0c',border:`1px solid ${accent}40`,display:'grid',placeItems:'center',opacity:move,rotate:`${-6+progress*9}deg`}}><Glyph kind={icon} size={145}/></div>}
      {details[0] && <div dir="auto" style={{position:'absolute',left:110,right:110,top:1410,textAlign:'center',color:muted,fontFamily:sans,fontSize:40,opacity:reveal(4)}}>{details[0]}</div>}
    </>}
    {variant==='device' && <>
      <div style={{position:'absolute',left:300,top:graphicY-35+float,rotate:`${-7+progress*8}deg`,scale:.93+.07*move,opacity:move,translate:`0px ${(1-move)*100}px`}}><Phone accent={accent} ink={dark?'#F5F5F2':'#171917'} paper={dark?'#171a19':'#fafbf8'} progress={progress} motif={motif} details={details} reveals={details.map((_:string,i:number)=>detailReveal(i))}/></div>
      {motif==='privacy' && details.slice(0,3).map((text:string,i:number)=>tile(text,i,i%2===0?55:660,810+i*205,350))}
      {motif!=='privacy' && <div style={{position:'absolute',left:760,top:1060-float,color:accent,background:panel,padding:24,borderRadius:30,boxShadow:castShadow,opacity:reveal(6),rotate:'9deg'}}><Glyph kind={icon} size={95}/></div>}
    </>}
    {variant==='compare' && <>
      {media(block.media,{left:140,top:graphicY-20+float,width:800,height:460,rotate:`${-3+progress*4}deg`},block.media_treatment || 'cutout')}
      {[0,1].map(i=><div key={i} style={{position:'absolute',left:95+i*465,top:1180+(1-reveal(i*3+3))*60,width:425,height:230,borderRadius:32,background:i===1?accent:panel,color:i===1?(darkColor(accent)?'#fff':'#151615'):ink,border:`1px solid ${ink}1f`,boxShadow:castShadow,opacity:reveal(i*3+3),display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',gap:20}}><Glyph kind={i===0?'energy':motif==='protection'?'shield':'connection'} size={75}/><span dir="auto" style={{fontSize:45}}>{details[i] || ''}</span></div>)}
      <svg width="1080" height="1920" style={{position:'absolute',inset:0,pointerEvents:'none'}}><path d="M290 1120v35m460-35v35" stroke={accent} strokeWidth="3" strokeLinecap="round"/></svg>
    </>}
    {variant==='metric' && <>
      <div style={{position:'absolute',left:155,top:700,width:770,height:620,borderRadius:'50%',background:`radial-gradient(ellipse,${accent}16,transparent 70%)`,border:`1px solid ${accent}20`,rotate:'-12deg'}}/>
      <div dir="auto" style={{position:'absolute',left:75,right:75,top:760+float,textAlign:'center',fontSize:emphasis.length>7?165:230,lineHeight:1.25,color:accent,opacity:move,scale:.9+.1*move}}>{emphasis}</div>
      {details[0] && <div dir="auto" style={{position:'absolute',left:100,right:100,top:1200,textAlign:'center',fontSize:46,color:ink,opacity:reveal(5)}}>{details[0]}</div>}
    </>}
    {variant==='steps' && <div style={{position:'absolute',left:100,right:100,top:700,display:'grid',gap:32}}>
      {details.slice(0,3).map((text:string,i:number)=><div key={i} dir="auto" style={{minHeight:180,padding:'32px 35px',display:'flex',alignItems:'center',gap:30,borderRadius:30,background:panel,border:`1px solid ${ink}15`,boxShadow:castShadow,opacity:detailReveal(i),translate:`${(1-detailReveal(i))*70}px 0px`}}><span style={{display:'grid',placeItems:'center',width:94,height:94,borderRadius:28,color:accent,background:accent+'12'}}><Glyph kind={motif==='privacy'?['image','message','bank'][i]:i===0?icon:'check'} size={58}/></span><span style={{fontSize:52}}>{text}</span></div>)}
    </div>}
    {!moving && block.transition_style==='wipe' && <div style={{position:'absolute',inset:0,zIndex:20,background:accent,translate:`${interpolate(frame,[0,Math.min(8,entrance)],[0,-110],clamp)}% 0px`}}/>}
  </div>;
};
