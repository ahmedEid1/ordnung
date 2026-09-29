import { Fragment, useMemo, type ReactNode } from "react";
import { Link } from "react-router";
import { cn } from "@/lib/utils";
import { parseMarkdown, type Block, type Inline } from "./markdown";
import type { CitationRef } from "./citations";
import { formatInlineDates } from "@/lib/format";
import { keepCitations, protectRefs } from "@/lib/glue";
import PLACEHOLDERS from "./placeholders.json";
import { withoutThisYear } from "./tools";

export interface MarkdownProps {
  text: string;
  /** Validated citations by id; `null` hides every marker. */
  citations: ReadonlyMap<string, CitationRef> | null;
  /** Renders a validated citation chip. */
  renderCitation: (ref: CitationRef, key: string) => ReactNode;
  /** The answer's language (its check note's label says it): a German answer's ISO dates read German. */
  language?: "en" | "de";
  /**
   * The app's today (`useTodayISO`): this year's dates leave the year out ("Thu 15 Oct"), as on every
   * other page (UI audit round 2). Without it a date written out keeps its year, and an ISO date gets one.
   */
  today?: string;
  className?: string;
}

/** How an answer's pieces are rendered: its citation chips and its dates. */
interface Render {
  cite: MarkdownProps["renderCitation"];
  dates: (text: string) => string;
}

/** Every placeholder Ordnung's answer check writes where it left a value out (`support.py`, rule 5:
 * "[date left out]", "[amount only in the letter]", "[Uhrzeit weggelassen]" …; the Python test reads the
 * same list), matched with plain or no-break spaces. */
const LEFT_OUT = new RegExp(
  `\\[(${(PLACEHOLDERS as string[]).map((p) => p.slice(1, -1).replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/ /g, "[ \u00a0]")).join("|")})\\]`,
  "g",
);
/** A whole placeholder (its spaces already no-break): it always joins the chips after it (review round 1). */
const LEFT_OUT_WHOLE = new RegExp(`^${LEFT_OUT.source}$`);
/** Punctuation that must not wrap onto a line of its own after a citation chip. */
const TRAILING_PUNCT = /^[.,;:!?)\]»”“"'…]+/;
/** The longest word that joins the chips after it (a longer one could not wrap on a phone). */
const MAX_JOINED_WORD = 24;

const MONTH = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|Okt|Dez";
/** Spaces a line must not break at: inside an amount ("324,00 €") or a date ("Wed 14 Oct 2026"). */
const KEEP_TOGETHER: [RegExp, string][] = [
  [/(\d)[ \t]+(€|EUR\b|Euro\b|USD\b|CHF\b|GBP\b|£|\$)/g, "$1\u00a0$2"],
  [/(€|\bEUR|\bUSD|\bCHF|\bGBP|£|\$)[ \t]+(\d)/g, "$1\u00a0$2"],
  [/\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun|Mo\.|Di\.|Mi\.|Do\.|Fr\.|Sa\.|So\.)[ \t]+(\d)/g, "$1\u00a0$2"],
  [new RegExp(`\\b(\\d{1,2}\\.?)[ \\t]+(${MONTH})\\b`, "g"), "$1\u00a0$2"],
  [new RegExp(`\\b(${MONTH})[ \\t]+(\\d{4})\\b`, "g"), "$1\u00a0$2"],
];

/** `text` with no-break spaces inside amounts, dates, law references (the section sign and its number,
 * "Abs. 3", "Art. 6") and the check's placeholders, and no-break hyphens inside reference numbers
 * ("TM-2026-0048213"), so none of them is split across two lines (UI audit round 1: a line broke between
 * the section sign and "56" at 320 px). Display only: a copied answer is the stored text, selected text
 * loses the glue (`copyWithoutGlue`). */
export function keepTogether(text: string): string {
  const joined = KEEP_TOGETHER.reduce((out, [pattern, nbsp]) => out.replace(pattern, nbsp), text);
  return protectRefs(keepCitations(joined)).replace(LEFT_OUT, (mark) => mark.replace(/ /g, "\u00a0"));
}

/** U+2060 WORD JOINER: no line break between the text before a citation marker and the marker. */
const WORD_JOINER = "\u2060";

/** Text nodes as they will be shown (ISO dates formatted, values kept together), before grouping. */
function prepare(nodes: Inline[], dates: Render["dates"]): Inline[] {
  return nodes.map((n) =>
    n.t === "text"
      ? { t: "text", v: keepTogether(dates(n.v)) }
      : n.t === "strong" || n.t === "em" || n.t === "link"
        ? { ...n, c: prepare(n.c, dates) }
        : n,
  );
}

