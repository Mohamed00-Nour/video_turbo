import React from "react";
import { Img, interpolate, staticFile, useCurrentFrame } from "remotion";

interface SceneProps {
  durationFrames: number;
  block: any;
}

export const ZeroRansomScene: React.FC<SceneProps> = ({ durationFrames, block }) => {
  const frame = useCurrentFrame();
  const progress = frame / Math.max(1, durationFrames);

  // Entrance
  const fadeIn = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });

  // Hologram rotation & pulse
  const rot = (frame * 1.5) % 360;
  const glitch = frame % 28 < 3 ? (Math.random() - 0.5) * 12 : 0;
  const pulse = 1 + 0.04 * Math.sin(frame * 0.25);

  return (
    <div
      style={{
        position: "relative",
        width: 1080,
        height: 1920,
        backgroundColor: "#060912",
        overflow: "hidden",
        fontFamily: "'Courier New', monospace",
        color: "#fff",
      }}
    >
      {/* Background Matrix / Hex Hologram Grid */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "radial-gradient(circle at 50% 50%, rgba(0, 240, 255, 0.12) 0%, rgba(6, 9, 18, 0.98) 80%)",
        }}
      />

      {/* Top ANSSI / Forensic Header Bar */}
      <div
        style={{
          position: "absolute",
          top: 80,
          left: 80,
          right: 80,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderBottom: "1px solid rgba(0, 240, 255, 0.3)",
          paddingBottom: 16,
          opacity: fadeIn,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontSize: 28 }}>🛡️</span>
          <span style={{ fontSize: 24, letterSpacing: 2, color: "#00f0ff", fontWeight: "bold" }}>
            ANSSI // CYBERCRIME INVESTIGATION
          </span>
        </div>
        <div
          style={{
            fontSize: 20,
            letterSpacing: 2,
            padding: "6px 16px",
            borderRadius: 6,
            backgroundColor: "rgba(255, 0, 85, 0.2)",
            border: "1px solid #ff0055",
            color: "#ff0055",
            fontWeight: "bold",
          }}
        >
          CLASSIFIED DOSSIER
        </div>
      </div>

      {/* Main Arabic Mystery Banner */}
      <div
        dir="rtl"
        style={{
          position: "absolute",
          top: 170,
          left: 80,
          right: 80,
          background: "linear-gradient(90deg, rgba(255,0,85,0.25), rgba(15,20,35,0.9), rgba(0,240,255,0.25))",
          border: "2px solid #00f0ff",
          borderRadius: 20,
          padding: "16px 30px",
          textAlign: "center",
          fontFamily: "Lalezar, sans-serif",
          fontSize: 52,
          color: "#ffffff",
          textShadow: "0 0 20px #00f0ff",
          opacity: fadeIn,
        }}
      >
        لغز محير: لا طلب فدية ولا إعلان مسؤولية! 🕵️‍♂️
      </div>

      {/* Hero Hologram Visual Card */}
      <div
        style={{
          position: "absolute",
          top: 300,
          left: 80,
          width: 920,
          height: 600,
          borderRadius: 24,
          overflow: "hidden",
          border: "2px solid rgba(255, 0, 85, 0.5)",
          boxShadow: "0 20px 60px rgba(255, 0, 85, 0.3), inset 0 0 30px rgba(0,0,0,0.8)",
          opacity: fadeIn,
          transform: `scale(${pulse}) translateX(${glitch}px)`,
        }}
      >
        <Img
          src={staticFile("sections/media/cyber_mystery.png")}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />

        {/* Circular Radar Tech Overlay */}
        <div
          style={{
            position: "absolute",
            top: 20,
            right: 20,
            width: 70,
            height: 70,
            borderRadius: "50%",
            border: "2px dashed #00f0ff",
            transform: `rotate(${rot}deg)`,
          }}
        />

        {/* Hologram Status Tag */}
        <div
          style={{
            position: "absolute",
            bottom: 20,
            left: 20,
            right: 20,
            padding: "12px 20px",
            backgroundColor: "rgba(0, 0, 0, 0.8)",
            borderRadius: 12,
            border: "1px solid rgba(0, 240, 255, 0.4)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span style={{ fontSize: 20, color: "#ff0055", fontWeight: "bold" }}>
            MOTIVE: UNKNOWN (ZERO RANSOM)
          </span>
          <span style={{ fontSize: 18, color: "#00f0ff" }}>TARGET: CRITICAL INFRASTRUCTURE</span>
        </div>
      </div>

      {/* Forensic Comparison Badges */}
      <div
        style={{
          position: "absolute",
          top: 940,
          left: 80,
          right: 80,
          display: "flex",
          gap: 20,
          opacity: fadeIn,
        }}
      >
        {/* Ransom Demanded: $0 */}
        <div
          style={{
            flex: 1,
            backgroundColor: "rgba(10, 18, 30, 0.9)",
            border: "2px solid rgba(0, 240, 255, 0.4)",
            borderRadius: 18,
            padding: "20px 24px",
          }}
        >
          <div style={{ fontSize: 18, color: "rgba(255,255,255,0.6)" }}>RANSOMWARE DEMAND</div>
          <div style={{ fontSize: 44, fontWeight: "900", color: "#00ff88", marginTop: 6 }}>$0.00</div>
          <div style={{ fontSize: 18, color: "#00ff88", marginTop: 4 }}>❌ لم تُطلب أي فدية نهائياً</div>
        </div>

        {/* Claim of Responsibility: None */}
        <div
          style={{
            flex: 1,
            backgroundColor: "rgba(10, 18, 30, 0.9)",
            border: "2px solid rgba(255, 0, 85, 0.4)",
            borderRadius: 18,
            padding: "20px 24px",
          }}
        >
          <div style={{ fontSize: 18, color: "rgba(255,255,255,0.6)" }}>RESPONSIBILITY CLAIM</div>
          <div style={{ fontSize: 44, fontWeight: "900", color: "#ff0055", marginTop: 6 }}>NONE</div>
          <div style={{ fontSize: 18, color: "#ff4477", marginTop: 4 }}>❌ لم تعلن أي جهة مسؤوليتها</div>
        </div>
      </div>

      {/* Chilling Message Callout */}
      <div
        dir="rtl"
        style={{
          position: "absolute",
          top: 1140,
          left: 80,
          right: 80,
          backgroundColor: "rgba(255, 0, 85, 0.15)",
          border: "2px solid #ff0055",
          borderRadius: 20,
          padding: "20px 30px",
          boxShadow: "0 10px 40px rgba(255, 0, 85, 0.3)",
          opacity: fadeIn,
        }}
      >
        <div
          style={{
            fontFamily: "Lalezar, sans-serif",
            fontSize: 42,
            color: "#ffffff",
            textAlign: "center",
            textShadow: "0 0 20px #ff0055",
          }}
        >
          كأن الرسالة: "إحنا نقدر نوقف أي حاجة.. في أي وقت!"
        </div>
      </div>

      {/* Threat Assessment Footer */}
      <div
        style={{
          position: "absolute",
          top: 1280,
          left: 80,
          right: 80,
          padding: "16px 24px",
          backgroundColor: "rgba(0, 0, 0, 0.7)",
          borderLeft: "4px solid #ffaa00",
          borderRadius: 12,
          fontSize: 20,
          color: "#ffcc00",
          opacity: fadeIn,
        }}
      >
        <div>&gt; ASSESSMENT: PURE POWER DEMONSTRATION OR NATION-STATE SABOTAGE</div>
      </div>
    </div>
  );
};
