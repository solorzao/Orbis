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
    <main className="about-page">
      <style>{`
        .about-page {
          min-height: 100vh;
          overflow: auto;
          background: var(--bg-page);
          color: var(--text-primary);
        }
        .about-hero {
          max-width: 640px;
          margin: 0 auto;
          padding: 5rem 1.5rem 3rem;
          text-align: center;
        }
        .about-back {
          display: inline-flex;
          align-items: center;
          gap: 0.375rem;
          color: var(--text-muted);
          text-decoration: none;
          font-size: 0.8125rem;
          margin-bottom: 3rem;
          transition: color 0.15s;
        }
        .about-back:hover { color: var(--text-secondary); }
        .about-title {
          font-family: var(--font-brand);
          font-size: clamp(2.25rem, 5vw, 3rem);
          margin: 0 0 0.5rem;
          letter-spacing: -0.02em;
        }
        .about-tagline {
          font-size: 1.125rem;
          color: var(--text-secondary);
          margin: 0 0 1.5rem;
          font-family: var(--font-heading);
        }
        .about-desc {
          color: var(--text-muted);
          font-size: 0.9375rem;
          line-height: 1.75;
          margin: 0;
        }
        .about-features {
          max-width: 640px;
          margin: 0 auto;
          padding: 0 1.5rem 3rem;
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 1px;
          background: var(--border-subtle);
          border: 1px solid var(--border-subtle);
          border-radius: 12px;
          overflow: hidden;
        }
        @media (max-width: 480px) {
          .about-features { grid-template-columns: 1fr; }
        }
        .about-feature {
          padding: 1.5rem;
          background: var(--bg-page);
        }
        .about-feature-title {
          font-size: 0.875rem;
          font-family: var(--font-heading);
          margin: 0 0 0.375rem;
          color: var(--text-primary);
        }
        .about-feature-desc {
          font-size: 0.8125rem;
          line-height: 1.6;
          color: var(--text-secondary);
          margin: 0;
        }
        .about-cta {
          text-align: center;
          padding: 3rem 1.5rem 4rem;
        }
        .about-cta-link {
          display: inline-block;
          padding: 0.625rem 1.75rem;
          border-radius: 8px;
          background: rgba(59,130,246,0.12);
          border: 1px solid var(--border-accent);
          color: var(--text-primary);
          text-decoration: none;
          font-family: var(--font-heading);
          font-size: 0.875rem;
          transition: background 0.15s;
        }
        .about-cta-link:hover {
          background: rgba(59,130,246,0.2);
        }
      `}</style>

      <div className="about-hero">
        <Link href="/" className="about-back">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10 12L6 8l4-4" />
          </svg>
          Back to Globe
        </Link>

        <h1 className="about-title">Orbis</h1>
        <p className="about-tagline">Every Story, Everywhere.</p>
        <p className="about-desc">
          An interactive 3D globe that visualises geolocated world news in real
          time. Spin the globe, zoom into regions, and explore headlines updated
          every 15&nbsp;minutes&nbsp;&mdash; with AI-generated summaries to help you
          make sense of it all.
        </p>
      </div>

      <div className="about-features">
        <div className="about-feature">
          <h3 className="about-feature-title">Real-time news data</h3>
          <p className="about-feature-desc">
            Sourced from the GDELT Project&nbsp;&mdash; monitoring news from
            65+ languages and 150+ countries.
          </p>
        </div>
        <div className="about-feature">
          <h3 className="about-feature-title">Smart clustering</h3>
          <p className="about-feature-desc">
            Nearby stories group together at low zoom levels and expand as you
            zoom in.
          </p>
        </div>
        <div className="about-feature">
          <h3 className="about-feature-title">AI summaries</h3>
          <p className="about-feature-desc">
            Cluster summaries powered by Anthropic Claude help you understand
            regional narratives at a glance.
          </p>
        </div>
        <div className="about-feature">
          <h3 className="about-feature-title">Topic filters</h3>
          <p className="about-feature-desc">
            Focus on conflict, politics, environment, economy, and more.
          </p>
        </div>
      </div>

      <div className="about-cta">
        <Link href="/" className="about-cta-link">
          Explore the Globe
        </Link>
      </div>
    </main>
  );
}
