/**
 * Demo "New mail" tray: letters that just arrived for Sam, as envelopes. "Let Ordnung read it"
 * opens one and shows the live pipeline (Reading → Understanding → Checking → Computing dates →
 * Filing) from SSE `job.progress`; "Read all" opens every envelope at once (→ batch recap). A
 * letter that couldn't be read stays with what to do next: Try again, a sharper photo, or remove.
 *
 * Focus never drops to the page: the button that starts reading hands focus to its envelope
 * (which stays through every stage), and when an envelope goes while focused, focus moves to the
 * next one or — the tray gone — to `focusFallback` (the letters list).
 */
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { Link } from "react-router";
import { motion, useReducedMotion } from "motion/react";
import { ArrowRight, Camera, Check, CircleX, FileText, Mailbox, RotateCw, Sparkles } from "lucide-react";
import type { MailTrayItem } from "@/api/types";
import { useHealth, useMailTray, useOpenMail, useReprocessDocument } from "@/api/hooks";
import { dismissJob, seedJob, useEvents, useServerEvent, type JobProgress } from "@/api/sse";
import { JOB_STAGE_COPY, PIPELINE_STEPS, copyFor, stageToStep } from "@/lib/copy";
import { formatDate } from "@/lib/format";
import { cn, initials, plural } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { useAddLetters } from "@/components/shell/AddLetters";
import { setUploadToastHidden } from "@/components/shell/UploadCenter";
import { TOUR_TARGETS } from "@/features/tour/steps";

type CardState =
  | { kind: "idle" }
  | { kind: "waiting" }
  | { kind: "reading"; job: JobProgress }
  | { kind: "done"; docId: string }
  | { kind: "failed"; docId: string; message: string };

/** The element an envelope keeps focus on while it is read (`data-mail-doc`: its document, once known). */
const ANCHOR = "[data-mail-anchor]";

/** Focus the envelope of a document (e.g. from the "couldn't be read" toast); false when it isn't on screen. */
export function focusMailEnvelope(docId: string): boolean {
  const el = document.querySelector<HTMLElement>(`${ANCHOR}[data-mail-doc="${CSS.escape(docId)}"]`);
  if (!el) return false;
  el.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  el.focus({ preventScroll: true });
  return true;
}

