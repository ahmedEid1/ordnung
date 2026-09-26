/** "Explained simply" — the letter in plain English, with German admin terms explained on hover. */
import { BookOpen, Landmark } from "lucide-react";
import type { Document } from "@/api/types";
import { Glossary } from "@/components/ui/Glossary";
import { splitGlossary } from "./glossary-text";
import { PanelSection } from "./PanelSection";

export function GlossaryText({ text }: { text: string }) {
  return (
    <>
      {splitGlossary(text).map((s, i) =>
        s.type === "text" ? <span key={i}>{s.text}</span> : <Glossary key={i} term={s.term} translate={!s.explained} />,
      )}
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
            <p key={i}>
              <GlossaryText text={p} />
            </p>
          ))}
        </div>
        {doc.tax_relevant && doc.tax_note ? (
          <p className="mt-4 flex items-start gap-2 rounded-lg bg-k-expiry-soft px-3 py-2.5 text-[13px] leading-5 text-k-expiry-ink">
            <Landmark className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              <span className="font-semibold">For your tax return: </span>
              {doc.tax_note}
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
