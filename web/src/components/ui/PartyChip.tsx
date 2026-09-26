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
 * Renders plain text when there is no id.
 *
 * @example <PartyChip party={doc.party} />
 */
export function PartyChip({ party, id, name, kind, size = "sm", showKind, className }: PartyChipProps) {
  const drawer = usePartyDrawer();
  const pid = party?.id ?? id ?? null;
  const pname = party?.name ?? name ?? "Unknown sender";
  const pkind = party?.kind ?? kind ?? null;
  const cls = cn(
    "inline-flex max-w-full items-center gap-1.5 rounded-full border border-line bg-surface py-0.5 pl-0.5 pr-2.5 font-medium text-ink",
    size === "sm" ? "text-[13px]" : "text-sm",
    className,
  );
  const inner = (
    <>
      <Avatar name={pname} kind={pkind} size={size === "sm" ? "xs" : "sm"} className="rounded-full" />
      <span className="truncate">{pname}</span>
      {showKind && pkind ? <span className="shrink-0 font-normal text-muted">· {partyKindLabel(pkind)}</span> : null}
    </>
  );
  if (!pid) return <span className={cls}>{inner}</span>;
  return (
    <button
      type="button"
      onClick={() => drawer.open(pid)}
      className={cn(cls, "transition-colors hover:border-line-strong hover:bg-surface-2")}
      aria-label={`${pname} — open details`}
    >
      {inner}
    </button>
  );
}
