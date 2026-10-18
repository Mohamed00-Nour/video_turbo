import React from "react";
import { Series, getRemotionEnvironment, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import {Audio} from "@remotion/media";
import {FlowScenes} from "./flow/FlowScenes";
import {FlowDepth} from "./flow/FlowDepth";
import {FlowHeadlines} from "./flow/FlowHeadlines";
import "./font.css";
import timelineData from "./timeline.json";
import { HookBlock } from "./HookBlock";
import { GameBlock } from "./GameBlock";
import { CtaBlock } from "./CtaBlock";
import { SectionBlock } from "./SectionBlock";
import { Caption } from "./Caption";
import {ReferenceScenes} from "./reference/ReferenceScenes";

export const MainVideo: React.FC<{timeline?:typeof timelineData}> = ({timeline=timelineData}) => {
  const currentFrame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const { blocks } = timeline;
  const flowFinish = blocks.length>0 && blocks.every((block:any)=>block.layout==='flow_clip' && block.flowFinish!==false);
  const flowAudio = (timeline as any).flowAudio;
  const movingReference=blocks.length>0 && blocks.every((block:any)=>block.layout==='reference_style' && block.referenceStyle?.renderer_version>=3);

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
      {flowFinish ? <FlowScenes blocks={blocks}/> : movingReference ? <ReferenceScenes blocks={blocks}/> : <Series>
        {blocks.map((block: any, index: number) => {
          if (block.type === "section") {
            return <Series.Sequence key={index} durationInFrames={block.durationFrames} premountFor={fps}>
              <SectionBlock block={block} blur={(timeline as any).style?.bgBlurScale ?? 0.6} />
            </Series.Sequence>;
          }
          if (block.type === "hook") {
            return (
              <Series.Sequence
                key={index}
                durationInFrames={block.durationFrames}
              >
                <HookBlock
                  durationFrames={block.durationFrames}
                  gtaOffset={block.gtaOffset}
                  bgDurationFrames={block.bgDurationFrames}
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
                  bgDurationFrames={block.bgDurationFrames}
                  bgVideo={block.bgVideo}
                  folder={block.folder}
                  title={block.title}
                  topClip={block.topClip}
                  topDurationFrames={block.topDurationFrames}
                  bottomDurationFrames={block.bottomDurationFrames}
                  bottomClip={block.bottomClip}
                  logo={block.logo}
                  hasLogo={block.hasLogo}
                  reveal={block.reveal}
                  logoEffect={block.logoEffect}
                  bgBlurScale={(timeline as any).style?.bgBlurScale}
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
                  bgDurationFrames={block.bgDurationFrames}
                  bgVideo={block.bgVideo}
                />
              </Series.Sequence>
            );
          }
          return null;
        })}
      </Series>}

      {flowFinish && <style>{`@font-face{font-family:ReferencePlex;src:url('${staticFile('reference-fonts/ibm-plex-sans-arabic-700.woff2')}');font-weight:700;font-style:normal;}@font-face{font-family:ReferencePlex;src:url('${staticFile('reference-fonts/ibm-plex-sans-arabic-400.woff2')}');font-weight:400;font-style:normal;}@font-face{font-family:ReferenceAmiri;src:url('${staticFile('reference-fonts/Amiri-Bold.ttf')}');font-weight:700;}@font-face{font-family:FlowDisplay;src:url('${staticFile('reference-fonts/Bodoni-Italic.ttf')}');font-style:italic;font-weight:400;}`}</style>}
      {flowFinish && <FlowHeadlines blocks={blocks}/>}
      {flowFinish && <FlowDepth accent={(blocks[0] as any).flowAccent || '#777777'} profile={(blocks[0] as any).flowFinishing}/>}
      {flowFinish && flowAudio && getRemotionEnvironment().isStudio && <>
        <Audio src={staticFile(flowAudio.voice)} premountFor={fps}/>
        <Audio src={staticFile(flowAudio.effects)} premountFor={fps}/>
      </>}

      {/* Global Caption Overlay */}
      <Caption currentFrame={currentFrame} timeline={timeline} />
    </div>
  );
};
