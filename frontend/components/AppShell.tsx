"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  
  // Add any routes here where you want a clean, fullscreen canvas
  const isHiddenPage = pathname === "/tailor" || pathname === "/job-search";

  return (
    <>
      {!isHiddenPage && (
        <header className="border-b border-border bg-white shrink-0">
          <div className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
            <Link href="/" className="flex items-center gap-2 group">
              <div className="w-6 h-6 rounded bg-accent text-white text-[11px] font-semibold flex items-center justify-center">
                R
              </div>
              <span className="text-sm font-semibold tracking-tight">
                Resume Tailor
              </span>
            </Link>
          </div>
        </header>
      )}

      <main className="flex-1 flex flex-col w-full">
        {children}
      </main>

      {!isHiddenPage && (
        <footer className="border-t border-border bg-white shrink-0">
          <div className="max-w-5xl mx-auto px-6 h-12 flex items-center justify-between text-xs text-muted">
            <span>Local-first resume tailoring</span>
            <span>v1.0</span>
          </div>
        </footer>
      )}
    </>
  );
}