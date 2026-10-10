import React from "react";
import { Composition } from "remotion";
import { MainVideo } from "./MainVideo";
import { TestWord } from "./TestWord";
import { TestVideo } from "./TestVideo";
import { TestGameBlock } from "./TestGameBlock";
import timelineData from "./timeline.json";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="MainVideo"
        component={MainVideo}
        durationInFrames={timelineData.totalFrames}
        fps={timelineData.fps}
        width={1080}
        height={1920}
      />
      <Composition
        id="TestWord"
        component={TestWord}
        durationInFrames={30}
        fps={30}
        width={1080}
        height={1920}
      />
      <Composition
        id="TestVideo"
        component={TestVideo}
        durationInFrames={30}
        fps={30}
        width={1080}
        height={1920}
      />
      <Composition
        id="TestGameBlock"
        component={TestGameBlock}
        durationInFrames={30}
        fps={30}
        width={1080}
        height={1920}
      />
    </>
  );
};
