import React from "react";
import { useCurrentFrame } from "remotion";
import { LoopingVideo } from "./LoopingVideo";
import { FlashTransition } from "./FlashTransition";

interface CtaBlockProps {
  durationFrames: number;
  gtaOffset: number;
  bgDurationFrames?: number;
  bgVideo?: string;
}

export const CtaBlock: React.FC<CtaBlockProps> = ({
  durationFrames,
  gtaOffset,
  bgDurationFrames,
  bgVideo = "roblox.mp4",
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
          src={bgVideo}
          offsetSeconds={gtaOffset}
          durationFrames={bgDurationFrames}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
        />
      </div>

      {/* Flash transition on block start */}
      <FlashTransition frameInBlock={frame} />
    </div>
  );
};
