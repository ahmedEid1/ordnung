import { describe, expect, it } from "vitest";
import type { Contract, Item, Suggestion } from "@/api/types";
import { createMockServer } from "@/mocks/server";
import { parsePrefill } from "@/features/letters/logic";
import type { Dashboard, Document } from "@/api/types";
import {
  actionFromContract,
  actionFromItem,
  agendaSentence,
  allClearTitle,
  buildCandidates,
  calendarIdea,
  composerHref,
  groupByWeek,
  greetingFor,
  ideaFigure,
  pickTopThree,
  selectIdeas,
  stripGreeting,
  urgencyScore,
  toPayWithin,
} from "./selection";

const TODAY = "2026-09-28"; // Monday

let seq = 0;
function item(p: Partial<Item> & Pick<Item, "kind" | "title">): Item {
  seq += 1;
  return {
    id: p.id ?? `itm_${seq}`,
    description: null,
    action: null,
    consequence: null,
    due_date: null,
    due_time: null,
    send_by: null,
    date_spec: null,
    computation: null,
    amount: null,
    currency: null,
    direction: null,
    recurrence: null,
    status: "open",
    snoozed_until: null,
    priority: "normal",
    area: "other",
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
    ...p,
  };
}

function contract(p: Partial<Contract> & Pick<Contract, "id" | "name">): Contract {
  return {
    party_id: null,
    case_id: null,
    category: "mobile",
    customer_number: null,
    concluded_date: null,
    start_date: null,
    initial_term_months: null,
    renewal_term_months: null,
    notice_value: null,
    notice_unit: null,
    notice_basis: null,
    end_date: null,
    is_basic_supply: false,
    cost_amount: null,
    cost_currency: "EUR",
    cost_interval: null,
    is_consumer: true,
    status: "active",
    computed: null,
    source_doc_id: null,
    evidence: [],
    area: "home",
    cancellable: true,
    cancel_hint: null,
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:00:00Z",
    ...p,
  };
}

function idea(p: Partial<Suggestion> & Pick<Suggestion, "id" | "kind" | "title">): Suggestion {
  return {
    body: "",
    rationale: null,
    priority: "normal",
    status: "new",
    snoozed_until: null,
    fingerprint: p.id,
    refs: [],
    action: null,
    source: "rule",
    rule_id: null,
    savings_estimate: null,
    due_date: null,
    created_at: "2026-09-20T10:00:00Z",
    updated_at: "2026-09-20T10:00:00Z",
    ...p,
  };
}

const ctx = { today: TODAY };

