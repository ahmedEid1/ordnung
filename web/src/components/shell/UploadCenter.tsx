import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore, type FocusEvent } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Camera, ChevronUp, FileStack, FileText, RotateCw, X } from "lucide-react";
import { useDocument, useReprocessDocument } from "@/api/hooks";
import { dismissJob, seedJob, useEvents, type JobProgress } from "@/api/sse";
import { JOB_STAGE_COPY, PIPELINE_STEPS, copyFor, stageToStep } from "@/lib/copy";
import { cn, plural } from "@/lib/utils";
import { Spinner } from "@/components/ui/Spinner";
import { Stepper } from "@/components/ui/Stepper";
import { useModalOpen } from "@/components/ui/internal";

/** How long a filed letter's card stays (its time only runs while it isn't hovered or focused). */
export const DONE_LINGER_MS = 9000;

/** The look shared by the cards in the corner: an edge that holds in dark mode too. */
const cardCls = "pointer-events-auto w-full rounded-xl border border-line bg-surface shadow-[var(--shadow-pop)] dark:border-line-strong";
/** A text-sized card action that is still a 28 px target (as in toasts). */
const actionCls =
  "inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-sm font-semibold text-accent transition-[background-color] hover:bg-accent-soft disabled:opacity-60";

/**
 * A card (or row) is about to go while focus is in it: hand focus to the next card's first control,
 * the previous one's, the group's summary button, or the page's main — never drop it on the page.
 */
function handOffFocus(card: HTMLElement | null): void {
  if (!card?.contains(document.activeElement)) return;
  const control = (el: Element | null | undefined) => el?.querySelector<HTMLElement>("a[href], button:not([disabled])");
  const target =
    control(card.nextElementSibling) ??
    control(card.previousElementSibling) ??
    card.parentElement?.closest("[data-upload-group]")?.querySelector<HTMLElement>("[data-upload-summary]") ??
    document.querySelector<HTMLElement>("main");
  target?.focus({ preventScroll: true });
}

/** Is the pointer over, or focus inside, the element? Filed letters' cards wait while it is. */
function useHeld() {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  return {
    held: hovered || focused,
    handlers: {
      onMouseEnter: () => setHovered(true),
      onMouseLeave: () => setHovered(false),
      onFocus: () => setFocused(true),
      onBlur: (e: FocusEvent<HTMLElement>) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false);
      },
    },
  };
}

function UploadRow({ job, grouped }: { job: JobProgress; grouped?: boolean }) {
  const ref = useRef<HTMLLIElement>(null);
  const docId = job.doc_id ?? "";
  const { data } = useDocument(job.doc_id ?? undefined);
  const reprocess = useReprocessDocument();
  const doc = data?.document;
  const done = job.status === "done";
  const failed = job.status === "failed";
  const step = done ? PIPELINE_STEPS.length : stageToStep(job.stage);
  const name = doc?.title ?? doc?.filename ?? "New letter";
  const photo = doc?.text_mode === "vision" || doc?.mime?.startsWith("image/");
  const Icon = photo ? Camera : FileText;
  const stageLabel = failed ? (job.error ?? "Couldn't read this letter") : done ? "Filed — everything is on your timeline" : copyFor(JOB_STAGE_COPY, job.stage ?? "intake").label + "…";

  // gone some other way (read in place, a batch recap) while focused: focus moves on, not to the page
  useLayoutEffect(() => {
    const el = ref.current;
    return () => handOffFocus(el);
  }, []);

  const dismiss = () => {
    handOffFocus(ref.current);
    dismissJob(docId);
  };

  return (
    <motion.li
      ref={ref}
      layout={!grouped}
      initial={{ opacity: 0, y: grouped ? 0 : 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: grouped ? 0 : 24, transition: { duration: 0.15 } }}
      data-upload-row=""
      className={grouped ? "px-3.5 py-3" : cn(cardCls, "p-3.5")}
    >
      <div className="flex items-start gap-3">
        <span className={cn("grid size-9 shrink-0 place-items-center rounded-lg", done ? "bg-ok-soft text-ok" : failed ? "bg-danger-soft text-danger" : "bg-accent-soft text-accent")}>
          <Icon className="size-[18px]" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-medium text-ink" title={name}>
            {name}
          </p>
          <p className={cn("mt-0.5 text-sm leading-5 [overflow-wrap:anywhere]", failed ? "text-danger-ink" : cn("line-clamp-2", done ? "text-ok-ink" : "text-muted"))}>{stageLabel}</p>
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
          aria-label={`Hide progress for ${name}`}
          title="Hide"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="mt-3 px-0.5">
        <Stepper steps={PIPELINE_STEPS} current={step} status={failed ? "error" : "active"} size="sm" labels="all" fallback="none" live label={`Reading ${name}`} />
      </div>
      {(done || failed) && docId ? (
        <div className="-mb-1 mt-1.5 flex flex-wrap justify-end gap-1">
          {failed ? (
            <button
              type="button"
              className={actionCls}
              disabled={reprocess.isPending}
              aria-busy={reprocess.isPending || undefined}
              onClick={() =>
                reprocess.mutate(docId, {
                  onSuccess: (j) => seedJob({ job_id: j.id, doc_id: docId, stage: "intake", progress: 0, status: "running" }),
                })
              }
            >
              {reprocess.isPending ? <Spinner className="size-3.5" /> : <RotateCw className="size-3.5" aria-hidden />}
              Try again
            </button>
          ) : null}
          <Link to={`/documents/${docId}`} onClick={() => dismissJob(docId)} className={actionCls}>
            Open letter <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </div>
      ) : null}
    </motion.li>
  );
}

