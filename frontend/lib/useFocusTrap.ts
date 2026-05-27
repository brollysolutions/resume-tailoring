"use client";

import { useEffect, useRef } from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/**
 * Trap Tab focus inside the returned ref element while `active`.
 * - Tab from last focusable → first.
 * - Shift+Tab from first → last.
 * - Auto-focuses first focusable on mount.
 * - Restores focus to the previously focused element on unmount.
 *
 * Esc handling is left to the caller (modals already have it).
 */
export function useFocusTrap<T extends HTMLElement>(active: boolean = true) {
  const ref = useRef<T | null>(null);
  const previousActive = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active) return;
    const root = ref.current;
    if (!root) return;

    previousActive.current = (document.activeElement as HTMLElement) || null;

    const queryFocusable = () =>
      Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => !el.hasAttribute("inert") && el.offsetParent !== null
      );

    const focusables = queryFocusable();
    focusables[0]?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const list = queryFocusable();
      if (list.length === 0) return;
      const first = list[0];
      const last = list[list.length - 1];
      const current = document.activeElement as HTMLElement | null;

      if (e.shiftKey) {
        if (current === first || !root.contains(current)) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (current === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previousActive.current?.focus?.();
    };
  }, [active]);

  return ref;
}
