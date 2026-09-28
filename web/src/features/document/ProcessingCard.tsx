/** Live progress while Ordnung reads (or re-reads) a letter, and the "couldn't read it" state. */
import { useEffect, useRef } from "react";
import { CircleX, RotateCw } from "lucide-react";
import type { Document } from "@/api/types";
import { useReprocessDocument } from "@/api/hooks";
import { dismissJob, seedJob, useJobProgress } from "@/api/sse";
import { setUploadToastHidden } from "@/components/shell/UploadCenter";
import { FileNameText } from "@/components/ui/FileNameText";
import { JOB_STAGE_COPY, PIPELINE_STEPS, copyFor, stageToStep } from "@/lib/copy";
import { Button } from "@/components/ui/Button";
import { Stepper } from "@/components/ui/Stepper";

/**
 * The letter was read before: its verdict — the earlier reading — stays on the page below this card
 * (as the letter's page decides: a letter with a kind or a title shows it).
 */
export function wasReadBefore(doc: Pick<Document, "title" | "kind">): boolean {
  return Boolean(doc.title || doc.kind);
}

/**
 * A letter read before says so in a line above the verdict, whose title is the page's heading — no second
 * title over it (UI audit round 2: the title twice, an h2 before the page's h1). A letter read for the first
 * time has no verdict yet: the card's title is the page's heading.
 */
export function ProcessingCard({ doc }: { doc: Document }) {
  const job = useJobProgress(doc.id);
  const reprocess = useReprocessDocument();
  const jobRef = useRef(job);
  useEffect(() => {
    jobRef.current = job;
  });
  // the progress is shown right here — no duplicate toast; once filed, the toast isn't needed
  useEffect(() => {
    const id = doc.id;
    setUploadToastHidden(id, true);
    return () => {
      setUploadToastHidden(id, false);
      if (jobRef.current?.status === "done") dismissJob(id);
    };
  }, [doc.id]);
  const again = wasReadBefore(doc);
  const name = doc.title ?? doc.filename;

  if (doc.status === "failed" || job?.status === "failed") {
    const reason = job?.error ?? doc.error ?? "Something went wrong while reading it.";
    return (
      <div className="card flex gap-3 border-danger/30 px-5 py-4" role="alert">
        <CircleX className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
        <div className="min-w-0 flex-1">
          {again ? (
            <p className="text-md font-semibold text-danger-ink">Couldn't read it again</p>
          ) : (
            <h1 className="text-md font-semibold text-danger-ink">Ordnung couldn't read this letter</h1>
          )}
          <p className="mt-1 text-[13.5px] leading-5 text-muted wrap-break-word">
            {/* the verdict below still shows what the earlier reading found */}
            {again ? "What's shown below is from the earlier reading. " : ""}
            {reason} Your file is safe.
          </p>
          <Button
            size="sm"
            className="mt-3"
            icon={RotateCw}
            loading={reprocess.isPending}
            onClick={() =>
              reprocess.mutate(doc.id, {
                onSuccess: (j) => seedJob({ job_id: j.id, doc_id: doc.id, stage: "intake", progress: 0, status: "running" }),
              })
            }
          >
            Try again
          </Button>
        </div>
      </div>
    );
  }

  const done = job?.status === "done";
  const step = done ? PIPELINE_STEPS.length : stageToStep(job?.stage);
  const label = done ? "Filed — loading what was found…" : `${copyFor(JOB_STAGE_COPY, job?.stage ?? "intake").label}…`;
  return (
    <div className="card overflow-hidden">
      <div className="relative px-5 pb-5 pt-5 sm:px-6">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-0.5 animate-pulse-soft bg-gradient-to-r from-transparent via-accent to-transparent motion-reduce:animate-none"
        />
        <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-accent">{again ? "Reading it again" : "Reading your letter"}</p>
        {again ? null : (
          // nothing read yet, so no title: the file's name
          <h1 className="display mt-1.5 text-title font-semibold text-ink wrap-break-word">
            <FileNameText name={doc.filename} />
          </h1>
        )}
        <p className="mt-1 text-[13.5px] text-muted" aria-hidden>
          {label}
        </p>
        <div className="mt-5">
          <Stepper steps={PIPELINE_STEPS} current={step} labels="all" live label={`Reading ${name}`} />
        </div>
        <p className="mt-5 text-[12.5px] leading-5 text-muted">
          Claude reads the letter; the dates are then computed by tested rules, and every fact is checked against the page.
          {again ? " Dates you changed yourself are kept." : ""}
        </p>
      </div>
    </div>
  );
}
