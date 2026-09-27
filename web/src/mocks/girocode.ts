/**
 * The static demo's GiroCodes: the server's answers, generated from the real gate and payload
 * builder (`data/girocodes.ts`, `scripts/gen_mock_girocodes.py`), the person's "These match the
 * letter", and "no code" once a payment is marked paid or set aside. Which payments were compared
 * belongs to the mock state, so resetting the demo forgets it.
 */
import type { GiroCode, GiroCodeBlocked, GiroCodeReady, Item, TransferValues } from "@/api/types";
import { normalizeIban } from "@/lib/format";
import { GIROCODE_MESSAGES, GIROCODE_REFUSALS, GIROCODES, GIROCODES_CHECKED } from "./data/girocodes";
import type { MockDb } from "./db";

const compared = new WeakMap<object, Set<string>>();

function comparedIn(db: MockDb): Set<string> {
  let ids = compared.get(db.state);
  if (!ids) {
    ids = new Set();
    compared.set(db.state, ids);
  }
  return ids;
}

function blocked(item: Item, reason: GiroCodeBlocked["reason"], message: string): GiroCodeBlocked {
  return { status: "blocked", item_id: item.id, reason, message, to_check: [], values: null };
}

/** A payment's GiroCode in the demo, as the server would answer it now. */
export function mockGiroCode(db: MockDb, item: Item): GiroCode {
  if (item.status === "done" || item.status === "dismissed") return blocked(item, "settled", GIROCODE_MESSAGES[item.status]);
  const checked = GIROCODES_CHECKED[item.id];
  if (checked && comparedIn(db).has(item.id)) return checked;
  return GIROCODES[item.id] ?? blocked(item, "no_iban", GIROCODE_MESSAGES.no_iban);
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
  const ready = GIROCODES_CHECKED[item.id];
  if (!current.values || !ready || !sameTransfer(values, current.values)) return { status: 409, message: GIROCODE_REFUSALS.changed };
  comparedIn(db).add(item.id);
  db.log("payment.checked", `You compared the transfer details of “${item.title}” with the paper letter`, "item", item.id, { ...current.values });
  return { code: ready, docId: item.doc_id };
}
