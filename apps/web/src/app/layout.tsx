import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NW Digital Operations Hub V3",
  description: "Backend-Driven Digital Operations Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
