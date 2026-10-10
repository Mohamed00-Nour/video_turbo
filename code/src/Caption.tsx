import React from "react";
import timelineData from "./timeline.json";

interface WordData {
  word: string;
  start: number;
  end: number;
  startFrame: number;
  endFrame: number;
}

interface CaptionProps {
  currentFrame: number;
}

export const Caption: React.FC<CaptionProps> = ({ currentFrame }) => {
  // Determine if captions should be displayed at this frame
  const { blocks, words } = timelineData;

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

  if (!currentBlock) return null;

  // Captions are shown for the whole video (hook, game blocks and CTA).

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
  const yCenter =
    currentBlock.type === "hook" ? 883 : currentBlock.type === "game" ? 1205 : 1382;

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
            transition: "transform 0.05s ease-out",
          }}
        >
          <text
            x="540"
            y={yCenter}
            textAnchor="middle"
            dominantBaseline="central"
            direction="rtl"
            filter="url(#caption-glow)"
            style={{
              fontFamily: "Lalezar, sans-serif",
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
