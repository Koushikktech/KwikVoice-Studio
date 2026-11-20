import type { Metadata } from "next";
import "@fontsource-variable/inter";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./styles.css";

export const metadata: Metadata = {
  title: "KwikVoice ChaosLab",
  description: "A local workbench for testing voice agents on synthetic checkout calls.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en" data-type="software">
    <head><meta name="page-type" content="software" /><meta name="site-kind" content="software" /></head>
    <body>{children}</body>
  </html>;
}