function renderText(v: string, key: string, dates: Render["dates"]): ReactNode {
  // answers quote dates from the ledger as ISO ("due 2026-10-01"): show them like the rest of the app — in
  // the answer's language (review round 3 of phase 2: a German answer read "bis Thu 15 Oct 2026 fällig")
  const parts = v.split(LEFT_OUT);
  if (parts.length === 1) return <Fragment key={key}>{keepTogether(dates(v))}</Fragment>;
  return (
    <Fragment key={key}>
      {parts.map((part, i) =>
        i % 2 ? (
          // explained by the check's note under the answer (visible, not a hover-only tooltip)
          <span key={i} data-left-out="" className="whitespace-nowrap rounded bg-surface-2 px-1 py-px text-[0.88em] italic text-muted">
            {part}
          </span>
        ) : (
          <Fragment key={i}>{keepTogether(dates(part))}</Fragment>
        ),
      )}
    </Fragment>
  );
}

/** Where the last word of `v` starts (a run without breaking spaces: no-break spaces join), with the
 * spaces after it; found from the end, so linear. */
function lastWordStart(v: string): number {
  let end = v.length;
  while (end > 0 && BREAKING_SPACE.test(v[end - 1]!)) end--;
  let start = end;
  while (start > 0 && !BREAKING_SPACE.test(v[start - 1]!)) start--;
  return start;
}

const BREAKING_SPACE = /[ \t\n\r]/;

/**
 * `nodes` split before their last word (with the spaces after it): `[head, word]`. The word keeps
 * its emphasis; a link or code span is taken whole; a line break ends the search.
 */
function splitLastWord(nodes: Inline[]): [Inline[], Inline[]] {
  const head = [...nodes];
  const word: Inline[] = [];
  while (head.length) {
    const n = head.pop()!;
    if (n.t === "text") {
      const at = lastWordStart(n.v);
      if (at < n.v.length) word.unshift({ t: "text", v: n.v.slice(at) });
      if (at > 0) head.push({ t: "text", v: n.v.slice(0, at) });
      if (at > 0 || n.v.trim()) break; // found the word (or the node was one word)
      continue; // only spaces: the word is in the node before
    }
    if (n.t === "strong" || n.t === "em") {
      const [inner, last] = splitLastWord(n.c);
      if (last.length) word.unshift({ ...n, c: last });
      if (inner.length) head.push({ ...n, c: inner });
      break;
    }
    if (n.t === "link" || n.t === "code") word.unshift(n);
    else head.push(n); // a line break or a chip: nothing to join
    break;
  }
  return [head, word];
}

function shownLength(nodes: Inline[]): number {
  return nodes.reduce((sum, n) => sum + (n.t === "text" || n.t === "code" ? n.v.length : n.t === "br" || n.t === "cite" ? 0 : shownLength(n.c)), 0);
}

type Piece = { t: "node"; n: Inline } | { t: "chips"; word: Inline[]; refs: CitationRef[]; punct: string };

function isPlaceholder(word: Inline[]): boolean {
  const only = word.length === 1 ? word[0] : undefined;
  return only?.t === "text" && LEFT_OUT_WHOLE.test(only.v.trim());
}

/**
 * Inline nodes with every run of citation chips grouped with the word before it and the
 * punctuation after it: the group never wraps, so a chip never starts a line on its own ("…for
 * 2025²:" moves to the next line as a whole). A word too long to wrap stays outside the group (a
 * word joiner keeps the chip on its line).
 */
function groupChips(nodes: Inline[]): Piece[] {
  const pieces: Piece[] = [];
  let pending: Inline[] = [];
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i]!;
    if (n.t !== "cite") {
      pending.push(n);
      continue;
    }
    const refs = [n.ref];
    for (let next = nodes[i + 1]; next; next = nodes[i + 1]) {
      if (next.t === "cite") refs.push(next.ref);
      else if (!(next.t === "text" && /^\s+$/.test(next.v) && nodes[i + 2]?.t === "cite")) break;
      i++;
    }
    let [head, word] = splitLastWord(pending);
    // the check's placeholders are longer than a joined word may be, but a pill that always fits a line
    if (shownLength(word) > MAX_JOINED_WORD && !isPlaceholder(word)) [head, word] = [pending, []];
    pieces.push(...head.map((h): Piece => ({ t: "node", n: h })));
    pending = [];
    const after = nodes[i + 1];
    const punct = after?.t === "text" ? (TRAILING_PUNCT.exec(after.v)?.[0] ?? "") : "";
    if (punct && after?.t === "text") {
      i++;
      if (after.v.length > punct.length) pending.push({ t: "text", v: after.v.slice(punct.length) });
    }
    pieces.push({ t: "chips", word, refs, punct });
  }
  pieces.push(...pending.map((p): Piece => ({ t: "node", n: p })));
  return pieces;
}

