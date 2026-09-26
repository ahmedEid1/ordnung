import { cn } from "@/lib/utils";
import {
  AREA_COPY,
  CONTRACT_CATEGORY_COPY,
  copyFor,
  DOCUMENT_KIND_COPY,
  PARTY_KIND_COPY,
  SUGGESTION_KIND_COPY,
  TIMELINE_TYPE_COPY,
  TONES,
  type EnumCopy,
} from "@/lib/copy";
import type {
  Area,
  ContractCategory,
  DocumentKind,
  ItemKind,
  PartyKind,
  SuggestionKind,
  TimelineType,
} from "@/api/types";

/** Which enum the value belongs to (exactly one). */
export type KindSource =
  | { kind: ItemKind | TimelineType; docKind?: never; category?: never; area?: never; ideaKind?: never; partyKind?: never }
  | { docKind: DocumentKind | null | undefined; kind?: never; category?: never; area?: never; ideaKind?: never; partyKind?: never }
  | { category: ContractCategory; kind?: never; docKind?: never; area?: never; ideaKind?: never; partyKind?: never }
  | { area: Area; kind?: never; docKind?: never; category?: never; ideaKind?: never; partyKind?: never }
  | { ideaKind: SuggestionKind; kind?: never; docKind?: never; category?: never; area?: never; partyKind?: never }
  | { partyKind: PartyKind; kind?: never; docKind?: never; category?: never; area?: never; ideaKind?: never };

/** Resolve label/icon/tone for any kind-like enum value. */
export function resolveKind(src: KindSource): EnumCopy {
  if ("kind" in src && src.kind) return copyFor(TIMELINE_TYPE_COPY, src.kind);
  if ("docKind" in src && src.docKind !== undefined) return copyFor(DOCUMENT_KIND_COPY, src.docKind ?? "other");
  if ("category" in src && src.category) return copyFor(CONTRACT_CATEGORY_COPY, src.category);
  if ("area" in src && src.area) return copyFor(AREA_COPY, src.area);
  if ("ideaKind" in src && src.ideaKind) return copyFor(SUGGESTION_KIND_COPY, src.ideaKind);
  if ("partyKind" in src && src.partyKind) return copyFor(PARTY_KIND_COPY, src.partyKind);
  return copyFor(DOCUMENT_KIND_COPY, "other");
}

export type KindBadgeProps = KindSource & {
  size?: "sm" | "md";
  /** Hide the icon. */
  noIcon?: boolean;
  /** Override the label (keeps colour + icon). */
  label?: string;
  className?: string;
};

/**
 * Colour-coded kind chip with icon: to-do kinds (`kind`), letter kinds (`docKind`), contract
 * categories (`category`), areas (`area`), Idea kinds (`ideaKind`) or party kinds (`partyKind`).
 *
 * @example <KindBadge kind="deadline" /> · <KindBadge docKind="tax_assessment" />
 */
export function KindBadge({ size = "sm", noIcon, label, className, ...src }: KindBadgeProps) {
  const c = resolveKind(src as KindSource);
  const t = TONES[c.tone];
  const Icon = c.icon;
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 whitespace-nowrap rounded-full font-medium leading-none",
        size === "sm" ? "h-[22px] px-2 text-[12px]" : "h-7 px-2.5 text-[13px]",
        t.soft,
        t.text,
        className,
      )}
    >
      {!noIcon ? <Icon className={cn("shrink-0", size === "sm" ? "size-3" : "size-3.5")} aria-hidden /> : null}
      <span className="truncate">{label ?? c.label}</span>
    </span>
  );
}

export type KindIconProps = KindSource & {
  size?: "sm" | "md" | "lg";
  className?: string;
  /** Accessible label; when omitted the icon is decorative. */
  title?: string;
};

const iconBox = { sm: "size-7 rounded-md [&>svg]:size-3.5", md: "size-9 rounded-lg [&>svg]:size-[18px]", lg: "size-11 rounded-xl [&>svg]:size-5" };

/**
 * Tinted rounded-square icon for list rows and cards.
 *
 * @example <KindIcon kind="payment" size="md" />
 */
export function KindIcon({ size = "md", className, title, ...src }: KindIconProps) {
  const c = resolveKind(src as KindSource);
  const t = TONES[c.tone];
  const Icon = c.icon;
  return (
    <span
      className={cn("inline-grid shrink-0 place-items-center", iconBox[size], t.soft, t.icon, className)}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <Icon />
    </span>
  );
}
