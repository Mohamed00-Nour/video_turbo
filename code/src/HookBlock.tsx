import React from "react";
import { OffthreadVideo, staticFile, useCurrentFrame } from "remotion";

interface HookBlockProps {
  durationFrames: number;
  gtaOffset: number;
}

export const HookBlock: React.FC<HookBlockProps> = ({
  durationFrames,
  gtaOffset,
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
          src={staticFile("gta_background.mp4")}
          startFrom={startFrom}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
          muted
        />
      </div>
    </div>
  );
};
