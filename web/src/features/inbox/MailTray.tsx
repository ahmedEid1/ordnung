/**
 * Demo "New mail" tray: letters that just arrived for Sam, as envelopes. "Let Ordnung read it"
 * opens one and shows the live pipeline (Reading → Understanding → Checking → Computing dates →
 * Filing) from SSE `job.progress`; "Read all" opens every envelope at once (→ batch recap).
 */
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { motion, useReducedMotion } from "motion/react";
import { ArrowRight, Camera, Check, CircleX, FileText, Mailbox, Sparkles } from "lucide-react";
import type { MailTrayItem } from "@/api/types";
import { useHealth, useMailTray, useOpenMail } from "@/api/hooks";
import { useEvents, useServerEvent, type JobProgress } from "@/api/sse";
import { JOB_STAGE_COPY, PIPELINE_STEPS, copyFor, stageToStep } from "@/lib/copy";
import { cn, initials } from "@/lib/utils";
import { formatDate } from "@/lib/format";
import { useToday } from "@/lib/today";
import { Button } from "@/components/ui/Button";
import { setUploadToastHidden } from "@/components/shell/UploadCenter";
import { TOUR_TARGETS } from "@/features/tour/steps";

type CardState =
  | { kind: "idle" }
  | { kind: "waiting" }
  | { kind: "reading"; job: JobProgress }
  | { kind: "done"; docId: string }
  | { kind: "failed"; message: string };

export function MailTray({ onOpened }: { onOpened: (docIds: string[]) => void }) {
  const health = useHealth();
  const demo = Boolean(health.data?.demo);
  const tray = useMailTray(demo);
  const { jobs } = useEvents();
  const openMail = useOpenMail();
  /** mail id → document id (null while the request is in flight) */
  const [started, setStarted] = useState<Record<string, string | null>>({});
  /** documents whose job finished while the tray was on screen */
  const [finished, setFinished] = useState<Record<string, boolean>>({});

  useServerEvent("job.progress", (ev) => {
    if (ev.doc_id && (ev.status === "done" || ev.status === "failed")) setFinished((f) => ({ ...f, [ev.doc_id!]: true }));
  });

  // progress is shown right here on the envelope, so no duplicate toast while the tray is open
  const shownHere = Object.values(started).filter(Boolean).join(",");
  useEffect(() => {
    const ids = shownHere ? shownHere.split(",") : [];
    ids.forEach((id) => setUploadToastHidden(id, true));
    return () => ids.forEach((id) => setUploadToastHidden(id, false));
  }, [shownHere]);

  if (!demo || !tray.data) return null;

  const stateOf = (t: MailTrayItem): CardState | null => {
    const docId = started[t.id] ?? t.doc_id;
    if (!(t.id in started)) return t.opened ? null : { kind: "idle" };
    if (!docId) return { kind: "waiting" };
    const job = jobs[docId];
    if (job?.status === "failed") return { kind: "failed", message: job.error ?? "Couldn't read this letter." };
    if (job?.status === "done") return { kind: "done", docId };
    if (job) return { kind: "reading", job };
    return finished[docId] ? null : { kind: "waiting" };
  };

  const cards = tray.data.map((t) => ({ t, state: stateOf(t) })).filter((c): c is { t: MailTrayItem; state: CardState } => c.state !== null);
  if (!cards.length) return null;
  const idle = cards.filter((c) => c.state.kind === "idle");

  const open = async (items: MailTrayItem[]) => {
    setStarted((s) => ({ ...s, ...Object.fromEntries(items.map((t) => [t.id, null])) }));
    const results = await Promise.allSettled(items.map((t) => openMail.mutateAsync(t.id)));
    const opened: Record<string, string> = {};
    results.forEach((r, i) => {
      if (r.status === "fulfilled") opened[items[i]!.id] = r.value.document.id;
    });
    setStarted((s) => {
      const next = { ...s, ...opened };
      // requests that failed go back to "unopened" (the error toast explains why)
      items.forEach((t) => {
        if (!(t.id in opened)) delete next[t.id];
      });
      return next;
    });
    onOpened(Object.values(opened));
  };

  return (
    <section aria-labelledby="new-mail-title" data-tour={TOUR_TARGETS.newMail} className="mb-10">
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <h2 id="new-mail-title" className="flex items-center gap-2 text-[13px] font-semibold uppercase tracking-[0.07em] text-muted">
            <Mailbox className="size-4" aria-hidden />
            New mail
            <span className="grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1.5 text-[11px] font-semibold tabular-nums text-on-accent">
              {cards.length}
            </span>
          </h2>
          <p className="mt-1 text-[14px] text-muted">
            {idle.length ? "Letters that just arrived. Let Ordnung read them — you'll see every step." : "Reading your mail — every fact is checked against the page."}
          </p>
        </div>
        {idle.length > 1 ? (
          <Button size="sm" icon={Sparkles} onClick={() => void open(idle.map((c) => c.t))}>
            Read all {idle.length}
          </Button>
        ) : null}
      </div>
      <ul className="-mx-4 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-2 pt-1 scrollbar-thin sm:mx-0 sm:pt-0 sm:grid sm:grid-cols-2 sm:gap-4 sm:overflow-visible sm:px-0 sm:pb-0 lg:grid-cols-3">
        {cards.map(({ t, state }, i) => (
          <Envelope key={t.id} item={t} state={state} index={i} onOpen={() => void open([t])} />
        ))}
      </ul>
    </section>
  );
}

