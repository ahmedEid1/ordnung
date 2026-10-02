import { Link } from "react-router";
import { Tooltip } from "@/components/ui/Tooltip";
import { usePartyDrawer } from "@/lib/party-drawer";
import { cn } from "@/lib/utils";
import type { RefInfo } from "./refs";

function useOpen(info: RefInfo) {
  const drawer = usePartyDrawer();
  return info.type === "party" ? () => drawer.open(info.id) : undefined;
}

/**
 * A citation marker's link or button: a 24 px high target, at least 24 px wide (WCAG 2.5.8) — a marker may
 * stand alone, in a list item of markers only or wrapped onto a line of its own, where the inline exception
 * doesn't hold. The marker that is seen is its `::before`, 3.5 px in from every side, so the target is
 * centred on it: 17 px high, at least 17 px wide, its digits 3 px from its top and 4 px from its sides (7.5
 * from the target's), as it always looked. The target's own box takes no room: negative margins of the same
 * 3.5 px keep its footprint the drawn marker's, 2 px after its word as before, so the line is no taller and
 * the words around it stay put. Two markers in a row ("…94.99 €¹ ²") stand at least 7 px apart (Markdown's
 * gap between chips), so neither target covers the other. Raised like a footnote, both together.
 *
 * Keyboard focus rings the drawn marker (its `::before`), not the invisible target round it. `isolate` keeps
 * the `::before` behind the digits and above whatever is under the answer.
 */
const MARKER =
  "relative isolate -top-[0.35em] -my-[3.5px] -ml-[1.5px] -mr-[3.5px] inline-grid h-6 min-w-6 place-items-center px-[7.5px] align-baseline text-[11px] font-semibold leading-none tabular-nums text-accent outline-none " +
  "before:absolute before:inset-[3.5px] before:-z-10 before:rounded-[5px] before:bg-accent-soft " +
  "transition-colors before:transition-colors hover:text-on-accent hover:before:bg-accent " +
  "focus-visible:before:outline-2 focus-visible:before:outline-offset-1 focus-visible:before:outline-accent";

/**
 * Inline citation: a small numbered marker right after the fact it supports ("…by Thu 8 Oct²"),
 * like a footnote: it follows the word without a space. Hover/focus shows what it is; click opens
 * the letter, to-do, contract or person. Its target reaches 3.5 px round the 17 px marker, 24 × 24 px
 * (`MARKER`), so a finger or a shaky pointer hits it, also where it stands alone.
 */
export function CitationMarker({ info, n }: { info: RefInfo; n: number }) {
  const onOpen = useOpen(info);
  const label = `Source ${n}: ${info.kindLabel} “${info.title}”`;
  const tip = (
    <span className="flex items-center gap-1.5">
      <info.icon className="size-3.5 shrink-0 opacity-80" aria-hidden />
      <span>
        <span className="opacity-75">{info.kindLabel} · </span>
        {info.title}
      </span>
    </span>
  );
  return (
    <Tooltip content={tip}>
      {onOpen ? (
        <button type="button" className={MARKER} onClick={onOpen} aria-label={label}>
          {n}
        </button>
      ) : (
        <Link to={info.href ?? "/"} className={MARKER} aria-label={label}>
          {n}
        </Link>
      )}
    </Tooltip>
  );
}

/**
 * A source in the list under an answer: number, icon and title. A long title wraps, up to three lines
 * (UI audit round 1: cut to one line, the rest only in a hover title touch can't reach); the whole of
 * it is the link's name and title.
 */
export function CitationChip({ info, n, className }: { info: RefInfo; n?: number; className?: string }) {
  const onOpen = useOpen(info);
  const Icon = info.icon;
  const label = `${n ? `Source ${n}: ` : ""}${info.kindLabel} “${info.title}”`;
  const cls = cn(
    "group/cite inline-flex min-h-8 max-w-full items-start gap-2 rounded-lg border border-line bg-surface py-[5px] pl-1.5 pr-2.5 text-left text-[13px] font-medium leading-5 text-ink/85 shadow-[var(--shadow-card)] transition-colors",
    "hover:border-accent/40 hover:bg-accent-soft/50 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
    className,
  );
  const body = (
    <>
      {n ? (
        <span className="grid h-5 min-w-5 shrink-0 place-items-center rounded-[5px] bg-accent-soft px-1 text-[11px] font-semibold tabular-nums text-accent" aria-hidden>
          {n}
        </span>
      ) : null}
      <Icon className="mt-[3px] size-3.5 shrink-0 text-muted transition-colors group-hover/cite:text-accent" aria-hidden />
      <span className="line-clamp-3 min-w-0 [overflow-wrap:anywhere]">{info.title}</span>
    </>
  );
  if (onOpen) {
    return (
      <button type="button" className={cls} onClick={onOpen} aria-label={label} title={label}>
        {body}
      </button>
    );
  }
  return (
    <Link to={info.href ?? "/"} className={cls} aria-label={label} title={label}>
      {body}
    </Link>
  );
}
