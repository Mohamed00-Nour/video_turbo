import React from "react";
import { useCurrentFrame } from "remotion";
import { LoopingVideo } from "./LoopingVideo";

interface HookBlockProps {
  durationFrames: number;
  gtaOffset: number;
  bgDurationFrames?: number;
}

export const HookBlock: React.FC<HookBlockProps> = ({
  durationFrames,
  gtaOffset,
  bgDurationFrames,
}) => {
  const frame = useCurrentFrame();
  const zoom = 1.0 + 0.08 * (frame / Math.max(1, durationFrames));

  return (
    <div
      style={{
        position: "relative",
        width: 1080,
        height: 1920,
        backgroundColor: "#000",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: 1080,
          height: 1920,
          overflow: "hidden",
          transform: `scale(${zoom})`,
          transformOrigin: "center center",
        }}
      >
        <LoopingVideo
          src="gta_background.mp4"
          offsetSeconds={gtaOffset}
          durationFrames={bgDurationFrames}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
        />
      </div>
    </div>
  );
};