function Envelope({ item, state, index, onOpen }: { item: MailTrayItem; state: CardState; index: number; onOpen: () => void }) {
  const reduced = useReducedMotion();
  const today = useToday();
  const opened = state.kind !== "idle";
  const active = state.kind === "reading" || state.kind === "waiting";
  const step = state.kind === "reading" ? stageToStep(state.job.stage) : state.kind === "done" ? PIPELINE_STEPS.length : 0;
  const stage =
    state.kind === "reading"
      ? `${copyFor(JOB_STAGE_COPY, state.job.stage ?? "intake").label}…`
      : state.kind === "waiting"
        ? "Opening the envelope…"
        : state.kind === "done"
          ? "Filed — everything is on your timeline"
          : "";
  const Kind = item.photo ? Camera : FileText;

  return (
    <motion.li
      // "position": when a letter is filed the others slide over without their text being squashed
      layout={reduced ? false : "position"}
      initial={reduced ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 30, delay: reduced ? 0 : index * 0.05 }}
      className={cn(
        "group relative flex w-[84%] shrink-0 snap-start flex-col overflow-hidden rounded-2xl border bg-surface shadow-[var(--shadow-card)] transition-[box-shadow,border-color] sm:w-auto",
        active ? "border-accent/50 shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-accent)_12%,transparent)]" : "border-line hover:shadow-[var(--shadow-pop)]",
        state.kind === "failed" && "border-danger/40",
      )}
    >
      {/* envelope flap */}
      <div className="relative h-12 shrink-0 bg-surface-2/70" aria-hidden>
        <svg viewBox="0 0 300 48" preserveAspectRatio="none" className="absolute inset-0 size-full">
          <motion.path
            initial={false}
            animate={{ d: opened ? "M0 48 L150 10 L300 48 Z" : "M0 0 L150 40 L300 0 Z" }}
            transition={{ duration: reduced ? 0 : 0.5, ease: [0.2, 0.8, 0.2, 1] }}
            fill="var(--color-surface-3)"
            stroke="var(--color-line-strong)"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
            opacity={0.9}
          />
        </svg>
        {/* stamp + postmark */}
        <div className="absolute right-4 top-2.5 flex items-start">
          <span className="mr-[-3px] mt-3 grid size-9 -rotate-12 place-items-center rounded-full border border-dashed border-muted/50 text-[7.5px] font-semibold uppercase leading-[1.05] tracking-wide text-muted/80">
            {formatDate(today, { style: "day", withYear: "never" })}
          </span>
          <span className="grid h-11 w-9 place-items-center rounded-[3px] border-2 border-dotted border-accent/40 bg-accent-soft text-[11px] font-bold text-accent">
            {initials(item.sender.replace(/\?$/, ""))}
          </span>
        </div>
      </div>

      <div className="flex flex-1 flex-col px-4 pb-4 pt-3">
        <p className="pr-10 text-[15px] font-semibold leading-snug text-ink">{item.sender}</p>
        <p lang="de" className="mt-1 line-clamp-2 text-[13.5px] italic leading-5 text-muted">
          {item.subject}
        </p>
        {/* no "kind" chip: what the letter is, is what Ordnung is about to find out */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="inline-flex h-[22px] items-center gap-1 rounded-full bg-surface-2 px-2 text-[12px] font-medium text-muted">
            <Kind className="size-3" aria-hidden />
            {item.photo ? "Phone photo" : "PDF"}
          </span>
        </div>

        <div className="mt-auto pt-4">
          {state.kind === "idle" ? (
            <Button variant="primary" className="w-full" icon={Sparkles} onClick={onOpen}>
              Let Ordnung read it
            </Button>
          ) : state.kind === "failed" ? (
            <p className="flex items-start gap-2 text-[13px] text-danger-ink" role="alert">
              <CircleX className="mt-0.5 size-4 shrink-0" aria-hidden />
              {state.message}
            </p>
          ) : (
            <div className="rounded-xl bg-surface-2/70 px-3 pb-2.5 pt-3">
              <StageList step={step} label={`Reading the letter from ${item.sender}`} />
              <div className="mt-3 flex items-center justify-between gap-2">
                <p className={cn("truncate text-[12.5px]", state.kind === "done" ? "font-medium text-ok-ink" : "text-muted")} aria-hidden>
                  {stage}
                </p>
                {state.kind === "done" ? (
                  <Link
                    to={`/documents/${state.docId}`}
                    className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[13px] font-semibold text-accent hover:bg-accent-soft"
                  >
                    Open <ArrowRight className="size-3.5" aria-hidden />
                  </Link>
                ) : null}
              </div>
            </div>
          )}
        </div>
      </div>
    </motion.li>
  );
}

