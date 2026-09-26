import { looksGerman } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Text taken from a letter that may still be German ("Geht der Betrag nicht fristgerecht ein…"):
 * shown as a marked quote with `lang="de"` (right hyphenation and voice), so it never reads as
 * the app's own English. English text passes through unchanged.
 */
export function LetterText({ text, className }: { text: string; className?: string }) {
  if (!looksGerman(text)) return <>{text}</>;
  return (
    <span className={className}>
      <span className="text-muted">The letter says (in German): </span>
      <q lang="de" className={cn("italic hyphens-auto")}>
        {text.replace(/^[„“"]|[“”"]$/g, "")}
      </q>
    </span>
  );
}
