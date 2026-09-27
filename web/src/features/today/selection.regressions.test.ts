/**
 * Round-2 regression review: "To pay · next 30 days" (Greeting) is summed in the browser by
 * `toPayWithin` and was shown with `formatMoney(total)` — i.e. in euros. It added up the raw amounts
 * of every outgoing payment whatever its currency, so a $50 invoice became €50 of the total.
 */
import { describe, expect, it } from "vitest";
import type { Item } from "@/api/types";
import { formatTotals } from "@/lib/format";
import { SENDING_TIME_PASSED, actionFromItem, groupByWeek, postTooLate, toPayTotals, toPayWithin } from "./selection";

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

describe("the usual time to post has passed (review round 4 of phase 2)", () => {
  // the inbox and Today said "Send by Mon 28 Sep · today" for an Einspruch due that day: a letter posted then arrives late
  it("says when it must arrive, not when to post it", () => {
    const base = payment("einspruch", "2026-09-29", 0, "EUR");
    const receipt = {
      due_date: "2026-09-29",
      send_by: "2026-09-28",
      safe_date: null,
      holiday_calendar: "",
      summary: "",
      steps: [],
      rule_ids: ["zpo_339"],
      warnings: ["The usual sending time has passed — send it today, by the fastest channel allowed (online, fax or in person)."],
      confidence: "medium" as const,
    };
    const late = { ...base, kind: "deadline" as const, amount: null, send_by: "2026-09-28", computation: receipt };
    expect(postTooLate(late)).toBe(true);
    const action = actionFromItem(late, { today: TODAY })!;
    expect(action.dateRole).toBe("arrive_by");
    expect(action.actionDate).toBe("2026-09-29");
    expect(action.dueDate).toBeNull();
    // in good time: post it by the send-by date
    const early = { ...late, computation: { ...receipt, warnings: [] } };
    expect(postTooLate(early)).toBe(false);
    expect(actionFromItem(early, { today: TODAY })!).toMatchObject({ dateRole: "send_by", actionDate: "2026-09-28", dueDate: "2026-09-29" });
    expect(SENDING_TIME_PASSED).toBe("The usual sending time has passed");
  });
});