/** Vertical pipeline stepper for the envelope cards: every stage is named and visible. */
function StageList({ step, label }: { step: number; label: string }) {
  const done = step >= PIPELINE_STEPS.length;
  const current = PIPELINE_STEPS[step]?.label;
  return (
    <>
      <ol aria-label={label} className="space-y-1">
        {PIPELINE_STEPS.map((s, i) => {
          const state = i < step ? "done" : i === step ? "current" : "todo";
          return (
            <li
              key={s.id}
              aria-current={state === "current" ? "step" : undefined}
              className="flex items-center gap-2.5 text-[13px] leading-5"
            >
              <span
                aria-hidden
                className={cn(
                  "grid size-4 shrink-0 place-items-center rounded-full transition-colors duration-300",
                  state === "done" && "bg-accent text-on-accent",
                  state === "current" && "bg-accent-soft ring-2 ring-accent",
                  state === "todo" && "ring-1 ring-line-strong",
                )}
              >
                {state === "done" ? <Check className="size-2.5" strokeWidth={3.5} /> : null}
                {state === "current" ? <span className="size-1.5 animate-pulse-soft rounded-full bg-accent motion-reduce:animate-none" /> : null}
              </span>
              <span className={cn(state === "current" ? "font-semibold text-ink" : state === "done" ? "text-ink/70" : "text-muted")}>{s.label}</span>
              <span className="sr-only">{state === "done" ? " — done" : state === "current" ? " — in progress" : ""}</span>
            </li>
          );
        })}
      </ol>
      <span className="sr-only" aria-live="polite">
        {done ? "Finished — the letter is filed." : `${current}, step ${step + 1} of ${PIPELINE_STEPS.length}.`}
      </span>
    </>
  );
}