describe("actions from to-dos & dates", () => {
  it("uses the send-by date as the action date and keeps the must-arrive date", () => {
    const a = actionFromItem(
      item({ kind: "deadline", title: "Cancel phone", due_date: "2026-10-14", send_by: "2026-10-08", contract_id: "ctr_phone" }),
      ctx,
    )!;
    expect(a.actionDate).toBe("2026-10-08");
    expect(a.dueDate).toBe("2026-10-14");
    expect(a.dateRole).toBe("send_by");
    expect(a.daysLeft).toBe(10);
    expect(a.verb).toBe("draft");
    expect(a.draftKind).toBe("cancellation");
  });

  it("chooses one verb by kind: Pay · Draft letter · Mark done · Check · Open", () => {
    const verb = (p: Partial<Item> & Pick<Item, "kind" | "title">) => actionFromItem(item({ due_date: "2026-10-01", ...p }), ctx)!.verb;
    expect(verb({ kind: "payment", title: "Pay rent" })).toBe("pay");
    expect(verb({ kind: "payment", title: "Refund", direction: "in" })).toBe("open");
    expect(verb({ kind: "task", title: "Return books" })).toBe("done");
    expect(verb({ kind: "appointment", title: "Dentist" })).toBe("open");
    expect(
      verb({
        kind: "deadline",
        title: "Objection",
        date_spec: {
          type: "relative",
          date: null,
          time: null,
          anchor: "deemed_delivery",
          anchor_date: null,
          amount: 1,
          unit: "months",
          delivery_rule: "de_admin_post",
          shift_rule: "auto",
          nature: "objection",
          legal_basis: null,
          text: "",
        },
      }),
    ).toBe("draft");
    // an unconfirmed date always asks for a check first — even for a payment
    expect(verb({ kind: "payment", title: "Parking fine", grounding: "unverified" })).toBe("check");
  });

  it("flags items from letters that need review, with the letter's warning as the reason", () => {
    const a = actionFromItem(item({ kind: "payment", title: "Pay fine", due_date: "2026-09-29", doc_id: "doc_p" }), {
      today: TODAY,
      reviewDocs: [{ id: "doc_p", warnings: ["We don't know when this letter arrived."] }],
    })!;
    expect(a.needsCheck).toBe(true);
    expect(a.verb).toBe("check");
    expect(a.reason).toBe("We don't know when this letter arrived.");
  });

  it("skips done, dismissed, undated and still-snoozed items but includes snoozes that ended", () => {
    expect(actionFromItem(item({ kind: "task", title: "x", due_date: "2026-10-01", status: "done" }), ctx)).toBeNull();
    expect(actionFromItem(item({ kind: "task", title: "x", due_date: "2026-10-01", status: "dismissed" }), ctx)).toBeNull();
    expect(actionFromItem(item({ kind: "task", title: "x" }), ctx)).toBeNull();
    expect(actionFromItem(item({ kind: "task", title: "x", due_date: "2026-10-01", status: "snoozed", snoozed_until: "2026-10-02" }), ctx)).toBeNull();
    expect(actionFromItem(item({ kind: "task", title: "x", due_date: "2026-10-01", status: "snoozed", snoozed_until: "2026-09-27" }), ctx)).not.toBeNull();
  });

  it("scores overdue, urgent, important and unconfirmed dates as more urgent", () => {
    const base = { daysLeft: 5, priority: "normal" as const, needsCheck: false, kind: "task" as const };
    expect(urgencyScore({ ...base, daysLeft: -1 })).toBeLessThan(urgencyScore(base));
    expect(urgencyScore({ ...base, priority: "high" })).toBeLessThan(urgencyScore(base));
    expect(urgencyScore({ ...base, needsCheck: true })).toBeLessThan(urgencyScore(base));
    expect(urgencyScore({ ...base, kind: "deadline" })).toBeLessThan(urgencyScore(base));
  });
});

describe("contract decisions", () => {
  const phone = contract({
    id: "ctr_phone",
    name: "FunkNetz Allnet L",
    party_id: "pty_funk",
    computed: {
      regime: "tkg56",
      current_term_end: "2026-11-14",
      cancel_by: "2026-10-14",
      send_by: "2026-10-08",
      safe_date: null,
      confidence: "high",
      warnings: [],
      next_renewal: null,
      earliest_exit: "2026-11-14",
      summary: "Minimum term ends Sat 14 Nov.",
      notes: [],
      steps: [],
      rule_ids: [],
    },
  });

  it("uses send_by for contracts ('send by Thu 8 Oct') and offers a cancellation letter", () => {
    const a = actionFromContract(phone, ctx)!;
    expect(a.actionDate).toBe("2026-10-08");
    expect(a.dateRole).toBe("send_by");
    expect(a.dueDate).toBe("2026-10-14");
    expect(a.verb).toBe("draft");
    expect(a.draftKind).toBe("cancellation");
  });

  it("asks to check a contract's uncertain dates — not a notice period the person entered (R2-inbox-timeline-contracts-1)", () => {
    const low = { ...phone, computed: { ...phone.computed!, regime: "as_written" as const, confidence: "low" as const } };
    expect(actionFromContract(low, ctx)!.needsCheck).toBe(true);
    const entered = { doc_id: "doc_phone", page: null, quote: "one month's notice to the end of a month", grounding: "user" as const, value_consistent: true, score: 0, boxes: [] };
    expect(actionFromContract({ ...low, evidence: [entered] }, ctx)!.needsCheck).toBe(false);
  });

  it("ignores inactive contracts and passed decision dates", () => {
    expect(actionFromContract({ ...phone, status: "cancelled" }, ctx)).toBeNull();
    expect(actionFromContract({ ...phone, cancellable: false, cancel_hint: "Required by law." }, ctx)).toBeNull();
    expect(actionFromContract(phone, { today: "2026-10-20" })).toBeNull();
  });

  it("does not list a decision twice when a to-do already covers the contract", () => {
    const todo = item({ kind: "deadline", title: "Cancel phone", due_date: "2026-10-14", send_by: "2026-10-08", contract_id: "ctr_phone" });
    const all = buildCandidates({ attention: [todo], upcoming: [], decisions: [phone] }, ctx);
    expect(all.map((a) => a.key)).toEqual([`item:${todo.id}`]);
    const withoutTodo = buildCandidates({ attention: [], upcoming: [], decisions: [phone] }, ctx);
    expect(withoutTodo.map((a) => a.key)).toEqual(["contract:ctr_phone"]);
  });
});

