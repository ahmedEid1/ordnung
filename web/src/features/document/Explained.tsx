/** "Explained simply" — the letter in plain English, with German admin terms explained on hover. */
import { Fragment } from "react";
import { BookOpen, Landmark } from "lucide-react";
import type { Document } from "@/api/types";
import { Glossary } from "@/components/ui/Glossary";
import { englishInline, germanRuns } from "./fact-text";
import { splitGlossary } from "./glossary-text";
import { PanelSection } from "./PanelSection";

/** Plain text with its German words marked `lang="de"` (read out as German, hyphenated by German rules). */
function MarkedGerman({ text }: { text: string }) {
  return (
    <>
      {germanRuns(text).map((part, i) =>
        part.german ? (
          <span key={i} lang="de">
            {part.text}
          </span>
        ) : (
          <Fragment key={i}>{part.text}</Fragment>
        ),
      )}
    </>
  );
}

export function GlossaryText({
  text,
  inline,
  markGerman,
  explained,
}: {
  text: string;
  /** Money and dates in the app's format ("63.00 €" → "€63.00", "09.10.2026" → "Fri 9 Oct 2026"). */
  inline?: boolean;
  /** Mark the German words in the English text `lang="de"` ("(Werbungskosten/Entfernungspauschale)"). */
  markGerman?: boolean;
  /** The text around already says what the terms mean: no "(objection)" after them. */
  explained?: boolean;
}) {
  return (
    <>
      {splitGlossary(text).map((s, i) => {
        if (s.type === "term") return <Glossary key={i} term={s.term} translate={!(explained || s.explained)} />;
        const plain = inline ? englishInline(s.text) : s.text;
        return <span key={i}>{markGerman ? <MarkedGerman text={plain} /> : plain}</span>;
      })}
    </>
  );
}

export function ExplainedSimply({ doc }: { doc: Document }) {
  if (!doc.explanation && !doc.tax_note) return null;
  const paragraphs = (doc.explanation ?? "").split(/\n{2,}/).filter(Boolean);
  return (
    <PanelSection id="explained" title="Explained simply" icon={BookOpen}>
      <div className="card px-5 py-4 sm:px-6">
        <div className="space-y-3 text-[15px] leading-[1.7] text-ink/90">
          {paragraphs.map((p, i) => (
            <p key={i} className="wrap-break-word hyphens-auto">
              <GlossaryText text={p} inline markGerman />
            </p>
          ))}
        </div>
        {doc.tax_relevant && doc.tax_note ? (
          <p className="mt-4 flex items-start gap-2 rounded-lg bg-k-expiry-soft px-3 py-2.5 text-[13px] leading-5 text-k-expiry-ink">
            <Landmark className="mt-0.5 size-4 shrink-0" aria-hidden />
            {/* a long German term ("Werbungskosten/Entfernungspauschale") breaks — hyphenated by German rules where
                the browser can — instead of widening the page (UI audit round 1: it stuck out of the box at 320 px) */}
            <span className="min-w-0 [overflow-wrap:anywhere] hyphens-auto">
              <span className="font-semibold">For your tax return: </span>
              <GlossaryText text={doc.tax_note} inline markGerman />
            </span>
          </p>
        ) : null}
        {doc.language && doc.language !== "en" ? (
          <p className="mt-3 text-[12px] text-muted">Written by Claude from the German letter. The letter itself is what counts.</p>
        ) : null}
      </div>
    </PanelSection>
  );
}
