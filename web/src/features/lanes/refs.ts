/** Where a lane bar / marker / timeline entry leads when clicked. */
import type { Item, RefLink } from "@/api/types";
import { contractHref } from "@/features/contracts/links";

export interface RefTarget {
  href: string;
  /** "Opens the letter", "Opens the contract" … (tooltips, accessible names) */
  hint: string;
}

/**
 * Resolve a reference to an in-app link. Items (to-dos & dates) have no page of their own: they
 * open the letter they came from, else their contract. Unknown references resolve to `null`.
 */
export function refTarget(ref: RefLink | null | undefined, items?: ReadonlyMap<string, Pick<Item, "doc_id" | "contract_id">>): RefTarget | null {
  if (!ref?.id) return null;
  const id = encodeURIComponent(ref.id);
  switch (ref.type) {
    case "document":
      return { href: `/documents/${id}`, hint: "Opens the letter" };
    case "contract":
      return { href: contractHref(ref.id), hint: "Opens the contract" };
    case "draft":
      return { href: `/letters/${id}`, hint: "Opens your letter" };
    case "party":
      return { href: `?party=${id}`, hint: "Opens the details" };
    case "item": {
      const item = items?.get(ref.id);
      if (item?.doc_id) return { href: `/documents/${encodeURIComponent(item.doc_id)}`, hint: "Opens the letter" };
      if (item?.contract_id) return { href: contractHref(item.contract_id), hint: "Opens the contract" };
      return null;
    }
    default:
      return null;
  }
}
