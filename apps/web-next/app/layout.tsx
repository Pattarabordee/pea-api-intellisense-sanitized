import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PEA Intellisense Operator Console",
  description: "Shadow operator console for PEA Intellisense decision support"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="th">
      <body>{children}</body>
    </html>
  );
}
