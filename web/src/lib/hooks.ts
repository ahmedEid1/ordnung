import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/** Subscribe to a CSS media query (e.g. `(min-width: 1024px)`). */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (cb: () => void) => {
      if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
      const mql = window.matchMedia(query);
      mql.addEventListener?.("change", cb);
      return () => mql.removeEventListener?.("change", cb);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => (typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(query).matches : false),
    () => false,
  );
}

/** Tailwind breakpoints as hooks. */
export const useIsDesktop = () => useMediaQuery("(min-width: 1024px)");
export const useIsTabletUp = () => useMediaQuery("(min-width: 768px)");

/** Debounce a changing value. */
export function useDebounced<T>(value: T, ms = 200): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** localStorage-backed state (JSON), resilient to storage being unavailable. */
export function useLocalStorage<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (v: T) => {
      setValue(v);
      try {
        localStorage.setItem(key, JSON.stringify(v));
      } catch {
        /* ignore */
      }
    },
    [key],
  );
  return [value, set];
}

/** True once the window has scrolled past `threshold` px. */
export function useScrolled(threshold = 4): boolean {
  const subscribe = useCallback((cb: () => void) => {
    window.addEventListener("scroll", cb, { passive: true });
    return () => window.removeEventListener("scroll", cb);
  }, []);
  return useSyncExternalStore(
    subscribe,
    () => window.scrollY > threshold,
    () => false,
  );
}

/** Run `handler` on a global keyboard shortcut (ignored while typing in inputs, unless `allowInInputs`). */
export function useHotkey(match: (e: KeyboardEvent) => boolean, handler: (e: KeyboardEvent) => void, allowInInputs = false): void {
  const ref = useRef({ match, handler });
  useEffect(() => {
    ref.current = { match, handler };
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
      if (typing && !allowInInputs) return;
      if (ref.current.match(e)) ref.current.handler(e);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [allowInInputs]);
}
