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
 * Inline citation: a small numbered marker right after the fact it supports ("…by Thu 8 Oct ²").
 * Hover/focus shows what it is; click opens the letter, to-do, contract or person.
 */
export function CitationMarker({ info, n }: { info: RefInfo; n: number }) {
  const onOpen = useOpen(info);
  const label = `Source ${n}: ${info.kindLabel} “${info.title}”`;
  const cls =
    "relative -top-[0.35em] mx-[1px] inline-grid h-[17px] min-w-[17px] place-items-center rounded-[5px] bg-accent-soft px-[4px] align-baseline text-[10.5px] font-semibold leading-none tabular-nums text-accent " +
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

/** A source in the list under an answer: number, icon and title. */
export function CitationChip({ info, n, className }: { info: RefInfo; n?: number; className?: string }) {
  const onOpen = useOpen(info);
  const Icon = info.icon;
  const label = `${n ? `Source ${n}: ` : ""}${info.kindLabel} “${info.title}”`;
  const cls = cn(
    "group/cite inline-flex h-8 max-w-full items-center gap-2 rounded-lg border border-line bg-surface pl-1.5 pr-2.5 text-[13px] font-medium text-ink/85 shadow-[var(--shadow-card)] transition-colors",
    "hover:border-accent/40 hover:bg-accent-soft/50 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
    className,
  );
  const body = (
    <>
      {n ? (
        <span className="grid h-5 min-w-5 place-items-center rounded-[5px] bg-accent-soft px-1 text-[11px] font-semibold tabular-nums text-accent" aria-hidden>
          {n}
        </span>
      ) : null}
      <Icon className="size-3.5 shrink-0 text-muted transition-colors group-hover/cite:text-accent" aria-hidden />
      <span className="min-w-0 truncate">{info.title}</span>
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
