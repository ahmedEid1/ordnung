import { cn } from "@/lib/utils";
import { usePartyDrawer } from "@/lib/party-drawer";
import { partyKindLabel } from "@/lib/copy";
import type { Party, PartyKind } from "@/api/types";
import { Avatar } from "./Avatar";

export type PartyChipProps = {
  /** A full party, or id + name (+ kind). */
  party?: Pick<Party, "id" | "name" | "kind"> | null;
  id?: string | null;
  name?: string | null;
  kind?: PartyKind | null;
  size?: "sm" | "md";
  /** Show the party kind after the name ("Landlord"). */
  showKind?: boolean;
  className?: string;
};

/**
 * Person / organisation chip. Clicking opens the People & organisations drawer (`?party=id`).
 * Renders plain text when there is no id. In a tight spot the kind gives way first ("Ausländer-
 * behörde Musterstadt · Immig…"), then the name ends in "…"; the full name is in its tooltip.
 * At least 24 px tall, also where a row strips its padding.
 *
 * @example <PartyChip party={doc.party} />
 */
export function PartyChip({ party, id, name, kind, size = "sm", showKind, className }: PartyChipProps) {
  const drawer = usePartyDrawer();
  const pid = party?.id ?? id ?? null;
  const pname = party?.name ?? name ?? "Unknown sender";
  const pkind = party?.kind ?? kind ?? null;
  const kindLabel = showKind && pkind ? partyKindLabel(pkind) : null;
  const cls = cn(
    "inline-flex min-h-6 min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface py-0.5 pl-0.5 pr-2.5 font-medium text-ink",
    size === "sm" ? "text-sm" : "text-base",
    className,
  );
  const inner = (
    <>
      <Avatar name={pname} kind={pkind} size={size === "sm" ? "xs" : "sm"} className="rounded-full" />
      <span className="min-w-0 truncate">{pname}</span>
      {/* the kind shrinks (and ends in "…") long before the name does */}
      {kindLabel ? <span className="min-w-0 shrink-[999] truncate font-normal text-muted">· {kindLabel}</span> : null}
    </>
  );
  const title = kindLabel ? `${pname} · ${kindLabel}` : pname;
  if (!pid)
    return (
      <span className={cls} title={title}>
        {inner}
      </span>
    );
  return (
    <button
      type="button"
      onClick={() => drawer.open(pid)}
      title={title}
      className={cn(cls, "transition-[color,background-color,border-color] hover:border-line-strong hover:bg-surface-2")}
      aria-label={`${pname} — open details`}
    >
      {inner}
    </button>
  );
}
