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
 * Inline citation: a small numbered marker right after the fact it supports ("…by Thu 8 Oct²"),
 * like a footnote: it follows the word without a space. Hover/focus shows what it is; click opens
 * the letter, to-do, contract or person. It sits in a line of text (WCAG 2.5.8's inline exception),
 * and still reacts 4 px around its 17 px box, so a finger or a shaky pointer hits it.
 */
export function CitationMarker({ info, n }: { info: RefInfo; n: number }) {
  const onOpen = useOpen(info);
  const label = `Source ${n}: ${info.kindLabel} “${info.title}”`;
  const cls =
    "relative -top-[0.35em] ml-[2px] inline-grid h-[17px] min-w-[17px] place-items-center rounded-[5px] bg-accent-soft px-[4px] align-baseline text-[11px] font-semibold leading-none tabular-nums text-accent " +
    "after:absolute after:-inset-1 after:rounded-md " +
    "transition-colors hover:bg-accent hover:text-on-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent";
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
        <button type="button" className={cls} onClick={onOpen} aria-label={label}>
          {n}
        </button>
      ) : (
        <Link to={info.href ?? "/"} className={cls} aria-label={label}>
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
