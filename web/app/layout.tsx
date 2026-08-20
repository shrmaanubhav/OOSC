import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Project Sentinel",
  description:
    "Energy supply-chain resilience for India — corridor risk, scenario cascade, procurement reallocation.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
