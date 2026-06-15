"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

interface TemplatePreviewProps {
  html: string | null;
  baseWidth?: number;
  showControls?: boolean;
  /** When true, the component is flex-1 and fits the resume to the full panel height + width. */
  fillParent?: boolean;
  /** Fallback max-height when fillParent is false and showControls is true. */
  maxScrollHeight?: string;
  /** When provided, an X button is prepended to the controls bar. */
  onClose?: () => void;
  /** Rendered centered in the container when html is null. */
  placeholder?: React.ReactNode;
  /** Zoom readout is an explicit, always-odd integer % stepped ~3% per click
   *  (never lands on an even value like 72%). Used by the upload modal. */
  oddZoom?: boolean;
}

export function TemplatePreview({
  html,
  baseWidth = 816,
  showControls = false,
  fillParent = false,
  maxScrollHeight = "600px",
  onClose,
  placeholder,
  oddZoom = false,
}: TemplatePreviewProps) {
  const noControlsRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 });
  const [userZoom, setUserZoom] = useState(1);
  const [contentHeight, setContentHeight] = useState(1056); // default 1 page
  // Explicit integer-% zoom for oddZoom mode (null until the fit scale is known).
  const [pctZoom, setPctZoom] = useState<number | null>(null);

  // Measure the container for both paths
  useEffect(() => {
    const el = showControls ? containerRef.current : noControlsRef.current;
    if (!el) return;
    const apply = () =>
      setContainerSize({ w: el.clientWidth, h: el.clientHeight });
    apply();
    const obs = new ResizeObserver(apply);
    obs.observe(el);
    return () => obs.disconnect();
  }, [showControls]);

  const onIframeLoad = () => {
    const doc = iframeRef.current?.contentDocument;
    if (doc?.body) setContentHeight(Math.max(1056, doc.body.scrollHeight));
  };

  // fillParent: fit both axes (panel height is known from flex layout)
  // otherwise: width-only fit — height is scroll, measuring clientHeight causes circular lock
  const fitScale =
    fillParent && containerSize.h > 0 && contentHeight > 0
      ? Math.min(containerSize.w / baseWidth, containerSize.h / contentHeight)
      : containerSize.w > 0
      ? containerSize.w / baseWidth
      : 0.3;

  const totalScale = fitScale * userZoom;

  // Odd-zoom mode: the readout is an explicit always-odd integer %, stepped ~3%
  // per click, so it never shows an even value like 72%. The render scale is
  // driven by that % so the label stays honest.
  const fitPct = Math.max(1, Math.round(fitScale * 100));
  const oddFitPct = fitPct % 2 === 0 ? Math.max(1, fitPct - 1) : fitPct;

  // pctZoom stays null until the user actually zooms — display falls back to the
  // odd fit %, so no setState-in-effect is needed to seed an initial value.
  const displayPct = oddZoom ? (pctZoom ?? oddFitPct) : Math.round(totalScale * 100);
  const scale = oddZoom ? displayPct / 100 : totalScale;

  const stepOddZoom = (dir: 1 | -1) => {
    setPctZoom((cur) => {
      let next = (cur ?? oddFitPct) + dir * 3;
      if (next % 2 === 0) next += dir; // snap back to an odd value
      return Math.max(oddFitPct, Math.min(301, next));
    });
  };

  const adjustZoom = (next: number) => {
    setUserZoom(Math.max(1, next));
  };

  // ── No-controls path (thumbnail mode) ─────────────────────────────────────
  if (!showControls) {
    const thumbScale = containerSize.w > 0 ? containerSize.w / baseWidth : 0.3;
    return (
      <div
        ref={noControlsRef}
        className="relative w-full bg-white overflow-hidden"
        style={{ aspectRatio: "8.5 / 11" }}
      >
        {html ? (
          <iframe
            title="Template preview"
            srcDoc={html}
            aria-hidden="true"
            scrolling="no"
            sandbox="allow-same-origin allow-scripts"
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: `${baseWidth}px`,
              height: `${(baseWidth * 11) / 8.5}px`,
              transformOrigin: "top left",
              transform: `scale(${thumbScale})`,
              border: 0,
              pointerEvents: "none",
              background: "white",
              overflow: "hidden",
            }}
          />
        ) : (
          <div className="absolute inset-0 p-4 flex flex-col justify-between animate-pulse bg-subtle select-none">
            <div className="space-y-1">
              <div className="h-2.5 bg-muted/60 rounded w-1/3 mx-auto" />
              <div className="h-1.5 bg-muted/40 rounded w-1/2 mx-auto" />
            </div>
            <div className="space-y-1">
              <div className="h-1.5 bg-muted/50 rounded w-1/4" />
              <div className="h-1.5 bg-muted/30 rounded w-full" />
              <div className="h-1.5 bg-muted/30 rounded w-5/6" />
            </div>
            <div className="space-y-1">
              <div className="h-1.5 bg-muted/50 rounded w-1/4" />
              <div className="h-1.5 bg-muted/30 rounded w-full" />
              <div className="h-1.5 bg-muted/30 rounded w-4/5" />
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Controls path ──────────────────────────────────────────────────────────
  const outerClass = fillParent ? "flex-1 min-h-0" : "";

  return (
    <div className={`relative flex flex-col ${outerClass}`}>
      {/* X — standalone, top-right */}
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          className="absolute top-2 right-2 z-10 w-7 h-7 flex items-center justify-center bg-white/90 backdrop-blur-sm border border-border rounded-md shadow-sm hover:bg-subtle transition-colors"
          aria-label="Close"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}

      {/* Zoom controls — separate pill, bottom-right */}
      <div className="absolute bottom-3 right-3 z-10 flex items-center gap-1 bg-white/90 backdrop-blur-sm border border-border rounded-md px-1.5 py-1 shadow-sm">
        <button
          type="button"
          className="w-6 h-6 flex items-center justify-center text-sm font-mono hover:bg-subtle rounded transition-colors"
          onClick={() => (oddZoom ? stepOddZoom(-1) : adjustZoom(+(userZoom - 0.1).toFixed(1)))}
          disabled={oddZoom ? displayPct <= oddFitPct : userZoom <= 1}
          aria-label="Zoom out"
        >
          −
        </button>
        <span className="text-[11px] text-muted w-8 text-center tabular-nums">
          {displayPct}%
        </span>
        <button
          type="button"
          className="w-6 h-6 flex items-center justify-center text-sm font-mono hover:bg-subtle rounded transition-colors"
          onClick={() => (oddZoom ? stepOddZoom(1) : adjustZoom(Math.min(3, +(userZoom + 0.1).toFixed(1))))}
          aria-label="Zoom in"
        >
          +
        </button>
      </div>

      {/* Scroll container — native scrollbars when zoomed past fit */}
      <div
        ref={containerRef}
        className={`rounded border border-border select-none overflow-auto scrollbar-thin bg-gray-100 ${outerClass}`}
        style={fillParent ? undefined : { maxHeight: maxScrollHeight }}
      >
        {html ? (
          /* Inner div auto-centres when smaller than container; scrollable when larger */
          <div
            style={{
              position: "relative",
              width: `${baseWidth * scale}px`,
              height: `${contentHeight * scale}px`,
              margin: "0 auto",
            }}
          >
            <iframe
              ref={iframeRef}
              title="Template preview"
              srcDoc={html}
              aria-hidden="true"
              scrolling="no"
              sandbox="allow-same-origin allow-scripts"
              onLoad={onIframeLoad}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: `${baseWidth}px`,
                height: `${contentHeight}px`,
                transformOrigin: "top left",
                transform: `scale(${scale})`,
                border: 0,
                pointerEvents: "none",
                background: "white",
              }}
            />
          </div>
        ) : placeholder ? (
          <div className="w-full h-full flex items-center justify-center">
            {placeholder}
          </div>
        ) : (
          <div className="w-full h-full flex items-center justify-center p-8 bg-gray-50/50">
            <div className="w-[85%] max-w-[500px] aspect-[8.5/11] bg-white rounded shadow-md border border-border/60 p-8 space-y-6 animate-pulse select-none">
              {/* Name and title */}
              <div className="space-y-2 text-center">
                <div className="h-4.5 bg-muted/60 rounded w-1/3 mx-auto" />
                <div className="h-3 bg-muted/50 rounded w-1/2 mx-auto" />
              </div>
              
              {/* Contact info bar */}
              <div className="h-2.5 bg-muted/40 rounded w-3/4 mx-auto" />

              <hr className="border-border/60" />

              {/* Summary section */}
              <div className="space-y-2">
                <div className="h-3 bg-muted/60 rounded w-1/4" />
                <div className="space-y-1.5">
                  <div className="h-2 bg-muted/30 rounded w-full" />
                  <div className="h-2 bg-muted/30 rounded w-5/6" />
                </div>
              </div>

              {/* Experience section */}
              <div className="space-y-3">
                <div className="h-3 bg-muted/60 rounded w-1/4" />
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="h-2.5 bg-muted/50 rounded w-1/3" />
                    <div className="h-2 bg-muted/40 rounded w-1/6" />
                  </div>
                  <div className="space-y-1.5 pl-3">
                    <div className="h-2 bg-muted/30 rounded w-11/12" />
                    <div className="h-2 bg-muted/30 rounded w-full" />
                  </div>
                </div>
              </div>

              {/* Skills section */}
              <div className="space-y-2.5">
                <div className="h-3 bg-muted/60 rounded w-1/4" />
                <div className="flex gap-2">
                  <div className="h-5 bg-muted/40 rounded w-16" />
                  <div className="h-5 bg-muted/40 rounded w-20" />
                  <div className="h-5 bg-muted/40 rounded w-12" />
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
