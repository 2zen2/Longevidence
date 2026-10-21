import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppStateProvider } from "@/components/AppState";
import Header from "@/components/Header";
import "./globals.css";

export const metadata: Metadata = { title: "Longevidence", description: "Research on treatments, supplements and diagnostics, matched to your profile." };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans">
        <AppStateProvider>
          <Header />
          <main className="mx-auto max-w-6xl px-5 pb-20 sm:px-8">{children}</main>
        </AppStateProvider>
      </body>
    </html>
  );
}
