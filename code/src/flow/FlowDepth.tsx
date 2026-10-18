import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {getFlowFinishing} from './flowStyle';

// Large defocused corner forms, animated on one continuous clock across scenes.
export const FlowDepth: React.FC<{accent:string; profile?:any}> = ({accent,profile}) => {
  const frame=useCurrentFrame();
  const {fps}=useVideoConfig();
  const time=frame/fps;
  const style=getFlowFinishing({flowFinishing:profile});
  if(style.depth_motif==='none')return null;
  const shape=style.depth_motif==='arrows'?'M90 350H590M390 140L600 350 390 560':style.depth_motif==='orbits'?'M350 70a280 280 0 1 0 0 560a280 280 0 1 0 0-560':'M350 70V630M107 210L593 490M107 490L593 210';
  return <div data-flow-depth="true" aria-hidden="true" style={{position:'absolute',inset:0,pointerEvents:'none',overflow:'hidden',zIndex:16}}>
    <svg data-depth="far" data-corner="upper-right" width="720" height="720" viewBox="0 0 700 700" style={{position:'absolute',
      right:-280+Math.sin(time*.4)*45,top:-230+Math.cos(time*.32)*45,opacity:style.depth_opacity,
      rotate:`${-18+Math.sin(time*.23)*13}deg`,filter:`blur(${style.depth_blur}px)`}}>
      <path d={shape} fill="none" stroke={accent} strokeWidth={style.depth_motif==='orbits'?20:88} strokeLinecap="round"/>
    </svg>
    <svg data-depth="near" data-corner="lower-left" width="800" height="800" viewBox="0 0 700 700" style={{position:'absolute',
      left:-360+Math.cos(time*.29)*45,bottom:-310+Math.sin(time*.48)*65,opacity:style.depth_opacity*.49/.53,
      rotate:`${24+Math.sin(time*.19)*18}deg`,filter:`blur(${style.depth_blur+7}px)`}}>
      <path d={shape} fill="none" stroke={accent} strokeWidth={style.depth_motif==='orbits'?25:95} strokeLinecap="round"/>
    </svg>
    <div data-depth="middle" style={{position:'absolute',width:460,height:460,border:`12px solid ${accent}`,
      borderRadius:'50%',right:-310+Math.sin(time*.21)*55,top:850+Math.cos(time*.38)*180,
      opacity:.13,filter:'blur(12px)',scale:1+Math.sin(time*.33)*.13}}/>
  </div>;
};
