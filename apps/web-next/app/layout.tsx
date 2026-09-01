import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PEA Intellisense Incident Command Center",
  description: "Shadow operator decision-support for incident priority queue"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="th">
      <body>{children}</body>
    </html>
  );
}
