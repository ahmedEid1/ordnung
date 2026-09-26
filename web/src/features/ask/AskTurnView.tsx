import { useMemo } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Check, Copy, Info, RotateCw, ShieldAlert, Square } from "lucide-react";
import { LogoMark } from "@/components/shell/Logo";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { useClipboard } from "@/features/today/clipboard";
import { citationIndex, numberCitations, stripAllMarkers } from "./citations";
import { CitationChip, CitationMarker } from "./CitationChip";
import { Markdown } from "./Markdown";
import type { RefInfo } from "./refs";
import type { AnswerState } from "./stream";
import { ToolTrace } from "./ToolTrace";
import type { AskTurn } from "./useAskThread";
import type { CitationRef } from "./citations";
import type { TitleLookup } from "./tools";

export function QuestionBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-accent-soft px-4 py-2.5 text-[15px] leading-relaxed text-ink">
        <span className="sr-only">You asked: </span>
        {text}
      </p>
    </div>
  );
}

function Thinking() {
  return (
    <p className="flex items-center gap-2 text-[14px] text-muted">
      <span className="flex gap-1" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span key={i} className="size-1.5 rounded-full bg-accent/60 animate-pulse-soft motion-reduce:animate-none" style={{ animationDelay: `${i * 180}ms` }} />
        ))}
      </span>
      Looking through your records…
    </p>
  );
}

/** The label the check's note is shown (and copied) under. */
export const CHECK_NOTE_LABEL = "Checked by Ordnung.";

/**
 * What Ordnung's answer check did (ADR 0008): dates or amounts left out because the records their
 * sentences cite don't hold them, and values shown in quotation marks as a letter's (or the
 * person's) words. The text comes only from the `done` event's `note` field, never from the answer.
 */
export function CheckNote({ text }: { text: string }) {
  return (
    <p
      role="note"
      className="mt-3 flex items-start gap-2 rounded-lg border border-line bg-surface-2/60 px-3 py-2 text-[13px] leading-5 text-muted"
    >
      <Info className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
      <span className="min-w-0 break-words">
        <span className="font-medium text-ink">{CHECK_NOTE_LABEL}</span> {text}
      </span>
    </p>
  );
}

/** A partial answer that ended before the check ran (stopped, or failed): its values are unchecked. */
function UncheckedNote({ stopped }: { stopped: boolean }) {
  return (
    <p role="note" className="mt-2 flex items-start gap-1.5 text-[13px] leading-5 text-muted">
      <ShieldAlert className="mt-0.5 size-3.5 shrink-0 text-warn" aria-hidden />
      <span className="min-w-0">
        {stopped ? "Stopped before Ordnung checked it — " : "This partial answer was not checked — "}
        its dates and amounts are unchecked and may be wrong.
      </span>
    </p>
  );
}

export interface AnswerViewProps {
  answer: AnswerState;
  resolve: (ref: CitationRef) => RefInfo;
  titleOf?: TitleLookup;
  onRetry?: () => void;
  /** Shown under a finished answer in the zero-install demo for questions without a recording. */
  demoNote?: boolean;
}

/** One answer: tool trace, the (streaming) text with citation chips, sources and actions. */
export function AnswerView({ answer, resolve, titleOf, onRetry, demoNote }: AnswerViewProps) {
  const { copy, copied } = useClipboard();
  const live = answer.status === "streaming";
  const body = answer.text;
  const note = answer.note;
  // stopped or failed before the check ran: the streamed words stay, visibly unchecked
  const unchecked = (answer.status === "stopped" || answer.status === "error") && Boolean(body.trim());
  const valid = useMemo(() => (live ? null : citationIndex(answer.citations)), [live, answer.citations]);
  const numbers = useMemo(() => (valid ? numberCitations(body, valid) : new Map<string, number>()), [valid, body]);
  const sources = useMemo(
    () => (valid ? [...numbers.entries()].map(([id, n]) => ({ n, info: resolve(valid.get(id)!) })) : []),
    [valid, numbers, resolve],
  );
  const plain = stripAllMarkers(answer.text).trim();
  // the note travels with a copied answer: it explains its quotation marks and "[date left out]"
  const copyText = note ? `${plain}\n\n${CHECK_NOTE_LABEL} ${note}` : plain;
  const copyId = answer.messageId ?? plain;
  const isCopied = copied === copyId;

  return (
    <div className="flex gap-3">
      <LogoMark className="mt-0.5 size-7 rounded-lg" />
      <div className="min-w-0 flex-1" aria-busy={live || undefined}>
        <ToolTrace steps={answer.tools} live={live} titleOf={titleOf} />
        {body ? (
          <Markdown
            text={body}
            citations={valid}
            streaming={live || unchecked}
            muted={live || unchecked}
            renderCitation={(ref, key) => <CitationMarker key={key} info={resolve(ref)} n={numbers.get(ref.id) ?? 0} />}
          />
        ) : live ? (
          <Thinking />
        ) : null}

        {live && body ? (
          <p className="mt-2 text-[12.5px] leading-5 text-muted">Dates and amounts are checked against your records when the answer is complete.</p>
        ) : null}

        {note && !live ? <CheckNote text={note} /> : null}

        {unchecked ? <UncheckedNote stopped={answer.status === "stopped"} /> : null}

        {answer.status === "stopped" && !unchecked ? (
          <p className="mt-2 inline-flex items-center gap-1.5 text-[13px] text-muted">
            <Square className="size-3" aria-hidden /> Stopped before an answer arrived.
          </p>
        ) : null}

        {answer.status === "error" ? (
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
            <ul className="flex flex-wrap gap-1.5">
              {sources.map((s) => (
                <li key={s.info.id} className="max-w-full">
                  <CitationChip info={s.info} n={s.n} />
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {demoNote && answer.status === "done" ? (
          <Callout tone="info" className="mt-3" title="This online demo replays recorded answers">
            Try one of the suggested questions — or install Ordnung to ask anything about your own letters.
          </Callout>
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
  demoNote,
}: {
  turn: AskTurn;
  resolve: AnswerViewProps["resolve"];
  titleOf?: TitleLookup;
  onRetry?: () => void;
  demoNote?: boolean;
}) {
  const reduce = useReducedMotion();
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
      <AnswerView answer={turn.answer} resolve={resolve} titleOf={titleOf} onRetry={onRetry} demoNote={demoNote} />
    </motion.article>
  );
}
