import type { Contract } from "@/api/types";

/**
 * The Contracts page with one contract selected and scrolled into view: `/contracts?contract=ID`.
 * Every link to a contract uses this (the page also accepts the older `?focus=ID`).
 */
export function contractHref(id: string): string {
  return `/contracts?${new URLSearchParams({ contract: id }).toString()}`;
}

/** Letters composer pre-filled for cancelling this contract: `/letters?kind=cancellation&contract=ID`. */
export function composerHrefFor(c: Pick<Contract, "id">): string {
  return `/letters?${new URLSearchParams({ kind: "cancellation", contract: c.id }).toString()}`;
}

/**
 * Whether to offer a letter that ends this contract: a consumer cancellation — or, for a job, a
 * resignation (same composer; the API's send guidance requires a hand-signed letter, § 623 BGB).
 * The broadcasting fee and obligations towards authorities can't be cancelled (`cancel_hint`
 * says why).
 */
export function offersEndingLetter(c: Pick<Contract, "status" | "category" | "cancellable">): boolean {
  return c.status === "active" && (c.cancellable !== false || c.category === "employment");
}

/** "Draft cancellation", or "Draft resignation" for a job. */
export function endingLetterLabel(c: Pick<Contract, "category">): string {
  return c.category === "employment" ? "Draft resignation" : "Draft cancellation";
}