describe("Top 3 this week", () => {
  const mk = (p: Partial<Item> & Pick<Item, "kind" | "title">) => item(p);

  it("orders by urgency and takes three", () => {
    const later = mk({ kind: "payment", title: "Later", due_date: "2026-10-09" });
    const soon = mk({ kind: "payment", title: "Soon", due_date: "2026-09-30" });
    const overdue = mk({ kind: "task", title: "Overdue", due_date: "2026-09-25" });
    const mid = mk({ kind: "task", title: "Mid", due_date: "2026-10-03" });
    const top = pickTopThree(buildCandidates({ attention: [later, soon, overdue, mid], upcoming: [], decisions: [] }, ctx));
    expect(top.map((a) => a.title)).toEqual(["Overdue", "Soon", "Mid"]);
  });

  it("puts an unconfirmed, important date first even if another is a day earlier", () => {
    const fine = mk({ kind: "payment", title: "Parking fine", due_date: "2026-09-30", priority: "high", grounding: "unverified" });
    const books = mk({ kind: "task", title: "Books", due_date: "2026-09-29" });
    const top = pickTopThree(buildCandidates({ attention: [books, fine], upcoming: [], decisions: [] }, ctx));
    expect(top[0]!.title).toBe("Parking fine");
  });

  it("keeps one action per person or organisation", () => {
    const fee = mk({ kind: "payment", title: "Library fee", due_date: "2026-10-02", party_id: "pty_lib" });
    const books = mk({ kind: "task", title: "Return books", due_date: "2026-10-02", party_id: "pty_lib" });
    const rent = mk({ kind: "payment", title: "Rent", due_date: "2026-10-05", party_id: "pty_home" });
    const top = pickTopThree(buildCandidates({ attention: [fee, books, rent], upcoming: [], decisions: [] }, ctx));
    expect(top.map((a) => a.title)).toEqual(["Library fee", "Rent"]);
  });

  it("only picks actions within the horizon (overdue always counts)", () => {
    const far = mk({ kind: "payment", title: "Far", due_date: "2026-11-30" });
    const old = mk({ kind: "payment", title: "Old", due_date: "2026-09-01" });
    const top = pickTopThree(buildCandidates({ attention: [], upcoming: [far, old], decisions: [] }, ctx));
    expect(top.map((a) => a.title)).toEqual(["Old"]);
  });

  it("returns nothing when nothing is due (→ 'All clear' state)", () => {
    expect(pickTopThree([])).toEqual([]);
  });

  it("matches the demo: parking fine, TechMarkt reminder, library fee", async () => {
    const srv = createMockServer({ staticDemo: false, latency: 0 });
    const get = async <T,>(path: string, q = "") => (await (await srv.handle("GET", path, new URLSearchParams(q), undefined)).json()) as T;
    const dash = await get<Dashboard>("/dashboard");
    const review = await get<Document[]>("/documents", "status=needs_review");
    const all = buildCandidates(dash, { today: dash.today, reviewDocs: review });
    const top = pickTopThree(all);
    expect(top.map((a) => a.key)).toEqual(["item:itm_parking", "item:itm_tm_dunning", "item:itm_library_fee"]);
    expect(top.map((a) => a.verb)).toEqual(["check", "pay", "pay"]);
    // the phone decision is next week — it stays in "Coming up" with its send-by date
    const phone = all.find((a) => a.key === "item:itm_phone_cancel")!;
    expect(phone.actionDate).toBe("2026-10-08");
    expect(phone.verb).toBe("draft");
  });
});

