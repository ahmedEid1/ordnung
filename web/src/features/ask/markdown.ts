/**
 * A tiny, safe Markdown subset for Ask answers (SPEC §10: "rendered without raw HTML and without
 * remote images").
 *
 * The parser produces a small AST that `<Markdown>` renders as React elements — nothing is ever
 * passed to `innerHTML`, so HTML in an answer shows up as literal text. Supported: paragraphs
 * (single newlines become line breaks), `-`/`*`/`•` and `1.` lists, headings (rendered as a bold
 * line), fenced code, quotes, **bold**, *italic*, `inline code`, and links **only to internal
 * routes** (`/documents/doc_x`). External links keep their text but lose the link; images keep
 * only their alt text. Citation markers become `cite` nodes when validated and vanish otherwise.
 */
import { markerAt, type CitationRef } from "./citations";

export type Inline =
  | { t: "text"; v: string }
  | { t: "strong"; c: Inline[] }
  | { t: "em"; c: Inline[] }
  | { t: "code"; v: string }
  | { t: "link"; to: string; c: Inline[] }
  | { t: "cite"; ref: CitationRef }
  | { t: "br" };

export type Block =
  | { t: "p"; c: Inline[] }
  | { t: "h"; c: Inline[] }
  | { t: "ul"; items: Inline[][] }
  | { t: "ol"; start: number; items: Inline[][] }
  | { t: "pre"; v: string }
  | { t: "quote"; c: Inline[] };

export interface ParseOptions {
  /**
   * Validated citations by id. `null` (while streaming) hides every marker; an id missing from
   * the map is stripped.
   */
  citations: ReadonlyMap<string, CitationRef> | null;
}

/** Only same-app paths are clickable: `/documents/doc_x`, `/timeline?month=…`. */
export function isInternalHref(href: string): boolean {
  return /^\/(?![/\\])[^\s\\]*$/.test(href);
}

// ------------------------------------------------------------------------------------------------
// Blocks
// ------------------------------------------------------------------------------------------------

