import React from "react";
import timelineData from "./timeline.json";
import {scenePalette} from "./reference/visualStyle";
import {CaptionWords, textDirection} from "./captionText";

interface WordData {
  word: string;
  start: number;
  end: number;
  startFrame: number;
  endFrame: number;
}

interface CaptionProps {
  currentFrame: number;
  timeline?: typeof timelineData;
}

export const Caption: React.FC<CaptionProps> = ({ currentFrame, timeline=timelineData }) => {
  // Determine if captions should be displayed at this frame
  const { blocks, words } = timeline;

  // Find which block we are currently in
  let currentBlock: any = null;
  for (const block of blocks) {
    if (
      currentFrame >= block.startFrame &&
      currentFrame < block.startFrame + block.durationFrames
    ) {
      currentBlock = block;
      break;
    }
  }

  if (!currentBlock || currentBlock.captions === false) return null;

  if (currentBlock.type === "game" && timeline.captionsInGameBlocks === false) {
    return null;
  }

  // Find the word that is currently active
  let activeWord: WordData | null = null;
  for (const w of words as WordData[]) {
    if (currentFrame >= w.startFrame && currentFrame < w.endFrame) {
      activeWord = w;
      break;
    }
  }

  // If in ending block and no active word found, use the last word
  if (currentBlock.type === "ending" && !activeWord && words.length > 0) {
    activeWord = words[words.length - 1];
  }

  if (!activeWord) return null;

  if (currentBlock.layout === 'reference_style') {
    const style = currentBlock.referenceStyle;
    const localWords = (words as WordData[]).filter(w => w.endFrame > currentBlock.startFrame && w.startFrame < currentBlock.startFrame + currentBlock.durationFrames);
    const index = localWords.findIndex(w => w === activeWord);
    if (index < 0) return null;
    const group = style.caption_style === 'word' ? [activeWord] : localWords.slice(Math.floor(index / 4) * 4, Math.floor(index / 4) * 4 + 4);
    if(style.renderer_version >= 2){
      const palette=scenePalette(style,currentBlock);
      const age=Math.min(1,Math.max(0,(currentFrame-activeWord.startFrame)/3));
      return <div dir={textDirection(group.map(word=>word.word).join(' '))} style={{position:'absolute',left:85,right:85,top:(currentBlock.captionY ?? style.caption_y)*1920,textAlign:'center',fontFamily:'ReferencePlex, sans-serif',fontWeight:700,fontSize:style.caption_style==='word'?68:54,lineHeight:1.55,zIndex:50,translate:`0px ${(1-age)*8}px`}}>
        <div style={{display:'inline-block',maxWidth:'100%',padding:'7px 22px',borderRadius:12,background:palette.background+'e8',boxShadow:palette.dark?'0 8px 30px #0003':'0 8px 25px #00000008'}}>
          <CaptionWords words={group} wordStyle={i=>({color:group[i]===activeWord?palette.ink:palette.muted,margin:'0 7px',borderBottom:group[i]===activeWord?`3px solid ${style.accent}`:'3px solid transparent',paddingBottom:3})}/>
        </div>
      </div>;
    }
    return <div dir={textDirection(group.map(word=>word.word).join(' '))} style={{position:'absolute',left:100,right:100,top:style.caption_y*1920,textAlign:'center',fontFamily:'ReferencePlex, Lalezar, sans-serif',fontWeight:700,fontSize:53,lineHeight:1.6,zIndex:50}}>
      <div style={{display:'inline-block',maxWidth:'100%',padding:'8px 18px',borderRadius:20,backgroundColor:style.background+'ed',boxShadow:'0 8px 24px #00000008'}}>
      <CaptionWords words={group} wordStyle={i=>({color:group[i]===activeWord?style.accent:style.ink,opacity:group[i].startFrame > currentFrame ? .45 : 1,margin:'0 7px'})}/>
      </div>
    </div>;
  }

  // Calculate popup scale animation over 6 frames: 0.6 -> 1.12 -> 1.0
  const frameSinceWordStart = Math.max(0, currentFrame - activeWord.startFrame);
  let scale = 1.0;
  if (frameSinceWordStart === 0) scale = 0.6;
  else if (frameSinceWordStart === 1) scale = 0.75;
  else if (frameSinceWordStart === 2) scale = 0.95;
  else if (frameSinceWordStart === 3) scale = 1.08;
  else if (frameSinceWordStart === 4) scale = 1.12;
  else if (frameSinceWordStart === 5) scale = 1.05;
  else scale = 1.0;

  // Vertical position based on block type
  // Hook at ~46% height = 883px. CTA at ~72% height = 1382px.
  // Game blocks: just under the logo (logo is centered at ~970px), above the bottom clip.
  const fallbackY = currentBlock.type === "hook" ? 883 : currentBlock.type === "game" ? 1205 : 1382;
  const yCenter = typeof currentBlock.captionY === "number" ? currentBlock.captionY * 1920 : fallbackY;

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: 1080,
        height: 1920,
        pointerEvents: "none",
        zIndex: 50,
      }}
    >
      <svg
        width="1080"
        height="1920"
        viewBox="0 0 1080 1920"
        style={{
          overflow: "visible",
          width: "100%",
          height: "100%",
        }}
      >
        <defs>
          <filter id="caption-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow
              dx="0"
              dy="0"
              stdDeviation="6"
              floodColor="#FD40FF"
              floodOpacity="0.5"
            />
          </filter>
        </defs>
        <g
          style={{
            transform: `scale(${scale})`,
            transformOrigin: `540px ${yCenter}px`,
          }}
        >
          <text
            x="540"
            y={yCenter}
            textAnchor="middle"
            dominantBaseline="central"
            direction={textDirection(activeWord.word)}
            lang={textDirection(activeWord.word)==='ltr'?'en':undefined}
            filter="url(#caption-glow)"
            style={{
              fontFamily: textDirection(activeWord.word)==='ltr'?"Arial, sans-serif":"Lalezar, sans-serif",
              fontWeight: textDirection(activeWord.word)==='ltr'?700:undefined,
              unicodeBidi: "isolate",
              fontSize: "90px",
              fill: "#FFFFFF",
              stroke: "#FD40FF",
              strokeWidth: "15px",
              strokeLinejoin: "round",
              paintOrder: "stroke fill",
            }}
          >
            {activeWord.word}
          </text>
        </g>
      </svg>
    </div>
  );
};