function renderInline(nodes: Inline[], r: Render, prefix: string): ReactNode[] {
  return groupChips(prepare(nodes, r.dates)).map((piece, i) => {
    const key = `${prefix}.${i}`;
    if (piece.t === "node") return renderNode(piece.n, key, r);
    return (
      <span key={key} className="whitespace-nowrap">
        {/* a word too long to join the group: the marker still never starts a line (it follows the word
            without a space, and an inline-grid box is a break opportunity of its own) */}
        {piece.word.length ? null : WORD_JOINER}
        {piece.word.map((w, j) => renderNode(w, `${key}.w${j}`, r))}
        {piece.refs.map((ref, j) => (
          <Fragment key={`${key}.c${j}`}>
            {j ? "\u00a0" : null}
            {r.cite(ref, `${key}.c${j}`)}
          </Fragment>
        ))}
        {piece.punct}
      </span>
    );
  });
}

function renderNode(n: Inline, key: string, r: Render): ReactNode {
  switch (n.t) {
    case "text":
      return renderText(n.v, key, r.dates);
    case "br":
      return <br key={key} />;
    case "code":
      return (
        <code key={key} className="rounded bg-surface-2 px-1 py-px font-mono text-[0.88em] text-ink">
          {n.v}
        </code>
      );
    case "strong":
      return (
        <strong key={key} className="font-semibold text-ink">
          {renderInline(n.c, r, key)}
        </strong>
      );
    case "em":
      return <em key={key}>{renderInline(n.c, r, key)}</em>;
    case "link":
      return (
        <Link key={key} to={n.to} className="font-medium text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent">
          {renderInline(n.c, r, key)}
        </Link>
      );
    case "cite":
      return r.cite(n.ref, key);
  }
}

function renderBlock(b: Block, i: number, r: Render): ReactNode {
  const key = `b${i}`;
  switch (b.t) {
    case "p":
      return <p key={key}>{renderInline(b.c, r, key)}</p>;
    case "h":
      return (
        <p key={key} className="font-semibold text-ink">
          {renderInline(b.c, r, key)}
        </p>
      );
    case "quote":
      return (
        <blockquote key={key} className="border-l-2 border-line-strong pl-3 text-muted">
          {renderInline(b.c, r, key)}
        </blockquote>
      );
    case "pre":
      return (
        <pre key={key} className="overflow-x-auto rounded-lg bg-surface-2 p-3 font-mono text-[13px] leading-relaxed scrollbar-thin">
          <code>{b.v}</code>
        </pre>
      );
    case "ul":
      return (
        <ul key={key} className="list-disc space-y-1.5 pl-5 marker:text-faint">
          {b.items.map((item, j) => (
            <li key={j} className="pl-0.5">
              {renderInline(item, r, `${key}.${j}`)}
            </li>
          ))}
        </ul>
      );
    case "ol":
      return (
        <ol key={key} start={b.start} className="list-decimal space-y-1.5 pl-5 marker:font-medium marker:text-muted">
          {b.items.map((item, j) => (
            // each item keeps the number the answer wrote (the check read that number, not a count)
            <li key={j} value={b.numbers[j]} className="pl-0.5">
              {renderInline(item, r, `${key}.${j}`)}
            </li>
          ))}
        </ol>
      );
  }
}

/**
 * Renders an Ask answer from the safe Markdown subset (see `markdown.ts`). Output is React
 * elements only — raw HTML is shown as text, remote images and external links are never rendered.
 */
export function Markdown({ text, citations, renderCitation, language = "en", today, className }: MarkdownProps) {
  const blocks = useMemo(() => parseMarkdown(text, { citations }), [text, citations]);
  // an English answer's dates, ISO or written out, leave this year out as every other page does; a German
  // answer's read as Ordnung's German note writes them ("Do. 15.10.2026")
  const r: Render = {
    cite: renderCitation,
    dates: (v) => (language === "de" ? formatInlineDates(v, today, "de") : withoutThisYear(formatInlineDates(v, today), today)),
  };
  return (
    // a long compound ("Wohnungsgeberbestätigung") or reference wraps anywhere rather than widen the page,
    // inside any flex or grid parent too (UI audit round 1: 344 px wide at 320)
    <div lang={language === "de" ? "de" : undefined} className={cn("space-y-3 text-[15px] leading-[1.65] text-ink/90 [overflow-wrap:anywhere]", className)}>
      {blocks.map((b, i) => renderBlock(b, i, r))}
    </div>
  );
}
