import { Link } from "react-router";
import { CirclePause } from "lucide-react";
import { useJobs } from "@/api/hooks";
import { useEvents } from "@/api/sse";
import type { LlmPausedEvent } from "@/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { SHELL_GUTTERS, shellWidth } from "./layout";
import { usePageMeta } from "./page-meta";

const sameDay = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
const hhmm = (d: Date) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

/**
 * When the break ends, relative to `now`: "until 15:30 today", "until 09:00 tomorrow", else
 * "until Mon 5 Oct, 15:30" — never a bare weekday that could mean today or next week.
 * The end is a real clock time, so it is compared with the real clock (not the demo's date).
 */
export function pauseEnds(until: string, now: Date = new Date()): string | null {
  const end = new Date(until);
  if (Number.isNaN(end.getTime())) return null;
  if (sameDay(end, now)) return `until ${hhmm(end)} today`;
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  if (sameDay(end, tomorrow)) return `until ${hhmm(end)} tomorrow`;
  return `until ${formatDateTime(end, { today: now })}`;
}

/** The banner's text; the queued-letter count is only fetched while it shows. */
function PausedMessage({ paused }: { paused: LlmPausedEvent }) {
  const { data: jobs } = useJobs(true);
  // count letters, not jobs
  const waiting = new Set((jobs ?? []).flatMap((j) => (j.doc_id ? [j.doc_id] : []))).size;
  // no end: Claude isn't installed or signed in — reading goes on once it is
  const forClaude = !paused.until;
  const ends = forClaude ? null : pauseEnds(paused.until);
  const title = forClaude ? "Waiting for Claude" : ends ? `Claude is taking a break ${ends}` : "Claude is taking a short break";
  return (
    <p className="min-w-0 text-balance text-ink/90">
      <span className="font-semibold text-warn-ink">{title}</span>
      {waiting ? <span className="whitespace-nowrap"> · {waiting === 1 ? "1 letter waiting" : `${waiting} letters waiting`}</span> : null}.{" "}
      {paused.reason ? `${paused.reason} ` : ""}
      {forClaude ? (
        <>
          Your letters are safe in the queue and are read as soon as Claude is connected —{" "}
          <Link to="/settings?section=claude" className="font-medium text-accent underline underline-offset-2 hover:no-underline">
            Claude connection
          </Link>
          .
        </>
      ) : (
        "Your letters are safe in the queue and will be read automatically — nothing gets lost."
      )}
    </p>
  );
}

/**
 * Shown while the AI worker is paused — Claude's usage limit, or Claude not installed or not signed in:
 * letters stay safely queued and are read automatically once the pause is over (or Claude is
 * connected). Lined up with the top bar and the page column.
 */
export function PausedBanner() {
  const { paused } = useEvents();
  const { width } = usePageMeta();
  if (!paused) return null;
  return (
    <div role="status" className="border-b border-warn/25 bg-warn-soft py-2.5 text-base">
      <div className={cn("mx-auto flex w-full items-start gap-2.5", SHELL_GUTTERS, shellWidth(width))}>
        <CirclePause className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
        <PausedMessage paused={paused} />
      </div>
    </div>
  );
}
