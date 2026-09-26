/**
 * Resolve cited ids (`doc_…`, `itm_…`, `ctr_…`, `pty_…`) to a title, an icon and where the chip
 * leads. Uses the cached ledger lists (cheap: everything is local).
 */
import { useCallback, useMemo } from "react";
import { FileText, ListTodo, Signature, Users, type LucideIcon } from "lucide-react";
import { useContracts, useDocuments, useItems, useParties } from "@/api/hooks";
import type { Contract, Document, Item, Party } from "@/api/types";
import type { CitationRef, CiteType } from "./citations";
import { contractHref } from "@/features/contracts/links";

export interface RefInfo {
  type: CiteType;
  id: string;
  /** readable title ("Phone contract — FunkNetz Allnet L") */
  title: string;
  /** what kind of record it is ("Letter", "To-do", …) */
  kindLabel: string;
  icon: LucideIcon;
  /** route for letters, to-dos and contracts; null for people (they open the drawer) */
  href: string | null;
}

const KIND: Record<CiteType, { label: string; icon: LucideIcon }> = {
  document: { label: "Letter", icon: FileText },
  item: { label: "To-do & date", icon: ListTodo },
  contract: { label: "Contract", icon: Signature },
  party: { label: "Person or organisation", icon: Users },
};

export interface RefSources {
  documents?: Document[];
  items?: Item[];
  contracts?: Contract[];
  parties?: Party[];
}

/** Pure resolver (exported for tests). */
export function makeRefResolver(src: RefSources) {
  const docs = new Map((src.documents ?? []).map((d) => [d.id, d]));
  const items = new Map((src.items ?? []).map((i) => [i.id, i]));
  const contracts = new Map((src.contracts ?? []).map((c) => [c.id, c]));
  const parties = new Map((src.parties ?? []).map((p) => [p.id, p]));

  const titleOf = (id: string): string | null => {
    const d = docs.get(id);
    if (d) return d.title ?? d.filename;
    const it = items.get(id);
    if (it) return it.title;
    const c = contracts.get(id);
    if (c) return c.name;
    const p = parties.get(id);
    if (p) return p.name;
    return null;
  };

  const resolve = (ref: CitationRef): RefInfo => {
    const kind = KIND[ref.type];
    const label = ref.label?.trim();
    // never show a bare id ("doc_x9…") as a title: fall back to the ledger's title, then the kind
    const title = (label && label !== ref.id ? label : null) || titleOf(ref.id) || kind.label;
    let href: string | null = null;
    if (ref.type === "document") href = `/documents/${encodeURIComponent(ref.id)}`;
    else if (ref.type === "item") {
      const it = items.get(ref.id);
      href = it?.doc_id ? `/documents/${encodeURIComponent(it.doc_id)}` : "/timeline";
    } else if (ref.type === "contract") href = contractHref(ref.id);
    return { type: ref.type, id: ref.id, title, kindLabel: kind.label, icon: kind.icon, href };
  };

  return { resolve, titleOf };
}

/** Hook version of {@link makeRefResolver} over the cached ledger lists. */
export function useRefResolver() {
  const documents = useDocuments();
  const items = useItems();
  const contracts = useContracts();
  const parties = useParties();
  const resolver = useMemo(
    () => makeRefResolver({ documents: documents.data, items: items.data, contracts: contracts.data, parties: parties.data }),
    [documents.data, items.data, contracts.data, parties.data],
  );
  const resolve = useCallback((ref: CitationRef) => resolver.resolve(ref), [resolver]);
  const titleOf = useCallback((id: string) => resolver.titleOf(id), [resolver]);
  return { resolve, titleOf };
}