export function MailTray({
  onOpened,
  focusFallback,
}: {
  /** Letters taken out of the tray: the documents they became, with their senders. */
  onOpened: (opened: { docId: string; sender: string }[]) => void;
  /** Where focus goes when the tray is gone while focused (default: the page's main). */
  focusFallback?: () => HTMLElement | null;
}) {
  const health = useHealth();
  const demo = Boolean(health.data?.demo);
  const tray = useMailTray(demo);
  const { jobs } = useEvents();
  const openMail = useOpenMail();
  const sectionRef = useRef<HTMLElement>(null);
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

  // an envelope (or the whole tray) that had focus is gone: focus moves on, never to the page
  const lastFocus = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const el = lastFocus.current;
    if (!el || el.isConnected) return;
    lastFocus.current = null;
    if (document.activeElement && document.activeElement !== document.body) return;
    const next = sectionRef.current?.querySelector<HTMLElement>(ANCHOR) ?? focusFallback?.() ?? document.querySelector<HTMLElement>("main");
    next?.focus({ preventScroll: true });
  });

  if (!demo || !tray.data) return null;

  const stateOf = (t: MailTrayItem): CardState | null => {
    const docId = started[t.id] ?? t.doc_id;
    if (!(t.id in started)) return t.opened ? null : { kind: "idle" };
    if (!docId) return { kind: "waiting" };
    const job = jobs[docId];
    if (job?.status === "failed") return { kind: "failed", docId, message: job.error ?? "Couldn't read this letter." };
    if (job?.status === "done") return { kind: "done", docId };
    if (job) return { kind: "reading", job };
    return finished[docId] ? null : { kind: "waiting" };
  };

  const cards = tray.data.map((t) => ({ t, state: stateOf(t) })).filter((c): c is { t: MailTrayItem; state: CardState } => c.state !== null);
  if (!cards.length) return null;
  const idle = cards.filter((c) => c.state.kind === "idle");
  const reading = cards.length > idle.length;

  const anchorOf = (mailId: string) => sectionRef.current?.querySelector<HTMLElement>(`${ANCHOR}[data-mail-id="${CSS.escape(mailId)}"]`);

  const open = async (items: MailTrayItem[]) => {
    // the button goes when reading starts: its envelope takes focus first (and keeps it)
    if (sectionRef.current?.contains(document.activeElement) && items[0]) anchorOf(items[0].id)?.focus({ preventScroll: true });
    setStarted((s) => ({ ...s, ...Object.fromEntries(items.map((t) => [t.id, null])) }));
    const results = await Promise.allSettled(items.map((t) => openMail.mutateAsync(t.id)));
    const opened: Record<string, string> = {};
    const letters: { docId: string; sender: string }[] = [];
    results.forEach((r, i) => {
      if (r.status !== "fulfilled") return;
      opened[items[i]!.id] = r.value.document.id;
      letters.push({ docId: r.value.document.id, sender: items[i]!.sender });
    });
    setStarted((s) => {
      const next = { ...s, ...opened };
      // requests that failed go back to "unopened" (the error toast explains why)
      items.forEach((t) => {
        if (!(t.id in opened)) delete next[t.id];
      });
      return next;
    });
    onOpened(letters);
  };

  return (
    <section
      ref={sectionRef}
      aria-labelledby="new-mail-title"
      data-tour={TOUR_TARGETS.newMail}
      className="mb-10"
      onFocus={(e) => {
        lastFocus.current = e.target as HTMLElement;
      }}
      onBlur={(e) => {
        // focus left for somewhere else on the page (not: its element was removed)
        const to = e.relatedTarget as Node | null;
        if (to && !e.currentTarget.contains(to)) lastFocus.current = null;
      }}
    >
      <SectionHeader
        id="new-mail-title"
        icon={Mailbox}
        title={
          // "New mail · 3" on screen, "New mail, 3 letters" to a screen reader
          <>
            <span aria-hidden>
              New mail<span className="font-medium tabular-nums">{` · ${cards.length}`}</span>
            </span>
            <span className="sr-only">{`New mail, ${plural(cards.length, "letter")}`}</span>
          </>
        }
        description={idle.length ? "Letters that just arrived. Let Ordnung read them — you'll see every step." : "Reading your mail — every fact is checked against the page."}
        action={
          idle.length > 1 ? (
            <Button size="sm" icon={Sparkles} onClick={() => void open(idle.map((c) => c.t))}>
              Read all {idle.length}
            </Button>
          ) : null
        }
        className="mb-4 max-sm:flex-col max-sm:items-start"
      />
      <div className="@container">
        <ul
          className={cn(
            "-mx-4 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-2 pt-1 scrollbar-thin",
            "sm:mx-0 sm:grid sm:grid-cols-2 sm:gap-4 sm:overflow-visible sm:px-0 sm:pb-0 sm:pt-0 @3xl:grid-cols-3",
            // a last envelope alone in a row of two takes the whole row
            "sm:[&>li:last-child:nth-child(odd)]:col-span-2 @3xl:[&>li:last-child:nth-child(odd)]:col-span-1",
            // while one is read (and grows), the others keep their own height
            reading && "sm:items-start",
          )}
        >
          {cards.map(({ t, state }, i) => (
            <Envelope key={t.id} item={t} state={state} index={i} onOpen={() => void open([t])} />
          ))}
        </ul>
      </div>
    </section>
  );
}

