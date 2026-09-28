import { useMemo } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Check, Copy, Info, RotateCw, Square, TriangleAlert } from "lucide-react";
import { LogoMark } from "@/components/shell/Logo";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { useClipboard } from "@/features/today/clipboard";
import { looksGerman } from "@/lib/format";
import { useTodayISO } from "@/lib/today";
import { isStaticDemo } from "@/mocks/mode";
import { citationIndex, numberCitations, stripAllMarkers } from "./citations";
import { CitationChip, CitationMarker } from "./CitationChip";
import { Markdown } from "./Markdown";
import type { RefInfo } from "./refs";
import type { AnswerState } from "./stream";
import { ToolTrace } from "./ToolTrace";
import PAYMENT_NOTES from "./paymentNotes.json";
import type { AskTurn } from "./useAskThread";
import type { CitationRef } from "./citations";
import type { TitleLookup } from "./tools";

/**
 * The question, as a heading of its turn: screen readers can jump from question to question, and each
 * answer's "Sources" (h3) sits under its question instead of straight under the page's h1 (UI audit
 * round 1). A long word or an IBAN wraps inside the bubble instead of widening the page.
 */
export function QuestionBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <h2 className="min-w-0 max-w-[85%] whitespace-pre-line rounded-2xl rounded-br-md bg-accent-soft px-4 py-2.5 text-[15px] font-normal leading-relaxed text-ink [overflow-wrap:anywhere]">
        <span className="sr-only">You asked: </span>
        {text}
      </h2>
    </div>
  );
}

/** The progress line while an answer is written. Not a live region: the page's announcer already says
 * "Writing the answer …", and a second status in `<main>` would announce it twice. */
function Thinking({ writing }: { writing: boolean }) {
  return (
    // the dots sit on the first line of a wrapped line (phones), as the trace's icons do — centred on the
    // whole paragraph they sat beside its middle line (UI audit round 2)
    <p className="flex items-start gap-2 text-[14px] leading-5 text-muted">
      <span className="mt-[7px] flex shrink-0 gap-1" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span key={i} className="size-1.5 rounded-full bg-accent/60 animate-pulse-soft motion-reduce:animate-none" style={{ animationDelay: `${i * 180}ms` }} />
        ))}
      </span>
      {writing ? "Writing the answer — it appears once Ordnung has checked it against your records…" : "Looking through your records…"}
    </p>
  );
}

/** The label the check's note is shown (and copied) under, as the backend stores and prints it. */
export const CHECK_NOTE_LABEL = "Checked by Ordnung:";
export const CHECK_NOTE_LABEL_DE = "Von Ordnung geprüft:";

/**
 * The note's label: the one the backend sends with the answer (it knows the answer's language);
 * only a note without one (an older recording) has its language guessed.
 */
export function checkNoteLabel(note: string, label?: string | null): string {
  if (label) return label;
  return looksGerman(note) ? CHECK_NOTE_LABEL_DE : CHECK_NOTE_LABEL;
}

/**
 * Shown under a checked answer the check did not change, in the answer's language. It says what was
 * checked — the dates, times, amounts and laws, not every claim ("there is no deadline" is never read).
 */
export const CHECKED_LINE = "Dates and amounts checked against your records.";
export const CHECKED_LINE_DE = "Daten und Beträge mit Ihren Unterlagen abgeglichen.";

/**
 * What Ordnung's answer check did (ADR 0008): dates or amounts left out because the records their
 * sentences cite don't hold them, values marked as only a letter's, the person's words in quotation
 * marks, citations it added. The text comes only from the `done` event's `note` field, never from the
 * answer. Every checked answer shows the line, so an answer without a note is visibly checked too.
 */
/**
 * The check's note split into what to decide before paying — a rent increase's new rent, a late statement's
 * back-payment, a demand with scam signs (`support._PAYMENT_NOTES`; a Python test keeps the file equal) — and
 * the check's bookkeeping. The backend writes those first; an answer stored before had them last.
 */
