import { useCallback, useEffect, useRef, useState } from "react";

/** Copy text to the clipboard (falls back to a hidden textarea on old browsers / http). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}

/**
 * `copy(text, id)` + which id was copied last (resets after 1.8 s) — for "Copied" feedback on
 * copy buttons. Announce the state in an aria-live region.
 */
export function useClipboard(resetMs = 1800) {
  const [copied, setCopied] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  const copy = useCallback(
    async (text: string, id: string = text) => {
      const ok = await copyText(text);
      if (!ok) return false;
      setCopied(id);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(null), resetMs);
      return true;
    },
    [resetMs],
  );
  return { copy, copied };
}