describe("Coming up · grouped by week", () => {
  it("groups Monday-first weeks with labels and payment totals", () => {
    const groups = groupByWeek(
      [
        { date: "2026-09-25", amount: 10, outgoing: true },
        { date: "2026-09-30", amount: 94.99, outgoing: true },
        { date: "2026-10-04", amount: 5, outgoing: false },
        { date: "2026-10-05", amount: 640, outgoing: true },
        { date: "2026-10-14", amount: 93, outgoing: true },
        { date: "2026-11-30", amount: 1, outgoing: true },
      ],
      TODAY,
    );
    // later weeks are named by their days, not "Week of 12 Oct 12 – 18 Oct"
    expect(groups.map((g) => g.label)).toEqual(["Overdue", "This week", "Next week", "12 – 18 Oct"]);
    expect(groups.map((g) => g.range)).toEqual(["", "28 Sep – 4 Oct", "5 – 11 Oct", ""]);
    expect(groups[1]!.totals).toEqual({ EUR: 94.99 });
    expect(groups[2]!.totals).toEqual({ EUR: 640 });
    expect(groups.flatMap((g) => g.entries).some((e) => e.date === "2026-11-30")).toBe(false);
  });
});

describe("Ideas", () => {
  const ideas = [
    idea({ id: "s_cal", kind: "hygiene", title: "3 new dates", rule_id: "calendar_outdated" }),
    idea({ id: "s_dup", kind: "risk", title: "Pay TechMarkt", priority: "high", refs: [{ type: "item", id: "itm_tm" }] }),
    idea({ id: "s_save", kind: "saving", title: "Ticket twice", savings_estimate: 756 }),
    idea({ id: "s_phone", kind: "deadline", title: "Phone", priority: "high" }),
    idea({ id: "s_scam", kind: "scam", title: "Scam", priority: "critical", refs: [{ type: "item", id: "itm_tm" }] }),
    idea({ id: "s_old", kind: "info", title: "Old", status: "dismissed" }),
    idea({ id: "s_new", kind: "risk", title: "Newer", created_at: "2026-09-28T09:00:00Z" }),
  ];

  it("shows at most three new Ideas, scams first, without repeating Top 3 or the calendar card", () => {
    const { shown, more } = selectIdeas(ideas, { shownItemIds: new Set(["itm_tm"]) });
    expect(shown.map((s) => s.id)).toEqual(["s_scam", "s_phone", "s_new"]);
    expect(more.map((s) => s.id)).toEqual(["s_save"]);
    expect(calendarIdea(ideas)?.id).toBe("s_cal");
  });

  it("labels savings as savings and price increases as extra cost (never 'savings')", () => {
    expect(ideaFigure({ kind: "saving", savings_estimate: 756 })).toEqual({ tone: "ok", label: "Could save about €756 a year" });
    expect(ideaFigure({ kind: "risk", savings_estimate: 84 })!.label).toBe("+€84.00/year extra cost");
    expect(ideaFigure({ kind: "risk", savings_estimate: null })).toBeNull();
  });

  it("links to the letters composer with the target prefilled", () => {
    expect(composerHref("cancellation", { contractId: "ctr_x" })).toBe("/letters?kind=cancellation&contract=ctr_x");
    expect(composerHref("objection", { docId: "doc_tax" })).toBe("/letters?kind=objection&doc=doc_tax");
    // the recipient goes in `to=` — what the composer reads (`party=` would open the People drawer)
    const reply = composerHref("general_reply", { partyId: "pty_x" });
    expect(reply).toBe("/letters?kind=general_reply&to=pty_x");
    expect(parsePrefill(new URL(reply, "http://x").searchParams)).toEqual({ kind: "general_reply", contractId: null, docId: null, partyId: "pty_x" });
  });
});

