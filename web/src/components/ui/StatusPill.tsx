import { cn } from "@/lib/utils";
import {
  AREA_STATUS_COPY,
  CONTRACT_STATUS_COPY,
  copyFor,
  DOCUMENT_STATUS_COPY,
  DRAFT_STATUS_COPY,
  ITEM_STATUS_COPY,
  LANE_BAR_STATUS_COPY,
  SUGGESTION_STATUS_COPY,
  TONES,
  type EnumCopy,
} from "@/lib/copy";
import type {
  AreaStatusLevel,
  ContractStatus,
  DocumentStatus,
  DraftStatus,
  ItemStatus,
  LaneBarStatus,
  SuggestionStatus,
} from "@/api/types";

export type StatusSource =
  | { of: "document"; status: DocumentStatus }
  | { of: "item"; status: ItemStatus }
  | { of: "suggestion"; status: SuggestionStatus }
  | { of: "draft"; status: DraftStatus }
  | { of: "contract"; status: ContractStatus }
  | { of: "area"; status: AreaStatusLevel }
  | { of: "lane"; status: LaneBarStatus };

const MAPS: Record<StatusSource["of"], Record<string, EnumCopy>> = {
  document: DOCUMENT_STATUS_COPY,
  item: ITEM_STATUS_COPY,
  suggestion: SUGGESTION_STATUS_COPY,
  draft: DRAFT_STATUS_COPY,
  contract: CONTRACT_STATUS_COPY,
  area: AREA_STATUS_COPY,
  lane: LANE_BAR_STATUS_COPY,
};

export type StatusPillProps = StatusSource & {
  /** `dot` (default) or `icon` leading marker. */
  marker?: "dot" | "icon";
  /** Override label. */
  label?: string;
  className?: string;
};

/**
 * Status chip for documents ("Please check"), to-dos ("Done"), Ideas, letters, contracts, areas.
 * Processing states animate subtly (disabled with reduced motion).
 *
 * @example <StatusPill of="document" status="needs_review" />
 */
export function StatusPill({ of, status, marker = "dot", label, className }: StatusPillProps) {
  const c = copyFor(MAPS[of], status);
  const t = TONES[c.tone];
  const Icon = c.icon;
  const busy = of === "document" && status === "processing";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-[3px] text-[12px] font-medium leading-4",
        t.soft,
        t.text,
        className,
      )}
    >
      {marker === "dot" ? (
        <span className={cn("size-1.5 rounded-full", t.solid, busy && "animate-pulse-soft motion-reduce:animate-none")} aria-hidden />
      ) : (
        <Icon className={cn("size-3", busy && "animate-spin motion-reduce:animate-none")} aria-hidden />
      )}
      {label ?? c.label}
    </span>
  );
}