export function splitCheckNote(text: string): { warnings: string[]; rest: string } {
  const warnings = (PAYMENT_NOTES as string[]).filter((note) => text.includes(note));
  const rest = warnings.reduce((left, note) => left.replace(note, ""), text).replace(/\s{2,}/g, " ").trim();
  return { warnings, rest };
}

export function CheckNote({ text, label }: { text: string | null; label?: string | null }) {
  const { warnings, rest } = text ? splitCheckNote(text) : { warnings: [], rest: "" };
  const shownLabel = text ? checkNoteLabel(text, label) : label;
  // a German note is read in a German voice (WCAG 3.1.2; review round 4 of phase 2: only the answer had lang="de")
  const lang = shownLabel === CHECK_NOTE_LABEL_DE ? "de" : undefined;
  return (
    <div className="mt-3 space-y-2">
      {/* what to decide before paying comes first, in the warning tone — under an answer that says the new rent
          "is due" it was the last sentence of the grey note (review round 2) */}
      {warnings.length ? (
        <p role="note" lang={lang} className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn-soft px-3 py-2 text-[13.5px] leading-5 text-ink">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          <span className="min-w-0 break-words">
            <span className="font-medium text-warn-ink">{shownLabel}</span> {warnings.join(" ")}
          </span>
        </p>
      ) : null}
      {rest || !warnings.length ? (
        <p role="note" lang={lang} className="flex items-start gap-2 rounded-lg border border-line bg-surface-2/60 px-3 py-2 text-[13px] leading-5 text-muted">
          <Info className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
          <span className="min-w-0 break-words">
            {rest ? (
              <>
                {warnings.length ? null : <span className="font-medium text-ink">{shownLabel}</span>} {rest}
              </>
            ) : (
              <span className="font-medium text-ink">{label === CHECK_NOTE_LABEL_DE ? CHECKED_LINE_DE : CHECKED_LINE}</span>
            )}
          </span>
        </p>
      ) : null}
    </div>
  );
}

export interface AnswerViewProps {
  answer: AnswerState;
  resolve: (ref: CitationRef) => RefInfo;
  titleOf?: TitleLookup;
  onRetry?: () => void;
  /**
   * The app's today (`useTodayISO`, the demo's simulated day): the steps' and the answer's dates leave
   * this year out ("Thu 15 Oct"), as on every other page (UI audit round 2). Display only.
   */
  today?: string;
}

/**
 * What the demo shows for a question it has no recorded answer for (`error_code: "demo_miss"`): a note,
 * not a failure — "Try again" could never work (UI audit round 1). The same words in the local demo and
 * the online one, which also says how to ask about your own letters.
 */
export function DemoMissNote() {
  return (
    <Callout tone="info" className="mt-2" title="No recorded answer for this question">
      The demo replays answers recorded for its sample letters — try one of the suggested questions.
      {isStaticDemo() ? " To ask about your own letters, install Ordnung." : null}
    </Callout>
  );
}

/**
 * One answer: tool trace, the checked text with citation chips, the check's line, sources and actions.
 * While the answer streams only the trace and a "writing" line show: its words appear once checked.
 */
