/**
 * German admin terms, shown as "Einspruch (objection)" with a one-line English explanation in a
 * tooltip (see `<Glossary term="Einspruch" />`). Keys are the canonical German spelling.
 */
export interface GlossaryEntry {
  /** German term as it appears on letters */
  term: string;
  /** short English translation shown in brackets */
  translation: string;
  /** one-line plain-English explanation */
  explanation: string;
}

const entries: GlossaryEntry[] = [
  {
    term: "Einspruch",
    translation: "objection",
    explanation: "A formal objection to a tax office decision. Usually due one month after the letter counts as delivered.",
  },
  {
    term: "Widerspruch",
    translation: "objection",
    explanation: "A formal objection to a decision by an authority (not the tax office), e.g. health insurance or city office.",
  },
  {
    term: "Bescheid",
    translation: "official decision",
    explanation: "A formal decision from an authority. It becomes final if you don't object in time.",
  },
  {
    term: "Bekanntgabe",
    translation: "official delivery",
    explanation: "The day a decision counts as delivered — for posted letters since 2025 usually four days after the letter date.",
  },
  {
    term: "Frist",
    translation: "deadline",
    explanation: "A period within which something must be done or must arrive.",
  },
  {
    term: "Kündigung",
    translation: "cancellation / notice",
    explanation: "Ending a contract (phone, gym, flat, job). Often has a notice period and a required form.",
  },
  {
    term: "Mahnung",
    translation: "payment reminder",
    explanation: "A reminder that a payment is overdue. Later reminders can add fees and interest.",
  },
  {
    term: "Rechtsbehelfsbelehrung",
    translation: "how to object",
    explanation: "The paragraph at the end of a decision explaining how, where and by when you can object.",
  },
  {
    term: "Aktenzeichen",
    translation: "reference number",
    explanation: "The file number of your case. Always quote it when you reply.",
  },
  {
    term: "Nebenkostenabrechnung",
    translation: "utility cost statement",
    explanation: "Your landlord's yearly bill for heating, water, rubbish etc. — it can mean a back payment or a refund.",
  },
  {
    term: "Abschlag",
    translation: "instalment",
    explanation: "A fixed monthly advance payment (e.g. for electricity), settled once a year against real usage.",
  },
  {
    term: "Sonderkündigungsrecht",
    translation: "special right to cancel",
    explanation: "An extra right to leave a contract early, e.g. when the provider raises prices.",
  },
  {
    term: "Aufenthaltstitel",
    translation: "residence permit",
    explanation: "Your permission to live in Germany. Apply for an extension before it expires.",
  },
  {
    term: "Fiktionsbescheinigung",
    translation: "interim permit certificate",
    explanation: "A certificate proving your residence status continues while your extension is being processed.",
  },
  {
    term: "Rundfunkbeitrag",
    translation: "broadcasting fee",
    explanation: "The mandatory fee per household for public TV and radio (18,36 € per month in 2026).",
  },
  {
    term: "Semesterbeitrag",
    translation: "semester fee",
    explanation: "The fee you pay each semester to stay enrolled; often includes a public transport ticket.",
  },
  {
    term: "Werkstudent",
    translation: "working student",
    explanation: "A student job of usually up to 20 hours a week during the semester, with reduced social contributions.",
  },
  {
    term: "Verwarnungsgeld",
    translation: "on-the-spot fine",
    explanation: "A small fine (e.g. for parking). If you don't pay in time it can turn into a formal fine with fees.",
  },
  {
    term: "Einschreiben",
    translation: "registered letter",
    explanation: "A tracked letter. \"Einwurf-Einschreiben\" proves delivery to the mailbox — keep the receipt.",
  },
];

/** Lookup table (case-insensitive by German term). */
export const GLOSSARY: Record<string, GlossaryEntry> = Object.fromEntries(
  entries.map((e) => [e.term.toLowerCase(), e]),
);

export const GLOSSARY_TERMS: readonly GlossaryEntry[] = entries;

/** Find a glossary entry by German term (case-insensitive). */
export function lookupTerm(term: string): GlossaryEntry | undefined {
  return GLOSSARY[term.trim().toLowerCase()];
}

/** "Einspruch (objection)" — or the term unchanged when unknown. */
export function termWithTranslation(term: string): string {
  const e = lookupTerm(term);
  return e ? `${e.term} (${e.translation})` : term;
}
