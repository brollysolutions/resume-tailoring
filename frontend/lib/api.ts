/**
 * Resolves the base path prefix for client-side navigation that uses
 * window.location.href (bypassing Next.js router). In production the app is
 * served under /resume_generator, locally it's at root.
 *
 * Priority:
 *  1. NEXT_PUBLIC_BASE_PATH env var (baked at build time)
 *  2. Runtime detection from current URL pathname
 *  3. Empty string (root)
 */
export function getBasePath(): string {
  // 1. Build-time env var (Next.js inlines NEXT_PUBLIC_* at build)
  const envBase = process.env.NEXT_PUBLIC_BASE_PATH;
  if (envBase) return envBase;

  // 2. Runtime fallback — extract first path segment if it looks like a subpath
  if (typeof window !== "undefined") {
    const match = window.location.pathname.match(/^(\/[^/]+)/);
    // Only treat it as a basePath if it's not one of our known route segments
    if (match && !["/job-search", "/tailor"].includes(match[1])) {
      return match[1];
    }
  }

  // 3. Root — local dev or no subpath
  return "";
}

/**
 * Resolves the correct API base URL depending on whether the app is running
 * locally (development) or on the production server.
 */
export function getApiUrl(): string {
  // If running in the browser, check the hostname
  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    // Check if the page is loaded from a local address (localhost, 127.0.0.1, or local IP)
    if (
      hostname === "localhost" ||
      hostname === "127.0.0.1" ||
      hostname.startsWith("192.168.") ||
      hostname.startsWith("10.") ||
      hostname.startsWith("172.") ||
      hostname.endsWith(".local")
    ) {
      // The backend local development server runs on port 8004 by default.
      return `http://${hostname}:8004`;
    }
  }

  // Production default fallback (or read from build-time baked environment variable)
  return process.env.NEXT_PUBLIC_API_URL || "https://brollysolutions.in/resume_generator";
}
