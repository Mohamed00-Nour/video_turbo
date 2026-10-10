import React from "react";

interface FlashTransitionProps {
  frameInBlock: number;
}

export const FlashTransition: React.FC<FlashTransitionProps> = ({
  frameInBlock,
}) => {
  if (frameInBlock < 0 || frameInBlock >= 6) return null;

  let opacity = 0;
  if (frameInBlock === 0 || frameInBlock === 1) {
    opacity = 1.0;
  } else if (frameInBlock === 2) {
    opacity = 0.8;
  } else if (frameInBlock === 3) {
    opacity = 0.6;
  } else if (frameInBlock === 4) {
    opacity = 0.4;
  } else if (frameInBlock === 5) {
    opacity = 0.2;
  }

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: 1080,
        height: 1920,
        backgroundColor: "#FFFFFF",
        opacity,
        pointerEvents: "none",
        zIndex: 100,
      }}
    />
  );
};