export interface UploadSummary {
  /** "Reading 2 letters", else "1 letter couldn't be read", else "3 letters filed". */
  title: string;
  /** The other counts: "1 filed", "1 couldn't be read" (danger). */
  parts: { text: string; danger?: boolean }[];
  reading: number;
  failed: number;
}

/** "Reading 2 letters · 1 filed · 1 couldn't be read" — the group's summary, in parts. */
export function uploadSummary(jobs: Pick<JobProgress, "status">[]): UploadSummary {
  const failed = jobs.filter((j) => j.status === "failed").length;
  const done = jobs.filter((j) => j.status === "done").length;
  const reading = jobs.length - failed - done;
  const title = reading ? `Reading ${plural(reading, "letter")}` : failed ? `${plural(failed, "letter")} couldn't be read` : `${plural(done, "letter")} filed`;
  const parts: UploadSummary["parts"] = [];
  if (done && (reading || failed)) parts.push({ text: `${done} filed` });
  if (failed && reading) parts.push({ text: `${failed} couldn't be read`, danger: true });
  return { title, parts, reading, failed };
}

/**
 * Several letters at once: one compact card ("Reading 3 letters · 1 couldn't be read" and the
 * overall progress) that opens into their cards — so the stack never covers the page (open, the
 * card stays within 40 % of a phone's height, and its list scrolls).
 */
function UploadGroup({ jobs }: { jobs: JobProgress[] }) {
  const ref = useRef<HTMLLIElement>(null);
  const [open, setOpen] = useState(false);
  const listId = useId();
  const summary = uploadSummary(jobs);
  const { title, parts, failed } = summary;
  const reading = summary.reading > 0;
  const said = [title, ...parts.map((p) => p.text)].join(" · ");
  // how far the batch is: a finished letter (filed or not) counts in full
  const progress = jobs.reduce((sum, j) => sum + (j.status === "done" || j.status === "failed" ? PIPELINE_STEPS.length : stageToStep(j.stage)), 0) / (jobs.length * PIPELINE_STEPS.length);
  useLayoutEffect(() => {
    const el = ref.current;
    return () => handOffFocus(el);
  }, []);
  return (
    <motion.li
      ref={ref}
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: 24, transition: { duration: 0.15 } }}
      data-upload-group=""
      // open, the whole card stays within 40 % of a phone's height; its list scrolls
      className={cn(cardCls, "flex max-h-[40dvh] flex-col overflow-hidden md:max-h-[min(60dvh,36rem)]")}
    >
      <button
        type="button"
        data-upload-summary=""
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-14 w-full shrink-0 items-center gap-3 px-3.5 py-3 text-left transition-colors hover:bg-surface-2/60"
      >
        <span className={cn("grid size-9 shrink-0 place-items-center rounded-lg", failed && !reading ? "bg-danger-soft text-danger" : "bg-accent-soft text-accent")}>
          <FileStack className="size-[18px]" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-base font-medium text-ink">{title}</span>
          {parts.length ? (
            <span className="block text-sm text-muted">
              {parts.map((p, i) => (
                <span key={p.text} className={p.danger ? "text-danger-ink" : undefined}>
                  {i ? " · " : ""}
                  {p.text}
                </span>
              ))}
            </span>
          ) : null}
          <span className="sr-only">{open ? " — hide the letters" : " — show the letters"}</span>
        </span>
        <ChevronUp className={cn("size-4 shrink-0 text-muted transition-transform motion-reduce:transition-none", open ? "rotate-180" : "")} aria-hidden />
      </button>
      <div aria-hidden className="h-0.5 shrink-0 bg-surface-3">
        <div className={cn("h-full transition-[width] duration-300", failed && !reading ? "bg-danger" : "bg-accent")} style={{ width: `${Math.round(progress * 100)}%` }} />
      </div>
      {/* a polite summary for screen readers: counts change, not every stage */}
      <p className="sr-only" aria-live="polite">
        {said}
      </p>
      {open ? (
        <ul id={listId} aria-label="Each letter" className="min-h-0 divide-y divide-line overflow-y-auto overscroll-contain scrollbar-thin">
          <AnimatePresence initial={false}>
            {jobs.map((j) => (
              <UploadRow key={j.doc_id} job={j} grouped />
            ))}
          </AnimatePresence>
        </ul>
      ) : null}
    </motion.li>
  );
}

