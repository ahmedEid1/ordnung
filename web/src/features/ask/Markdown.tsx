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

function renderInline(nodes: Inline[], renderCitation: MarkdownProps["renderCitation"], prefix: string): ReactNode[] {
  return nodes.map((n, i) => {
    const key = `${prefix}.${i}`;
    switch (n.t) {
      case "text":
        // answers quote dates from the ledger as ISO ("due 2026-10-01"): show them like the rest of the app
        return <Fragment key={key}>{formatInlineDates(n.v)}</Fragment>;
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
  });
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
 * Renders an Ask answer from the safe Markdown subset (see `markdown.ts`). Output is React
 * elements only — raw HTML is shown as text, remote images and external links are never rendered.
 */
export function Markdown({ text, citations, renderCitation, streaming, className }: MarkdownProps) {
  const source = streaming ? stripPartialMarker(text) : text;
  const blocks = useMemo(() => parseMarkdown(source, { citations }), [source, citations]);
  return (
    <div className={cn("space-y-3 text-[15px] leading-[1.65] text-ink/90", className)}>
      {blocks.map((b, i) => renderBlock(b, i, renderCitation))}
    </div>
  );
}
