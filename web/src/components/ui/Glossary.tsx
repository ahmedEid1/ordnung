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
  /**
   * Plain text, no tooltip and no tab stop — for use inside a `<label>` (a radio card, a switch's
   * description), where a focusable term would be an extra Tab stop and clicking it would pick
   * the option.
   */
  plain?: boolean;
  className?: string;
}

/**
 * German admin term with its English meaning — "Einspruch (objection)" — and a one-line
 * explanation on hover/focus. Only the German word is marked `lang="de"` (the translation is
 * English). Unknown terms render as plain text.
 *
 * @example You can file an <Glossary term="Einspruch" /> until Wed 21 Oct.
 */
export function Glossary({ term, translate = true, children, plain, className }: GlossaryProps) {
  const entry = lookupTerm(term);
  if (!entry) return children !== undefined ? <span className={className}>{children}</span> : <span lang="de" className={className}>{term}</span>;
  const text =
    children !== undefined ? (
      children
    ) : (
      <>
        <span lang="de">{entry.term}</span>
        {translate ? ` (${entry.translation})` : null}
      </>
    );
  if (plain) return <span className={className}>{text}</span>;
  return (
    <Tooltip content={<><span lang="de" className="font-semibold">{entry.term}</span> — {entry.explanation}</>}>
      <span
        tabIndex={0}
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
