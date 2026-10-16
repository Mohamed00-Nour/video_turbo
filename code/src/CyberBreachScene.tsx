import React from "react";
import { Img, interpolate, staticFile, useCurrentFrame } from "remotion";

interface SceneProps {
  durationFrames: number;
  block: any;
}

export const CyberBreachScene: React.FC<SceneProps> = ({ durationFrames, block }) => {
  const frame = useCurrentFrame();
  const progress = frame / Math.max(1, durationFrames);

  // Entrance animation
  const fadeIn = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });
  const slideUp = interpolate(frame, [0, 15], [40, 0], { extrapolateRight: "clamp" });

  // Timecode simulation (02:44:18:frame)
  const sec = Math.floor(frame / 30);
  const msec = Math.floor((frame % 30) * 3.33);
  const timeStr = `02:44:${String(18 + sec).padStart(2, "0")}:${String(msec).padStart(2, "0")}`;

  // Counter animation: 0 -> 480 stores
  const storeCount = Math.floor(interpolate(frame, [10, 60], [0, 480], { extrapolateRight: "clamp" }));

  // Scanline laser movement
  const laserY = (frame * 12) % 600;

  // Blinking alert
  const alertBlink = Math.sin(frame * 0.4) > 0;

  return (
    <div
      style={{
        position: "relative",
        width: 1080,
        height: 1920,
        backgroundColor: "#050811",
        overflow: "hidden",
        fontFamily: "'Courier New', monospace",
        color: "#fff",
      }}
    >
      {/* Background Cyber Grid */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(to right, rgba(0, 240, 255, 0.05) 1px, transparent 1px), linear-gradient(to bottom, rgba(0, 240, 255, 0.05) 1px, transparent 1px)",
          backgroundSize: "60px 60px",
          opacity: 0.8,
        }}
      />

      {/* Vignette & scanlines */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "radial-gradient(circle at 50% 50%, transparent 40%, rgba(0,0,0,0.85) 100%)",
          pointerEvents: "none",
        }}
      />

      {/* Top CCTV HUD Bar */}
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
          <div
            style={{
              width: 18,
              height: 18,
              borderRadius: "50%",
              backgroundColor: alertBlink ? "#ff0055" : "#550011",
              boxShadow: alertBlink ? "0 0 16px #ff0055" : "none",
            }}
          />
          <span style={{ fontSize: 24, letterSpacing: 2, color: "#ff0055", fontWeight: "bold" }}>
            LIVE CCTV // CAM-04
          </span>
          <span style={{ fontSize: 22, color: "rgba(255,255,255,0.7)", marginLeft: 16 }}>{timeStr}</span>
        </div>
        <div
          style={{
            fontSize: 22,
            letterSpacing: 2,
            padding: "6px 16px",
            borderRadius: 6,
            backgroundColor: "rgba(255, 0, 85, 0.15)",
            border: "1px solid #ff0055",
            color: "#ff0055",
            fontWeight: "bold",
          }}
        >
          CRITICAL BREACH
        </div>
      </div>

      {/* Arabic Main Label Banner */}
      <div
        dir="rtl"
        style={{
          position: "absolute",
          top: 170,
          left: 80,
          right: 80,
          background: "linear-gradient(90deg, rgba(255,0,85,0.2), rgba(15,20,35,0.9), rgba(0,240,255,0.2))",
          border: "2px solid #ff0055",
          borderRadius: 20,
          padding: "16px 30px",
          textAlign: "center",
          fontFamily: "Lalezar, sans-serif",
          fontSize: 54,
          color: "#ffffff",
          textShadow: "0 0 20px #ff0055",
          opacity: fadeIn,
          transform: `translateY(${slideUp}px)`,
        }}
      >
        اختراق أنظمة التبريد في مئات السوبرماركتات 🇫🇷
      </div>

      {/* Main Center Holographic Card (The Attack Map) */}
      <div
        style={{
          position: "absolute",
          top: 300,
          left: 80,
          width: 920,
          height: 580,
          borderRadius: 24,
          overflow: "hidden",
          border: "2px solid rgba(0, 240, 255, 0.4)",
          boxShadow: "0 20px 60px rgba(0, 240, 255, 0.2), inset 0 0 30px rgba(0,0,0,0.8)",
          opacity: fadeIn,
          transform: `scale(${1 + 0.04 * progress})`,
        }}
      >
        <Img
          src={staticFile("sections/media/hacker_map.png")}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />

        {/* Moving Laser Scanner Line */}
        <div
          style={{
            position: "absolute",
            top: laserY,
            left: 0,
            right: 0,
            height: 4,
            background: "linear-gradient(90deg, transparent, #00f0ff, #ff0055, transparent)",
            boxShadow: "0 0 20px #00f0ff, 0 0 10px #ff0055",
          }}
        />

        {/* Corner HUD Tech Brackets */}
        <div style={{ position: "absolute", top: 12, left: 16, fontSize: 18, color: "#00f0ff", letterSpacing: 2 }}>
          SYS_ID: IOT-FR-CHILLER-NET
        </div>
        <div style={{ position: "absolute", bottom: 12, right: 16, fontSize: 18, color: "#ff0055", letterSpacing: 2 }}>
          STATUS: COMPROMISED [842 NODES]
        </div>
      </div>

      {/* Target Stores Badges (Carrefour & Intermarché) */}
      <div
        style={{
          position: "absolute",
          top: 920,
          left: 80,
          right: 80,
          display: "flex",
          gap: 20,
          justifyContent: "space-between",
          opacity: fadeIn,
        }}
      >
        {/* Carrefour Card */}
        <div
          style={{
            flex: 1,
            backgroundColor: "rgba(10, 18, 32, 0.85)",
            border: "2px solid rgba(0, 240, 255, 0.5)",
            borderRadius: 18,
            padding: "20px 24px",
            boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            gap: 16,
          }}
        >
          <div
            style={{
              width: 50,
              height: 50,
              borderRadius: "50%",
              backgroundColor: "rgba(0, 240, 255, 0.2)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 26,
            }}
          >
            🛒
          </div>
          <div>
            <div style={{ fontSize: 26, fontWeight: "bold", color: "#00f0ff", letterSpacing: 1 }}>CARREFOUR</div>
            <div style={{ fontSize: 18, color: "#ff4477", marginTop: 4 }}>80+ فروع مخترقة بالكامل</div>
          </div>
        </div>

        {/* Intermarche Card */}
        <div
          style={{
            flex: 1,
            backgroundColor: "rgba(10, 18, 32, 0.85)",
            border: "2px solid rgba(255, 0, 85, 0.5)",
            borderRadius: 18,
            padding: "20px 24px",
            boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            gap: 16,
          }}
        >
          <div
            style={{
              width: 50,
              height: 50,
              borderRadius: "50%",
              backgroundColor: "rgba(255, 0, 85, 0.2)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 26,
            }}
          >
            🏬
          </div>
          <div>
            <div style={{ fontSize: 26, fontWeight: "bold", color: "#ff0055", letterSpacing: 1 }}>INTERMARCHÉ</div>
            <div style={{ fontSize: 18, color: "#ff4477", marginTop: 4 }}>300+ فرع تحت السيطرة</div>
          </div>
        </div>
      </div>

      {/* Telemetry Counter & Progress Bar */}
      <div
        style={{
          position: "absolute",
          top: 1090,
          left: 80,
          right: 80,
          backgroundColor: "rgba(8, 12, 22, 0.9)",
          border: "1px solid rgba(0, 240, 255, 0.3)",
          borderRadius: 20,
          padding: "24px 30px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          opacity: fadeIn,
        }}
      >
        <div>
          <div style={{ fontSize: 20, color: "rgba(255,255,255,0.6)", letterSpacing: 1 }}>TOTAL SITES BREACHED</div>
          <div style={{ fontSize: 48, fontWeight: "900", color: "#00f0ff", marginTop: 4 }}>
            {storeCount} <span style={{ fontSize: 26, color: "#ff0055" }}>STORES</span>
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 20, color: "rgba(255,255,255,0.6)", letterSpacing: 1 }}>ATTACK VECTOR</div>
          <div style={{ fontSize: 26, fontWeight: "bold", color: "#ffaa00", marginTop: 8 }}>
            DANFOSS IOT EXPLOIT
          </div>
        </div>
      </div>

      {/* Terminal Monospace Stream at bottom */}
      <div
        style={{
          position: "absolute",
          top: 1250,
          left: 80,
          right: 80,
          padding: "16px 24px",
          backgroundColor: "rgba(0, 0, 0, 0.7)",
          borderLeft: "4px solid #00f0ff",
          borderRadius: 12,
          fontSize: 20,
          color: "#00f0ff",
          opacity: fadeIn,
        }}
      >
        <div>&gt; INJECTING OVERHEAT PAYLOAD TO COMMERCIAL FREEZERS...</div>
        <div style={{ color: "#ff0055", marginTop: 6 }}>
          &gt; EXECUTING SCRIPT: OVERRIDE_DEFROST_TEMP_TARGET(+50C)
        </div>
      </div>
    </div>
  );
};
