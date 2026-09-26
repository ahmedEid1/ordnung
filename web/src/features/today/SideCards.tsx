import { Link } from "react-router";
import { motion } from "motion/react";
import { CalendarCheck, CalendarPlus, ChevronRight, Download, TriangleAlert } from "lucide-react";
import { useMarkCalendarExported } from "@/api/hooks";
import type { Document, Suggestion } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { KindIcon } from "@/components/ui/KindBadge";
import { toast } from "@/components/ui/Toast";
import { cn, plural } from "@/lib/utils";
import { downloadCalendar } from "./helpers";
import { fadeUp } from "./motion";

/** How many letters the "Please check" card lists. */
export const PLEASE_CHECK_SHOWN = 4;

/** Rule id of the Idea that says "Please check: <letter>" — the card already lists those letters. */
const PLEASE_CHECK_RULE = "please_check";

/**
 * Does this Idea only repeat a letter the "Please check" card lists ("Please check: Fixed-term
 * working student contract…" next to the card that lists that contract)?
 */
export function repeatsPleaseCheck(idea: Pick<Suggestion, "rule_id" | "action" | "refs">, listed: ReadonlySet<string>): boolean {
  if (idea.rule_id !== PLEASE_CHECK_RULE) return false;
  const target = idea.action?.target_type === "document" ? idea.action.target_id : idea.refs.find((r) => r.type === "document")?.id;
  return Boolean(target && listed.has(target));
}

/** "Please check: 1 date could not be confirmed…" → "1 date could not be confirmed…" (the card says "Please check"). */
export function checkReason(warning: string): string {
  const rest = warning.replace(/^\s*please check\s*[:–—-]\s*/i, "").trim();
  return rest ? rest.charAt(0).toUpperCase() + rest.slice(1) : warning;
}

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
        {docs.slice(0, PLEASE_CHECK_SHOWN).map((d) => (
          <li key={d.id}>
            <Link
              to={`/documents/${encodeURIComponent(d.id)}`}
              className="group -mx-2 flex items-start gap-2.5 rounded-lg px-2 py-2 outline-none transition-colors hover:bg-surface/70 focus-visible:ring-2 focus-visible:ring-accent"
            >
              <KindIcon docKind={d.kind} size="sm" />
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-medium leading-snug text-ink [overflow-wrap:anywhere]">{d.title ?? d.filename}</span>
                {d.warnings[0] ? <span className="mt-0.5 block text-[12.5px] leading-snug text-ink/75">{checkReason(d.warnings[0])}</span> : null}
              </span>
              <span className="mt-0.5 inline-flex shrink-0 items-center text-[12.5px] font-semibold text-accent">
                Check <ChevronRight className="size-3.5" aria-hidden />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </motion.section>
  );
}

/**
 * "3 new dates since your last calendar update → Add to calendar". After the download the card
 * stays (its Idea is gone by then) and says what to do with the file, so focus and the person's
 * place on the page stay where they were.
 */
export function CalendarCard({ idea, done, onDone }: { idea: Suggestion | null; done: boolean; onDone: () => void }) {
  const exported = useMarkCalendarExported();
  if (!idea && !done) return null;
  const add = () => {
    downloadCalendar();
    onDone();
    exported.mutate(undefined, { onSuccess: () => toast.success("Calendar file downloaded") });
  };
  return (
    <motion.section variants={fadeUp} aria-labelledby="calendar-card-title" className="card flex gap-3.5 p-4 sm:p-5">
      <span className={cn("grid size-10 shrink-0 place-items-center rounded-xl", done ? "bg-ok-soft text-ok" : "bg-accent-soft text-accent")}>
        {done ? <CalendarCheck className="size-5" aria-hidden /> : <CalendarPlus className="size-5" aria-hidden />}
      </span>
      <div className="min-w-0 flex-1">
        <h2 id="calendar-card-title" className="text-[14px] font-semibold leading-snug text-ink">
          {done ? "Calendar file downloaded" : idea?.title}
        </h2>
        <p className="mt-1 text-[13px] leading-relaxed text-muted">
          {done ? "Open ordnung.ics to add your dates to your calendar — reminders are included." : idea?.body}
        </p>
        {/* no busy state: the file is already downloaded, and a disabled button would drop focus */}
        <Button size="sm" variant={done ? "ghost" : "soft"} icon={done ? Download : CalendarPlus} className={cn("mt-3", done && "-ml-2")} onClick={add}>
          {done ? "Download again" : "Add to calendar"}
        </Button>
      </div>
    </motion.section>
  );
}
