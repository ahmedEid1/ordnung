import { useEffect, useSyncExternalStore } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Camera, FileText, X } from "lucide-react";
import { useDocument } from "@/api/hooks";
import { dismissJob, useEvents, type JobProgress } from "@/api/sse";
import { JOB_STAGE_COPY, PIPELINE_STEPS, copyFor, stageToStep } from "@/lib/copy";
import { cn } from "@/lib/utils";
import { Stepper } from "@/components/ui/Stepper";

const DONE_LINGER_MS = 9000;

function UploadRow({ job }: { job: JobProgress }) {
  const docId = job.doc_id ?? "";
  const { data } = useDocument(job.doc_id ?? undefined);
  const doc = data?.document;
  const done = job.status === "done";
  const failed = job.status === "failed";
  const step = done ? PIPELINE_STEPS.length : stageToStep(job.stage);
  const name = doc?.title ?? doc?.filename ?? "New letter";
  const photo = doc?.text_mode === "vision" || doc?.mime?.startsWith("image/");
  const Icon = photo ? Camera : FileText;
  const stageLabel = failed ? job.error ?? "Couldn't read this letter" : done ? "Filed — everything is on your timeline" : copyFor(JOB_STAGE_COPY, job.stage ?? "intake").label + "…";

  useEffect(() => {
    if (!done) return;
    const t = setTimeout(() => dismissJob(docId), DONE_LINGER_MS);
    return () => clearTimeout(t);
  }, [done, docId]);

  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: 24, transition: { duration: 0.15 } }}
      className="pointer-events-auto w-full rounded-xl border border-line bg-surface p-3.5 shadow-[var(--shadow-pop)]"
    >
      <div className="flex items-start gap-3">
        <span className={cn("grid size-9 shrink-0 place-items-center rounded-lg", done ? "bg-ok-soft text-ok" : failed ? "bg-danger-soft text-danger" : "bg-accent-soft text-accent")}>
          <Icon className="size-[18px]" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-medium text-ink" title={name}>
            {name}
          </p>
          <p className={cn("mt-0.5 truncate text-[12.5px]", failed ? "text-danger-ink" : done ? "text-ok-ink" : "text-muted")}>{stageLabel}</p>
        </div>
        <button
          type="button"
          onClick={() => dismissJob(docId)}
          className="grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
          aria-label={`Hide progress for ${name}`}
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="mt-3 px-0.5">
        <Stepper steps={PIPELINE_STEPS} current={step} status={failed ? "error" : "active"} size="sm" labels="all" fallback="none" live label={`Reading ${name}`} />
      </div>
      {done && docId ? (
        <div className="-mb-1 mt-1 flex justify-end">
          <Link
            to={`/documents/${docId}`}
            onClick={() => dismissJob(docId)}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[13px] font-semibold text-accent hover:bg-accent-soft"
          >
            Open letter <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </div>
      ) : null}
    </motion.li>
  );
}

// Documents whose progress is already shown in place (e.g. the Inbox's New-mail tray) — no toast.
let hiddenDocs = new Set<string>();
const hiddenListeners = new Set<() => void>();

/** Hide (or show again) the progress toast of a document while a page shows it in place. */
export function setUploadToastHidden(docId: string, hidden: boolean): void {
  if (hiddenDocs.has(docId) === hidden) return;
  hiddenDocs = new Set(hiddenDocs);
  if (hidden) hiddenDocs.add(docId);
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
 * Live progress of letters being read (uploads and demo New mail): one card per document with
 * the Reading → Understanding → Checking → Computing dates → Filing stepper.
 */
export function UploadCenter() {
  const { jobs } = useEvents();
  const hidden = useHiddenDocs();
  const list = Object.values(jobs)
    .filter((j) => j.doc_id && !hidden.has(j.doc_id))
    .sort((a, b) => a.startedAt - b.startedAt)
    .slice(-4);
  return (
    <ul aria-label="Letters being read" className="flex flex-col items-stretch gap-2 md:items-end">
      <AnimatePresence initial={false}>
        {list.map((j) => (
          <UploadRow key={j.doc_id} job={j} />
        ))}
      </AnimatePresence>
    </ul>
  );
}
