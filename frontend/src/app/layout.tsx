import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import { ThemeProvider } from "@/lib/theme";
import { Analytics } from "@vercel/analytics/next";
import "./globals.css";

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Orbis — Global News Intelligence",
  description: "Explore the world's news on an interactive 3D globe",
  icons: {
    icon: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('orbis-theme');if(t==='light'||t==='dark'){document.documentElement.setAttribute('data-theme',t)}else{var d=window.matchMedia('(prefers-color-scheme: dark)').matches;document.documentElement.setAttribute('data-theme',d?'dark':'light')}}catch(e){}})()`,
          }}
        />
      </head>
      <body
        className={`${jetbrainsMono.variable} antialiased`}
        style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}
      >
        <ThemeProvider>{children}</ThemeProvider>
        <Analytics />
      </body>
    </html>
  );
}
