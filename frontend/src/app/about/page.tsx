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
        .about-divider {
          max-width: 640px;
          margin: 0 auto 2.5rem;
          padding: 0 1.5rem;
        }
        .about-divider-line {
          height: 1px;
          background: linear-gradient(
            90deg,
            transparent,
            var(--border-subtle) 20%,
            rgba(59,130,246,0.18) 50%,
            var(--border-subtle) 80%,
            transparent
          );
        }
        .about-features {
          max-width: 640px;
          margin: 0 auto;
          padding: 0 1.5rem 3rem;
          display: flex;
          flex-direction: column;
          gap: 0;
        }
        .about-feature {
          display: flex;
          gap: 1.25rem;
          padding: 1.25rem 0;
          border-bottom: 1px solid var(--border-subtle);
          align-items: baseline;
        }
        .about-feature:last-child {
          border-bottom: none;
        }
        .about-feature-num {
          font-family: var(--font-mono);
          font-size: 0.6875rem;
          color: rgba(59,130,246,0.5);
          letter-spacing: 0.05em;
          flex-shrink: 0;
          width: 1.5rem;
          padding-top: 0.125rem;
        }
        .about-feature-content {
          flex: 1;
        }
        .about-feature-title {
          font-size: 0.9375rem;
          font-family: var(--font-heading);
          margin: 0 0 0.25rem;
          color: var(--text-primary);
        }
        .about-feature-desc {
          font-size: 0.8125rem;
          line-height: 1.65;
          color: var(--text-muted);
          margin: 0;
        }
        .about-cta {
          text-align: center;
          padding: 2rem 1.5rem 4rem;
        }
        .about-cta-link {
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.625rem 1.5rem;
          border-radius: 8px;
          background: rgba(59,130,246,0.1);
          border: 1px solid rgba(59,130,246,0.15);
          color: var(--text-secondary);
          text-decoration: none;
          font-family: var(--font-heading);
          font-size: 0.8125rem;
          letter-spacing: 0.01em;
          transition: all 0.2s;
        }
        .about-cta-link:hover {
          background: rgba(59,130,246,0.18);
          color: var(--text-primary);
          border-color: rgba(59,130,246,0.25);
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

      <div className="about-divider">
        <div className="about-divider-line" />
      </div>

      <div className="about-features">
        <div className="about-feature">
          <span className="about-feature-num">01</span>
          <div className="about-feature-content">
            <h3 className="about-feature-title">Real-time news data</h3>
            <p className="about-feature-desc">
              Sourced from the GDELT Project&nbsp;&mdash; the world&apos;s largest open
              event database, monitoring news from 65+ languages and 150+ countries.
            </p>
          </div>
        </div>
        <div className="about-feature">
          <span className="about-feature-num">02</span>
          <div className="about-feature-content">
            <h3 className="about-feature-title">Smart clustering</h3>
            <p className="about-feature-desc">
              Nearby stories group together at low zoom levels so the globe stays
              readable, and expand as you zoom in.
            </p>
          </div>
        </div>
        <div className="about-feature">
          <span className="about-feature-num">03</span>
          <div className="about-feature-content">
            <h3 className="about-feature-title">AI summaries</h3>
            <p className="about-feature-desc">
              Cluster summaries powered by the latest LLMs help you understand
              regional narratives at a glance.
            </p>
          </div>
        </div>
        <div className="about-feature">
          <span className="about-feature-num">04</span>
          <div className="about-feature-content">
            <h3 className="about-feature-title">Topic filters</h3>
            <p className="about-feature-desc">
              Focus on conflict, politics, environment, economy, and more.
            </p>
          </div>
        </div>
      </div>

      <div className="about-cta">
        <Link href="/" className="about-cta-link">
          Explore the World
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M6 4l4 4-4 4" />
          </svg>
        </Link>
      </div>
    </main>
  );
}
