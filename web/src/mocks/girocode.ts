/**
 * The static demo's GiroCodes: the server's answers, generated from the real gate and payload
 * builder (`data/girocodes.ts`, `scripts/gen_mock_girocodes.py`), the person's "These match the
 * letter", "no code" once a payment is marked paid or set aside, and — like the server — a code
 * whose amount was changed by hand asks to compare with the letter again (and then carries the new
 * amount). Which payments were compared, and at which amount, belongs to the mock state, so
 * resetting the demo forgets it.
 */
import type { GiroCode, GiroCodeBlocked, GiroCodeReady, Item, TransferValues } from "@/api/types";
import { normalizeIban } from "@/lib/format";
import { readPayload } from "@/features/girocode/qr";
import { GIROCODE_MESSAGES, GIROCODE_REFUSALS, GIROCODES, GIROCODES_AMOUNT_CHANGED, GIROCODES_CHECKED } from "./data/girocodes";
import type { MockDb } from "./db";

/** Per mock state: item id → the amount the person compared with the letter. */
const compared = new WeakMap<object, Map<string, number>>();

function comparedIn(db: MockDb): Map<string, number> {
  let ids = compared.get(db.state);
  if (!ids) {
    ids = new Map();
    compared.set(db.state, ids);
  }
  return ids;
}

function blocked(item: Item, reason: GiroCodeBlocked["reason"], message: string): GiroCodeBlocked {
  return { status: "blocked", item_id: item.id, reason, message, to_check: [], values: null };
}

const sameAmount = (a: number | null | undefined, b: number | null | undefined) => a != null && b != null && a.toFixed(2) === b.toFixed(2);

/** `EUR` and the amount as the payload builder writes it: 30 → "EUR30", 184.30 → "EUR184.3". */
export function amountText(amount: number): string {
  return `EUR${amount.toFixed(2).replace(/\.?0+$/, "")}`;
}

/** The payload with another amount (EPC069-12 element 8). */
function withAmount(payload: string, amount: number): string {
  const lines = payload.split("\n");
  lines[7] = amountText(amount);
  return lines.join("\n");
}

/** A payment's GiroCode in the demo, as the server would answer it now. */
export function mockGiroCode(db: MockDb, item: Item): GiroCode {
  if (item.status === "done" || item.status === "dismissed") return blocked(item, "settled", GIROCODE_MESSAGES[item.status]);
  const base = GIROCODES[item.id];
  if (!base) return blocked(item, "no_iban", GIROCODE_MESSAGES.no_iban);
  const ready = base.status === "ready" ? base : GIROCODES_CHECKED[item.id];
  if (!ready) return base; // no code for another reason (a scam, several payments …)
  if (item.amount == null) return blocked(item, "no_amount", GIROCODE_MESSAGES.no_amount);
  const seen = comparedIn(db).get(item.id);
  const letterAmount = readPayload(ready.payload).amount;
  if (sameAmount(item.amount, letterAmount)) {
    if (base.status === "ready") return base;
    return sameAmount(seen, item.amount) ? ready : base;
  }
  // the amount isn't the one on the letter any more: only the person's comparison vouches for it
  if (sameAmount(seen, item.amount)) return { ...ready, payload: withAmount(ready.payload, item.amount), checked: true };
  const asks = GIROCODES_AMOUNT_CHANGED[item.id]!;
  return { ...asks, values: { ...asks.values!, amount: item.amount } };
}

const oneLine = (text: string | null | undefined) => (text ?? "").replace(/\s+/g, " ").trim();

/** The same payment, spacing and case aside (the server's `same_values`). */
export function sameTransfer(a: TransferValues, b: TransferValues): boolean {
  const key = (v: TransferValues) => [oneLine(v.payee), normalizeIban(v.iban ?? ""), oneLine(v.reference), v.amount == null ? "" : v.amount.toFixed(2)].join("\n");
  return key(a) === key(b);
}

export type MockConfirm = { code: GiroCodeReady; docId: string } | { status: 404 | 409; message: string };

/** `POST /items/{id}/girocode/confirm`: refused (409) unless the payment waits for exactly these details. */
export function confirmMockGiroCode(db: MockDb, itemId: string, values: TransferValues): MockConfirm {
  const item = db.state.items.find((i) => i.id === itemId);
  if (!item) return { status: 404, message: "Unknown to-do." };
  if (item.kind !== "payment" || !item.doc_id) return { status: 409, message: GIROCODE_REFUSALS.not_a_payment };
  const current = mockGiroCode(db, item);
  if (current.status === "ready") return { status: 409, message: GIROCODE_REFUSALS.nothing_to_compare };
  if (current.reason !== "check_letter") return { status: 409, message: current.message };
  if (!current.values || item.amount == null || !sameTransfer(values, current.values)) return { status: 409, message: GIROCODE_REFUSALS.changed };
  comparedIn(db).set(item.id, item.amount);
  db.log("payment.checked", `You compared the transfer details of “${item.title}” with the letter`, "item", item.id, { ...current.values, doc_id: item.doc_id });
  const code = mockGiroCode(db, item);
  if (code.status !== "ready") return { status: 409, message: GIROCODE_REFUSALS.changed };
  return { code, docId: item.doc_id };
}
