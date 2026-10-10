import React from "react";
import { Series, useCurrentFrame } from "remotion";
import "./font.css";
import timelineData from "./timeline.json";
import { HookBlock } from "./HookBlock";
import { GameBlock } from "./GameBlock";
import { CtaBlock } from "./CtaBlock";
import { Caption } from "./Caption";

export const MainVideo: React.FC = () => {
  const currentFrame = useCurrentFrame();
  const { blocks } = timelineData;

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
      <Series>
        {blocks.map((block: any, index: number) => {
          if (block.type === "hook") {
            return (
              <Series.Sequence
                key={index}
                durationInFrames={block.durationFrames}
              >
                <HookBlock
                  durationFrames={block.durationFrames}
                  gtaOffset={block.gtaOffset}
                />
              </Series.Sequence>
            );
          } else if (block.type === "game") {
            return (
              <Series.Sequence
                key={index}
                durationInFrames={block.durationFrames}
              >
                <GameBlock
                  durationFrames={block.durationFrames}
                  gtaOffset={block.gtaOffset}
                  bgVideo={block.bgVideo}
                  folder={block.folder}
                  title={block.title}
                  topClip={block.topClip}
                  bottomClip={block.bottomClip}
                  logo={block.logo}
                  hasLogo={block.hasLogo}
                  reveal={block.reveal}
                  logoEffect={block.logoEffect}
                  bgBlurScale={(timelineData as any).style?.bgBlurScale}
                />
              </Series.Sequence>
            );
          } else if (block.type === "cta") {
            return (
              <Series.Sequence
                key={index}
                durationInFrames={block.durationFrames}
              >
                <CtaBlock
                  durationFrames={block.durationFrames}
                  gtaOffset={block.gtaOffset}
                  bgVideo={block.bgVideo}
                />
              </Series.Sequence>
            );
          }
          return null;
        })}
      </Series>

      {/* Global Caption Overlay */}
      <Caption currentFrame={currentFrame} />
    </div>
  );
};
