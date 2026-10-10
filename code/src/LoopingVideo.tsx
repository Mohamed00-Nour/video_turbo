import React from "react";
import { Loop, OffthreadVideo, Sequence, staticFile, useVideoConfig } from "remotion";

interface LoopingVideoProps {
  src: string;
  durationFrames?: number;
  offsetSeconds?: number;
  style?: React.CSSProperties;
}

// Repeat short footage using frame-based timing, including the background offset.
export const LoopingVideo: React.FC<LoopingVideoProps> = ({
  src, durationFrames, offsetSeconds = 0, style,
}) => {
  const { fps } = useVideoConfig();
  const offset = Math.round(offsetSeconds * fps);
  if (!durationFrames) {
    return <OffthreadVideo src={staticFile(src)} startFrom={offset} style={style} muted />;
  }
  return (
    <Sequence from={-(offset % durationFrames)} layout="none">
      <Loop durationInFrames={durationFrames} layout="none">
        <OffthreadVideo src={staticFile(src)} style={style} muted />
      </Loop>
    </Sequence>
  );
};