const FENCE = /^\s{0,3}(```|~~~)/;
const HEADING = /^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/;
const RULE = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/;
const UL = /^\s*[-*+•]\s+(.*)$/;
const OL = /^\s*(\d{1,4})[.)]\s+(.*)$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;

function startsBlock(line: string): boolean {
  return FENCE.test(line) || HEADING.test(line) || RULE.test(line) || UL.test(line) || OL.test(line) || QUOTE.test(line);
}

/** Parse Markdown into blocks with inline nodes. */
export function parseMarkdown(text: string, opts: ParseOptions): Block[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  const inline = (s: string) => parseInline(s, opts.citations);
  let i = 0;
  while (i < lines.length) {
    const line = lines[i]!;
    if (!line.trim()) {
      i++;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i]!.trimStart().startsWith(fence[1]!)) body.push(lines[i++]!);
      i++; // closing fence (or end)
      blocks.push({ t: "pre", v: body.join("\n") });
      continue;
    }
    if (RULE.test(line)) {
      i++;
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({ t: "h", c: inline(heading[1]!) });
      i++;
      continue;
    }
    if (UL.test(line) || OL.test(line)) {
      const ordered = !UL.test(line);
      const re = ordered ? OL : UL;
      const start = ordered ? Number(OL.exec(line)![1]) : 1;
      const items: string[] = [];
      while (i < lines.length) {
        const l = lines[i]!;
        const m = re.exec(l);
        if (m) {
          items.push(ordered ? m[2]! : m[1]!);
          i++;
        } else if (l.trim() && /^\s+/.test(l) && !startsBlock(l.trim()) && items.length) {
          items[items.length - 1] += `\n${l.trim()}`; // indented continuation line
          i++;
        } else if (l.trim() && items.length && (UL.test(l) || OL.test(l))) {
          break; // the other list type starts
        } else {
          break;
        }
      }
      const parsed = items.map(inline);
      blocks.push(ordered ? { t: "ol", start, items: parsed } : { t: "ul", items: parsed });
      continue;
    }
    if (QUOTE.test(line)) {
      const body: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i]!)) body.push(QUOTE.exec(lines[i++]!)![1]!);
      blocks.push({ t: "quote", c: inline(body.join("\n")) });
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i]!.trim() && !(para.length && startsBlock(lines[i]!))) para.push(lines[i++]!.trim());
    const c = inline(para.join("\n"));
    if (c.length) blocks.push({ t: "p", c });
  }
  return blocks.filter((b) => !("c" in b) || b.c.some((n) => n.t !== "br"));
}

// ------------------------------------------------------------------------------------------------
// Inline
// ------------------------------------------------------------------------------------------------

const LINK = /\[([^\]\n]+)\]\(\s*([^)\s]*)(?:\s+"[^"\n]*")?\s*\)/y;
const IMAGE = /!\[([^\]\n]*)\]\(\s*[^)\n]*\)/y;
const ESCAPABLE = /[\\`*_[\]()#+\-.!>~|{}]/;

function isWordChar(ch: string | undefined): boolean {
  return Boolean(ch && /[\p{L}\p{N}]/u.test(ch));
}

/** Find the closing delimiter for emphasis starting at `i`; returns [innerStart, innerEnd, next]. */
function emphasisAt(src: string, i: number): { strong: boolean; inner: string; next: number } | null {
  const ch = src[i]!;
  const double = src[i + 1] === ch;
  const delim = double ? ch + ch : ch;
  const open = i + delim.length;
  if (open >= src.length || /\s/.test(src[open]!)) return null;
  // underscores only count at word boundaries (snake_case stays literal)
  if (ch === "_" && isWordChar(src[i - 1])) return null;
  let j = open;
  while (j < src.length) {
    const k = src.indexOf(delim, j);
    if (k < 0) return null;
    const closeOk =
      k > open &&
      !/\s/.test(src[k - 1]!) &&
      (double || src[k + 1] !== ch) &&
      !(ch === "_" && isWordChar(src[k + delim.length]));
    if (closeOk && !src.slice(open, k).includes("\n\n")) return { strong: double, inner: src.slice(open, k), next: k + delim.length };
    j = k + 1;
  }
  return null;
}

function pushText(out: Inline[], v: string) {
  if (!v) return;
  const last = out[out.length - 1];
  if (last?.t === "text") last.v += v;
  else out.push({ t: "text", v });
}

/** Parse inline Markdown. `citations` as in {@link ParseOptions}. */
export function parseInline(src: string, citations: ReadonlyMap<string, CitationRef> | null, depth = 0): Inline[] {
  const out: Inline[] = [];
  let i = 0;
  while (i < src.length) {
    const ch = src[i]!;
    if (ch === "\\" && i + 1 < src.length && ESCAPABLE.test(src[i + 1]!)) {
      pushText(out, src[i + 1]!);
      i += 2;
      continue;
    }
    if (ch === "\n") {
      out.push({ t: "br" });
      i++;
      continue;
    }
    if (ch === "`") {
      const end = src.indexOf("`", i + 1);
      if (end > i + 1) {
        out.push({ t: "code", v: src.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
    }
    if (ch === "[") {
      const marker = markerAt(src, i);
      if (marker) {
        const seen = new Set<string>();
        const kept = marker.refs.filter((r) => {
          const ok = citations?.get(r.id)?.type === r.type && !seen.has(r.id);
          seen.add(r.id);
          return ok;
        });
        if (kept.length) for (const r of kept) out.push({ t: "cite", ref: citations!.get(r.id)! });
        else {
          // drop the marker together with the spaces before it: "fact [doc:x]." → "fact."
          const last = out[out.length - 1];
          if (last?.t === "text") last.v = last.v.replace(/[ \t]+$/, "");
        }
        i = marker.end;
        continue;
      }
      LINK.lastIndex = i;
      const link = LINK.exec(src);
      if (link) {
        const inner = parseInline(link[1]!, citations, depth + 1);
        const href = link[2]!;
        if (isInternalHref(href)) out.push({ t: "link", to: href, c: inner });
        else
          for (const n of inner) {
            if (n.t === "text") pushText(out, n.v);
            else out.push(n);
          }
        i = LINK.lastIndex;
        continue;
      }
    }
    if (ch === "!" && src[i + 1] === "[") {
      IMAGE.lastIndex = i;
      const img = IMAGE.exec(src);
      if (img) {
        pushText(out, img[1]!); // never load remote images — keep only the description
        i = IMAGE.lastIndex;
        continue;
      }
    }
    if ((ch === "*" || ch === "_") && depth < 4) {
      const em = emphasisAt(src, i);
      if (em) {
        const c = parseInline(em.inner, citations, depth + 1);
        out.push(em.strong ? { t: "strong", c } : { t: "em", c });
        i = em.next;
        continue;
      }
    }
    pushText(out, ch);
    i++;
  }
  return out;
}

/** Plain text of inline nodes (for tests and accessible summaries). */
export function inlineText(nodes: Inline[]): string {
  return nodes
    .map((n) => (n.t === "text" || n.t === "code" ? n.v : n.t === "br" ? "\n" : n.t === "cite" ? "" : inlineText(n.c)))
    .join("");
}