// Documents whose progress is already shown in place (e.g. the Inbox's New-mail tray) — no toast.
let hiddenDocs = new Set<string>();
const hiddenListeners = new Set<() => void>();
/** How many places show a document's progress: the letter's progress card and a Pay panel's GiroCode block can both. */
const hiders = new Map<string, number>();

/**
 * Hide (or show again) the progress toast of a document while a page shows it in place. Each hide is
 * paired with a show: the toast comes back once no place shows the progress any more.
 */
export function setUploadToastHidden(docId: string, hidden: boolean): void {
  const count = Math.max(0, (hiders.get(docId) ?? 0) + (hidden ? 1 : -1));
  if (count) hiders.set(docId, count);
  else hiders.delete(docId);
  if (hiddenDocs.has(docId) === count > 0) return;
  hiddenDocs = new Set(hiddenDocs);
  if (count) hiddenDocs.add(docId);
  else hiddenDocs.delete(docId);
  hiddenListeners.forEach((l) => l());
}

function useHiddenDocs(): Set<string> {
  return useSyncExternalStore(
    (l) => {
      hiddenListeners.add(l);
      return () => hiddenListeners.delete(l);
    },
    () => hiddenDocs,
    () => hiddenDocs,
  );
}

/**
 * Live progress of letters being read (uploads and demo New mail), with the Reading → Understanding
 * → Checking → Computing dates → Filing stepper: one card for one letter, a compact summary card
 * that opens into all of them for several. A filed letter's card goes after a while (not while
 * hovered or focused); a failed one stays, with "Try again", until it is dismissed.
 */
export function UploadCenter() {
  const { jobs } = useEvents();
  const hidden = useHiddenDocs();
  const modal = useModalOpen();
  const { held, handlers } = useHeld();
  const list = Object.values(jobs)
    .filter((j) => j.doc_id && !hidden.has(j.doc_id))
    .sort((a, b) => a.startedAt - b.startedAt);
  return (
    <ul aria-label="Letters being read" className="flex flex-col items-stretch gap-2" {...handlers}>
      {list.map((j) => (j.status === "done" ? <DoneLinger key={j.doc_id} docId={j.doc_id!} paused={held || modal} /> : null))}
      <AnimatePresence initial={false}>
        {list.length > 1 ? <UploadGroup key="group" jobs={list} /> : list.map((j) => <UploadRow key={j.doc_id} job={j} />)}
      </AnimatePresence>
    </ul>
  );
}

/**
 * A filed letter's card goes after {@link DONE_LINGER_MS} — its time only runs while no card is
 * pointed at or focused and no dialog is open (as with toasts), whether it shows as a card or
 * inside the group.
 */
function DoneLinger({ docId, paused }: { docId: string; paused: boolean }) {
  const remaining = useRef(DONE_LINGER_MS);
  useEffect(() => {
    if (paused) return;
    const started = Date.now();
    const t = setTimeout(() => dismissJob(docId), Math.max(0, remaining.current));
    return () => {
      clearTimeout(t);
      remaining.current -= Date.now() - started;
    };
  }, [paused, docId]);
  return null;
}
