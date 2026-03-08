import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Orbis — Every Story, Everywhere";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OgImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #030712 0%, #0f1729 50%, #1e293b 100%)",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <div
          style={{
            width: 120,
            height: 120,
            borderRadius: "50%",
            background: "linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%)",
            marginBottom: 32,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 0 60px rgba(59,130,246,0.3)",
          }}
        >
          <div
            style={{
              width: 80,
              height: 80,
              borderRadius: "50%",
              border: "3px solid rgba(255,255,255,0.6)",
              display: "flex",
            }}
          />
        </div>
        <div
          style={{
            fontSize: 64,
            fontWeight: 700,
            color: "#e2e8f0",
            letterSpacing: "-0.02em",
            marginBottom: 12,
            display: "flex",
          }}
        >
          Orbis
        </div>
        <div
          style={{
            fontSize: 24,
            color: "#94a3b8",
            display: "flex",
          }}
        >
          Every Story, Everywhere
        </div>
        <div
          style={{
            fontSize: 16,
            color: "#64748b",
            marginTop: 24,
            display: "flex",
          }}
        >
          Real-time world news on an interactive 3D globe
        </div>
      </div>
    ),
    { ...size },
  );
}
