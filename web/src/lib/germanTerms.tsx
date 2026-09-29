/**
 * Titles with a German term in them — "Operating-cost statement (Betriebskostenabrechnung)", "Nebenkostenabrechnung
 * 2025 (Betriebs- und Heizkostenabrechnung) – Wohnbau Musterstadt eG" — keep the term whole or break it where
 * German breaks it: at 320 px it broke as "(Heizkostenabrechn" / "ung)" (review rounds 3 and 4 of phase 2). A German
 * term in brackets is marked German (hyphenated as German, read in a German voice), and a soft hyphen after the head
 * of a long compound lets it break there even where no German hyphenation is installed.
 */

/** The heads of German compounds after which a long word may break (the rest must be a word of 4+ letters). */
const COMPOUND_HEADS =
  /(Betriebskosten|Heizkosten|Nebenkosten|Vollstreckungs|Kündigungs|Kappungs|Mieterhöhungs|Einspruchs|Widerspruchs|Beitrags|Einkommensteuer|Miet|Mahn)(?=\p{Ll}{4,})/gu;

/**
 * A compound's joint after a linking "s" ("Immatrikulations|bescheinigung", "Verwaltungs|gericht"): the last one
 * in a long word, followed by a part of five letters or more.
 */
const LINKING_JOINT = /(\p{L}{3,}(?:ions|ungs|heits|keits|schafts|täts))(?=\p{Ll}{5,})/gu;

/** ``term`` with a soft hyphen after each compound head, when it is long enough to need one. */
export function softHyphens(term: string): string {
  if (term.length < 16) return term;
  // a known head first; a long word without one breaks at its last linking joint
  return term.replace(COMPOUND_HEADS, "$1\u00ad").replace(/[^\s\u00ad]{16,}/g, (word) => word.replace(LINKING_JOINT, "$1\u00ad"));
}

/** What makes a bracketed term German: an umlaut or ß, or a German word ending (not an English title's "(2025)"). */
const GERMAN = /[äöüßÄÖÜ]|(?:ung|bescheid|verlangen|schreiben|klage|abrechnung|beitrag|kosten|frist)\b/i;

/**
 * ``text`` with its bracketed German term marked German (``lang="de"``, manual hyphens) and soft hyphens after the
 * compound heads of its long words.
 */
export function GermanTerms({ text }: { text: string }) {
  const found = /^(.*?)\s*\(([^()]+)\)(.*)$/.exec(text);
  if (!found || !GERMAN.test(found[2]!)) return <>{softHyphens(text)}</>;
  const [, head, term, tail] = found;
  return (
    <>
      {softHyphens(head!)}{" "}
      <span lang="de" className="hyphens-manual">
        ({softHyphens(term!)})
      </span>
      {softHyphens(tail!)}
    </>
  );
}
