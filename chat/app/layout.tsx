import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono, Source_Serif_4 } from "next/font/google";
import "./globals.css";

// Three faces, three jobs. The sans is the product talking, the serif is
// the model talking, the mono is the machine (latency, ids, model tags,
// code). Each is exposed as a CSS var and consumed through the
// --font-sans / --font-serif / --font-mono tokens.
const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-instrument-sans",
  weight: ["400", "500", "600", "700"],
});

const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-source-serif",
  weight: ["400", "600"],
  style: ["normal", "italic"],
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "DejaQ Chat",
  description: "Chat with your organization's AI assistant",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${instrumentSans.variable} ${sourceSerif.variable} ${jetbrainsMono.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
