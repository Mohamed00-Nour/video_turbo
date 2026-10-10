import React from "react";
import { OffthreadVideo, staticFile, useCurrentFrame } from "remotion";
import { FlashTransition } from "./FlashTransition";

interface CtaBlockProps {
  durationFrames: number;
  gtaOffset: number;
  bgVideo?: string;
}

export const CtaBlock: React.FC<CtaBlockProps> = ({
  durationFrames,
  gtaOffset,
  bgVideo = "roblox.mp4",
}) => {
  const frame = useCurrentFrame();
  const zoom = 1.0 + 0.08 * (frame / Math.max(1, durationFrames));
  const startFrom = Math.round(gtaOffset * 30);

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
        <OffthreadVideo
          src={staticFile(bgVideo)}
          startFrom={startFrom}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
          muted
        />
      </div>

      {/* Flash transition on block start */}
      <FlashTransition frameInBlock={frame} />
    </div>
  );
};
