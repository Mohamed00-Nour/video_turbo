import React from "react";
import { Img, interpolate, staticFile, useCurrentFrame } from "remotion";

interface SceneProps {
  durationFrames: number;
  block: any;
}

export const ThermalMeltdownScene: React.FC<SceneProps> = ({ durationFrames, block }) => {
  const frame = useCurrentFrame();
  const progress = frame / Math.max(1, durationFrames);

  // Entrance
  const fadeIn = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });

  // Temperature animation: starts at -18°C and surges up to +50.0°C!
  const currentTemp = interpolate(frame, [5, 65], [-18, 50], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  }).toFixed(1);

  // Gauge bar fill percent: 0 -> 100%
  const gaugePercent = interpolate(frame, [5, 65], [10, 100], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Alarm bypass stamp appearance at frame 40
  const alarmBypassed = frame > 35;
  const alarmScale = interpolate(frame, [35, 42], [1.8, 1.0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Financial loss counter: €0 -> €10,000,000+
  const lossMillions = interpolate(frame, [45, 95], [0, 10], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  }).toFixed(1);

  // Warning pulse
  const pulse = 1 + 0.05 * Math.sin(frame * 0.3);

  return (
    <div
      style={{
        position: "relative",
        width: 1080,
        height: 1920,
        backgroundColor: "#0d0407",
        overflow: "hidden",
        fontFamily: "'Courier New', monospace",
        color: "#fff",
      }}
    >
      {/* Background Thermal Heat Waves / Gradients */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(circle at 50% 20%, rgba(255, 60, 0, 0.25) 0%, rgba(13, 4, 7, 0.95) 80%)",
        }}
      />

      {/* Emergency flashing strobe edge */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          border: "4px solid rgba(255, 30, 0, 0.6)",
          boxShadow: `inset 0 0 ${40 + 20 * Math.sin(frame * 0.4)}px rgba(255, 0, 0, 0.4)`,
          pointerEvents: "none",
        }}
      />

      {/* Top Emergency Status Bar */}
      <div
        style={{
          position: "absolute",
          top: 80,
          left: 80,
          right: 80,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderBottom: "1px solid rgba(255, 60, 0, 0.4)",
          paddingBottom: 16,
          opacity: fadeIn,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontSize: 32 }}>🔥</span>
          <span style={{ fontSize: 24, letterSpacing: 2, color: "#ff4422", fontWeight: "bold" }}>
            THERMAL RUNAWAY // OVERHEAT MODE
          </span>
        </div>
        <div
          style={{
            fontSize: 20,
            letterSpacing: 2,
            padding: "6px 16px",
            borderRadius: 6,
            backgroundColor: "rgba(255, 60, 0, 0.2)",
            border: "1px solid #ff4422",
            color: "#ff4422",
            fontWeight: "bold",
          }}
        >
          DEFROST ACTIVE
        </div>
      </div>

      {/* Main Temperature Meter (Giant Digital Display) */}
      <div
        style={{
          position: "absolute",
          top: 170,
          left: 80,
          right: 80,
          backgroundColor: "rgba(25, 8, 12, 0.92)",
          border: "3px solid #ff3300",
          borderRadius: 24,
          padding: "24px 30px",
          boxShadow: "0 0 50px rgba(255, 50, 0, 0.35)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          opacity: fadeIn,
          transform: `scale(${Number(currentTemp) >= 50 ? pulse : 1})`,
        }}
      >
        <div>
          <div style={{ fontSize: 22, color: "rgba(255,255,255,0.7)", letterSpacing: 1 }}>
            CHILLER CORE TEMPERATURE
          </div>
          <div
            style={{
              fontSize: 84,
              fontWeight: "900",
              color: Number(currentTemp) >= 40 ? "#ff2200" : "#ffaa00",
              fontFamily: "'Courier New', monospace",
              textShadow: "0 0 30px rgba(255,50,0,0.8)",
              letterSpacing: 2,
              marginTop: 4,
            }}
          >
            {Number(currentTemp) > 0 ? `+${currentTemp}` : currentTemp}°C
          </div>
        </div>

        {/* Thermometer Vertical Bar */}
        <div style={{ width: 60, height: 130, position: "relative", textAlign: "center" }}>
          <div
            style={{
              width: 26,
              height: 120,
              backgroundColor: "rgba(255,255,255,0.1)",
              borderRadius: 14,
              overflow: "hidden",
              margin: "0 auto",
              border: "2px solid rgba(255,255,255,0.3)",
              position: "relative",
            }}
          >
            <div
              style={{
                position: "absolute",
                bottom: 0,
                left: 0,
                right: 0,
                height: `${gaugePercent}%`,
                background: "linear-gradient(to top, #00bbff, #ffaa00, #ff0033)",
                boxShadow: "0 0 15px #ff2200",
              }}
            />
          </div>
          <div style={{ fontSize: 16, color: "#ff4422", marginTop: 4, fontWeight: "bold" }}>MAX</div>
        </div>
      </div>

      {/* Alarm System Bypassed Alert Banner */}
      <div
        style={{
          position: "absolute",
          top: 390,
          left: 80,
          right: 80,
          backgroundColor: alarmBypassed ? "rgba(255, 0, 50, 0.2)" : "rgba(30, 15, 20, 0.7)",
          border: `2px solid ${alarmBypassed ? "#ff0044" : "rgba(255,255,255,0.2)"}`,
          borderRadius: 18,
          padding: "16px 24px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          opacity: fadeIn,
          transform: `scale(${alarmScale})`,
          boxShadow: alarmBypassed ? "0 0 30px rgba(255,0,60,0.4)" : "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontSize: 32 }}>🔕</span>
          <div>
            <div style={{ fontSize: 20, color: "rgba(255,255,255,0.6)" }}>CENTRAL MONITORING ALARM</div>
            <div style={{ fontSize: 26, fontWeight: "bold", color: "#ff0044" }}>
              {alarmBypassed ? "SILENCED & BYPASSED BY HACKERS" : "CHECKING ALARM STATUS..."}
            </div>
          </div>
        </div>
        <div
          style={{
            fontSize: 20,
            color: "#ff0044",
            padding: "6px 14px",
            border: "1px solid #ff0044",
            borderRadius: 8,
            fontWeight: "bold",
          }}
        >
          OFFLINE
        </div>
      </div>

      {/* Visual Cards (Stacked Danfoss Controller & Spoiled Goods) */}
      <div
        style={{
          position: "absolute",
          top: 520,
          left: 80,
          right: 80,
          height: 520,
          display: "flex",
          gap: 20,
          opacity: fadeIn,
        }}
      >
        {/* Danfoss Overheat Panel */}
        <div
          style={{
            flex: 1,
            borderRadius: 20,
            overflow: "hidden",
            border: "2px solid rgba(255, 60, 0, 0.4)",
            boxShadow: "0 15px 40px rgba(0,0,0,0.7)",
            position: "relative",
          }}
        >
          <Img
            src={staticFile("sections/media/danfoss_overheat.png")}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
          <div
            style={{
              position: "absolute",
              bottom: 0,
              left: 0,
              right: 0,
              padding: "10px 14px",
              background: "linear-gradient(to top, rgba(0,0,0,0.9), transparent)",
              fontSize: 18,
              fontWeight: "bold",
              color: "#ffaa00",
            }}
          >
            DANFOSS AK-CC 550 // OVERHEAT
          </div>
        </div>

        {/* Spoiled Goods Freezers */}
        <div
          style={{
            flex: 1,
            borderRadius: 20,
            overflow: "hidden",
            border: "2px solid rgba(255, 0, 60, 0.4)",
            boxShadow: "0 15px 40px rgba(0,0,0,0.7)",
            position: "relative",
          }}
        >
          <Img
            src={staticFile("sections/media/spoiled_food.png")}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
          <div
            style={{
              position: "absolute",
              bottom: 0,
              left: 0,
              right: 0,
              padding: "10px 14px",
              background: "linear-gradient(to top, rgba(0,0,0,0.9), transparent)",
              fontSize: 18,
              fontWeight: "bold",
              color: "#ff4444",
            }}
          >
            MELTED & SPOILED STOCK
          </div>
        </div>
      </div>

      {/* Financial Loss Ticker Banner */}
      <div
        dir="rtl"
        style={{
          position: "absolute",
          top: 1070,
          left: 80,
          right: 80,
          backgroundColor: "rgba(30, 8, 12, 0.95)",
          border: "2px solid #ff2200",
          borderRadius: 20,
          padding: "20px 30px",
          boxShadow: "0 10px 40px rgba(255,0,0,0.3)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          opacity: fadeIn,
        }}
      >
        <div>
          <div style={{ fontFamily: "Lalezar, sans-serif", fontSize: 32, color: "rgba(255,255,255,0.8)" }}>
            خسائر إتلاف الأغذية والمجمدات:
          </div>
          <div
            style={{
              fontFamily: "Lalezar, sans-serif",
              fontSize: 56,
              color: "#ff2200",
              textShadow: "0 0 20px #ff0000",
            }}
          >
            أكثر من {lossMillions} مليون يورو! 💸
          </div>
        </div>
        <div style={{ fontSize: 48 }}>📉</div>
      </div>

      {/* Danger Notice Banner */}
      <div
        dir="rtl"
        style={{
          position: "absolute",
          top: 1240,
          left: 80,
          right: 80,
          backgroundColor: "rgba(255, 170, 0, 0.15)",
          border: "2px solid #ffaa00",
          borderRadius: 16,
          padding: "14px 24px",
          textAlign: "center",
          fontFamily: "Lalezar, sans-serif",
          fontSize: 34,
          color: "#ffcc00",
          opacity: fadeIn,
        }}
      >
        ⚠️ تلف كامل للحوم والألبان والمجمدات وإخلاء الأقسام فوراً
      </div>
    </div>
  );
};
