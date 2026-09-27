import { Fragment, useMemo, type ReactNode } from "react";
import { Link } from "react-router";
import { cn } from "@/lib/utils";
import { parseMarkdown, type Block, type Inline } from "./markdown";
import type { CitationRef } from "./citations";
import { formatInlineDates } from "@/lib/format";
import PLACEHOLDERS from "./placeholders.json";

export interface MarkdownProps {
  text: string;
  /** Validated citations by id; `null` hides every marker. */
  citations: ReadonlyMap<string, CitationRef> | null;
  /** Renders a validated citation chip. */
  renderCitation: (ref: CitationRef, key: string) => ReactNode;
  className?: string;
}

/** Every placeholder Ordnung's answer check writes where it left a value out (`support.py`, rule 5:
 * "[date left out]", "[amount only in the letter]", "[Uhrzeit weggelassen]" …; the Python test reads the
 * same list), matched with plain or no-break spaces. */
const LEFT_OUT = new RegExp(
  `\\[(${(PLACEHOLDERS as string[]).map((p) => p.slice(1, -1).replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/ /g, "[ \u00a0]")).join("|")})\\]`,
  "g",
);
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

/** `text` with no-break spaces inside amounts, dates and the check's placeholders, so none of them is
 * split across two lines. */
export function keepTogether(text: string): string {
  const joined = KEEP_TOGETHER.reduce((out, [pattern, nbsp]) => out.replace(pattern, nbsp), text);
  return joined.replace(LEFT_OUT, (mark) => mark.replace(/ /g, "\u00a0"));
}

/** Text nodes as they will be shown (ISO dates formatted, values kept together), before grouping. */
function prepare(nodes: Inline[]): Inline[] {
  return nodes.map((n) =>
    n.t === "text"
      ? { t: "text", v: keepTogether(formatInlineDates(n.v)) }
      : n.t === "strong" || n.t === "em" || n.t === "link"
        ? { ...n, c: prepare(n.c) }
        : n,
  );
}

function renderText(v: string, key: string): ReactNode {
  // answers quote dates from the ledger as ISO ("due 2026-10-01"): show them like the rest of the app
  const parts = v.split(LEFT_OUT);
  if (parts.length === 1) return <Fragment key={key}>{keepTogether(formatInlineDates(v))}</Fragment>;
  return (
    <Fragment key={key}>
      {parts.map((part, i) =>
        i % 2 ? (
          // explained by the check's note under the answer (visible, not a hover-only tooltip)
          <span key={i} data-left-out="" className="whitespace-nowrap rounded bg-surface-2 px-1 py-px text-[0.88em] italic text-muted">
            {part}
          </span>
        ) : (
          <Fragment key={i}>{keepTogether(formatInlineDates(part))}</Fragment>
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

/**
 * Inline nodes with every run of citation chips grouped with the word before it and the
 * punctuation after it: the group never wraps, so a chip never starts a line on its own ("…for
 * 2025 ²:" moves to the next line as a whole). A word too long to wrap stays outside the group.
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
    if (shownLength(word) > MAX_JOINED_WORD) [head, word] = [pending, []];
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

function renderInline(nodes: Inline[], renderCitation: MarkdownProps["renderCitation"], prefix: string): ReactNode[] {
  return groupChips(prepare(nodes)).map((piece, i) => {
    const key = `${prefix}.${i}`;
    if (piece.t === "node") return renderNode(piece.n, key, renderCitation);
    return (
      <span key={key} className="whitespace-nowrap">
        {piece.word.map((w, j) => renderNode(w, `${key}.w${j}`, renderCitation))}
        {piece.refs.map((ref, j) => (
          <Fragment key={`${key}.c${j}`}>
            {j ? "\u00a0" : null}
            {renderCitation(ref, `${key}.c${j}`)}
          </Fragment>
        ))}
        {piece.punct}
      </span>
    );
  });
}

function renderNode(n: Inline, key: string, renderCitation: MarkdownProps["renderCitation"]): ReactNode {
  switch (n.t) {
    case "text":
      return renderText(n.v, key);
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
          {renderInline(n.c, renderCitation, key)}
        </strong>
      );
    case "em":
      return <em key={key}>{renderInline(n.c, renderCitation, key)}</em>;
    case "link":
      return (
        <Link key={key} to={n.to} className="font-medium text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent">
          {renderInline(n.c, renderCitation, key)}
        </Link>
      );
    case "cite":
      return renderCitation(n.ref, key);
  }
}

function renderBlock(b: Block, i: number, renderCitation: MarkdownProps["renderCitation"]): ReactNode {
  const key = `b${i}`;
  switch (b.t) {
    case "p":
      return <p key={key}>{renderInline(b.c, renderCitation, key)}</p>;
    case "h":
      return (
        <p key={key} className="font-semibold text-ink">
          {renderInline(b.c, renderCitation, key)}
        </p>
      );
    case "quote":
      return (
        <blockquote key={key} className="border-l-2 border-line-strong pl-3 text-muted">
          {renderInline(b.c, renderCitation, key)}
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
              {renderInline(item, renderCitation, `${key}.${j}`)}
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
              {renderInline(item, renderCitation, `${key}.${j}`)}
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
export function Markdown({ text, citations, renderCitation, className }: MarkdownProps) {
  const blocks = useMemo(() => parseMarkdown(text, { citations }), [text, citations]);
  return (
    <div className={cn("space-y-3 break-words text-[15px] leading-[1.65] text-ink/90", className)}>
      {blocks.map((b, i) => renderBlock(b, i, renderCitation))}
    </div>
  );
}
