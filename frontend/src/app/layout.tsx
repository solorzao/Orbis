import type { Metadata } from "next";
import localFont from "next/font/local";
import { ThemeProvider } from "@/lib/theme";
import { Analytics } from "@vercel/analytics/next";
import "./globals.css";

// Self-hosted (latin subset, variable weight) so builds never depend on
// reaching Google Fonts. Files and OFL licences are in ./fonts.
// The variables go on <html>: globals.css points the Soft Orbit token stacks
// (--font-brand/heading/body/mono, and the --type-* shorthands built from
// them) at these, and those are resolved on :root.
const orbitron = localFont({
  src: "./fonts/orbitron-latin-wght-normal.woff2",
  variable: "--font-orbitron",
  weight: "400 900",
});

const spaceGrotesk = localFont({
  src: "./fonts/space-grotesk-latin-wght-normal.woff2",
  variable: "--font-space-grotesk",
  weight: "300 700",
});

const jetbrainsMono = localFont({
  src: "./fonts/jetbrains-mono-latin-wght-normal.woff2",
  variable: "--font-jetbrains-mono",
  weight: "100 800",
});

const rawUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://orbisapp.co";
const siteUrl = rawUrl.startsWith("http") ? rawUrl : `https://${rawUrl}`;
const title = "Orbis — Every Story, Everywhere";
const description =
  "Explore the world's news on an interactive 3D globe. Orbis visualises geolocated headlines in real time, powered by GDELT and AI-driven summaries.";

export const metadata: Metadata = {
  title,
  description,
  metadataBase: new URL(siteUrl),
  icons: {
    icon: "/favicon.ico",
    apple: "/favicon.png",
  },
  openGraph: {
    title,
    description,
    url: siteUrl,
    siteName: "Orbis",
    locale: "en_US",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
  },
  alternates: {
    canonical: siteUrl,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${orbitron.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable}`}
    >
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('orbis-theme');if(t==='light'||t==='dark'){document.documentElement.setAttribute('data-theme',t)}else{var d=window.matchMedia('(prefers-color-scheme: dark)').matches;document.documentElement.setAttribute('data-theme',d?'dark':'light')}}catch(e){}})()`,
          }}
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "WebApplication",
              name: "Orbis",
              url: siteUrl,
              description,
              applicationCategory: "NewsApplication",
              operatingSystem: "Web",
              offers: {
                "@type": "Offer",
                price: "0",
                priceCurrency: "USD",
              },
              creator: {
                "@type": "Organization",
                name: "Orbis",
                url: siteUrl,
              },
            }),
          }}
        />
      </head>
      <body className="antialiased">
        <ThemeProvider>{children}</ThemeProvider>
        <Analytics />
      </body>
    </html>
  );
}
