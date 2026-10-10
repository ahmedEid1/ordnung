import { useEffect, useId, useRef, useState } from "react";
import { Link, useLocation } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { ChevronDown, CircleCheck, Lightbulb, MapPinHouse, PenLine, X } from "lucide-react";
import { useDrafts, useUpdateSuggestion } from "@/api/hooks";
import type { Suggestion } from "@/api/types";
import { Button, buttonVariants } from "@/components/ui/Button";
import { Countdown } from "@/components/ui/Countdown";
import { Checkbox } from "@/components/ui/Field";
import { toast } from "@/components/ui/Toast";
import { cn } from "@/lib/utils";
import { RefText } from "@/features/ask/RefText";
import { focusAfterLeaving, focusWhenReady } from "./focus";
import { ideaHref } from "./helpers";
import { collapseOut, fadeUp } from "./motion";
import { MOVING_CHECKLIST_ID, MOVING_SHOWN, openDraftFor } from "./moving";

const TITLE_ID = `${MOVING_CHECKLIST_ID}-title`;
const checkId = (id: string) => `moving-check-${id}`;

const quiet =
  "inline-flex h-8 items-center gap-1.5 rounded-md px-1.5 text-[12.5px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent";

/**
 * Today's "Moving checklist" (after the person said they moved, Settings → Profile): who needs the new address,
 * one row per `moved_house` Idea. A native checkbox ticks a row off (`done`), "Not needed" hides it (`dismissed`);
 * both say so in a toast with Undo. Focus goes to the next row's checkbox, or to the heading when none is left, and
 * back to a row Undo brought back. "Write the letter" opens a new-address letter to that sender (or the one already
 * started); the row is never ticked for the person. The card stays for this visit once the last row is ticked, and
 * says so. "Open your moving checklist" in Settings leads here (`/#moving-checklist`): the page goes to the card and
 * its heading takes focus. Ordnung sends nothing.
 */
export function MovingChecklist({ rows }: { rows: Suggestion[] }) {
  // the card had rows during this visit: it stays, with "everyone has it", once the last one left
  const [hadRows, setHadRows] = useState(rows.length > 0);
  if (rows.length > 0 && !hadRows) setHadRows(true);
  // no move told (nearly always): nothing is asked for, not even the letters started
  return rows.length > 0 || hadRows ? <ChecklistCard rows={rows} /> : null;
}

