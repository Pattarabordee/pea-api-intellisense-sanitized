import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PEA API Intellisense Mission Control",
  description: "Production-path shadow console for AIS outage verification"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
