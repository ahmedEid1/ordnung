/**
 * Today's lower sections (UI audit round 1, today-b): Coming-up rows that say what is due without
 * repeating the date and never cut it to one line, week headings that read right, Ideas that keep
 * their "Show fewer" button and hand focus on (not to <body>), announce once, name what each
 * button is about and use the Top-3 Pay panel for "Pay", Recent letters in the order of the dates
 * they show with a way to all letters, a secretary's note in the app's date and money style, and whose letter a row
 * is when it is filed for someone of the household (a tag, never a filter).
 * jsdom has no layout; e2e/today-sections.spec.ts checks the real one.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import type { Brief, Household, Suggestion } from "@/api/types";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { contract, item } from "@/mocks/data/helpers";
import { makeTestQueryClient, renderWithProviders, TEST_TODAY } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { createMockServer } from "@/mocks/server";
import { ComingUp } from "./ComingUp";
import { comingUpMeta, ideaActionLabel, ideaHref, noteText, payActionFor, recentLetterDate, recentLetterMeta, sortRecentLetters } from "./helpers";
import { PartyDrawer } from "@/features/party/PartyDrawer";
import { RecentLetters } from "./RecentLetters";
import { actionFromContract, actionFromItem, type TodayAction } from "./selection";
import { TodayView } from "./TodayView";
import { TopThree } from "./TopThree";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const NBSP = " ";

async function renderToday(client = makeTestQueryClient()) {
  const user = userEvent.setup();
  renderWithProviders(
    <>
      <TodayView />
      <Toaster />
    </>,
    { client },
  );
  await screen.findByRole("region", { name: "Top 3 this week" });
  return { user };
}

function idea(over: Partial<Suggestion> & Pick<Suggestion, "id">): Suggestion {
  return {
    kind: "risk",
    title: "Pay the fee",
    body: "",
    rationale: null,
    priority: "normal",
    status: "new",
    rule_id: null,
    due_date: null,
    savings_estimate: null,
    refs: [],
    action: { type: "open", draft_kind: null, target_type: "document", target_id: "doc_fee", label: "Pay" },
    snoozed_until: null,
    created_at: "2026-09-28T06:00:00Z",
    updated_at: "2026-09-28T06:00:00Z",
    ...over,
  } as Suggestion;
}

// ------------------------------------------------------------------------------------------------
// Coming up
// ------------------------------------------------------------------------------------------------

describe("Coming up", () => {
  it("says what the date means and who it is with — the leaf already shows the day", () => {
    expect(comingUpMeta({ dateRole: "transfer_by", time: null }, { name: "Stadtwerke Musterstadt GmbH" })).toBe("Transfer · Stadtwerke Musterstadt GmbH");
    expect(comingUpMeta({ dateRole: "collected", time: null }, { name: "Muster BKK" })).toBe("Direct debit · Muster BKK");
    expect(comingUpMeta({ dateRole: "send_by", time: null }, undefined)).toBe("Send");
    expect(comingUpMeta({ dateRole: "on", time: "09:15:00" }, { name: "Zahnarztpraxis Dr. Anna Beispiel" })).toBe("09:15 · Zahnarztpraxis Dr. Anna Beispiel");
    expect(comingUpMeta({ dateRole: "due", time: null }, undefined)).toBe("");
  });

  it("rows keep two lines for the title and for who, with the full text on hover, and no date repeated", async () => {
    useMockApi();
    await renderToday();
    const coming = screen.getByRole("region", { name: /Coming up/ });
    const rows = within(coming).getAllByRole("link").filter((l) => l.dataset.part === "coming-row");
    expect(rows.length).toBeGreaterThan(2);
    for (const row of rows) {
      const title = row.querySelector("span.line-clamp-2")!;
      expect(title.getAttribute("title")).toBe(title.textContent);
      expect(title.className).not.toMatch(/(^|\s)(sm:)?line-clamp-1|truncate/);
      const meta = row.querySelector("[data-part=meta]");
      if (meta) {
        expect(meta.className).toContain("line-clamp-2");
        expect(meta.className).not.toContain("truncate");
        expect(meta.getAttribute("title")).toBe(meta.textContent);
        // "Transfer · Wohnbau…", never "Transfer by Thu 8 Oct · Wohn…"
        expect(meta.textContent).not.toMatch(/\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2}\b/);
      }
      // a roomy card: kind icon and an amount column; a phone-sized one: the amount leads the second line
      expect(row.querySelector("[aria-hidden=true].inline-grid")?.parentElement?.className).toBe("hidden @md:contents");
    }
    const paid = rows.find((r) => r.querySelector("[data-part=meta] .tabular-nums"));
    expect(paid, "a payment row").toBeTruthy();
    expect(paid!.querySelector("[data-part=meta] .tabular-nums")!.className).toContain("@md:hidden");
    expect(paid!.querySelector(":scope > .tabular-nums")!.className).toMatch(/hidden .*@md:inline/);
  });

  it("names a week with a space before its days, keeps the days together and lets the total wrap", async () => {
    useMockApi();
    await renderToday();
    const coming = screen.getByRole("region", { name: /Coming up/ });
    const weeks = within(coming).getAllByRole("heading", { level: 3 });
    expect(weeks.map((h) => h.textContent)).toContain("This week 28 Sep – 4 Oct");
    for (const h of weeks) {
      expect(h.textContent).not.toMatch(/^Week of|[a-z]\d/);
      const days = h.querySelector("span");
      if (days) expect(days.className).toContain("whitespace-nowrap");
      expect(h.parentElement!.className).toContain("flex-wrap");
    }
  });

  it("says 'Nothing else' only when Top 3 has something in these 30 days", () => {
    const partyById = new Map();
    const soon = actionFromItem(item({ id: "itm_a", kind: "payment", title: "Pay the fee", amount: 5, due_date: "2026-09-30" }), { today: TEST_TODAY })!;
    const { unmount } = renderWithProviders(<ComingUp actions={[]} all={[soon]} partyById={partyById} today={TEST_TODAY} />);
    expect(screen.getByText("Nothing else in the next 30 days.")).toBeInTheDocument();
    unmount();
    renderWithProviders(<ComingUp actions={[]} all={[]} partyById={partyById} today={TEST_TODAY} />);
    expect(screen.getByText("Nothing in the next 30 days.")).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------
// Ideas
// ------------------------------------------------------------------------------------------------

describe("Ideas", () => {
  it("'Pay' opens the Top-3 Pay panel when the page has that payment, else it says 'Open letter'", () => {
    const pay = idea({ id: "sug_fee" });
    const action = { verb: "pay", docId: "doc_fee" } as TodayAction;
    expect(payActionFor(pay, [action])).toBe(action);
    expect(payActionFor(pay, [{ ...action, docId: "doc_other" }])).toBeNull();
    expect(payActionFor(pay, [{ ...action, verb: "open" }])).toBeNull();
    expect(payActionFor(idea({ id: "s", action: { ...pay.action!, label: "Check the letter" } }), [action])).toBeNull();
    expect(ideaActionLabel(pay, { canPay: true })).toBe("Pay");
    expect(ideaActionLabel(pay)).toBe("Open letter");
    expect(ideaActionLabel(idea({ id: "s", action: { ...pay.action!, target_type: "contract" } }))).toBe("Open contract");
    expect(ideaActionLabel(idea({ id: "s", action: { ...pay.action!, label: "Check passport" } }))).toBe("Check passport");
  });

  it("“Answer” on a sender's state opens their details at the question (`state=ask`); other Ideas about a sender just open them", () => {
    const land = idea({
      id: "sug_land",
      kind: "deadline",
      rule_id: "sender_land",
      action: { type: "open", draft_kind: null, target_type: "party", target_id: "pty_techmarkt", label: "Answer" },
    });
    expect(ideaActionLabel(land)).toBe("Answer");
    expect(ideaHref(land)).toBe("?party=pty_techmarkt&state=ask");
    expect(ideaHref({ ...land, rule_id: "contract_review" })).toBe("?party=pty_techmarkt");
  });

  it("“See the documents” on the tax Idea opens that year's tax letters", () => {
    const tax = idea({
      id: "sug_tax",
      kind: "tax",
      rule_id: "tax_documents",
      action: { type: "open", draft_kind: null, target_type: "tax_year", target_id: "2025", label: "See the documents" },
    });
    expect(ideaActionLabel(tax)).toBe("See the documents");
    expect(ideaHref(tax)).toBe("/inbox/taxes?year=2025");
    expect(ideaHref({ ...tax, action: { ...tax.action!, target_id: "25/26" } })).toBe("/inbox/taxes");
  });

  it("“Write the letter” on a moving-checklist row opens a new-address letter to that sender, filled in", () => {
    const tell = idea({
      id: "sug_move",
      kind: "hygiene",
      rule_id: "moved_house",
      action: { type: "open", draft_kind: null, target_type: "party", target_id: "pty_funknetz", label: "Write the letter" },
    });
    expect(ideaHref(tell)).toBe("/letters?kind=address_change&to=pty_funknetz");
    // the row to register at the Bürgeramt acts in place
    expect(ideaHref({ ...tell, action: { type: "none", draft_kind: null, target_type: null, target_id: null, label: "Not needed" } })).toBeNull();
    // any other Idea about a sender still opens their details
    expect(ideaHref({ ...tell, rule_id: "contract_review" })).toBe("?party=pty_funknetz");
  });

  it("“Answer” takes the keyboard to the sender's State heading, not to Yes", async () => {
    const { srv } = useMockApi();
    srv.db.state.suggestions.unshift({
      ...srv.db.state.suggestions[0]!,
      id: "sug_land_funknetz",
      kind: "deadline",
      priority: "high",
      title: "Is FunkNetz Mobil GmbH in Berlin?",
      body: "12351 is on their letter.",
      status: "new",
      rule_id: "sender_land",
      refs: [{ type: "party", id: "pty_funknetz" }],
      action: { type: "open", draft_kind: null, target_type: "party", target_id: "pty_funknetz", label: "Answer" },
    });
    const user = userEvent.setup();
    const { router } = renderWithProviders(
      <>
        <TodayView />
        <PartyDrawer />
      </>,
    );
    const ideas = await screen.findByRole("region", { name: "Ideas from your secretary" });
    const card = within(ideas).getByRole("heading", { level: 3, name: "Is FunkNetz Mobil GmbH in Berlin?" }).closest("article")!;
    await user.click(within(card).getByRole("button", { name: "Answer" }));
    const drawer = await screen.findByRole("dialog", { name: "FunkNetz Mobil GmbH" });
    await waitFor(() => expect(within(drawer).getByRole("heading", { name: "State" })).toHaveFocus());
    expect(within(drawer).getByRole("group", { name: "Is FunkNetz Mobil GmbH in Berlin? (12351 on their letter)" })).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.search).toBe("?party=pty_funknetz"));
  });

  it("keeps its toggle, moves focus to the first new Idea, and says what changed once", async () => {
    useMockApi();
    const { user } = await renderToday();
    const ideas = screen.getByRole("region", { name: "Ideas from your secretary" });
    // the only section header with an icon — not any more
    expect(within(ideas).getByRole("heading", { level: 2 }).querySelector("svg")).toBeNull();
    const list = within(ideas).getByRole("list");
    expect(list).not.toHaveAttribute("aria-live");
    const before = within(ideas).getAllByRole("article").length;

    const more = within(ideas).getByRole("button", { name: /^Show \d+ more Ideas?$/ });
    const n = Number(/\d+/.exec(more.textContent!)![0]);
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more).toHaveAttribute("aria-controls", list.id);
    await user.click(more);

    const fewer = within(ideas).getByRole("button", { name: "Show fewer Ideas" });
    expect(fewer).toBe(more); // the same button, still there (focus doesn't fall to <body>)
    expect(fewer).toHaveAttribute("aria-expanded", "true");
    const cards = within(ideas).getAllByRole("article");
    expect(cards).toHaveLength(before + n);
    await waitFor(() => expect(document.activeElement).toBe(within(cards[before]!).getByRole("heading", { level: 3 })));
    expect(within(ideas).getByText(n === 1 ? "1 more Idea shown" : `${n} more Ideas shown`)).toHaveAttribute("aria-live", "polite");

    await user.click(fewer);
    await waitFor(() => expect(within(ideas).getAllByRole("article")).toHaveLength(before));
    expect(fewer).toHaveAttribute("aria-expanded", "false");
    expect(within(ideas).getByText(`Showing ${before} Ideas`)).toBeInTheDocument();
  });

  it("each button says which Idea it is about; one 'New' badge; the whole body behind Read more", async () => {
    useMockApi();
    await renderToday();
    const ideas = screen.getByRole("region", { name: "Ideas from your secretary" });
    for (const card of within(ideas).getAllByRole("article")) {
      const title = within(card).getByRole("heading", { level: 3 }).textContent!;
      for (const b of within(card).getAllByRole("button")) {
        if (b.getAttribute("aria-expanded") !== null) continue; // Read more
        expect(b).toHaveAccessibleDescription(title);
      }
      expect(within(card).queryByText("New today")).toBeNull();
      expect(within(card).queryAllByText("New").length).toBeLessThanOrEqual(1);
      const body = card.querySelector("h3 + p")!;
      expect(body.className).toContain("line-clamp-4");
      expect(body.className).not.toContain("line-clamp-3");
    }
  });

  it("after 'Not relevant', focus goes to the Idea now in its place", async () => {
    useMockApi();
    const { user } = await renderToday();
    const ideas = screen.getByRole("region", { name: "Ideas from your secretary" });
    const [first, second] = within(ideas).getAllByRole("article");
    const next = within(second!).getByRole("heading", { level: 3 }).textContent!;
    const gone = within(first!).getByRole("heading", { level: 3 }).textContent!;
    await user.click(within(first!).getByRole("button", { name: "Not relevant" }));
    await waitFor(() => expect(within(ideas).queryByRole("heading", { name: gone })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(within(ideas).getByRole("heading", { level: 3, name: next })));
  });

  it("hides the Idea, says so and moves focus on even when the Idea leaves before every list is refreshed (review round 4)", async () => {
    useMockApi();
    // the note is refreshed last: the Idea leaves with the refreshed list before the call is done — its own
    // callbacks never ran in a card that had gone, so there was no "Idea hidden", no Undo and focus was lost
    const answer = globalThis.fetch;
    let release = () => undefined as void;
    const held = new Promise<void>((resolve) => (release = resolve));
    let hidden = false;
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if ((init?.method ?? "GET").toUpperCase() === "PATCH") hidden = true;
      else if (hidden && url.includes("/brief")) await held;
      return answer(input, init);
    });
    const { user } = await renderToday();
    const ideas = screen.getByRole("region", { name: "Ideas from your secretary" });
    const [first, second] = within(ideas).getAllByRole("article");
    const next = within(second!).getByRole("heading", { level: 3 }).textContent!;
    const gone = within(first!).getByRole("heading", { level: 3 }).textContent!;
    await user.click(within(first!).getByRole("button", { name: "Not relevant" }));
    await waitFor(() => expect(within(ideas).queryByRole("heading", { name: gone })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(within(ideas).getByRole("heading", { level: 3, name: next })));
    release();
    expect(await screen.findByText("Idea hidden")).toBeInTheDocument();
  });

  it("an Idea about a Top-3 payment opens the same Pay panel", async () => {
    const { srv } = useMockApi();
    // the TechMarkt Idea no longer points at the Top-3 to-do, so it isn't filtered out as a repeat
    const tm = srv.db.state.suggestions.find((s) => s.id === "sug_techmarkt")!;
    tm.refs = tm.refs.filter((r) => r.type !== "item");
    const { user } = await renderToday();
    const ideas = screen.getByRole("region", { name: "Ideas from your secretary" });
    const card = within(ideas).getByRole("heading", { level: 3, name: /TechMarkt/ }).closest("article")!;
    await user.click(within(card).getByRole("button", { name: "Pay" }));
    const panel = await screen.findByRole("dialog", { name: /^Pay: TechMarkt reminder/ });
    expect(await within(panel).findByRole("button", { name: "Mark as paid" })).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------------------------------
// Recent letters
// ------------------------------------------------------------------------------------------------

describe("Recent letters", () => {
  it("says a letter's status in words on phones too — under the letter, beside it in a roomier card", async () => {
    const user = userEvent.setup();
    const srv = createMockServer({ staticDemo: false, latency: 0 });
    const docs = srv.db.state.documents.slice(0, 3).map((d, i) => ({ ...d, status: i === 0 ? ("needs_review" as const) : ("processed" as const) }));
    renderWithProviders(<RecentLetters docs={docs} partyById={new Map()} />);
    await user.click(screen.getByRole("button", { name: /^Recent letters/ }));
    const rows = screen.getAllByRole("listitem");
    const pills = within(rows.find((r) => r.textContent?.includes(docs[0]!.title ?? docs[0]!.filename))!).getAllByText("Please check");
    expect(pills.map((p) => p.closest("[class*='@md:']")!.className)).toEqual([expect.stringContaining("@md:hidden"), expect.stringContaining("hidden")]);
    expect(pills[1]!.closest("[class*='@md:']")!.className).toContain("@md:inline-flex");
    for (const row of rows.filter((r) => !r.textContent?.includes(docs[0]!.title ?? docs[0]!.filename))) expect(within(row).queryByText("Please check")).toBeNull();
  });

  it("lists letters by the day each one shows, newest first", () => {
    const d = (id: string, received: string | null, doc: string | null, created = "2026-09-28T06:00:00Z") => ({ id, received_date: received, doc_date: doc, created_at: created });
    const sorted = sortRecentLetters([d("a", "2026-09-20", null), d("b", "2026-09-21", "2026-09-18"), d("c", null, "2026-09-25"), d("d", null, null, "2026-09-22T09:00:00Z")]);
    expect(sorted.map((x) => x.id)).toEqual(["c", "d", "b", "a"]);
    expect(recentLetterDate(sorted[1]!)).toBe("2026-09-22");
  });

  it("the heading is only 'Recent letters · N'; the latest is its description; 'All letters' goes to the inbox", async () => {
    useMockApi();
    const { user } = await renderToday();
    const heading = screen.getByRole("heading", { level: 2, name: /^Recent letters · \d+$/ });
    const toggle = within(heading).getByRole("button");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAccessibleDescription(/^Latest: /);
    const section = heading.closest("section")!;
    expect(within(section).getByRole("link", { name: "All letters" })).toHaveAttribute("href", "/inbox");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const list = within(section).getByRole("list");
    const days = within(list)
      .getAllByRole("listitem")
      .map((li) => li.querySelector("time")!.getAttribute("datetime")!);
    expect(days).toEqual([...days].sort().reverse());
    for (const li of within(list).getAllByRole("listitem")) {
      const title = li.querySelector("a > span > span")!;
      expect(title.className).toContain("line-clamp-2");
      expect(title.className).not.toContain("truncate");
      expect(title).toHaveAttribute("title", title.textContent);
    }
  });
});

// ------------------------------------------------------------------------------------------------
// The secretary's note
// ------------------------------------------------------------------------------------------------

describe("the secretary's note", () => {
  it("writes dates and money the app's way, whoever wrote the note", () => {
    const out = noteText("the Deutschlandticket (63,00 €) on 30 September and two payments by Thu 1 Oct: library fees 4,50 € and €30.00", "2026-09-28");
    expect(out).toBe(`the Deutschlandticket (€63.00) on Wed${NBSP}30${NBSP}Sep and two payments by Thu${NBSP}1${NBSP}Oct: library fees €4.50 and €30.00`);
    expect(noteText("by Tuesday, 29 September", "2026-09-28")).toBe(`by Tue${NBSP}29${NBSP}Sep`);
    expect(noteText("expires 10 February 2027", "2026-09-28")).toBe(`expires Wed${NBSP}10${NBSP}Feb${NBSP}2027`);
    // near the turn of the year, a date without a year is the nearest one
    expect(noteText("due 5 January", "2026-12-20")).toBe(`due Tue${NBSP}5${NBSP}Jan${NBSP}2027`);
    // a weekday that doesn't match, or a day that doesn't exist, stays as written (glued, not rewritten)
    expect(noteText("on Monday 29 September", "2026-09-28")).toBe(`on Monday${NBSP}29${NBSP}September`);
    expect(noteText("on 31 September", "2026-09-28")).toBe(`on 31${NBSP}September`);
  });

  it("shows the note in that style, amounts and days in bold, and a 24 px 'Read more'", async () => {
    useMockApi();
    const client = makeTestQueryClient();
    const brief: Brief = {
      text: "Sam, your first priority is paying TechMarkt 94,99 € by Tue 29 Sep. This week you also have the Deutschlandticket (€63.00) on 30 September and the library fees €4.50 by Thu 1 Oct — so get that sorted.",
      source: "llm",
      date: TEST_TODAY,
      generated_at: "2026-09-28T06:13:00Z",
    } as Brief;
    client.setQueryData(qk.brief, brief);
    await renderToday(client);
    const note = screen.getByRole("region", { name: "Your secretary's note" });
    const bold = Array.from(note.querySelectorAll("strong")).map((s) => s.textContent);
    expect(bold).toEqual(["€94.99", `Tue${NBSP}29${NBSP}Sep`, "€63.00", `Wed${NBSP}30${NBSP}Sep`, "€4.50", `Thu${NBSP}1${NBSP}Oct`]);
    const more = within(note).getByRole("button", { name: "Read more" });
    expect(more.className).toMatch(/inline-flex/);
    expect(more.className).toMatch(/min-h-6/);
    expect(document.getElementById(more.getAttribute("aria-controls")!)).toHaveTextContent(/^Sam, your first priority/);
  });
});

// ------------------------------------------------------------------------------------------------
// Whose letter it is (your household, ADR 0023): a tag on a row, never a filter
// ------------------------------------------------------------------------------------------------

const ALEX = { id: "hhm_alex000000001", name: "Alex Rivera", signs: true, letters: 1 };
const MIA = { id: "hhm_mia0000000001", name: "Mia Rivera", signs: false, letters: 1 };

/** A test client that has the household, as if `GET /api/household` had answered: `filed` is letter id → person id. */
function withHousehold(filed: Record<string, string>, client = makeTestQueryClient()) {
  const household: Household = { members: [ALEX, MIA], filed, mine: [], suggested: {}, version: "0123456789abcdef" };
  client.setQueryData(qk.household, household);
  return client;
}

