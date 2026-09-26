import { cn } from "@/lib/utils";
import { lookupTerm } from "@/lib/glossary";
import { Tooltip } from "./Tooltip";

export interface GlossaryProps {
  /** German term, e.g. "Einspruch". */
  term: string;
  /** Show "(objection)" after the term (default true). */
  translate?: boolean;
  /** Override the visible text (keeps the tooltip). */
  children?: string;
  className?: string;
}

/**
 * German admin term with its English meaning — "Einspruch (objection)" — and a one-line
 * explanation on hover/focus. Unknown terms render as plain text.
 *
 * @example You can file an <Glossary term="Einspruch" /> until Wed 21 Oct.
 */
export function Glossary({ term, translate = true, children, className }: GlossaryProps) {
  const entry = lookupTerm(term);
  if (!entry) return <span className={className}>{children ?? term}</span>;
  const text = children ?? (translate ? `${entry.term} (${entry.translation})` : entry.term);
  return (
    <Tooltip content={<><span className="font-semibold">{entry.term}</span> — {entry.explanation}</>}>
      <span
        tabIndex={0}
        lang={children ? undefined : "de"}
        className={cn(
          "cursor-help rounded-sm underline decoration-muted/60 decoration-dotted underline-offset-[3px] hover:decoration-accent focus-visible:decoration-accent",
          className,
        )}
      >
        {text}
      </span>
    </Tooltip>
  );
}
