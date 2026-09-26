import { Link } from "react-router";
import { motion } from "motion/react";
import { CalendarPlus, ChevronRight, TriangleAlert } from "lucide-react";
import { useMarkCalendarExported } from "@/api/hooks";
import type { Document, Suggestion } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { KindIcon } from "@/components/ui/KindBadge";
import { toast } from "@/components/ui/Toast";
import { plural } from "@/lib/utils";
import { downloadCalendar } from "./helpers";
import { fadeUp } from "./motion";

/** "Please check": letters where something needs a quick look (unknown arrival date, possible scam…). */
export function PleaseCheckCard({ docs }: { docs: Document[] }) {
  if (!docs.length) return null;
  return (
    <motion.section
      variants={fadeUp}
      aria-labelledby="please-check-title"
      className="rounded-[var(--radius-card)] border border-warn/30 bg-warn-soft/60 p-4 sm:p-5"
    >
      <h2 id="please-check-title" className="flex items-center gap-2 text-[14px] font-semibold text-warn-ink">
        <TriangleAlert className="size-4 shrink-0 text-warn" aria-hidden />
        Please check · {plural(docs.length, "letter")}
      </h2>
      <ul className="mt-2.5 flex flex-col gap-1">
        {docs.slice(0, 4).map((d) => (
          <li key={d.id}>
            <Link
              to={`/documents/${encodeURIComponent(d.id)}`}
              className="group -mx-2 flex items-start gap-2.5 rounded-lg px-2 py-2 outline-none transition-colors hover:bg-surface/70 focus-visible:ring-2 focus-visible:ring-accent"
            >
              <KindIcon docKind={d.kind} size="sm" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13.5px] font-medium text-ink">{d.title ?? d.filename}</span>
                {d.warnings[0] ? <span className="line-clamp-2 text-[12.5px] leading-snug text-ink/75">{d.warnings[0]}</span> : null}
              </span>
              <span className="mt-1 inline-flex shrink-0 items-center text-[12.5px] font-semibold text-accent">
                Check <ChevronRight className="size-3.5" aria-hidden />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </motion.section>
  );
}

/** "3 new dates since your last calendar update → Add to calendar". */
export function CalendarCard({ idea }: { idea: Suggestion | null }) {
  const exported = useMarkCalendarExported();
  if (!idea) return null;
  const add = () => {
    downloadCalendar();
    exported.mutate(undefined, {
      onSuccess: () =>
        toast.success("Calendar file downloaded", {
          description: "Open ordnung.ics to add your dates — reminders are included.",
        }),
    });
  };
  return (
    <motion.section variants={fadeUp} aria-labelledby="calendar-card-title" className="card flex gap-3.5 p-4 sm:p-5">
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
        <CalendarPlus className="size-5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <h2 id="calendar-card-title" className="text-[14px] font-semibold leading-snug text-ink">
          {idea.title}
        </h2>
        <p className="mt-1 text-[13px] leading-relaxed text-muted">{idea.body}</p>
        <Button size="sm" variant="soft" icon={CalendarPlus} className="mt-3" onClick={add} loading={exported.isPending}>
          Add to calendar
        </Button>
      </div>
    </motion.section>
  );
}
