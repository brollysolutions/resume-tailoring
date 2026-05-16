import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { AppShell } from "@/components/AppShell";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "Resume Tailor",
  description: "Tailor your resume to any job description.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${inter.variable} font-sans bg-background text-foreground min-h-screen flex flex-col`}>
        <AppShell>
          {children}
        </AppShell>
      </body>
    </html>
  );
}