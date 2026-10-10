import React from "react";
import { OffthreadVideo, staticFile, useCurrentFrame } from "remotion";
import { FlashTransition } from "./FlashTransition";

export const EndingBlock: React.FC = () => {
  const frame = useCurrentFrame();

  // 6 rapid cuts, 5 frames (0.167s) each:
  // Cut 0 (frames 0-4): GTA offset 1.5s
  // Cut 1 (frames 5-9): GTA offset 3.5s
  // Cut 2 (frames 10-14): GTA offset 5.5s
  // Cut 3 (frames 15-19): GTA offset 7.5s
  // Cut 4 (frames 20-24): GTA offset 9.5s
  // Cut 5 (frames 25-29): Hold on last frame (offset 11.5s)
  const cuts = [
    { start: 0, end: 5, offset: 1.5, freeze: false },
    { start: 5, end: 10, offset: 3.5, freeze: false },
    { start: 10, end: 15, offset: 5.5, freeze: false },
    { start: 15, end: 20, offset: 7.5, freeze: false },
    { start: 20, end: 25, offset: 9.5, freeze: false },
    { start: 25, end: 30, offset: 11.5, freeze: true },
  ];

  let currentCut = cuts[cuts.length - 1];
  for (const cut of cuts) {
    if (frame >= cut.start && frame < cut.end) {
      currentCut = cut;
      break;
    }
  }

  // Calculate startFrom frame for this cut
  const baseOffsetFrame = Math.round(currentCut.offset * 30);
  const frameInCut = currentCut.freeze ? 0 : frame - currentCut.start;
  const startFrom = baseOffsetFrame + frameInCut;

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

      {/* Flash transition on block start */}
      <FlashTransition frameInBlock={frame} />
    </div>
  );
};
