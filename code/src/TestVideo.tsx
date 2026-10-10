import React from "react";
import { OffthreadVideo, staticFile } from "remotion";

export const TestVideo: React.FC = () => {
  return (
    <div style={{ width: 1080, height: 1920, backgroundColor: "#000" }}>
      <OffthreadVideo
        src={staticFile("gta_background.mp4")}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
        }}
      />
    </div>
  );
};