describe("whose letter it is", () => {
  it("a Coming-up row's second line, and a recent letter's, start with who the letter is filed for", () => {
    expect(comingUpMeta({ dateRole: "transfer_by", time: null }, { name: "Stadtwerke Musterstadt GmbH" }, "Alex Rivera")).toBe(
      "For Alex Rivera · Transfer · Stadtwerke Musterstadt GmbH",
    );
    expect(comingUpMeta({ dateRole: "due", time: null }, undefined, "Mia Rivera")).toBe("For Mia Rivera");
    expect(comingUpMeta({ dateRole: "send_by", time: null }, undefined, null)).toBe("Send");
    expect(recentLetterMeta({ kind: "invoice" }, { name: "TechMarkt GmbH" }, "Alex Rivera")).toBe("For Alex Rivera · TechMarkt GmbH · Invoice");
    expect(recentLetterMeta({ kind: null }, undefined, "Mia Rivera")).toBe("For Mia Rivera");
    expect(recentLetterMeta({ kind: "invoice" }, { name: "TechMarkt GmbH" }, null)).toBe("TechMarkt GmbH · Invoice");
  });

  it("tags the Coming-up rows of letters filed for someone — never a contract's, whose decision is the person's", () => {
    const ctx = { today: TEST_TODAY };
    const fee = actionFromItem(item({ id: "itm_fee", kind: "payment", title: "Pay the fee", amount: 5, due_date: "2026-10-02", doc_id: "doc_fee" }), ctx)!;
    const own = actionFromItem(item({ id: "itm_own", kind: "task", title: "Water the plants", due_date: "2026-10-03" }), ctx)!;
    const yours = actionFromItem(item({ id: "itm_yours", kind: "task", title: "Renew the passport", due_date: "2026-10-05", doc_id: "doc_yours" }), ctx)!;
    const phone = actionFromContract(
      contract({
        id: "ctr_phone",
        name: "FunkNetz Allnet L",
        category: "mobile",
        source_doc_id: "doc_phone",
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
      }),
      ctx,
    )!;
    renderWithProviders(<ComingUp actions={[fee, own, yours, phone]} partyById={new Map()} today={TEST_TODAY} />, {
      client: withHousehold({ doc_fee: ALEX.id, doc_phone: MIA.id }),
    });
    const meta = (title: string) => screen.getByText(title).closest("a")!.querySelector<HTMLElement>("[data-part=meta]");
    expect(meta("Pay the fee")!.textContent).toMatch(/^€5\.00 · For Alex Rivera · /);
    expect(meta("Pay the fee")!.title).toBe(meta("Pay the fee")!.textContent);
    // its letter is filed for Mia, but a contract's dates name no one (ADR 0025), as on the Timeline
    expect(meta("Decide on FunkNetz Allnet L")!.textContent).toBe("Send");
    expect(meta("Water the plants")?.textContent ?? "").not.toMatch(/For /);
    expect(meta("Renew the passport")?.textContent ?? "").not.toMatch(/For /);
  });

  it("tags a Top 3 card of a letter filed for someone — never a contract's", () => {
    const ctx = { today: TEST_TODAY };
    const fee = actionFromItem(item({ id: "itm_fee", kind: "payment", title: "Pay the fee", amount: 5, due_date: "2026-10-02", doc_id: "doc_fee" }), ctx)!;
    const phone = actionFromContract(
      contract({
        id: "ctr_phone",
        name: "FunkNetz Allnet L",
        category: "mobile",
        source_doc_id: "doc_phone",
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
      }),
      ctx,
    )!;
    renderWithProviders(<TopThree actions={[fee, phone]} next={undefined} partyById={new Map()} today={TEST_TODAY} />, {
      client: withHousehold({ doc_fee: ALEX.id, doc_phone: MIA.id }),
    });
    const card = (title: string) => screen.getByText(title).closest("article")!;
    expect(within(card("Pay the fee")).getByText("For Alex Rivera")).toBeInTheDocument();
    expect(card("Decide on FunkNetz Allnet L").querySelector("[data-person-tag]")).toBeNull();
    expect(within(card("Decide on FunkNetz Allnet L")).queryByText(/^For /)).toBeNull();
  });

  it("tags the recent letters filed for someone, the tag first on the row's second line", async () => {
    const user = userEvent.setup();
    const srv = createMockServer({ staticDemo: false, latency: 0 });
    const docs = srv.db.state.documents.slice(0, 3);
    const filed = docs[1]!;
    renderWithProviders(<RecentLetters docs={docs} partyById={new Map()} />, { client: withHousehold({ [filed.id]: ALEX.id }) });
    await user.click(screen.getByRole("button", { name: /^Recent letters/ }));
    const rows = screen.getAllByRole("listitem");
    const row = rows.find((r) => r.textContent?.includes(filed.title ?? filed.filename))!;
    const second = within(row).getByText(/^For Alex Rivera/);
    expect(second).toHaveAttribute("title", second.textContent);
    for (const other of rows.filter((r) => r !== row)) expect(within(other).queryByText(/^For /)).toBeNull();
  });

  it("Today has the tags but no filter: no choice of whose letters, no link to one person's", async () => {
    const { srv } = useMockApi();
    const filed = Object.fromEntries(srv.db.liveDocuments().map((d) => [d.id, ALEX.id]));
    await renderToday(withHousehold(filed));
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByText(/Whose letters/)).toBeNull();
    expect(screen.getAllByRole("link").filter((a) => /[?&]for=/.test(a.getAttribute("href") ?? ""))).toEqual([]);
    const coming = screen.getByRole("region", { name: /Coming up/ });
    expect(within(coming).getAllByText(/(^|· )For Alex Rivera( ·|$)/).length).toBeGreaterThan(0);
  });
});

describe("whose letter it is in the static demo", () => {
  it("tags Today's rows of the letters a visitor filed for someone, through the demo's own household", async () => {
    const { srv } = useMockApi({ staticDemo: true });
    const none = new URLSearchParams();
    const empty = (await (await srv.handle("GET", "/household", none, undefined)).json()) as Household;
    const added = (await (await srv.handle("PUT", "/household", none, { base: empty.version, members: [{ id: null, name: "Alex Rivera", signs: true }] })).json()) as Household;
    const letters = Object.fromEntries(srv.db.liveDocuments().map((d) => [d.id, added.members[0]!.id]));
    expect((await srv.handle("PATCH", "/household", none, { letters })).status).toBe(200);
    await renderToday();
    const coming = screen.getByRole("region", { name: /Coming up/ });
    expect((await within(coming).findAllByText(/(^|· )For Alex Rivera( ·|$)/)).length).toBeGreaterThan(0);
    expect(within(screen.getByRole("region", { name: "Top 3 this week" })).getAllByText("For Alex Rivera").length).toBeGreaterThan(0);
  });
});
