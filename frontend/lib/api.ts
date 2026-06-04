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
