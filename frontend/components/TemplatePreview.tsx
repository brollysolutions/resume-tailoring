"use client";

import { useEffect, useRef, useState } from "react";

interface TemplatePreviewProps {
  html: string | null;
  /** Pixel width the inner HTML is rendered at; scales down to fit container. */
  baseWidth?: number;
}

/**
 * Scaled-down iframe rendering of a resume template using the user's actual data.
 *
 * The inner HTML is rendered at letter-size (816px wide ≈ 8.5in @ 96dpi), then
 * `transform: scale()` shrinks it to fit whatever space the parent gives us.
 * A ResizeObserver keeps the scale in sync with the container width.
 */
export function TemplatePreview({ html, baseWidth = 816 }: TemplatePreviewProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.3);

  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const apply = () => setScale(el.clientWidth / baseWidth);
    apply();
    const obs = new ResizeObserver(apply);
    obs.observe(el);
    return () => obs.disconnect();
  }, [baseWidth]);

  return (
    <div
      ref={wrapperRef}
      className="relative w-full bg-white overflow-hidden"
      style={{ aspectRatio: "8.5 / 11" }}
    >
      {html ? (
        <iframe
          title="Template preview"
          srcDoc={html}
          aria-hidden="true"
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: `${baseWidth}px`,
            height: `${(baseWidth * 11) / 8.5}px`,
            transformOrigin: "top left",
            transform: `scale(${scale})`,
            border: 0,
            pointerEvents: "none",
            background: "white",
          }}
        />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-6 h-6 rounded-full border-2 border-border border-t-foreground animate-spin" />
        </div>
      )}
    </div>
  );
}
