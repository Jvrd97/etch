// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: root layout — viewport/themeColor + apple-touch-icon for the PWA, shell selection delegated to AppShell
import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import AppShell from "@/components/AppShell";
import { THEME_COLOR } from "@/lib/theme";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Habit Tracker - Track Your Life",
  description: "A powerful habit tracking application with dynamic categories and fields",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "Habits",
    statusBarStyle: "black-translucent",
  },
  icons: {
    icon: "/icon-192.png",
    apple: "/apple-touch-icon.png",
  },
};

export const viewport: Viewport = {
  themeColor: THEME_COLOR,
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${inter.className} bg-background text-text-primary min-h-screen antialiased overflow-x-hidden`}
      >
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
