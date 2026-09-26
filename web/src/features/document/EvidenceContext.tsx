/**
 * Shared hover / selection state between the panel (facts, to-dos) and the page viewer.
 * Hovering a fact lights up its highlight; selecting it scrolls the page to the highlight and
 * pulses it. `nonce` increments on every selection so re-selecting the same fact scrolls again.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { EvidenceAnchor } from "./evidence";

export interface EvidenceApi {
  anchors: EvidenceAnchor[];
  hovered: string | null;
  selected: string | null;
  nonce: number;
  hover: (id: string | null) => void;
  select: (id: string | null) => void;
  anchor: (id: string | null | undefined) => EvidenceAnchor | null;
}

const Ctx = createContext<EvidenceApi | null>(null);

export function EvidenceProvider({ anchors, children }: { anchors: EvidenceAnchor[]; children: ReactNode }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [sel, setSel] = useState<{ id: string | null; nonce: number }>({ id: null, nonce: 0 });
  const byId = useMemo(() => new Map(anchors.map((a) => [a.id, a])), [anchors]);

  const hover = useCallback((id: string | null) => setHovered(id), []);
  const select = useCallback((id: string | null) => setSel((s) => ({ id, nonce: s.nonce + 1 })), []);
  const anchor = useCallback((id: string | null | undefined) => (id ? byId.get(id) ?? null : null), [byId]);

  const value = useMemo<EvidenceApi>(
    () => ({ anchors, hovered, selected: sel.id, nonce: sel.nonce, hover, select, anchor }),
    [anchors, hovered, sel, hover, select, anchor],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

const NOOP: EvidenceApi = {
  anchors: [],
  hovered: null,
  selected: null,
  nonce: 0,
  hover: () => {},
  select: () => {},
  anchor: () => null,
};

/** Evidence hover/selection (a no-op outside a provider, so pieces render standalone in tests). */
export function useEvidence(): EvidenceApi {
  return useContext(Ctx) ?? NOOP;
}
