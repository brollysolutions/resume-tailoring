"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Loader2, Minus, Plus, Maximize, FileText, Download, ChevronDown, AlertTriangle, Info } from "lucide-react";
import type { ResumeData, Suggestion, GeneratedProject } from "@/types/resume";

type NewProject = Pick<GeneratedProject, "name" | "tech" | "bullets">;

interface ResumePreviewProps {
  resumeId: string | null;
  templateId?: string;
  approvedSuggestions: Suggestion[];
  newProjects?: NewProject[];
  /** Tailored resume after accepted suggestions — used to attribute overflow to sections. */
  resume?: ResumeData | null;
  onDownload?: (format: "pdf" | "docx", layoutDensity?: string) => void;
  isDownloading?: "pdf" | "docx" | null;
  /** Increments on every accepted edit to guarantee the preview re-fetches. */
  previewKey?: number;
}

const BASE_WIDTH = 816;   // 8.5in @ 96dpi
const BASE_HEIGHT = 1056; // 11in @ 96dpi
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 3;
// Rough rendered line height in the iframe (matches the templates' body line-height).
// Used only for advisory math ("you're ~K lines over") — not for layout.
const LINE_HEIGHT_PX = 22;
// Characters per visual line at typical body width — used to estimate how many
// visual lines a long bullet wraps to in the rendered template.
const CHARS_PER_LINE = 95;

/**
 * Canvas-style resume preview. The iframe renders at native letter size
 * (816×1056); a transform stage handles zoom + pan. Mouse-wheel + Ctrl/⌘
 * zooms; drag pans. Toolbar exposes fit-width / fit-page / 100%.
 */
