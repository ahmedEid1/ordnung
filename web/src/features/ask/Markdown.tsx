import { Fragment, useMemo, type ReactNode } from "react";
import { Link } from "react-router";
import { cn } from "@/lib/utils";
import { parseMarkdown, type Block, type Inline } from "./markdown";
import { stripPartialMarker, type CitationRef } from "./citations";
import { formatInlineDates } from "@/lib/format";

export interface MarkdownProps {
  text: string;
  /** Validated citations by id; `null` while streaming (all markers hidden). */
  citations: ReadonlyMap<string, CitationRef> | null;
  /** Renders a validated citation chip. */
  renderCitation: (ref: CitationRef, key: string) => ReactNode;
  /** Streaming: hide a half-received marker at the end. */
  streaming?: boolean;
  className?: string;
}

/** What Ordnung's answer check writes where it left a date or amount out (`support.py`, rule 5). */
const LEFT_OUT = /\[(date left out|amount left out|Datum weggelassen|Betrag weggelassen)\]/g;
/** Punctuation that must not wrap onto a line of its own after a citation chip. */
const TRAILING_PUNCT = /^[.,;:!?)\]»”“"'…]+/;

function renderText(v: string, key: string): ReactNode {
  // answers quote dates from the ledger as ISO ("due 2026-10-01"): show them like the rest of the app
  const parts = v.split(LEFT_OUT);
  if (parts.length === 1) return <Fragment key={key}>{formatInlineDates(v)}</Fragment>;
  return (
    <Fragment key={key}>
      {parts.map((part, i) =>
        i % 2 ? (
          <span
            key={i}
            className="whitespace-nowrap rounded bg-surface-2 px-1 py-px text-[0.88em] italic text-muted"
            title="Ordnung left this out: the record the sentence cites does not hold it"
          >
            {part}
          </span>
        ) : (
          <Fragment key={i}>{formatInlineDates(part)}</Fragment>
        ),
      )}
    </Fragment>
  );
}

function renderInline(nodes: Inline[], renderCitation: MarkdownProps["renderCitation"], prefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i]!;
    const key = `${prefix}.${i}`;
    if (n.t !== "cite") {
      out.push(renderNode(n, key, renderCitation));
      continue;
    }
    // a run of chips and the punctuation right after it never wrap apart ("… 2025 ²:" keeps its colon)
    const chips: ReactNode[] = [renderCitation(n.ref, key)];
    for (let next = nodes[i + 1]; next; next = nodes[i + 1]) {
      if (next.t === "cite") chips.push(renderCitation(next.ref, `${prefix}.${++i}`));
      else if (next.t === "text" && /^[\s\u00a0]+$/.test(next.v) && nodes[i + 2]?.t === "cite") {
        chips.push(<Fragment key={`${prefix}.${++i}`}>{"\u00a0"}</Fragment>);
      } else break;
    }
    const after = nodes[i + 1];
    const punct = after?.t === "text" ? TRAILING_PUNCT.exec(after.v)?.[0] : undefined;
    out.push(
      <span key={`${key}.g`} className="whitespace-nowrap">
        {chips}
        {punct}
      </span>,
    );
    if (punct && after?.t === "text") {
      i++;
      if (after.v.length > punct.length) out.push(renderText(after.v.slice(punct.length), `${prefix}.${i}`));
    }
  }
  return out;
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
            <li key={j} className="pl-0.5">
              {renderInline(item, renderCitation, `${key}.${j}`)}
            </li>
          ))}
        </ol>
      );
  }
}

/**
 * A half-received answer ("Electricity: **48,00"): an emphasis or code span still open on the last
 * line loses its opening marker, so the words show without stray asterisks until the rest arrives.
 */
export function closePartialEmphasis(text: string): string {
  const start = text.lastIndexOf("\n") + 1;
  let line = text.slice(start);
  for (const marker of ["**", "`"]) {
    if (line.split(marker).length % 2 === 0) {
      const at = line.lastIndexOf(marker);
      line = line.slice(0, at) + line.slice(at + marker.length);
    }
  }
  return text.slice(0, start) + line;
}

/**
 * Renders an Ask answer from the safe Markdown subset (see `markdown.ts`). Output is React
 * elements only — raw HTML is shown as text, remote images and external links are never rendered.
 */
export function Markdown({ text, citations, renderCitation, streaming, className }: MarkdownProps) {
  const source = streaming ? closePartialEmphasis(stripPartialMarker(text)) : text;
  const blocks = useMemo(() => parseMarkdown(source, { citations }), [source, citations]);
  return (
    <div className={cn("space-y-3 text-[15px] leading-[1.65] text-ink/90", className)}>
      {blocks.map((b, i) => renderBlock(b, i, renderCitation))}
    </div>
  );
}