function ChecklistCard({ rows }: { rows: Suggestion[] }) {
  const update = useUpdateSuggestion();
  const drafts = useDrafts();
  const listId = useId();
  const list = useRef<HTMLUListElement>(null);
  const [expanded, setExpanded] = useState(false);
  // rows being ticked: their checkbox shows the tick until they leave (and again unticked after Undo)
  const [ticking, setTicking] = useState<ReadonlySet<string>>(() => new Set());
  // arrived by the link to the card: the page goes to it, once
  const { hash } = useLocation();
  const section = useRef<HTMLElement>(null);
  useEffect(() => {
    if (hash !== `#${MOVING_CHECKLIST_ID}` || !section.current) return;
    section.current.scrollIntoView?.({ block: "start" });
    focusWhenReady(() => document.getElementById(TITLE_ID), 1000, { always: true });
  }, [hash]);

  const shown = expanded ? rows : rows.slice(0, MOVING_SHOWN);
  const more = rows.length - shown.length;
  const toGo = rows.filter((r) => !ticking.has(r.id)).length;
  const checksOnPage = () => Array.from(list.current?.querySelectorAll<HTMLElement>("[data-moving-check]") ?? []);
  const mark = (id: string, on: boolean) =>
    setTicking((s) => {
      const next = new Set(s);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const undo = (row: Suggestion) => async () => {
    await update.mutateAsync({ id: row.id, patch: { status: "new" } });
    mark(row.id, false);
    // the row asked back takes focus — also from the toast's Undo pressed by keyboard, which would hand focus
    // back to the row after it
    focusWhenReady(() => document.getElementById(checkId(row.id)), 3000, { always: true });
  };

  // focus is watched from the click, while the row is in its place, and the toast follows the call's promise
  // (the row leaves with the refreshed list, as an Idea card does)
  const answer = (row: Suggestion, status: "done" | "dismissed") => {
    if (status === "done") mark(row.id, true);
    focusAfterLeaving(checksOnPage, checkId(row.id), TITLE_ID);
    update.mutateAsync({ id: row.id, patch: { status } }).then(
      () => toast({ title: status === "done" ? "Ticked off" : "Hidden", description: row.title, undo: undo(row) }),
      () => mark(row.id, false), // the error toast comes from the mutation's meta
    );
  };

  return (
    <motion.section ref={section} variants={fadeUp} id={MOVING_CHECKLIST_ID} aria-labelledby={TITLE_ID} className="card scroll-mt-20 p-4 sm:p-5">
      <h2 id={TITLE_ID} className="flex items-center gap-2 text-[15px] font-semibold text-ink outline-none">
        <MapPinHouse className="size-[18px] shrink-0 text-accent" aria-hidden />
        Moving checklist
      </h2>
      <p className="mt-1 text-[13.5px] leading-relaxed text-muted">
        Who needs your new address. Tick each one off when it's done — Ordnung never sends anything for you.
      </p>
      {rows.length ? (
        <>
          <p className="mt-2 text-[12.5px] font-medium tabular-nums text-muted">{toGo} to go</p>
          <ul ref={list} id={listId} className="mt-2 divide-y divide-line">
            <AnimatePresence initial={false}>
              {shown.map((row) => (
                <MovingRow key={row.id} row={row} ticked={ticking.has(row.id)} busy={update.isPending} draftId={openDraftFor(row, drafts.data)?.id ?? null} onAnswer={answer} />
              ))}
            </AnimatePresence>
          </ul>
          {more > 0 || expanded ? (
            <Button
              variant="ghost"
              size="sm"
              iconRight={ChevronDown}
              aria-expanded={expanded}
              aria-controls={listId}
              className={cn("mt-1 [&_svg]:transition-transform motion-reduce:[&_svg]:transition-none", expanded && "[&_svg]:rotate-180")}
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? "Show fewer" : `Show ${more} more`}
            </Button>
          ) : null}
        </>
      ) : (
        <p className="mt-3 flex items-center gap-2 text-[13.5px] font-medium text-ok-ink">
          <CircleCheck className="size-4 shrink-0 text-ok" aria-hidden />
          Everyone on the list has your new address.
        </p>
      )}
      <p className="mt-3 border-t border-line pt-3 text-[12.5px] leading-5 text-muted">
        Not in Ordnung? Also think of your doctor, a car's registration, online shops and subscriptions, and a forwarding order for your post
        (Nachsendeauftrag, a paid Deutsche Post service).
      </p>
    </motion.section>
  );
}

function MovingRow({
  row,
  ticked,
  busy,
  draftId,
  onAnswer,
}: {
  row: Suggestion;
  ticked: boolean;
  busy: boolean;
  draftId: string | null;
  onAnswer: (row: Suggestion, status: "done" | "dismissed") => void;
}) {
  const href = draftId ? `/letters/${encodeURIComponent(draftId)}` : ideaHref(row);
  // the buttons name the row they are about: its title
  const titleId = `${checkId(row.id)}-title`;
  return (
    <motion.li layout variants={fadeUp} exit={collapseOut} className="py-3 first:pt-1">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <Checkbox
          id={checkId(row.id)}
          data-moving-check=""
          checked={ticked}
          onChange={() => {
            if (!ticked) onAnswer(row, "done");
          }}
          label={
            <span id={titleId} className="text-[14.5px] leading-snug [overflow-wrap:anywhere]">
              {row.title}
            </span>
          }
          className="min-w-0 flex-1"
        />
        {row.due_date ? <Countdown date={row.due_date} className="ml-8 text-[12px] sm:ml-0" /> : null}
      </div>
      <div className="ml-[30px]">
        <p className="mt-1 text-[13px] leading-relaxed text-muted">
          <RefText text={row.body} />
        </p>
        {row.rationale ? (
          <p className="mt-1.5 flex items-start gap-1.5 text-[12px] leading-5 text-muted">
            <Lightbulb className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span>
              <span className="sr-only">Why you're seeing this: </span>
              <RefText text={row.rationale} />
            </span>
          </p>
        ) : null}
        <div className="-ml-1.5 mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
          {href ? (
            <Link to={href} aria-describedby={titleId} className={buttonVariants({ variant: "soft", size: "sm", className: "ml-1.5" })}>
              <PenLine aria-hidden />
              {draftId ? "Open your draft" : "Write the letter"}
            </Link>
          ) : null}
          <button type="button" onClick={() => onAnswer(row, "dismissed")} disabled={busy} aria-describedby={titleId} className={quiet}>
            <X className="size-3.5" aria-hidden />
            Not needed
          </button>
        </div>
      </div>
    </motion.li>
  );
}