export function ResumePreview({ resumeId, templateId = "standard", approvedSuggestions, newProjects, resume, onDownload, isDownloading, previewKey }: ResumePreviewProps) {
  const [showDownloadMenu, setShowDownloadMenu] = useState(false);
  const [html, setHtml] = useState<string>("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unapplied, setUnapplied] = useState<Array<{ section: string; mode: string; original: string; reason: string }>>([]);
  const [layoutDensity, setLayoutDensity] = useState<string>("compact");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const canvasRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [pageHeight, setPageHeight] = useState(BASE_HEIGHT);
  const isDragging = useRef(false);
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });

  const fitWidth = useCallback(() => {
    const el = canvasRef.current;
    if (!el) return;
    const z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, (el.clientWidth - 24) / BASE_WIDTH));
    setZoom(z);
    setPan({ x: Math.round((el.clientWidth - BASE_WIDTH * z) / 2), y: 12 });
  }, []);

  const fitPage = useCallback(() => {
    const el = canvasRef.current;
    if (!el) return;
    const zw = (el.clientWidth - 24) / BASE_WIDTH;
    const zh = (el.clientHeight - 24) / BASE_HEIGHT;
    const z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.min(zw, zh)));
    setZoom(z);
    setPan({
      x: Math.round((el.clientWidth - BASE_WIDTH * z) / 2),
      y: Math.round((el.clientHeight - BASE_HEIGHT * z) / 2),
    });
  }, []);

  useLayoutEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const maxFit = (el.clientWidth - 24) / BASE_WIDTH;
    const z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, maxFit));
    setZoom(z);
    setPan({ x: Math.round((el.clientWidth - BASE_WIDTH * z) / 2), y: 12 });
  }, []);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    let timer: ReturnType<typeof setTimeout>;
    const ro = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => fitWidth(), 100);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      clearTimeout(timer);
    };
  }, [fitWidth]);

  useEffect(() => {
    if (!resumeId) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setIsLoading(true);
      setError(null);
      try {
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8055";
        const res = await fetch(`${apiUrl}/api/tailor/preview`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            resume_id: resumeId,
            template_id: templateId,
            layout_density: layoutDensity,
            suggestions: approvedSuggestions.map((s) => ({
              id: s.id,
              section: s.section,
              mode: s.mode,
              original: s.original,
              suggested: s.suggested,
              category: s.category,
              skill: s.skill,
              target_category: s.target_category,
              is_new_category: s.is_new_category,
              new_skills: s.new_skills,
            })),
            ...(newProjects && newProjects.length > 0 ? { new_projects: newProjects } : {}),
          }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Preview failed.");
        }
        const data = await res.json();
        setHtml(data.html || "");
        setUnapplied(Array.isArray(data.unapplied) ? data.unapplied : []);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Could not load preview.");
      } finally {
        setIsLoading(false);
      }
    }, 250);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [resumeId, templateId, layoutDensity, approvedSuggestions, newProjects, previewKey]);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;

    const onWheelNative = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const rect = el.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;
        const factor = e.deltaY < 0 ? 1.1 : 0.9;
        setZoom((prevZoom) => {
          const next = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, prevZoom * factor));
          // Anchor zoom at cursor.
          setPan((prevPan) => {
            const ratio = next / prevZoom;
            return {
              x: Math.round(mouseX - (mouseX - prevPan.x) * ratio),
              y: Math.round(mouseY - (mouseY - prevPan.y) * ratio),
            };
          });
          return next;
        });
      } else {
        e.preventDefault();
        // Plain scroll → pan vertically and horizontally.
        setPan((prev) => ({ 
          x: Math.round(prev.x - e.deltaX), 
          y: Math.round(prev.y - e.deltaY) 
        }));
      }
    };

    el.addEventListener("wheel", onWheelNative, { passive: false });
    return () => {
      el.removeEventListener("wheel", onWheelNative);
    };
  }, []);

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    // Pan from anywhere — iframe has pointer-events:none so it never captures clicks.
    isDragging.current = true;
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDragging.current) return;
    setPan({
      x: Math.round(dragStart.current.panX + (e.clientX - dragStart.current.x)),
      y: Math.round(dragStart.current.panY + (e.clientY - dragStart.current.y)),
    });
  };

  const handleMouseUp = () => {
    isDragging.current = false;
    setDragging(false);
  };

  const setZoomClamped = useCallback((nextZoom: number) => {
    const z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, nextZoom));
    const el = canvasRef.current;
    if (el) {
      const cw = el.clientWidth;
      const ch = el.clientHeight;
      const scaledW = BASE_WIDTH * z;
      const scaledH = pageHeight * z;
      setPan({
        x: Math.round(Math.max(12, (cw - scaledW) / 2)),
        y: Math.round(scaledH < ch ? Math.max(12, (ch - scaledH) / 2) : 12),
      });
    }
    setZoom(z);
  }, [pageHeight]);


  // Per-section line-count estimate. Wrapping is approximated as
  // ceil(chars / CHARS_PER_LINE) — good enough for advisory math.
  const sectionBreakdown = useMemo(() => {
    if (!resume) return [] as Array<{ name: string; lines: number; px: number }>;
    const estimateLines = (text: string) =>
      Math.max(1, Math.ceil((text || "").length / CHARS_PER_LINE));

    const sections: Array<{ name: string; lines: number }> = [];

    if (resume.summary && resume.summary.trim()) {
      sections.push({ name: "Summary", lines: estimateLines(resume.summary) });
    }
    if (resume.experience && resume.experience.length > 0) {
      let lines = 0;
      for (const e of resume.experience) {
        lines += 1; // header
        for (const b of e.bullets || []) lines += estimateLines(b);
      }
      sections.push({ name: "Experience", lines });
    }
    if (resume.projects && resume.projects.length > 0) {
      let lines = 0;
      for (const p of resume.projects) {
        lines += 1; // header
        for (const b of p.bullets || []) lines += estimateLines(b);
      }
      sections.push({ name: "Projects", lines });
    }
    if (resume.education && resume.education.length > 0) {
      let lines = 0;
      for (const e of resume.education) {
        lines += 1;
        for (const d of e.details || []) lines += estimateLines(d);
      }
      sections.push({ name: "Education", lines });
    }
    if (resume.skills && resume.skills.length > 0) {
      let lines = 0;
      for (const c of resume.skills) {
        lines += 1 + estimateLines((c.skills || []).join(", "));
      }
      sections.push({ name: "Skills", lines });
    }
    if (resume.certifications && resume.certifications.length > 0) {
      let lines = 0;
      for (const c of resume.certifications) {
        const text = [c.name, c.issuer, c.date].filter(Boolean).join(" · ");
        lines += estimateLines(text);
      }
      sections.push({ name: "Certifications", lines });
    }

    return sections
      .map((s) => ({ ...s, px: s.lines * LINE_HEIGHT_PX }))
      .sort((a, b) => b.lines - a.lines);
  }, [resume]);

  const overflowPx = Math.max(0, pageHeight - BASE_HEIGHT);
  const overflowLines = overflowPx > 0 ? Math.ceil(overflowPx / LINE_HEIGHT_PX) : 0;
  const isOver = overflowPx > 0;
  const isNearEdge = !isOver && pageHeight > BASE_HEIGHT * 0.92;
  const headroomPx = Math.max(0, BASE_HEIGHT - pageHeight);

  const onIframeLoad = () => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    try {
      const doc = iframe.contentDocument;
      if (!doc?.body) return;
      // Belt-and-suspenders: kill any chance of the iframe body itself
      // scrolling. The outer canvas pan/zoom is the only allowed scroll path.
      if (!doc.getElementById("__no_iframe_scroll__")) {
        const style = doc.createElement("style");
        style.id = "__no_iframe_scroll__";
        style.textContent = "html,body{margin:0;overflow:hidden;}";
        doc.head?.appendChild(style);
      }
      const body = doc.body;
      const measure = () => {
        const h = Math.max(BASE_HEIGHT, body.scrollHeight);
        setPageHeight((cur) => (Math.abs(h - cur) > 1 ? h : cur));
      };
      measure();
      // Re-measure on layout changes inside the iframe (font swap, image
      // load, late paint) so pageHeight always covers the real content.
      const teardown = (iframe as unknown as { _cleanupRO?: () => void });
      teardown._cleanupRO?.();
      let measureTimer: ReturnType<typeof setTimeout>;
      const ro = new ResizeObserver(() => {
        clearTimeout(measureTimer);
        measureTimer = setTimeout(measure, 100);
      });
      ro.observe(body);
      teardown._cleanupRO = () => {
        ro.disconnect();
        clearTimeout(measureTimer);
      };

    } catch {
      // Cross-origin fallback ignored — srcDoc keeps us same-origin.
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-2 mb-2 px-2 py-1.5 rounded-lg bg-subtle/50 border border-border flex-wrap">
        <span className="text-xs font-semibold uppercase tracking-wider text-foreground/70 shrink-0">
          Preview
        </span>
        <div className="flex items-center gap-1 flex-wrap">
          <select
            value={layoutDensity}
            onChange={(e) => setLayoutDensity(e.target.value)}
            className="text-[11px] h-7 px-2 py-1 mr-1 rounded border border-border bg-background text-muted hover:text-foreground transition-colors outline-none focus:ring-1 focus:ring-primary/20"
            title="Adjust layout density"
          >
            <option value="expanded">Expanded</option>
            <option value="standard">Standard</option>
            <option value="compact">Compact</option>
            <option value="latex-tight">Tight</option>
          </select>
          <button
            onClick={() => setZoomClamped(zoom * 0.9)}
            className="btn-ghost p-1.5"
            title="Zoom out"
          >
            <Minus className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setZoomClamped(1)}
            className="text-[11px] tabular-nums px-2 py-1 rounded hover:bg-subtle transition-colors min-w-[3.5rem]"
            title="Reset to 100%"
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            onClick={() => setZoomClamped(zoom * 1.1)}
            className="btn-ghost p-1.5"
            title="Zoom in"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
          <span className="w-px h-4 bg-border mx-1" />
          <button
            onClick={fitPage}
            className="btn-ghost p-1.5"
            title="Fit whole page"
          >
            <FileText className="w-3.5 h-3.5" />
          </button>
          {onDownload && (
            <div className="relative ml-1">
              <button
                onClick={() => setShowDownloadMenu((v) => !v)}
                disabled={isDownloading != null}
                className="btn-primary h-7 px-2 text-[11px] inline-flex items-center gap-1 disabled:opacity-60"
                title="Download tailored resume"
              >
                {isDownloading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Download className="w-3.5 h-3.5" />
                )}
                Download
                <ChevronDown className="w-3 h-3" />
              </button>
              {showDownloadMenu && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setShowDownloadMenu(false)} />
                  <div className="absolute right-0 top-full mt-1 z-20 w-32 card shadow-xl py-1">
                    <button
                      onClick={() => { setShowDownloadMenu(false); onDownload("pdf", layoutDensity); }}
                      disabled={isDownloading != null}
                      className="w-full text-left px-3 py-1.5 text-xs hover:bg-subtle transition-colors flex items-center gap-2"
                    >
                      <Download className="w-3 h-3" /> PDF
                    </button>
                    <button
                      onClick={() => { setShowDownloadMenu(false); onDownload("docx", layoutDensity); }}
                      disabled={isDownloading != null}
                      className="w-full text-left px-3 py-1.5 text-xs hover:bg-subtle transition-colors flex items-center gap-2"
                    >
                      <Download className="w-3 h-3" /> DOCX
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Overflow advisory — appears above the canvas when content exceeds one page,
          or as a soft hint when close to the limit. */}
      {isOver && !isLoading && (
        <div className="mb-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-[11px] leading-snug">
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-700 mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1 space-y-1">
              <p className="font-semibold text-amber-900">
                Resume runs ~{overflowLines} extra line{overflowLines !== 1 ? "s" : ""} past page 1.
              </p>
              <p className="text-amber-800">
                Tip: remove ~{overflowLines} bullet{overflowLines !== 1 ? "s" : ""} from your longest section{resume?.summary && resume.summary.trim() ? ", or tighten the summary" : ""}.
              </p>
              {sectionBreakdown.length > 0 && (
                <p className="text-amber-700/90">
                  Longest:{" "}
                  {sectionBreakdown.slice(0, 3).map((s, i) => (
                    <span key={s.name}>
                      {i > 0 && " · "}
                      <span className="font-medium">{s.name}</span>{" "}
                      <span className="text-amber-700/70">({s.lines} lines · ~{Math.round(s.px)}px)</span>
                    </span>
                  ))}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
      {isNearEdge && !isLoading && (
        <div className="mb-2 rounded-md border border-border bg-subtle/40 px-3 py-1.5 text-[11px] inline-flex items-center gap-1.5 text-muted">
          <Info className="w-3 h-3" />
          Close to page-2 edge — add about {Math.max(1, Math.round(headroomPx / 18))} more line{Math.max(1, Math.round(headroomPx / 18)) !== 1 ? "s" : ""} before it spills.
        </div>
      )}


      {/* Canvas */}
      <div
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        className="relative flex-1 rounded-lg bg-subtle border border-border overflow-hidden"
        style={{
          cursor: dragging ? "grabbing" : "grab",
          minHeight: "60vh",
        }}
      >
        {isLoading && html && (
          <div className="absolute top-3 right-3 z-10 inline-flex items-center gap-1.5 text-[11px] text-muted bg-white/80 backdrop-blur px-2.5 py-1 rounded-full shadow-sm">
            <span className="flex h-2 w-2 relative">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
            </span>
            Updating preview…
          </div>
        )}

        {error && !isLoading && (
          <div className="absolute inset-0 flex items-center justify-center p-8 text-center text-sm text-danger">
            {error}
          </div>
        )}

        {!error && (
          <div
            ref={wrapperRef}
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: BASE_WIDTH,
              height: pageHeight,
              transformOrigin: "0 0",
              transform: `translate3d(${pan.x}px, ${pan.y}px, 0) scale(${zoom})`,
              willChange: "transform",
              boxShadow: "0 4px 24px rgba(0,0,0,0.10)",
              background: "white",
              backfaceVisibility: "hidden",
            }}
          >

            {!html ? (
              <div className="w-full h-full p-16 space-y-8 animate-pulse bg-white select-none">
                {/* Header */}
                <div className="space-y-3 text-center">
                  <div className="h-6 bg-muted/30 rounded w-1/3 mx-auto" />
                  <div className="h-4 bg-muted/20 rounded w-1/2 mx-auto" />
                  <div className="h-3.5 bg-muted/20 rounded w-3/4 mx-auto" />
                </div>
                <hr className="border-border/60" />
                {/* Summary */}
                <div className="space-y-3">
                  <div className="h-4 bg-muted/25 rounded w-1/4" />
                  <div className="space-y-2">
                    <div className="h-3 bg-muted/15 rounded w-full" />
                    <div className="h-3 bg-muted/15 rounded w-11/12" />
                  </div>
                </div>
                {/* Experience */}
                <div className="space-y-5">
                  <div className="h-4 bg-muted/25 rounded w-1/4" />
                  {[1, 2].map((i) => (
                    <div key={i} className="space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="h-3.5 bg-muted/20 rounded w-1/3" />
                        <div className="h-3 bg-muted/15 rounded w-1/6" />
                      </div>
                      <div className="space-y-2 pl-4">
                        <div className="h-3 bg-muted/15 rounded w-11/12" />
                        <div className="h-3 bg-muted/15 rounded w-full" />
                      </div>
                    </div>
                  ))}
                </div>
                {/* Skills */}
                <div className="space-y-3">
                  <div className="h-4 bg-muted/25 rounded w-1/4" />
                  <div className="flex gap-2 flex-wrap">
                    {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
                      <div key={i} className="h-6 bg-muted/15 rounded w-16" />
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <iframe
                ref={iframeRef}
                srcDoc={html}
                title="Resume preview"
                onLoad={onIframeLoad}
                scrolling="no"
                sandbox="allow-same-origin allow-scripts"
                style={{
                  width: BASE_WIDTH,
                  height: pageHeight,
                  border: 0,
                  background: "white",
                  display: "block",
                  pointerEvents: "none",
                }}
              />
            )}

          </div>
        )}

        <div className="absolute bottom-2 left-2 text-[10px] text-muted/70 select-none pointer-events-none bg-white/60 backdrop-blur px-1.5 py-0.5 rounded">
          drag to pan · Ctrl/⌘ + wheel to zoom
        </div>
      </div>
    </div>
  );
}
