import React from 'react';
import {Easing, interpolate, Sequence, useCurrentFrame, useVideoConfig} from 'remotion';
import {DirectedReferenceScene} from './DirectedReferenceScene';
import {scenePalette} from './visualStyle';

// Overlap after the boundary: narration and caption timestamps never move.
export const handoffFrames = (previous:any, next:any, fps:number) => Math.max(0,
  Math.min(Math.round(fps * (next.transition_style === 'cut' ? .24 : .4)),
    Math.floor(previous.durationFrames / 3), Math.floor(next.durationFrames / 3)));

const SceneLayer: React.FC<{block:any; incoming:number; outgoing:number}> = ({block,incoming,outgoing}) => {
  const frame=useCurrentFrame();
  const ease={extrapolateLeft:'clamp' as const,extrapolateRight:'clamp' as const,easing:Easing.bezier(.45,0,.2,1)};
  const enter=incoming>1?interpolate(frame,[0,incoming-1],[0,1],ease):1;
  const exit=outgoing>1?interpolate(frame,[block.durationFrames,block.durationFrames+outgoing-1],[0,1],ease):0;
  // Stagger focal content so two headings never dissolve over one another.
  const contentEnter=incoming>1?interpolate(frame,[(incoming-1)*.35,incoming-1],[0,1],ease):1;
  const contentExit=outgoing>1?interpolate(frame,[block.durationFrames,block.durationFrames+(outgoing-1)*.45],[0,1],ease):0;
  const wipe=block.transition_style==='wipe' && incoming>1;
  const drift=block.transition_style==='cut'?0:(1-enter)*36-exit*24;
  return <div data-reference-scene={block.startFrame} style={{position:'absolute',inset:0,
    background:scenePalette(block.referenceStyle,block).background,
    opacity:wipe?1:enter,clipPath:wipe?`inset(0 0 0 ${(1-enter)*100}%)`:undefined}}>
    <div style={{position:'absolute',inset:0,transform:`translateY(${drift}px) scale(${1+(1-enter)*.025+exit*.012})`}}>
      <DirectedReferenceScene block={block} visibility={contentEnter*(1-contentExit)}/>
    </div>
  </div>;
};

export const ReferenceScenes: React.FC<{blocks:any[]}> = ({blocks}) => {
  const {fps}=useVideoConfig();
  return <>{blocks.map((block,index)=>{
    const incoming=index?handoffFrames(blocks[index-1],block,fps):0;
    const outgoing=index+1<blocks.length?handoffFrames(block,blocks[index+1],fps):0;
    return <Sequence key={index} from={block.startFrame} durationInFrames={block.durationFrames+outgoing} premountFor={fps}>
      <SceneLayer block={block} incoming={incoming} outgoing={outgoing}/>
    </Sequence>;
  })}</>;
};
