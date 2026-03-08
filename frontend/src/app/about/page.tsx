import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "About — Orbis",
  description:
    "Orbis is a real-time interactive 3D globe for exploring geolocated world news, powered by GDELT data and AI summaries.",
  alternates: {
    canonical: "/about",
  },
};

const features = [
  {
    icon: "&#127758;",
    title: "Real-time news data",
    description:
      "Sourced from the GDELT Project — the world\u2019s largest open event database, monitoring news from 65+ languages and 150+ countries.",
  },
  {
    icon: "&#11044;",
    title: "Smart clustering",
    description:
      "Nearby stories group together at low zoom levels so the globe stays readable, and expand as you zoom in.",
  },
  {
    icon: "&#9889;",
    title: "AI summaries",
    description:
      "Cluster summaries powered by Anthropic Claude help you understand regional narratives at a glance.",
  },
  {
    icon: "&#9881;",
    title: "Topic filters",
    description:
      "Focus on conflict, politics, environment, economy, and more.",
  },
];

export default function AboutPage() {
  return (
    <main
      style={{
        minHeight: "100vh",
        overflow: "auto",
        background: "var(--bg-page)",
      }}
    >
      {/* Hero */}
      <div
        style={{
          position: "relative",
          padding: "5rem 1.5rem 4rem",
          textAlign: "center",
          background:
            "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(59,130,246,0.12), transparent)",
        }}
      >
        <Link
          href="/"
          style={{
            position: "absolute",
            top: "1.5rem",
            left: "1.5rem",
            color: "var(--text-muted)",
            textDecoration: "none",
            fontSize: "0.875rem",
            padding: "0.375rem 0.75rem",
            borderRadius: "6px",
            border: "1px solid var(--border-subtle)",
            background: "var(--surface-card)",
            transition: "border-color 0.2s",
          }}
        >
          &larr; Back to Globe
        </Link>

        <div
          style={{
            width: 64,
            height: 64,
            margin: "0 auto 1.5rem",
            borderRadius: "50%",
            background:
              "linear-gradient(135deg, rgba(59,130,246,0.3), rgba(59,130,246,0.08))",
            border: "1px solid var(--border-accent)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "1.75rem",
          }}
          dangerouslySetInnerHTML={{ __html: "&#127758;" }}
        />

        <h1
          style={{
            fontFamily: "var(--font-brand)",
            fontSize: "clamp(2rem, 5vw, 3.5rem)",
            margin: "0 0 0.75rem",
            letterSpacing: "-0.02em",
          }}
        >
          Orbis
        </h1>
        <p
          style={{
            fontSize: "1.25rem",
            color: "var(--text-secondary)",
            margin: "0 0 1.5rem",
            fontFamily: "var(--font-heading)",
          }}
        >
          Every Story, Everywhere.
        </p>
        <p
          style={{
            maxWidth: 560,
            margin: "0 auto",
            color: "var(--text-muted)",
            fontSize: "1rem",
            lineHeight: 1.7,
          }}
        >
          An interactive 3D globe that visualises geolocated world news in real
          time. Spin the globe, zoom into regions, and explore headlines updated
          every 15 minutes — with AI-generated summaries to help you make sense
          of it all.
        </p>
      </div>

      {/* Feature cards */}
      <div
        style={{
          maxWidth: 880,
          margin: "0 auto",
          padding: "0 1.5rem 4rem",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: "1rem",
        }}
      >
        {features.map((f) => (
          <div
            key={f.title}
            style={{
              padding: "1.5rem",
              borderRadius: "12px",
              background: "var(--surface-card)",
              border: "1px solid var(--border-subtle)",
              transition: "border-color 0.2s",
            }}
          >
            <div
              style={{ fontSize: "1.5rem", marginBottom: "0.75rem" }}
              dangerouslySetInnerHTML={{ __html: f.icon }}
            />
            <h3
              style={{
                fontSize: "1rem",
                fontFamily: "var(--font-heading)",
                margin: "0 0 0.5rem",
              }}
            >
              {f.title}
            </h3>
            <p
              style={{
                color: "var(--text-secondary)",
                fontSize: "0.875rem",
                lineHeight: 1.6,
                margin: 0,
              }}
            >
              {f.description}
            </p>
          </div>
        ))}
      </div>

      {/* CTA */}
      <div
        style={{
          textAlign: "center",
          padding: "2rem 1.5rem 4rem",
          borderTop: "1px solid var(--border-subtle)",
        }}
      >
        <Link
          href="/"
          style={{
            display: "inline-block",
            padding: "0.75rem 2rem",
            borderRadius: "8px",
            background: "rgba(59,130,246,0.15)",
            border: "1px solid var(--border-accent)",
            color: "var(--text-primary)",
            textDecoration: "none",
            fontFamily: "var(--font-heading)",
            fontSize: "0.9375rem",
            transition: "background 0.2s",
          }}
        >
          Explore the Globe
        </Link>
      </div>
    </main>
  );
}
