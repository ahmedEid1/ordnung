import { CalendarClock, Euro, MessageCircleQuestion, Smartphone, Stamp, type LucideIcon } from "lucide-react";

export interface SuggestedQuestion {
  question: string;
  icon: LucideIcon;
}

/**
 * The suggested questions (SPEC §14.7). The demo has recorded answers for exactly these, so they
 * must match `src/ordnung/demo/asks.json` word for word (checked by `suggestions.test.ts`); in the
 * demo the chips come from `/api/demo/questions` itself ({@link withIcons}), so they can't drift.
 */
export const SUGGESTED_QUESTIONS: readonly SuggestedQuestion[] = [
  { question: "When does my phone contract end, and by when do I have to cancel it?", icon: Smartphone },
  { question: "What do I have to pay in the next four weeks?", icon: Euro },
  { question: "Which deadlines are coming up in October?", icon: CalendarClock },
  { question: "When does my residence permit expire, and what should I do before then?", icon: Stamp },
];

export function isSuggestedQuestion(q: string): boolean {
  const norm = q.trim().toLowerCase();
  return SUGGESTED_QUESTIONS.some((s) => s.question.toLowerCase() === norm);
}

/** Icons for questions served by the backend: the known ones keep theirs, new ones get a generic one. */
export function withIcons(questions: readonly string[]): SuggestedQuestion[] {
  const known = new Map(SUGGESTED_QUESTIONS.map((s) => [s.question.toLowerCase(), s.icon]));
  return questions.map((question) => ({ question, icon: known.get(question.toLowerCase()) ?? MessageCircleQuestion }));
}
