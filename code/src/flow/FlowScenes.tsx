import React from 'react';
import {Easing, Freeze, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {getFlowFinishing} from './flowStyle';

const clamp = {extrapolateLeft:'clamp' as const,extrapolateRight:'clamp' as const};
export const flowHandoffFrames = (previous:any, next:any, fps:number) => getFlowFinishing(next).transition==='cut'?0:Math.max(0,
  Math.min(Math.round(getFlowFinishing(next).transition_seconds*fps),Math.floor(previous.durationFrames/3),Math.floor(next.durationFrames/3)));

const Clip: React.FC<{block:any}> = ({block}) => {
  const {fps} = useVideoConfig();
  return <OffthreadVideo src={staticFile(block.media.src)} muted startFrom={Math.round((block.offset_seconds ?? 0)*fps)}
    style={{width:'100%',height:'100%',objectFit:block.fit ?? 'cover'}}/>;
};

const FlowScene: React.FC<{block:any; incoming:number}> = ({block,incoming}) => {
  const frame = useCurrentFrame();
  const style=getFlowFinishing(block);
  const enter = incoming>1 ? interpolate(frame,[0,incoming-1],[0,1],{...clamp,easing:Easing.bezier(.4,0,.2,1)}) : 1;
  // Hold only the outgoing tail; never read past the imported clip or move narration.
  return <div data-flow-scene={block.startFrame} data-flow-held={frame>=block.durationFrames} style={{position:'absolute',inset:0,opacity:enter,
    translate:style.transition==='slide'?`${(1-enter)*120}px 0px`:undefined,
    scale:style.transition==='blur'?1+(1-enter)*.045:1,filter:`blur(${style.transition==='blur'?(1-enter)*9:0}px)`,background:block.flowPalette?.background || '#f4f4f2'}}>
    {frame < block.durationFrames ? <Clip block={block}/> :
      <Freeze frame={block.durationFrames-1}><Clip block={block}/></Freeze>}
  </div>;
};

export const FlowScenes: React.FC<{blocks:any[]}> = ({blocks}) => {
  const {fps} = useVideoConfig();
  return <>{blocks.map((block,index)=>{
    const incoming = index ? flowHandoffFrames(blocks[index-1],block,fps) : 0;
    const outgoing = index+1<blocks.length ? flowHandoffFrames(block,blocks[index+1],fps) : 0;
    return <Sequence name={block.title} key={block.startFrame} from={block.startFrame}
      durationInFrames={block.durationFrames+outgoing} premountFor={fps}>
      <FlowScene block={block} incoming={incoming}/>
    </Sequence>;
  })}</>;
};
