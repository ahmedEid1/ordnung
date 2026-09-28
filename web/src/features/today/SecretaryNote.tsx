import { Fragment, useId, useMemo, useState } from "react";
import { motion } from "motion/react";
import { RotateCw, ShieldCheck } from "lucide-react";
import { useBrief, useProfile, useRegenerateBrief } from "@/api/hooks";
import { LogoMark } from "@/components/shell/Logo";
import { IconButton } from "@/components/ui/Button";
import { SkeletonText } from "@/components/ui/Skeleton";
import { useTodayISO } from "@/lib/today";
import { fadeUp } from "./motion";
import { noteText, writtenAt } from "./helpers";
import { stripGreeting } from "./selection";
import { cn } from "@/lib/utils";

/**
 * Amounts and days the eye should find, in the note as {@link noteText} writes it ("€94.99",
 * "Tue 29 Sep" with non-breaking spaces, "tomorrow", "Friday").
 */
const EMPHASIS =
  /(€\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\b(?:today|tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b|\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[ \u00a0]\d{1,2}[ \u00a0](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b(?:[ \u00a0]\d{4}\b)?)/g;

/** Emphasise amounts and days in the note so the eye finds them. */
function Emphasised({ text }: { text: string }) {
  const parts = useMemo(() => text.split(EMPHASIS), [text]);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <strong key={i} className="whitespace-nowrap font-semibold tabular-nums text-ink">
            {p}
          </strong>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

/**
 * The secretary's note: a short plain-English brief from `/api/brief` (Claude, validated against
 * the ledger) with a "write a new note" button. Falls back to a code-generated agenda sentence. The
 * note is written from what was read: while letters from the watched folder wait unread, it says so
 * (the fallback sentence names them itself).
 */
export function SecretaryNote({ fallback, waiting = 0 }: { fallback: string; waiting?: number }) {
  const brief = useBrief();
  const regen = useRegenerateBrief();
  const data = brief.data;
  const today = useTodayISO();
  const raw = data?.text?.trim() ? stripGreeting(data.text) : fallback;
  // one style for dates and money, whoever wrote the note ("30 September" → "Wed 30 Sep", "94,99 €" → "€94.99")
  const text = useMemo(() => noteText(raw, today), [raw, today]);
  const noteId = useId();
  const fromAi = Boolean(data?.text?.trim()) && data?.source === "llm";
  const profile = useProfile();
  // a note prepared before its day (the demo's is from the day it was built) is "for today"
  const early = Boolean(data?.date && data.generated_at && data.generated_at.slice(0, 10) < data.date);
  const when = early ? "Written for today" : writtenAt(data?.generated_at, profile.data?.timezone);
  const [more, setMore] = useState(false);

  return (
    <motion.section variants={fadeUp} aria-labelledby="note-title" className="card relative overflow-hidden p-5 sm:p-7">
      <div
        aria-hidden
        className="pointer-events-none absolute -right-24 -top-28 size-72 rounded-full bg-accent-soft opacity-70 blur-3xl dark:opacity-40"
      />
      <div className="relative flex items-center gap-3">
        <LogoMark className="size-9 rounded-xl shadow-[var(--shadow-card)]" />
        <div className="min-w-0 flex-1">
          <h2 id="note-title" className="text-[14px] font-semibold leading-5 text-ink">
            Your secretary's note
          </h2>
          <p className="text-[12.5px] leading-4 text-muted">{when ?? "From your to-dos & dates"}</p>
        </div>
        <IconButton
          icon={RotateCw}
          label="Write a new note"
          variant="ghost"
          size="sm"
          loading={regen.isPending}
          onClick={() => regen.mutate()}
        />
      </div>

      {brief.isPending ? (
        <SkeletonText lines={3} className="relative mt-5" />
      ) : (
        <>
          {/* phones: three lines, so Top 3 stays in view */}
          <p
            id={noteId}
            aria-live="polite"
            className={cn("display relative mt-4 max-w-[62ch] text-[18px] leading-[1.6] text-ink/90 sm:text-[20px]", !more && "max-sm:line-clamp-3")}
          >
            <Emphasised text={text} />
          </p>
          {text.length > 140 ? (
            <button
              type="button"
              onClick={() => setMore(!more)}
              aria-expanded={more}
              aria-controls={noteId}
              className="relative -mx-1 mt-1 inline-flex min-h-6 items-center rounded-md px-1 text-sm font-semibold text-accent underline-offset-2 hover:underline sm:hidden"
            >
              {more ? "Show less" : "Read more"}
            </button>
          ) : null}
        </>
      )}

      {waiting && data?.text?.trim() ? (
        // the note is written from what was read: letters that wait unread are not in it
        <p className="relative mt-3 text-[13.5px] leading-snug text-ink/80">
          Not in this note: {waiting === 1 ? "1 letter" : `${waiting} letters`} from your folder, not read yet.
        </p>
      ) : null}
      <p className="relative mt-4 flex items-start gap-1.5 text-[12px] leading-5 text-muted">
        <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        {fromAi
          ? "Written by Claude from your to-dos & dates — every date and amount was checked against your records."
          : "Written from your to-dos & dates."}
      </p>
    </motion.section>
  );
}
