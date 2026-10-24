import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { Providers } from "@/providers";
import "./globals.css";

const display = localFont({ src: "./fonts/bricolage-grotesque-latin-wght-normal.woff2", variable: "--font-display", display: "swap", weight: "200 800" });
const body = localFont({
  src: [
    { path: "./fonts/ibm-plex-sans-latin-400-normal.woff2", weight: "400" },
    { path: "./fonts/ibm-plex-sans-latin-500-normal.woff2", weight: "500" },
    { path: "./fonts/ibm-plex-sans-latin-600-normal.woff2", weight: "600" },
  ],
  variable: "--font-body", display: "swap",
});

export const metadata: Metadata = { title: { default: "foodAgent", template: "%s · foodAgent" }, description: "foodAgent — Intelligent Food Recovery & Redistribution Platform. Turn surplus into recovery." };
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${display.variable} ${body.variable}`}><Providers>{children}</Providers></body>
    </html>
  );
}
