import { useId, useMemo, useState } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, ChevronDown } from "lucide-react";
import type { Document, Party } from "@/api/types";
import { DateText } from "@/components/ui/DateText";
import { KindIcon } from "@/components/ui/KindBadge";
import { StatusPill } from "@/components/ui/StatusPill";
import { documentKindLabel } from "@/lib/copy";
import { cn } from "@/lib/utils";
import { recentLetterDate, sortRecentLetters } from "./helpers";
import { fadeUp } from "./motion";

const allLetters = "inline-flex min-h-6 items-center gap-1 rounded text-[13px] font-medium text-accent hover:underline";

/**
 * "Recent letters" — collapsed by default (the latest one named under the heading); expands to the
 * latest letters with kind, status and the day each arrived, newest first. "All letters" goes to
 * the inbox.
 */
export function RecentLetters({ docs, partyById }: { docs: Document[]; partyById: Map<string, Party> }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const titleId = `${listId}-title`;
  const latestId = `${listId}-latest`;
  const sorted = useMemo(() => sortRecentLetters(docs), [docs]);
  if (!sorted.length) return null;
  const latest = sorted[0]!;
  const latestTitle = latest.title ?? latest.filename;
  return (
    <motion.section variants={fadeUp} aria-labelledby={titleId} className="card @container overflow-hidden">
      {/* the whole row opens the list (the button's ::after covers it); only "Recent letters · 6" is the heading */}
      <div className="relative flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-surface-2/60 sm:px-5">
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="m-0 text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">
            <button
              type="button"
              aria-expanded={open}
              aria-controls={listId}
              aria-describedby={open ? undefined : latestId}
              onClick={() => setOpen((v) => !v)}
              className="inline-block text-left uppercase leading-6 outline-none after:absolute after:inset-0 after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-accent"
            >
              Recent letters <span className="font-medium tabular-nums">· {sorted.length}</span>
            </button>
          </h2>
          {!open ? (
            <p id={latestId} title={latestTitle} className="mt-0.5 line-clamp-2 break-words text-[13.5px] leading-snug text-ink/85">
              Latest: {latestTitle}
            </p>
          ) : null}
        </div>
        {/* above the row's click area; a small phone has it under the open list instead */}
        <Link to="/inbox" className={cn(allLetters, "relative z-10 hidden shrink-0 @[20rem]:inline-flex")}>
          All letters <ArrowRight className="size-3.5" aria-hidden />
        </Link>
        <ChevronDown className={cn("pointer-events-none size-4 shrink-0 text-muted transition-transform duration-200", open && "rotate-180")} aria-hidden />
      </div>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            id={listId}
            key="list"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
            className="overflow-hidden"
          >
            <ul className="divide-y divide-line border-t border-line">
              {sorted.map((d) => {
                const party = d.party_id ? partyById.get(d.party_id) : undefined;
                const title = d.title ?? d.filename;
                const meta = [party?.name, d.kind ? documentKindLabel(d.kind) : null].filter(Boolean).join(" · ");
                const status = d.status !== "processed" ? d.status : null;
                return (
                  <li key={d.id}>
                    <Link
                      to={`/documents/${encodeURIComponent(d.id)}`}
                      className="flex items-start gap-3 px-4 py-2.5 outline-none transition-colors hover:bg-surface-2/60 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent sm:px-5 @md:items-center"
                    >
                      <KindIcon docKind={d.kind} size="sm" />
                      <span className="min-w-0 flex-1">
                        <span title={title} className="line-clamp-2 break-words text-base font-medium leading-snug text-ink">
                          {title}
                        </span>
                        {meta ? (
                          <span title={meta} className="mt-0.5 line-clamp-2 break-words text-sm leading-snug text-muted">
                            {meta}
                          </span>
                        ) : null}
                        {/* phones: the status in words under the letter (a pill beside it from a roomier card) */}
                        {status ? <StatusPill of="document" status={status} className="mt-1 @md:hidden" /> : null}
                      </span>
                      {status ? <StatusPill of="document" status={status} className="hidden shrink-0 @md:inline-flex" /> : null}
                      <DateText date={recentLetterDate(d)} style="day" className="mt-0.5 shrink-0 text-sm text-muted @md:mt-0" />
                    </Link>
                  </li>
                );
              })}
            </ul>
            <div className="border-t border-line px-4 py-2.5 sm:px-5 @[20rem]:hidden">
              <Link to="/inbox" className={allLetters}>
                All letters <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </motion.section>
  );
}
