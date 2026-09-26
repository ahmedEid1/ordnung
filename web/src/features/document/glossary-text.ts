/**
 * Find German admin terms (from the glossary) in plain English text so they can be rendered as
 * `<Glossary>` tooltips: "file an Einspruch (objection)" → [text, term "Einspruch", text].
 */
import { GLOSSARY_TERMS, lookupTerm } from "@/lib/glossary";

export type GlossarySegment =
  | { type: "text"; text: string }
  | { type: "term"; term: string; text: string; /** the text already explains it: "Einspruch (objection)" */ explained: boolean };

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Longest terms first so "Rechtsbehelfsbelehrung" wins over shorter overlaps.
const TERMS = [...GLOSSARY_TERMS].map((e) => e.term).sort((a, b) => b.length - a.length);
const TERM_RE = new RegExp(`(?<![\\p{L}\\p{N}])(${TERMS.map(escapeRe).join("|")})(?![\\p{L}\\p{N}])`, "gu");

/** Characters around a term searched for its English translation ("an objection (Einspruch)"). */
const NEAR = 40;

/**
 * The text already says what the term means: "Einspruch (objection)", "objection (Einspruch)",
 * "advance payment (Abschlag)" or "working student (Werkstudent)" — no "(…)" to add.
 */
function isExplained(text: string, at: number, term: string): boolean {
  const before = text.slice(Math.max(0, at - NEAR), at);
  const after = text.slice(at + term.length);
  if (/^\s*\(/.test(after) || /\(\s*$/.test(before)) return true;
  const translation = lookupTerm(term)?.translation.toLowerCase();
  if (!translation) return false;
  const near = `${before} ${after.slice(0, NEAR)}`.toLowerCase();
  return translation.split(/[\s/]+/).some((word) => word.length > 3 && near.includes(word));
}

/**
 * Split `text` into plain segments and glossary terms. Only the first occurrence of each term is
 * marked (so a paragraph isn't littered with underlines). A term the text already translates
 * ({@link isExplained}) is flagged `explained` — the caller then shows the tooltip without adding a
 * translation.
 */
export function splitGlossary(text: string): GlossarySegment[] {
  const out: GlossarySegment[] = [];
  const seen = new Set<string>();
  let last = 0;
  for (const m of text.matchAll(TERM_RE)) {
    const term = m[1]!;
    const at = m.index ?? 0;
    if (seen.has(term.toLowerCase())) continue;
    seen.add(term.toLowerCase());
    if (at > last) out.push({ type: "text", text: text.slice(last, at) });
    out.push({ type: "term", term, text: term, explained: isExplained(text, at, term) });
    last = at + term.length;
  }
  if (last < text.length) out.push({ type: "text", text: text.slice(last) });
  return out;
}
