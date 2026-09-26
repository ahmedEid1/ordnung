import { formatInlineText, looksGerman } from "@/lib/format";
import { useToday } from "@/lib/today";
import { cn } from "@/lib/utils";

/**
 * Text taken from a letter that may still be German ("Geht der Betrag nicht fristgerecht ein…"):
 * shown as a marked quote with `lang="de"` (right hyphenation and voice), so it never reads as
 * the app's own English.
 *
 * Money, dates and law references read the app's way and never break apart (`formatInlineText`):
 * English text gets "€94.99" for "94.99 EUR"; a German quote stays as the letter wrote it, with
 * only its units kept together ("184,30 €", "§ 56 Abs. 3").
 */
export function LetterText({ text, className }: { text: string; className?: string }) {
  const today = useToday();
  if (!looksGerman(text)) return <>{formatInlineText(text, { today })}</>;
  return (
    <span className={className}>
      <span className="text-muted">The letter says (in German): </span>
      <q lang="de" className={cn("italic hyphens-auto")}>
        {formatInlineText(text.replace(/^[„“"]|[“”"]$/g, ""), { rewrite: false })}
      </q>
    </span>
  );
}
