/**
 * Citation markers in Ask answers (SPEC §10): `[doc:ID]`, `[item:ID]`, `[contract:ID]`,
 * `[party:ID]`. Mirrors `ordnung/assistant/citations.py`: grouped markers (`[doc:a, item:b]`) and
 * spelled-out types (`[document:doc_a]`) are understood.
 *
 * Only ids in the **validated** list of the final `done` event become chips; every other marker is
 * stripped (together with the space before it). While an answer is still streaming nothing is
 * validated yet, so all markers — including a half-received one at the very end — are hidden.
 */
import type { SuggestionRef } from "@/api/types";

/** A citation as the UI uses it (the API's `done` event may add a human `label`). */
export interface CitationRef {
  type: CiteType;
  id: string;
  label?: string | null;
}

export type CiteType = "document" | "item" | "contract" | "party";

/** Canonical marker word → ledger reference type. */
const MARKER_TYPES: Record<string, CiteType> = {
  doc: "document",
  document: "document",
  letter: "document",
  item: "item",
  itm: "item",
  todo: "item",
  contract: "contract",
  ctr: "contract",
  party: "party",
  pty: "party",
};

/** Ledger reference type → id prefix of the records it may cite. */
const ID_PREFIX: Record<CiteType, string> = { document: "doc", item: "itm", contract: "ctr", party: "pty" };

const PAIR = String.raw`[a-z]+\s*:\s*[a-z]{3}_[a-z0-9_]+`;
const GROUP_SRC = String.raw`\[\s*(${PAIR}(?:\s*[,;]\s*${PAIR})*)\s*\]`;
const PAIR_RE = /([a-z]+)\s*:\s*([a-z]{3}_[a-z0-9_]+)/gi;

/** A complete marker group starting exactly at `lastIndex` (sticky). */
export function markerAt(text: string, index: number): { end: number; refs: CitationRef[]; wellFormed: boolean } | null {
  const re = new RegExp(GROUP_SRC, "iy");
  re.lastIndex = index;
  const m = re.exec(text);
  if (!m) return null;
  const refs: CitationRef[] = [];
  let wellFormed = false;
  for (const pair of m[1]!.matchAll(PAIR_RE)) {
    const type = MARKER_TYPES[pair[1]!.toLowerCase()];
    const id = pair[2]!;
    if (type && id.split("_", 1)[0]!.toLowerCase() === ID_PREFIX[type]) {
      refs.push({ type, id });
      wellFormed = true;
    }
  }
  return { end: index + m[0].length, refs, wellFormed };
}

/** Every cited reference in reading order (well-formed markers only, duplicates kept). */
export function parseCitations(text: string): CitationRef[] {
  const out: CitationRef[] = [];
  const re = new RegExp(GROUP_SRC, "gi");
  for (const m of text.matchAll(re)) {
    const found = markerAt(text, m.index);
    if (found) out.push(...found.refs);
  }
  return out;
}

/** Map of validated citations by id (from the `done` event / the stored message). */
export function citationIndex(citations: readonly (SuggestionRef | CitationRef)[] | null | undefined): Map<string, CitationRef> {
  const map = new Map<string, CitationRef>();
  for (const c of citations ?? []) {
    if (c.type === "document" || c.type === "item" || c.type === "contract" || c.type === "party") {
      if (!map.has(c.id)) map.set(c.id, { type: c.type, id: c.id, label: (c as CitationRef).label ?? null });
    }
  }
  return map;
}

/**
 * Number the validated sources in order of first appearance in the answer (1, 2, 3…); validated
 * citations that are not in the text come last.
 */
export function numberCitations(text: string, valid: ReadonlyMap<string, CitationRef>): Map<string, number> {
  const out = new Map<string, number>();
  for (const r of parseCitations(text)) if (valid.get(r.id)?.type === r.type && !out.has(r.id)) out.set(r.id, out.size + 1);
  for (const id of valid.keys()) if (!out.has(id)) out.set(id, out.size + 1);
  return out;
}

/**
 * Remove markers whose id is not validated (all markers when `valid` is null). A marker that loses
 * all its ids disappears together with the spaces before it: `fact [doc:x].` → `fact.`
 */
export function stripInvalid(text: string, valid: ReadonlyMap<string, CitationRef> | null): string {
  const re = new RegExp(String.raw`[ \t]*` + GROUP_SRC, "gi");
  return text.replace(re, (whole) => {
    const lead = /^[ \t]*/.exec(whole)![0];
    const found = markerAt(whole, lead.length);
    const kept = (found?.refs ?? []).filter((r) => valid?.get(r.id)?.type === r.type);
    if (!kept.length) return "";
    return lead + [...new Set(kept.map((r) => `[${markerWord(r.type)}:${r.id}]`))].join("");
  });
}

/** Remove every marker (plain-text copy, screen-reader summaries). */
export function stripAllMarkers(text: string): string {
  return stripInvalid(text, null);
}

function markerWord(type: CiteType): string {
  return type === "document" ? "doc" : type;
}
