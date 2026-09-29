import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useMatches } from "react-router";
import type { PageWidth } from "./layout";

export interface PageMeta {
  /** Title shown in the top bar and the browser tab. */
  title: string;
  /** Optional parent for a breadcrumb ("Inbox › Utility statement") and the phone back button. */
  parent?: { to: string; label: string };
  /** The page's content width, so the top bar can line up with it. */
  width?: PageWidth;
}

interface PageMetaApi {
  meta: PageMeta | null;
  setMeta: (m: PageMeta | null) => void;
}

const Ctx = createContext<PageMetaApi>({ meta: null, setMeta: () => {} });

export function PageMetaProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<PageMeta | null>(null);
  const value = useMemo(() => ({ meta, setMeta }), [meta]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Route `handle` shape used by the router ({ title, parent }). */
export interface RouteHandle {
  title?: string;
  parent?: { to: string; label: string };
}

/** Resolved meta: what the page set, else the matched route's `handle`. */
export function usePageMeta(): PageMeta {
  const { meta } = useContext(Ctx);
  const matches = useMatches();
  const handle = [...matches].reverse().find((m) => (m.handle as RouteHandle | undefined)?.title)?.handle as RouteHandle | undefined;
  return meta ?? { title: handle?.title ?? "Ordnung", parent: handle?.parent };
}

/**
 * Set the top-bar title (and `document.title`) for the current page, e.g. a letter's title.
 * Resets when the page unmounts.
 *
 * @example usePageTitle(doc?.title ?? "Letter", { to: "/inbox", label: "Inbox" })
 */
export function usePageTitle(title: string | null | undefined, parent?: { to: string; label: string }, width?: PageWidth): void {
  const { setMeta } = useContext(Ctx);
  const parentTo = parent?.to;
  const parentLabel = parent?.label;
  useEffect(() => {
    if (!title) return;
    setMeta({ title, parent: parentTo && parentLabel ? { to: parentTo, label: parentLabel } : undefined, width });
    return () => setMeta(null);
  }, [title, parentTo, parentLabel, width, setMeta]);
}

/** Keeps `document.title` in sync with the page meta. */
export function useDocumentTitle(): void {
  const { title } = usePageMeta();
  useEffect(() => {
    document.title = title && title !== "Ordnung" ? `${title} · Ordnung` : "Ordnung";
  }, [title]);
}
