/**
 * Which device this browser tab is, for code outside React (the API client's and the query client's wording):
 * the computer Ordnung runs on, or a phone paired over the home network. `useHealth()` sets it from each
 * `/api/health` answer (`Health.client`), and from a refusal only a phone gets (`phone_not_paired`).
 *
 * A module of its own, importing nothing at run time, so `api/client.ts` can read it without an import cycle.
 * Components use `usePhoneCompanion()` (`features/phone/client.ts`) instead.
 */
import type { ClientKind } from "./types";

let kind: ClientKind = "computer";

/** Who this tab is, as the server last said ("computer" until it says otherwise). */
export function clientKind(): ClientKind {
  return kind;
}

/** Remember who this tab is (`useHealth` does; tests reset it to "computer" after each test). */
export function setClientKind(next: ClientKind): void {
  kind = next;
}
