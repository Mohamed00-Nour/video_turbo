import React from 'react';
import {Easing, interpolate, useVideoConfig} from 'remotion';
import {CaptionWords, textDirection} from '../captionText';
import {getFlowFinishing} from './flowStyle';

export type FlowWord = {word:string; startFrame:number; endFrame:number};
const clamp = {extrapolateLeft:'clamp' as const, extrapolateRight:'clamp' as const};

export const FlowCaption: React.FC<{words:FlowWord[]; activeWord:FlowWord; block:any; frame:number}> = ({words,activeWord,block,frame}) => {
  const {fps} = useVideoConfig();
  const localWords = words.filter(w => w.endFrame > block.startFrame && w.startFrame < block.startFrame + block.durationFrames);
  const index = localWords.indexOf(activeWord);
  if (index < 0) return null;
  const group = localWords.slice(Math.floor(index / 4) * 4, Math.floor(index / 4) * 4 + 4);
  const start = Math.max(block.startFrame, group[0].startFrame);
  const age = frame - start;
  const entrance = Math.max(2, Math.min(.24 * fps, (group[group.length - 1].endFrame - start) / 3));
  const enter = interpolate(age, [0, entrance], [0, 1], {...clamp, easing:Easing.bezier(.16,1,.3,1)});
  const accent = block.flowAccent || '#777777';
  const palette=block.flowPalette || {background:'#f4f4f2',ink:'#171717'};
  const panel=getFlowFinishing(block).caption_style==='panel';
  const direction = textDirection(group.map(w => w.word).join(' '));
  return <div data-flow-caption={start} dir={direction} style={{position:'absolute',left:78,right:78,
    top:(block.captionY ?? .8)*1920,zIndex:50,textAlign:'center',pointerEvents:'none',
    fontFamily:direction==='rtl'?'ReferencePlex, Lalezar, sans-serif':'Arial, sans-serif',fontWeight:700,
    fontSize:62,lineHeight:1.65,translate:`0px ${(1-enter)*26}px`,scale:.94+enter*.06,
    opacity:.25+enter*.75,filter:`blur(${(1-enter)*7}px)`}}>
    <div style={{display:'inline-block',maxWidth:'100%',padding:'10px 24px 14px',borderRadius:18,
      background:panel?(palette.caption_background || palette.background)+'ed':'transparent',border:panel?'1px solid #ffffff55':'none',boxShadow:panel?'0 12px 40px #00000026':'none',
      borderBottom:panel?`4px solid ${accent}`:'none'}}>
      <CaptionWords words={group} wordStyle={i=>{
        const wordAge = frame - group[i].startFrame;
        const lift = group[i]===activeWord ? interpolate(wordAge,[0,.14*fps],[1,0],clamp) : 0;
        const reveal = interpolate(age-i*.025*fps,[0,entrance],[0,1],clamp);
        return {display:'inline-block',margin:'0 5px',color:group[i]===activeWord?accent:palette.ink,
          opacity:group[i].startFrame>frame?.48:1,translate:`0px ${(1-reveal)*12-lift*5}px`,
          scale:1+lift*.07,transformOrigin:'center 70%',unicodeBidi:'isolate'};
      }}/>
    </div>
  </div>;
};
