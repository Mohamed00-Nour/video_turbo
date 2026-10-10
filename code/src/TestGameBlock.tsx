import React from "react";
import { OffthreadVideo, staticFile } from "remotion";
import "./font.css";

export const TestGameBlock: React.FC = () => {
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
      {/* GTA Background */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: 1080,
          height: 1920,
          overflow: "hidden",
        }}
      >
        <OffthreadVideo
          src={staticFile("gta_background.mp4")}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: "scale(1.02)",
          }}
          muted
        />
      </div>

      {/* Top Clip: x 10%-83%, y 14%-38% */}
      <div
        style={{
          position: "absolute",
          left: 108,
          top: 269,
          width: 788,
          height: 461,
          borderRadius: 24,
          border: "3px solid rgba(0,0,0,0.8)",
          boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
          overflow: "hidden",
        }}
      >
        <OffthreadVideo
          src={staticFile("games/01_DDLC/top.mp4")}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
          muted
        />
      </div>

      {/* Bottom Clip: x 10%-83%, y 68%-90% */}
      <div
        style={{
          position: "absolute",
          left: 108,
          top: 1306,
          width: 788,
          height: 422,
          borderRadius: 24,
          border: "3px solid rgba(0,0,0,0.8)",
          boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
          overflow: "hidden",
        }}
      >
        <OffthreadVideo
          src={staticFile("games/01_DDLC/bottom.mp4")}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
          muted
        />
      </div>

      {/* Logo centered at y ~51%, max width 60% */}
      <div
        style={{
          position: "absolute",
          top: "51%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          maxWidth: "60%",
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
        }}
      >
        <img
          src={staticFile("games/01_DDLC/logo.png")}
          alt="Game Logo"
          style={{
            maxWidth: 648,
            maxHeight: 250,
            objectFit: "contain",
            filter: "drop-shadow(0 6px 16px rgba(0,0,0,0.7))",
          }}
        />
      </div>
    </div>
  );
};
