import React from "react";
import { Easing, interpolate, OffthreadVideo, staticFile, useCurrentFrame } from "remotion";
import { FlashTransition } from "./FlashTransition";
import { getHandshake } from "./handshake";

interface GameBlockProps {
  durationFrames: number;
  gtaOffset: number;
  bgVideo?: string;
  folder: string;
  title: string;
  topClip: string;
  bottomClip: string;
  logo: string;
  hasLogo: boolean;
  // New: provided by build_video.py through timeline.json (all optional)
  reveal?: { durationFrames?: number };
  logoEffect?: { amplitude?: number; speed?: number; frequency?: number };
  bgBlurScale?: number;
}

// The original background blur was 5px. build_video.py multiplies it by
// timeline.style.bgBlurScale (0.6 -> 3px). Change BG_BLUR_SCALE in the .py to tune.
const BASE_BG_BLUR = 5;
// Clips wait this many frames at the center so the white flash can fade first
const REVEAL_DELAY = 4;
const LOGO_STRIPS = 40;
const LOGO_APPROX_HEIGHT = 280;

export const GameBlock: React.FC<GameBlockProps> = ({
  durationFrames,
  gtaOffset,
  bgVideo = "gta_background.mp4",
  title,
  topClip,
  bottomClip,
  logo,
  hasLogo,
  reveal: revealCfg,
  logoEffect,
  bgBlurScale = 0.6,
}) => {
  const frame = useCurrentFrame();
  const zoom = 1.0 + 0.08 * (frame / Math.max(1, durationFrames));
  const startFrom = Math.round(gtaOffset * 30);

  // ---- Reveal: both clips start stacked at the center, then slide out ----
  // Quick, clean ease-out (no overshoot/bounce).
  const REVEAL_DURATION = revealCfg?.durationFrames ?? 14; // frames
  const revealEnd = REVEAL_DELAY + REVEAL_DURATION;
  const reveal = interpolate(frame, [REVEAL_DELAY, revealEnd], [0, 1], {
    easing: Easing.out(Easing.cubic),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const topRestY = 220;
  const bottomRestY = 1300;
  const centerY = 720; // center of screen minus half card height

  const topY = centerY + (topRestY - centerY) * reveal;
  const bottomY = centerY + (bottomRestY - centerY) * reveal;

  // Handshake keeps running after the reveal; eased in so it doesn't jump on.
  const shakeAmount = interpolate(frame, [revealEnd - 4, revealEnd + 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const hsTop = getHandshake(frame, 0);
  const hsBot = getHandshake(frame, 2.5);
  const shakeTop = { dx: hsTop.dx * shakeAmount, dy: hsTop.dy * shakeAmount, rot: hsTop.rot * shakeAmount };
  const shakeBot = { dx: hsBot.dx * shakeAmount, dy: hsBot.dy * shakeAmount, rot: hsBot.rot * shakeAmount };

  // Gentle floating motion for the logo as a whole
  const logoT = frame / 30;
  const logoWiggleX = Math.sin(logoT * 3.0) * 4 + Math.sin(logoT * 7.2) * 1.5;
  const logoWiggleY = Math.cos(logoT * 2.5) * 5 + Math.cos(logoT * 6.1) * 2;
  const logoWiggleRot = Math.sin(logoT * 2.0) * 1.5 + Math.cos(logoT * 5.5) * 0.6;

  // Logo entrance (same blur/scale keyframes as before) - starts while the clips
  // are opening, so it is visible instead of hiding under the white flash.
  const logoStart = REVEAL_DELAY + 5;
  const lf = frame - logoStart;
  const logoKeys = [0, 1, 2, 3, 4, 5, 6, 7, 8];
  const logoBlur = interpolate(lf, logoKeys, [20, 16, 12, 8, 4, 1, 0, 0, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const logoScale = interpolate(lf, logoKeys, [0.6, 0.72, 0.84, 0.94, 1.02, 1.05, 1.03, 1.01, 1.0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const logoOpacity = interpolate(lf, [0, 3], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Wave: each horizontal slice of the logo is shifted sideways by a moving sine wave
  const waveAmp = logoEffect?.amplitude ?? 14;
  const waveSpeed = logoEffect?.speed ?? 0.18;
  const waveFreq = logoEffect?.frequency ?? 0.03; // radians per px
  const waveBreath = 0.85 + 0.15 * Math.sin(frame * 0.09);

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
      {/* Background with cinematic blur and push-in zoom */}
      <div
        style={{
          width: 1080,
          height: 1920,
          overflow: "hidden",
          transform: `scale(${zoom})`,
          transformOrigin: "center center",
          filter: `blur(${(BASE_BG_BLUR * bgBlurScale).toFixed(2)}px) brightness(0.88)`,
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

      {/* Top Clip: with Handshake effect and deep drop shadow */}
      <div
        style={{
          position: "absolute",
          left: 90,
          top: topY,
          width: 900,
          height: 480,
          borderRadius: 28,
          border: "2px solid rgba(0, 0, 0, 0.4)",
          boxShadow:
            "0 24px 50px rgba(0, 0, 0, 0.88), 0 8px 20px rgba(0, 0, 0, 0.65)",
          overflow: "hidden",
          transform: `translate(${shakeTop.dx}px, ${shakeTop.dy}px) rotate(${shakeTop.rot}deg)`,
          transformOrigin: "center center",
          zIndex: 10,
        }}
      >
        <OffthreadVideo
          src={staticFile(topClip)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
          muted
        />
      </div>

      {/* Bottom Clip: with independent Handshake effect and deep drop shadow */}
      <div
        style={{
          position: "absolute",
          left: 90,
          top: bottomY,
          width: 900,
          height: 480,
          borderRadius: 28,
          border: "2px solid rgba(0, 0, 0, 0.4)",
          boxShadow:
            "0 24px 50px rgba(0, 0, 0, 0.88), 0 8px 20px rgba(0, 0, 0, 0.65)",
          overflow: "hidden",
          transform: `translate(${shakeBot.dx}px, ${shakeBot.dy}px) rotate(${shakeBot.rot}deg)`,
          transformOrigin: "center center",
          zIndex: 10,
        }}
      >
        <OffthreadVideo
          src={staticFile(bottomClip)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
          }}
          muted
        />
      </div>

      {/* Logo: Centered at y ~50.5%, prominent with layered drop shadow */}
      <div
        style={{
          position: "absolute",
          top: "50.5%",
          left: "50%",
          transform: `translate(calc(-50% + ${logoWiggleX}px), calc(-50% + ${logoWiggleY}px)) scale(${logoScale}) rotate(${logoWiggleRot}deg)`,
          transformOrigin: "center center",
          filter: `blur(${logoBlur}px) drop-shadow(0 16px 32px rgba(0, 0, 0, 0.9)) drop-shadow(0 4px 10px rgba(0, 0, 0, 0.6))`,
          maxWidth: "72%",
          opacity: logoOpacity,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          zIndex: 20,
        }}
      >
        {hasLogo ? (
          <div style={{ display: "grid" }}>
            {Array.from({ length: LOGO_STRIPS }).map((_, i) => {
              const v = (i + 0.5) / LOGO_STRIPS;
              const dx =
                Math.sin(v * LOGO_APPROX_HEIGHT * waveFreq - frame * waveSpeed) *
                waveAmp *
                waveBreath;
              const top = (i / LOGO_STRIPS) * 100;
              const bottom = 100 - ((i + 1) / LOGO_STRIPS) * 100;
              return (
                <img
                  key={i}
                  src={staticFile(logo)}
                  alt={i === 0 ? title : ""}
                  style={{
                    gridArea: "1 / 1",
                    justifySelf: "center",
                    alignSelf: "center",
                    maxWidth: 780,
                    maxHeight: LOGO_APPROX_HEIGHT,
                    objectFit: "contain",
                    transform: `translateX(${dx}px)`,
                    // tiny overlap between slices avoids hairline gaps
                    clipPath: `inset(${Math.max(0, top - 0.2)}% 0 ${Math.max(0, bottom - 0.2)}% 0)`,
                  }}
                />
              );
            })}
          </div>
        ) : (
          <svg
            width="780"
            height="280"
            viewBox="0 0 780 280"
            style={{ overflow: "visible" }}
          >
            <defs>
              <filter id="logo-glow" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow
                  dx="0"
                  dy="0"
                  stdDeviation="8"
                  floodColor="#FD40FF"
                  floodOpacity="0.6"
                />
              </filter>
            </defs>
            <text
              x="390"
              y="140"
              textAnchor="middle"
              dominantBaseline="central"
              filter="url(#logo-glow)"
              style={{
                fontFamily: "Lalezar, sans-serif",
                fontSize: "140px",
                fill: "#FFFFFF",
                stroke: "#FD40FF",
                strokeWidth: "20px",
                strokeLinejoin: "round",
                paintOrder: "stroke fill",
              }}
            >
              {title}
            </text>
          </svg>
        )}
      </div>

      {/* Flash transition on block start */}
      <FlashTransition frameInBlock={frame} />
    </div>
  );
};