export function AnswerView({ answer, resolve, titleOf, onRetry, today }: AnswerViewProps) {
  const { copy, copied } = useClipboard();
  const live = answer.status === "streaming";
  const demoMiss = answer.status === "error" && answer.errorCode === "demo_miss";
  const done = answer.status === "done";
  const body = done ? answer.text : "";
  const note = answer.note;
  // an answer that went through the claim-level check: not the demo's "no recording" reply, nor an
  // answer stored before the check existed (ADR 0008)
  const checked = done && answer.checked && Boolean(answer.messageId) && Boolean(body.trim());
  const valid = useMemo(() => (live ? null : citationIndex(answer.citations)), [live, answer.citations]);
  const numbers = useMemo(() => (valid ? numberCitations(body, valid) : new Map<string, number>()), [valid, body]);
  const sources = useMemo(
    () => (valid ? [...numbers.entries()].map(([id, n]) => ({ n, info: resolve(valid.get(id)!) })) : []),
    [valid, numbers, resolve],
  );
  const plain = stripAllMarkers(body).trim();
  // the note travels with a copied answer: it explains its quotation marks and "[date left out]"
  const copyText = note ? `${plain}\n\n${checkNoteLabel(note, answer.noteLabel)} ${note}` : plain;
  const copyId = answer.messageId ?? plain;
  const isCopied = copied === copyId;

  return (
    // on phones a smaller mark and gap leave the answer 12 px more of its narrow column (UI audit round 1)
    <div className="flex gap-2 sm:gap-3">
      <LogoMark className="mt-1 size-5 rounded-md sm:mt-0.5 sm:size-7 sm:rounded-lg" />
      <div className="min-w-0 flex-1" aria-busy={live || undefined}>
        <ToolTrace steps={answer.tools} live={live} titleOf={titleOf} today={today} />
        {body ? (
          <Markdown
            text={body}
            citations={valid}
            language={answer.noteLabel === CHECK_NOTE_LABEL_DE ? "de" : "en"}
            today={today}
            renderCitation={(ref, key) => <CitationMarker key={key} info={resolve(ref)} n={numbers.get(ref.id) ?? 0} />}
          />
        ) : live ? (
          <Thinking writing={answer.writing} />
        ) : null}

        {checked ? <CheckNote text={note} label={answer.noteLabel} /> : null}

        {answer.status === "stopped" ? (
          <p className="mt-2 inline-flex items-center gap-1.5 text-[13px] text-muted">
            <Square className="size-3" aria-hidden /> Stopped before Ordnung checked an answer — nothing of it is shown.
          </p>
        ) : null}

        {demoMiss ? (
          <DemoMissNote />
        ) : answer.status === "error" ? (
          <Callout
            tone="warn"
            className="mt-2"
            title="Couldn't answer this one"
            action={
              onRetry ? (
                <Button size="sm" icon={RotateCw} onClick={onRetry}>
                  Try again
                </Button>
              ) : undefined
            }
          >
            {answer.error}
          </Callout>
        ) : null}

        {sources.length ? (
          <div className="mt-4">
            <h3 className="mb-1.5 text-[11.5px] font-semibold uppercase tracking-[0.07em] text-muted">Sources</h3>
            {/* phones: one source per line, the whole width for its title; wider: chips side by side */}
            <ul className="grid gap-1.5 sm:flex sm:flex-wrap">
              {sources.map((s) => (
                <li key={s.info.id} className="flex min-w-0 sm:max-w-full">
                  <CitationChip info={s.info} n={s.n} className="w-full sm:w-auto" />
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {answer.status === "done" && plain ? (
          <div className="mt-2 flex items-center gap-1">
            <button
              type="button"
              onClick={() => void copy(copyText, copyId)}
              className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-ink"
            >
              {isCopied ? <Check className="size-3.5 text-ok" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
              {isCopied ? "Copied" : "Copy answer"}
            </button>
            <span className="sr-only" aria-live="polite">
              {isCopied ? "Answer copied to the clipboard" : ""}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** A question and its answer. */
export function AskTurnView({
  turn,
  resolve,
  titleOf,
  onRetry,
}: {
  turn: AskTurn;
  resolve: AnswerViewProps["resolve"];
  titleOf?: TitleLookup;
  onRetry?: () => void;
}) {
  const reduce = useReducedMotion();
  const today = useTodayISO();
  return (
    <motion.article
      aria-label={turn.question ? `Question: ${turn.question}` : "Answer"}
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      className="space-y-4"
      data-turn={turn.key}
    >
      {turn.question ? <QuestionBubble text={turn.question} /> : null}
      <AnswerView answer={turn.answer} resolve={resolve} titleOf={titleOf} onRetry={onRetry} today={today} />
    </motion.article>
  );
}