function Envelope({ item, state, index, onOpen }: { item: MailTrayItem; state: CardState; index: number; onOpen: () => void }) {
  const reduced = useReducedMotion();
  const anchor = useRef<HTMLDivElement>(null);
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
  // the day it arrived (the postmark, and the chip that says it in words)
  const arrived = item.received_date ? formatDate(item.received_date, { style: "short" }) : null;
  const docId = state.kind === "done" || state.kind === "failed" ? state.docId : state.kind === "reading" ? state.job.doc_id : item.doc_id;

  return (
    <motion.li
      // "position": when a letter is filed the others slide over without their text being squashed
      layout={reduced ? false : "position"}
      initial={reduced ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 30, delay: reduced ? 0 : index * 0.05 }}
      className={cn(
        "@container/envelope group relative flex w-[84%] shrink-0 snap-start flex-col overflow-hidden rounded-2xl border bg-surface shadow-[var(--shadow-card)] transition-[box-shadow,border-color] sm:w-auto",
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
        {/* postmark (a ring with wavy cancel lines and the day the letter arrived) + stamp */}
        <div className="absolute right-4 top-2.5 flex items-start">
          <svg viewBox="0 0 48 36" className="-mr-2 mt-2 h-9 w-12 -rotate-6 text-muted/60" fill="none" stroke="currentColor" strokeWidth="1.2">
            <circle cx="30" cy="18" r="14" strokeDasharray="2.5 2" />
            <path d="M0 12 q4 -3 8 0 t8 0 t8 0 t8 0 t8 0" />
            <path d="M0 18 q4 -3 8 0 t8 0 t8 0 t8 0 t8 0" />
            <path d="M0 24 q4 -3 8 0 t8 0 t8 0 t8 0 t8 0" />
            {item.received_date ? (
              <text textAnchor="middle" fill="currentColor" stroke="none" fontWeight="700" data-testid="postmark-date">
                <tspan x="30" y="18.5" fontSize="9">
                  {formatDate(item.received_date, { style: "numeric" }).slice(0, 2)}
                </tspan>
                <tspan x="30" y="25.5" fontSize="5.5" letterSpacing="0.4">
                  {formatDate(item.received_date, { style: "month" }).slice(0, 3).toUpperCase()}
                </tspan>
              </text>
            ) : null}
          </svg>
          <span className="relative grid h-11 w-9 place-items-center rounded-[3px] border-2 border-dotted border-accent/40 bg-accent-soft text-[11px] font-bold text-accent">
            {initials(item.sender.replace(/\?$/, ""))}
          </span>
        </div>
      </div>

      <div className="flex flex-1 flex-col px-4 pb-4 pt-3">
        <p className="text-md font-semibold leading-snug text-ink [overflow-wrap:anywhere]">{item.sender}</p>
        <p lang="de" className="mt-1 line-clamp-2 text-[13.5px] italic leading-5 text-muted" title={item.subject}>
          {item.subject}
        </p>
        {/* no "kind" chip: what the letter is, is what Ordnung is about to find out */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="inline-flex h-[22px] items-center gap-1 rounded-full bg-surface-2 px-2 text-xs font-medium text-muted">
            <Kind className="size-3" aria-hidden />
            {item.photo ? "Phone photo" : "PDF"}
          </span>
          {arrived ? (
            <span className="inline-flex h-[22px] items-center gap-1 whitespace-nowrap rounded-full bg-surface-2 px-2 text-xs font-medium text-muted">
              <Mailbox className="size-3" aria-hidden />
              Arrived {arrived}
            </span>
          ) : null}
        </div>

        <div className="mt-auto pt-4">
          {/* stays through every stage, so focus has somewhere to be when the buttons go */}
          <div
            ref={anchor}
            tabIndex={-1}
            role="group"
            aria-label={`Letter from ${item.sender}`}
            data-mail-anchor=""
            data-mail-id={item.id}
            data-mail-doc={docId ?? undefined}
            className="rounded-xl"
          >
            {state.kind === "idle" ? (
              <Button variant="primary" className="w-full @md/envelope:w-auto" icon={Sparkles} onClick={onOpen}>
                Let Ordnung read it
              </Button>
            ) : state.kind === "failed" ? (
              <FailedPanel item={item} docId={state.docId} message={state.message} anchor={anchor} />
            ) : (
              <div className="rounded-xl bg-surface-2/70 px-3 pb-2.5 pt-3">
                <StageList step={step} label={`Reading the letter from ${item.sender}`} />
                <div className="mt-3 flex items-center justify-between gap-2">
                  <p className={cn("line-clamp-2 min-w-0 text-sm leading-5", state.kind === "done" ? "font-medium text-ok-ink" : "text-muted")} aria-hidden>
                    {stage}
                  </p>
                  {state.kind === "done" ? (
                    <Link
                      to={`/documents/${state.docId}`}
                      className="inline-flex min-h-6 shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[13px] font-semibold text-accent hover:bg-accent-soft"
                    >
                      Open <ArrowRight className="size-3.5" aria-hidden />
                    </Link>
                  ) : null}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </motion.li>
  );
}

/**
 * A letter that couldn't be read: why (Claude's words), then what to do — read it again, add a
 * sharper photo, or take it out of New mail (it stays in the letters list, under Please check).
 * No `role="alert"`: the "couldn't be read" toast already says so.
 */
function FailedPanel({ item, docId, message, anchor }: { item: MailTrayItem; docId: string; message: string; anchor: RefObject<HTMLDivElement | null> }) {
  const reprocess = useReprocessDocument();
  const { openPicker } = useAddLetters();
  // the buttons go with the panel: the envelope takes focus first (and keeps it)
  const keepFocus = () => {
    if (anchor.current?.contains(document.activeElement)) anchor.current.focus({ preventScroll: true });
  };
  return (
    <div className="rounded-xl bg-danger-soft/60 px-3 pb-2 pt-3">
      <p className="flex items-start gap-2 text-sm leading-5 text-danger-ink">
        <CircleX className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span className="min-w-0 [overflow-wrap:anywhere]">{message}</span>
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="primary"
          icon={RotateCw}
          loading={reprocess.isPending}
          onClick={() => {
            keepFocus();
            reprocess.mutate(docId, {
              onSuccess: (j) => seedJob({ job_id: j.id, doc_id: docId, stage: "intake", progress: 0, status: "running" }),
            });
          }}
        >
          Try again
        </Button>
        {item.photo ? (
          <Button size="sm" icon={Camera} onClick={openPicker}>
            Add a sharper photo
          </Button>
        ) : null}
      </div>
      <Button
        variant="link"
        size="sm"
        className="mt-1.5"
        onClick={() => {
          keepFocus();
          dismissJob(docId);
        }}
      >
        Remove from New mail
      </Button>
    </div>
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