describe("words", () => {
  it("greets by time of day", () => {
    expect(greetingFor(7)).toBe("Good morning");
    expect(greetingFor(13)).toBe("Good afternoon");
    expect(greetingFor(21)).toBe("Good evening");
    expect(greetingFor(2)).toBe("Good evening");
  });

  it("strips a leading greeting from the note but keeps the rest", () => {
    expect(stripGreeting("Good morning, Sam. Two small payments this week.")).toBe("Two small payments this week.");
    expect(stripGreeting("Two small payments this week.")).toBe("Two small payments this week.");
  });

  it("says 'All clear until Friday' for a date within the week", () => {
    expect(allClearTitle("2026-10-02", TODAY)).toBe("All clear until Friday");
    expect(allClearTitle("2026-10-14", TODAY)).toBe("All clear until Wed 14 Oct");
    expect(allClearTitle(null, TODAY)).toBe("All clear");
  });

  it("builds a fallback note from the ledger only", () => {
    const fine = actionFromItem(item({ kind: "payment", title: "Pay the parking fine", due_date: "2026-09-29", amount: 30, grounding: "unverified" }), ctx)!;
    const tm = actionFromItem(item({ kind: "payment", title: "Pay TechMarkt reminder", due_date: "2026-09-30", amount: 94.99 }), ctx)!;
    const text = agendaSentence([fine, tm], [], TODAY);
    expect(text).toBe(
      "Two things this week: pay the parking fine (€30.00) by tomorrow; and pay TechMarkt reminder (€94.99) by Wednesday. One date needs a quick check from you.",
    );
    expect(agendaSentence([], [], TODAY)).toMatch(/^Nothing needs you right now/);
  });

  it("never says 'nothing needs you' while letters from the folder wait unread", () => {
    expect(agendaSentence([], [], TODAY, 2)).toBe("Nothing due from the letters that were read. 2 letters from your folder aren't read yet.");
    const tm = actionFromItem(item({ kind: "payment", title: "Pay TechMarkt reminder", due_date: "2026-09-30", amount: 94.99 }), ctx)!;
    expect(agendaSentence([tm], [], TODAY, 1)).toMatch(/by Wednesday\. One letter from your folder isn't read yet\.$/);
  });
});

describe("Ideas that came with new mail", () => {
  it("are pinned on top even when a scam or a more urgent Idea exists", () => {
    const list = [
      idea({ id: "s_scam", kind: "scam", title: "Scam", priority: "critical" }),
      idea({ id: "s_old", kind: "risk", title: "Old", priority: "critical" }),
      idea({ id: "s_price", kind: "deadline", title: "Price increase", priority: "normal" }),
    ];
    const { shown } = selectIdeas(list, { pinnedIds: new Set(["s_price"]) });
    expect(shown.map((s) => s.id)).toEqual(["s_price", "s_scam", "s_old"]);
  });
});

describe("money to pay", () => {
  it("counts every outgoing payment of the next 30 days, Top 3 included, but not old history", () => {
    const ctx = { today: "2026-09-28" };
    const pay = (id: string, due: string, amount: number, extra: Partial<Item> = {}) =>
      actionFromItem(item({ id, kind: "payment", title: id, due_date: due, amount, direction: "out", ...extra }), ctx)!;
    const actions = [
      pay("soon", "2026-09-29", 94.99),
      pay("debit", "2026-10-01", 63, { action: "Ensure sufficient funds for the SEPA direct debit." }),
      pay("later", "2026-11-15", 48),
      pay("ancient", "2025-10-01", 1560),
      pay("refund", "2026-10-10", 312.45, { direction: "in" }),
    ];
    expect(toPayWithin(actions)).toBe(157.99);
    // a direct debit is "collected", not "sent"
    expect(actions[1]!.dateRole).toBe("collected");
    expect(actions[0]!.dateRole).toBe("pay_by");
  });

  it("files a debit that failed under Pay, by its transfer date — the person pays it now", () => {
    const returned = actionFromItem(
      item({
        id: "returned",
        kind: "payment",
        title: "Rundfunkbeitrag nachzahlen – konnte nicht eingezogen werden",
        action: "Pay 49.99 € by 01.10.2026",
        due_date: "2026-10-01",
        send_by: "2026-09-29",
        amount: 49.99,
        direction: "out",
      }),
      { today: "2026-09-28" },
    )!;
    expect(returned.dateRole).toBe("transfer_by");
    expect(returned.actionDate).toBe("2026-09-29");
  });
});
