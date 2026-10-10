import React from "react";
import "./font.css";

export const TestWord: React.FC = () => {
  return (
    <div
      style={{
        width: 1080,
        height: 1920,
        backgroundColor: "#111111",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <svg
        width="1080"
        height="400"
        viewBox="0 0 1080 400"
        style={{ overflow: "visible" }}
      >
        <defs>
          <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow
              dx="0"
              dy="0"
              stdDeviation="6"
              floodColor="#FD40FF"
              floodOpacity="0.5"
            />
          </filter>
        </defs>
        <text
          x="540"
          y="230"
          textAnchor="middle"
          direction="rtl"
          filter="url(#glow)"
          style={{
            fontFamily: "Lalezar, sans-serif",
            fontSize: "90px",
            fill: "#FFFFFF",
            stroke: "#FD40FF",
            strokeWidth: "15px",
            strokeLinejoin: "round",
            paintOrder: "stroke fill",
          }}
        >
          الأسطورية
        </text>
      </svg>
    </div>
  );
};
