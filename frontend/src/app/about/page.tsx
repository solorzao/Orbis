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

export default function AboutPage() {
  return (
    <main
      style={{
        maxWidth: 720,
        margin: "0 auto",
        padding: "4rem 1.5rem",
        color: "var(--text-primary)",
        lineHeight: 1.7,
        overflow: "auto",
        height: "100vh",
      }}
    >
      <Link
        href="/"
        style={{
          color: "var(--text-muted)",
          textDecoration: "none",
          fontSize: "0.875rem",
        }}
      >
        &larr; Back to Globe
      </Link>

      <h1
        style={{
          fontFamily: "var(--font-brand)",
          fontSize: "2.5rem",
          marginTop: "2rem",
          marginBottom: "0.5rem",
        }}
      >
        Orbis
      </h1>
      <p
        style={{
          fontSize: "1.25rem",
          color: "var(--text-secondary)",
          marginBottom: "2.5rem",
        }}
      >
        Every Story, Everywhere.
      </p>

      <section style={{ marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.25rem", marginBottom: "0.75rem" }}>
          What is Orbis?
        </h2>
        <p style={{ color: "var(--text-secondary)" }}>
          Orbis is an interactive 3D globe that visualises geolocated world news
          in real time. Headlines from around the world appear as points on the
          globe, updated every 15 minutes. You can spin the globe, zoom into
          regions, and click on clusters to read AI-generated summaries and
          original source articles.
        </p>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.25rem", marginBottom: "0.75rem" }}>
          How it works
        </h2>
        <ul
          style={{
            color: "var(--text-secondary)",
            paddingLeft: "1.25rem",
          }}
        >
          <li style={{ marginBottom: "0.5rem" }}>
            <strong style={{ color: "var(--text-primary)" }}>
              Real-time news data
            </strong>{" "}
            — sourced from the GDELT Project, the world&apos;s largest open
            event database monitoring news from 65+ languages and 150+ countries.
          </li>
          <li style={{ marginBottom: "0.5rem" }}>
            <strong style={{ color: "var(--text-primary)" }}>
              Smart clustering
            </strong>{" "}
            — nearby stories group together at low zoom levels so the globe
            stays readable, and expand as you zoom in.
          </li>
          <li style={{ marginBottom: "0.5rem" }}>
            <strong style={{ color: "var(--text-primary)" }}>
              AI summaries
            </strong>{" "}
            — powered by Anthropic Claude, cluster summaries help you understand
            regional narratives at a glance.
          </li>
          <li style={{ marginBottom: "0.5rem" }}>
            <strong style={{ color: "var(--text-primary)" }}>
              Topic filters
            </strong>{" "}
            — focus on conflict, politics, environment, economy, and more.
          </li>
        </ul>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.25rem", marginBottom: "0.75rem" }}>
          Technology
        </h2>
        <p style={{ color: "var(--text-secondary)" }}>
          Built with Next.js and globe.gl (Three.js) on the frontend, Python
          FastAPI on the backend, and PostgreSQL with PostGIS and pgvector for
          geospatial and semantic search. Hosted on Vercel and Azure.
        </p>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.25rem", marginBottom: "0.75rem" }}>
          Open source
        </h2>
        <p style={{ color: "var(--text-secondary)" }}>
          Orbis is open source on{" "}
          <a
            href="https://github.com/solorzao/Orbis"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--text-primary)", textDecoration: "underline" }}
          >
            GitHub
          </a>
          .
        </p>
      </section>
    </main>
  );
}
