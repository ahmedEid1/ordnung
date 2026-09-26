/**
 * Round-2 regression review: "To pay · next 30 days" (Greeting) is summed in the browser by
 * `toPayWithin` and was shown with `formatMoney(total)` — i.e. in euros. It added up the raw amounts
 * of every outgoing payment whatever its currency, so a $50 invoice became €50 of the total.
 */
import { describe, expect, it } from "vitest";
import type { Item } from "@/api/types";
import { formatTotals } from "@/lib/format";
import { actionFromItem, groupByWeek, toPayTotals, toPayWithin } from "./selection";

const TODAY = "2026-09-28";

function payment(id: string, due: string, amount: number, currency: string): Item {
  return {
    id,
    kind: "payment",
    title: id,
    description: null,
    action: null,
    consequence: null,
    due_date: due,
    due_time: null,
    send_by: null,
    date_spec: null,
    computation: null,
    amount,
    currency,
    direction: "out",
    recurrence: null,
    status: "open",
    snoozed_until: null,
    priority: "normal",
    area: "money",
    party_id: null,
    case_id: null,
    contract_id: null,
    doc_id: null,
    evidence: [],
    grounding: "verified",
    slot_key: null,
    user_modified: false,
    due_date_source: "fixed",
    origin: "extracted",
    location: null,
    filed_on: null,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
    completed_at: null,
  };
}

describe("To pay · next 30 days (round 2)", () => {
  // toPayWithin ignored TodayAction.currency: 100 EUR + 50 USD was reported as €150.00
  it("never adds another currency's amount to the euro total", () => {
    const ctx = { today: TODAY };
    const actions = [
      actionFromItem(payment("rent", "2026-10-01", 100, "EUR"), ctx)!,
      actionFromItem(payment("saas", "2026-10-02", 50, "USD"), ctx)!,
    ];
    expect(actions.map((a) => a.currency)).toEqual(["EUR", "USD"]);
    expect(toPayWithin(actions)).toBe(100);
    // one total per currency, euros first — the Greeting and each Coming-up week show them all
    expect(toPayTotals(actions)).toEqual({ EUR: 100, USD: 50 });
    expect(formatTotals(toPayTotals(actions), { decimals: "auto" })).toBe("€100 + US$50.00");
    const weeks = groupByWeek(
      actions.map((a) => ({ date: a.actionDate, amount: a.amount, currency: a.currency, outgoing: true })),
      TODAY,
    );
    expect(weeks.map((g) => g.totals)).toEqual([{ EUR: 100, USD: 50 }]);
  });
});
