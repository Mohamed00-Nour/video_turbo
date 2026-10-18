import React, {useEffect, useLayoutEffect, useState} from 'react';
import {Easing, Sequence, cancelRender, continueRender, delayRender, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {textDirection} from '../captionText';
import {getFlowFinishing} from './flowStyle';

const clamp={extrapolateLeft:'clamp' as const,extrapolateRight:'clamp' as const};
const ease={...clamp,easing:Easing.bezier(.16,1,.3,1)};

// Fit the actual loaded glyphs, including italic overhang, inside the safe area.
const useDisplaySize=(text:string,arabic:boolean,fontKind:string)=>{
  const serif=fontKind==='serif';
  const base=serif?(arabic?190:228):174;
  const family=serif?(arabic?'ReferenceAmiri':'FlowDisplay'):fontKind==='mono'?'Courier New':'ReferencePlex';
  const [size,setSize]=useState<number|null>(null);
  const [handle]=useState(()=>delayRender('Fitting display headline'));
  useEffect(()=>{
    const font=`${serif&&!arabic?'italic 400':'700'} ${base}px "${family}"`;
    document.fonts.load(font,text).then(()=>{
      const context=document.createElement('canvas').getContext('2d')!;
      context.font=font;
      context.direction=arabic?'rtl':'ltr';
      const measured=context.measureText(text);
      const spacing=serif&&!arabic?-.045*base*Math.max(0,text.length-1):0;
      const width=Math.max(measured.width,measured.actualBoundingBoxLeft+measured.actualBoundingBoxRight)+spacing;
      setSize(Math.min(base,base*880/Math.max(1,width)));
    }).catch(cancelRender);
    return ()=>continueRender(handle);
  },[text,arabic,base,family,handle,serif]);
  useLayoutEffect(()=>{if(size!==null)continueRender(handle);},[size,handle]);
  return size ?? base;
};

const Headline: React.FC<{block:any}>=({block})=>{
  const frame=useCurrentFrame();
  const {fps}=useVideoConfig();
  const copy=block.flowText || {kicker:'',headline:block.title || '',support:''};
  const arabic=textDirection(copy.headline)==='rtl';
  const style=getFlowFinishing(block);
  const palette=block.flowPalette || {background:'#f4f4f2',ink:'#171717'};
  const serif=style.headline_font==='serif';
  const blur=style.headline_motion==='blur_slide';
  const still=style.headline_motion==='none';
  const seconds=block.durationFrames/fps;
  const speed=Math.min(1,seconds/2);
  const enter=still?1:interpolate(frame,[.24*fps*speed,.76*fps*speed],[0,1],ease);
  const kicker=still?1:interpolate(frame,[.1*fps*speed,.4*fps*speed],[0,1],ease);
  const support=still?1:interpolate(frame,[.62*fps*speed,1.06*fps*speed],[0,1],ease);
  const exit=still?0:interpolate(frame,[block.durationFrames-.24*fps*speed,block.durationFrames-1],[0,1],clamp);
  const fontSize=useDisplaySize(copy.headline,arabic,style.headline_font);
  return <div data-flow-headline={block.startFrame} style={{position:'absolute',inset:0,pointerEvents:'none'}}>
    {style.overlay && <div aria-hidden="true" style={{position:'absolute',left:0,right:0,top:0,height:760,zIndex:14,
      background:`linear-gradient(180deg,${palette.background}c4 0%,${palette.background}90 45%,${palette.background}00 100%)`}}/>}
    {style.show_grid && <div aria-hidden="true" style={{position:'absolute',left:50,right:50,top:190,height:370,opacity:.12,zIndex:15,
      backgroundImage:`radial-gradient(circle,${palette.ink} 2px,transparent 3px),linear-gradient(${palette.ink}55 1px,transparent 1px),linear-gradient(90deg,${palette.ink}55 1px,transparent 1px)`,
      backgroundSize:'90px 90px',maskImage:'radial-gradient(ellipse,#000 20%,transparent 75%)'}}/>}
    <div style={{position:'absolute',left:70,right:70,top:style.headline_position==='center'?650:155,zIndex:18,textAlign:'center',color:palette.ink,opacity:1-exit}}>
      <div data-flow-kicker="true" dir={textDirection(copy.kicker)} style={{fontFamily:'ReferencePlex, Arial, sans-serif',fontWeight:400,
        fontSize:42,lineHeight:1.45,minHeight:61,opacity:kicker,translate:`0px ${(1-kicker)*-18}px`}}>{copy.kicker}</div>
      <div data-flow-display="true" dir={arabic?'rtl':'ltr'} style={{fontFamily:serif?(arabic?'ReferenceAmiri, serif':'FlowDisplay, Bodoni MT, Times New Roman, serif'):style.headline_font==='mono'?'Courier New, monospace':'ReferencePlex, Arial, sans-serif',
        fontStyle:serif&&!arabic?'italic':'normal',fontWeight:serif&&!arabic?400:700,fontSize,lineHeight:serif&&arabic?1.5:1.12,whiteSpace:'nowrap',
        position:'absolute',left:0,right:0,top:84,
        letterSpacing:serif&&!arabic?'-.045em':0,color:style.headline_color==='ink'?palette.ink:block.flowAccent,
        opacity:enter,translate:`${blur?(1-enter)*84-exit*60:0}px ${(blur||style.headline_motion==='rise')?(1-enter)*34:0}px`,
        scale:blur?1+(1-enter)*.17:style.headline_motion==='scale'?.86+enter*.14:1,
        filter:`blur(${blur?(1-enter)*22+exit*8:0}px)`}}>{copy.headline}</div>
      <div data-flow-support="true" dir={textDirection(copy.support)} style={{fontFamily:'ReferencePlex, Arial, sans-serif',fontWeight:400,
        fontSize:46,lineHeight:1.5,position:'absolute',left:0,right:0,top:serif&&arabic?400:330,opacity:support,translate:`0px ${(1-support)*25}px`,
        filter:`blur(${blur?(1-support)*13:0}px)`}}>{copy.support}</div>
    </div>
  </div>;
};

export const FlowHeadlines:React.FC<{blocks:any[]}>=({blocks})=>{
  const {fps}=useVideoConfig();
  return <>{blocks.filter(block=>getFlowFinishing(block).headlines).map(block=><Sequence key={block.startFrame} name="Display headline" from={block.startFrame}
    durationInFrames={block.durationFrames} premountFor={fps}>
    <Headline block={block}/>
  </Sequence>)}</>;
};
