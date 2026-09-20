import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Self-hosted so a rebuild works with no internet — the venue Wi-Fi is not a
// dependency of `./demo.sh`.
const sans = localFont({
  src: "./fonts/PublicSans.woff2",
  weight: "100 900",
  variable: "--font-sans",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

const serif = localFont({
  src: "./fonts/SourceSerif4.woff2",
  weight: "200 900",
  variable: "--font-serif",
  display: "swap",
  fallback: ["ui-serif", "Georgia", "serif"],
});

export const metadata: Metadata = {
  title: "BillProof",
  description:
    "Compare a hospital bill against the hospital's own published prices, with a source for every number.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#fbfaf7",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable}`}>
      <body>{children}</body>
    </html>
  );
}
