import { useId, useState } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { ChevronDown } from "lucide-react";
import type { Document, Party } from "@/api/types";
import { DateText } from "@/components/ui/DateText";
import { KindIcon } from "@/components/ui/KindBadge";
import { StatusPill } from "@/components/ui/StatusPill";
import { documentKindLabel } from "@/lib/copy";
import { cn } from "@/lib/utils";
import { fadeUp } from "./motion";

/** "Recent letters" — collapsed by default; expands to the latest letters with kind and status. */
export function RecentLetters({ docs, partyById }: { docs: Document[]; partyById: Map<string, Party> }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  if (!docs.length) return null;
  const latest = docs[0]!;
  return (
    <motion.section variants={fadeUp} aria-labelledby={`${listId}-title`} className="card overflow-hidden">
      <h2 id={`${listId}-title`} className="m-0">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center gap-3 px-4 py-3.5 text-left outline-none transition-colors hover:bg-surface-2/60 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent sm:px-5"
        >
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-semibold uppercase tracking-[0.06em] text-muted">
              Recent letters <span className="font-medium tabular-nums text-muted">· {docs.length}</span>
            </span>
            {!open ? (
              <span className="mt-0.5 block truncate text-[13.5px] text-ink/85">
                Latest: {latest.title ?? latest.filename}
              </span>
            ) : null}
          </span>
          <ChevronDown className={cn("size-4 shrink-0 text-muted transition-transform duration-200", open && "rotate-180")} aria-hidden />
        </button>
      </h2>
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
              {docs.map((d) => {
                const party = d.party_id ? partyById.get(d.party_id) : undefined;
                return (
                  <li key={d.id}>
                    <Link
                      to={`/documents/${encodeURIComponent(d.id)}`}
                      className="flex items-center gap-3 px-4 py-2.5 outline-none transition-colors hover:bg-surface-2/60 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent sm:px-5"
                    >
                      <KindIcon docKind={d.kind} size="sm" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] font-medium text-ink">{d.title ?? d.filename}</span>
                        <span className="block truncate text-[12.5px] text-muted">
                          {[party?.name, d.kind ? documentKindLabel(d.kind) : null].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                      {d.status !== "processed" ? <StatusPill of="document" status={d.status} className="hidden sm:inline-flex" /> : null}
                      <DateText date={d.received_date ?? d.doc_date ?? d.created_at.slice(0, 10)} style="day" className="shrink-0 text-[12.5px] text-muted" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </motion.section>
  );
}
