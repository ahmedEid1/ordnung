/**
 * The weekly session: one step at a time (URL state), Back / Next with the focus on the new step's
 * heading, Pay and Confirm right in the rows, "Finish" → "All clear until …"; Today's one prompt with
 * "Not now", and the quiet link afterwards; the static demo following what the visitor does.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/api/endpoints";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import type { WeekEntry, WeekStep, WeeklySession } from "@/api/types";
import { MOCK_WEEK, MOCK_WEEK_DEADLINES } from "@/mocks/data/numbers";
import { mockWeek, nextPromptDay } from "@/mocks/numbers";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { entryHref, sessionHighlights, stepCount } from "./steps";
import { WeekView, describeSession } from "./WeekView";
import { WeeklyLink, WeeklyPrompt } from "./WeeklyPrompt";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

async function renderWeek(route = "/week", steps = 7) {
  const user = userEvent.setup();
  const out = renderWithProviders(
    <>
      <WeekView />
      <Toaster />
    </>,
    { route },
  );
  await screen.findByText(new RegExp(`^Step \\d of ${steps}$`));
  return { user, ...out };
}

/** A row as `ordnung/secretary/week.py` writes one (the fields a test does not care about empty). */
function row(fields: Partial<WeekEntry> & Pick<WeekEntry, "key" | "title">): WeekEntry {
  return {
    ref: { type: "item", id: fields.key },
    kind: "deadline",
    date: null,
    date_role: null,
    due_date: null,
    amount: null,
    currency: null,
    party_id: null,
    party_name: null,
    doc_id: null,
    status: "open",
    note: null,
    tone: "neutral",
    overdue: false,
    item: null,
    ...fields,
  };
}

function withStep(week: WeeklySession, step: WeekStep): WeeklySession {
  return { ...week, steps: [step, ...week.steps.filter((s) => s.id !== step.id)] };
}

describe("steps", () => {
  it("say where each row leads and what is waiting", () => {
    expect(entryHref({ ref: { type: "document", id: "doc_a" }, doc_id: "doc_a" })).toBe("/documents/doc_a");
    expect(entryHref({ ref: { type: "item", id: "itm_a" }, doc_id: "doc_b" })).toBe("/documents/doc_b");
    expect(entryHref({ ref: { type: "item", id: "itm_a" }, doc_id: null })).toBe("/timeline");
    expect(entryHref({ ref: { type: "contract", id: "ctr_a" }, doc_id: null })).toBe("/contracts?contract=ctr_a");
    expect(entryHref({ ref: { type: "draft", id: "drf_a" }, doc_id: null })).toBe("/letters/drf_a");
    // a promise made on the phone is on the Waiting for page
    expect(entryHref({ ref: { type: "call", id: "cal_a" }, doc_id: null })).toBe("/letters/waiting");
    expect(stepCount({ entries: [], more: 3 })).toBe(3);
    // the FitWell cancellation was sent: it is listed to keep its proof, not counted as one to post; its
    // promised written confirmation is overdue (Waiting for); "to compare" with the letter, not "to check"
    expect(sessionHighlights(MOCK_WEEK)).toEqual(["1 overdue", "8 new letters", "2 to compare", "4 to pay", "1 to post", "2 decisions"]);
    // overdue first; a fee paid at an appointment is no transfer
    const pay = MOCK_WEEK.steps.find((s) => s.id === "pay")!;
    const week = {
      ...MOCK_WEEK,
      overdue: 2,
      steps: MOCK_WEEK.steps.map((s) => (s.id === "pay" ? { ...pay, entries: [...pay.entries, row({ key: "fee", title: "Fee", date_role: "at_appointment" })] } : s)),
    };
    expect(sessionHighlights(week).slice(0, 4)).toEqual(["2 overdue", "8 new letters", "2 to compare", "4 to pay"]);
  });

  it("the next prompt comes a week on, or on the first Sunday 4 days on", () => {
    expect(nextPromptDay("2026-09-28")).toBe("2026-10-04"); // Monday → Sunday
    expect(nextPromptDay("2026-09-30")).toBe("2026-10-04"); // Wednesday → Sunday (4 days)
    expect(nextPromptDay("2026-10-01")).toBe("2026-10-08"); // Thursday → a week on
  });
});

describe("the session page", () => {
  it("walks through the steps one at a time", async () => {
    useMockApi();
    const { user, router } = await renderWeek();
    expect(screen.getByText("Step 1 of 7")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    // the accessible name starts with the visible words (WCAG 2.5.3)
    const next = screen.getByRole("button", { name: "Next: Compare — Compare with the letter" });
    expect(next).toHaveTextContent(/^Next: Compare/);
    await user.click(next);
    const heading = await screen.findByRole("heading", { level: 2, name: "Compare with the letter" });
    expect(router.state.location.search).toBe("?step=check");
    await waitFor(() => expect(heading).toHaveFocus());
    expect(screen.getByText("Step 2 of 7")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByRole("heading", { level: 2, name: MOCK_WEEK.steps[0]!.title })).toBeInTheDocument();
  });

  it("pays and confirms right in the rows", async () => {
    useMockApi();
    const { user } = await renderWeek("/week?step=pay");
    const step = screen.getByRole("heading", { level: 2, name: "Pay this week" }).closest("section")!;
    expect(within(step).getByText("To transfer this week:")).toBeInTheDocument();
    await user.click(within(step).getByRole("button", { name: "Pay: Pay TechMarkt reminder" }));
    expect(await screen.findByRole("dialog", { name: /Pay/ })).toBeInTheDocument();
  });

  it("confirms a value read from a photo: the row leaves, the focus goes on to the next one", async () => {
    const { calls } = useMockApi();
    const { user } = await renderWeek("/week?step=check");
    // the accessible name starts with the visible words (WCAG 2.5.3: "click The date looks right" finds it)
    // the parking fine's date was read from a photo, and the passport's expiry too; the button says it
    // vouches for the date (the amount is compared in the Pay panel)
    const confirm = screen.getByRole("button", { name: "The date looks right: Pay the parking fine" });
    expect(confirm).toHaveTextContent("The date looks right");
    await user.click(confirm);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && /\/items\/.+\/confirm$/.test(c.path))).toBe(true));
    expect(await screen.findByText("Date confirmed")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: "The date looks right: Pay the parking fine" })).toBeNull());
    await waitFor(() => expect(screen.getByRole("link", { name: "Passport expires" })).toHaveFocus());
  });

  it("marks a transfer paid: the row leaves, the focus goes on to the next one (not to the page)", async () => {
    const { calls } = useMockApi();
    const { user } = await renderWeek("/week?step=pay");
    const step = screen.getByRole("heading", { level: 2, name: "Pay this week" }).closest("section")!;
    const [first, second] = within(step).getAllByRole("link");
    await user.click(within(step).getByRole("button", { name: `Pay: ${first!.textContent}` }));
    const dialog = await screen.findByRole("dialog", { name: /Pay/ });
    await user.click(await within(dialog).findByRole("button", { name: "Mark as paid" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && /\/items\//.test(c.path))).toBe(true));
    await waitFor(() => expect(screen.queryByRole("link", { name: first!.textContent! })).toBeNull());
    await waitFor(() => expect(screen.getByRole("link", { name: second!.textContent! })).toHaveFocus());
    expect(document.activeElement).not.toBe(document.body);
  });

  it("says money coming in is expected, never to pay", async () => {
    useMockApi();
    const refund = row({ key: "refund", title: "Tax refund", kind: "payment", date: "2026-09-25", date_role: "expected", amount: 312 });
    const check = MOCK_WEEK.steps.find((s) => s.id === "check")!;
    vi.spyOn(api, "week").mockResolvedValue({ ...MOCK_WEEK, steps: MOCK_WEEK.steps.map((s) => (s.id === "check" ? { ...check, entries: [refund] } : s)) });
    await renderWeek("/week?step=check");
    const when = screen.getByText("Expected").closest("time")!;
    expect(when).toHaveTextContent("Expected Fri 25 Sep · 3 days ago");
    expect(when).not.toHaveAttribute("data-urgency", "danger");
    expect(screen.queryByText(/Pay by|overdue/)).toBeNull();
  });

  it("words each row's day as Today does", async () => {
    useMockApi();
    const today = MOCK_WEEK.today;
    const step: WeekStep = {
      id: "decide",
      title: "Decide in the next 30 days",
      summary: "4 decisions",
      more: 0,
      total: null,
      total_other_currencies: {},
      entries: [
        row({ key: "obj", title: "Object (Widerspruch)", date: today, date_role: "act_today", due_date: "2026-09-30" }),
        row({ key: "post", title: "Post the objection", date: "2026-10-08", date_role: "send_by", due_date: "2026-10-14" }),
        row({ key: "dentist", title: "Dental check-up", kind: "appointment", date: "2026-10-08", date_role: "on" }),
        row({ key: "passport", title: "Passport", kind: "expiry", date: "2027-02-10", date_role: "expires" }),
      ],
    };
    vi.spyOn(api, "week").mockResolvedValue(withStep(MOCK_WEEK, step));
    await renderWeek("/week");
    // the day to act is today: no countdown to the due date beside it ("in 2 days")
    const act = screen.getByText("Act today").parentElement!;
    expect(act).toHaveTextContent(/^Act today — due Wed 30 Sep$/);
    expect(act.querySelector("time")).toHaveAttribute("dateTime", "2026-09-30");
    expect(screen.getByText("Send by")).toBeInTheDocument();
    expect(screen.getByText("due Wed 14 Oct")).toBeInTheDocument();
    expect(screen.getByText("Expires")).toBeInTheDocument();
    expect(screen.queryByText("Due")).toBeNull(); // no "Due" for an appointment or an expiry
  });

  it("a fee paid at the appointment has no Pay button", async () => {
    useMockApi();
    const pay = MOCK_WEEK.steps.find((s) => s.id === "pay")!;
    const fee = row({ key: "fee", title: "Fee for the extension", kind: "payment", date: "2026-10-14", date_role: "at_appointment", amount: 100 });
    vi.spyOn(api, "week").mockResolvedValue({ ...MOCK_WEEK, steps: MOCK_WEEK.steps.map((s) => (s.id === "pay" ? { ...pay, entries: [...pay.entries, fee] } : s)) });
    await renderWeek("/week?step=pay");
    expect(screen.getByText("Pay at the appointment")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pay: Fee for the extension" })).toBeNull();
    expect(screen.getByRole("button", { name: "Pay: Pay TechMarkt reminder" })).toBeInTheDocument();
  });

  it("ticks only the steps looked at on the phone stepper, and jumps to any step from it", async () => {
    useMockApi();
    const { user, router } = await renderWeek("/week?step=pay");
    const stepper = screen.getByRole("list", { name: "Steps of the session" });
    expect(within(stepper).getByRole("button", { name: "New in the last 7 days" })).not.toHaveAttribute("aria-current");
    expect(within(stepper).getByRole("button", { name: "Pay this week" })).toHaveAttribute("aria-current", "step");
    await user.click(screen.getByRole("button", { name: /^Next: Post/ }));
    await screen.findByRole("heading", { level: 2, name: "Post and keep proof" });
    expect(within(stepper).getByRole("button", { name: "Pay this week (looked at)" })).toBeInTheDocument();
    expect(within(stepper).getByRole("button", { name: "Compare with the letter" })).toBeInTheDocument();
    // someone who came for "3 to pay" on a phone doesn't page through New and Compare first
    await user.click(within(stepper).getByRole("button", { name: "Decide in the next 30 days" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Decide in the next 30 days" })).toBeInTheDocument();
    expect(router.state.location.search).toBe("?step=decide");
  });

  it("finishes with “All clear until …” and remembers the session", async () => {
    const { calls, srv } = useMockApi();
    // the demo's phone promise is overdue: kept, nothing is (see "the static demo's session follows the visitor")
    srv.db.state.calls[0]!.promise_kept_on = MOCK_WEEK.today;
    const { user } = await renderWeek("/week?step=file");
    expect(screen.getByText("Nothing here this week — you're done: press Finish.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Finish/ }));
    expect(await screen.findByRole("heading", { name: /^All clear until Tue 29 Sep$/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /^All clear until/ }).querySelector('[data-badge="clear"]')).not.toBeNull();
    expect(calls.some((c) => c.method === "POST" && c.path === "/week/done")).toBe(true);
    expect(screen.getByRole("link", { name: "Back to Today" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("heading", { name: /^All clear until/ })).toHaveFocus();
    expect(screen.getByText("Session saved — Today suggests the next one on Sun 4 Oct.")).toBeInTheDocument();
  });

  it("says how many things are to do today, and where they are", async () => {
    useMockApi();
    const today = MOCK_WEEK.today;
    const form = row({ key: "form", title: "Hand in the form", date: today, date_role: "due" });
    const visit = row({ key: "visit", title: "Appointment", kind: "appointment", date: today, date_role: "on" });
    const fee = row({ key: "fee", title: "Pay the fee", kind: "payment", date: today, date_role: "transfer_by", due_date: "2026-09-30", amount: 10 });
    const now: WeekStep = { id: "now", title: "Act now", summary: "2 to do today", entries: [form, visit], more: 0, total: null, total_other_currencies: {} };
    const pay = MOCK_WEEK.steps.find((s) => s.id === "pay")!;
    const check = MOCK_WEEK.steps.find((s) => s.id === "check")!;
    const post = MOCK_WEEK.steps.find((s) => s.id === "post")!;
    // Compare with the letter lists the fee again, and a letter's send-by day is its deadline's: neither is counted twice
    const letter = row({ key: "letter", ref: { type: "draft", id: "drf_x" }, title: "Your objection", kind: "objection", date: today, date_role: "send_by" });
    const base = withStep(MOCK_WEEK, now);
    const moved = (s: WeekStep) => (s.id === "pay" ? { ...pay, entries: [fee] } : s.id === "check" ? { ...check, entries: [fee] } : s.id === "post" ? { ...post, entries: [letter] } : s);
    const week = { ...base, steps: base.steps.map(moved), overdue: 0, next_deadline: form, due_today: 3 };
    vi.spyOn(api, "week").mockResolvedValue(week);
    vi.spyOn(api, "weekDone").mockResolvedValue({ ...week, last_session: today, due: false, next_prompt: "2026-10-04" });
    const { user } = await renderWeek("/week?step=file", 8);
    await user.click(screen.getByRole("button", { name: /^Finish/ }));
    expect(await screen.findByRole("heading", { name: "3 things to do today" })).toHaveFocus();
    // not the "All clear" tick: there is something to do today
    const card = screen.getByRole("region", { name: "3 things to do today" });
    expect(card.querySelector('[data-badge="calendar"]')).not.toBeNull();
    expect(card.querySelector('[data-badge="clear"]')).toBeNull();
    expect(screen.queryByText(/One thing/)).toBeNull();
    expect(screen.getByRole("link", { name: "Hand in the form" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Act now (2)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Please check/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Post and keep proof/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Pay this week (1)" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Pay this week" })).toBeInTheDocument();
  });

  it("says “One thing to do today” only when there is one", async () => {
    useMockApi();
    const today = MOCK_WEEK.today;
    const form = row({ key: "form", title: "Hand in the form", date: today, date_role: "due" });
    const week = { ...MOCK_WEEK, next_deadline: form, due_today: 1, overdue: 0 };
    vi.spyOn(api, "week").mockResolvedValue(week);
    vi.spyOn(api, "weekDone").mockResolvedValue({ ...week, last_session: today });
    const { user } = await renderWeek("/week?step=file");
    await user.click(screen.getByRole("button", { name: /^Finish/ }));
    expect(await screen.findByRole("heading", { name: "One thing to do today" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^See/ })).toBeNull();
  });

  it("points to every step that holds something overdue", async () => {
    useMockApi();
    const late = row({ key: "late", title: "Send documents to the Jobcenter", kind: "task", date: "2026-09-25", date_role: "by", overdue: true, tone: "danger" });
    const unpaid = row({ key: "unpaid", title: "Pay the fine", kind: "payment", date: "2026-09-26", date_role: "pay_by", overdue: true, tone: "danger", amount: 30 });
    const now: WeekStep = { id: "now", title: "Act now", summary: "1 overdue", entries: [late], more: 0, total: null, total_other_currencies: {} };
    const pay = MOCK_WEEK.steps.find((s) => s.id === "pay")!;
    const waiting = MOCK_WEEK.steps.find((s) => s.id === "waiting")!;
    const check = MOCK_WEEK.steps.find((s) => s.id === "check")!;
    // a reply awaited past its day is counted (the server marks the rows it counts), a to-do listed again
    // on Compare with the letter never
    const reply = row({ key: "reply", ref: { type: "draft", id: "drf_x" }, title: "An answer to your letter", kind: "draft", date: "2026-09-24", date_role: "reply_by", overdue: true, tone: "danger" });
    const base = withStep(MOCK_WEEK, now);
    const moved = (s: WeekStep) =>
      s.id === "pay" ? { ...pay, entries: [unpaid, ...pay.entries] } : s.id === "waiting" ? { ...waiting, entries: [reply] } : s.id === "check" ? { ...check, entries: [unpaid] } : s;
    const week = { ...base, steps: base.steps.map(moved), overdue: 3 };
    vi.spyOn(api, "week").mockResolvedValue(week);
    vi.spyOn(api, "weekDone").mockResolvedValue({ ...week, last_session: MOCK_WEEK.today });
    const { user } = await renderWeek("/week?step=file", 8);
    await user.click(screen.getByRole("button", { name: /^Finish/ }));
    expect(await screen.findByRole("heading", { name: "3 things are overdue" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Act now (1)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Waiting for (1)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Compare with the letter/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Pay this week (1)" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Pay this week" })).toBeInTheDocument();
  });

  it("says how long it takes, not a step count that changes", async () => {
    useMockApi();
    await renderWeek();
    expect(screen.getByText(describeSession(10))).toBeInTheDocument();
    expect(describeSession(10)).toMatch(/^About 10 minutes/);
    expect(describeSession(10)).not.toMatch(/seven|ten/);
  });

  it("never ends “All clear” while something is overdue", async () => {
    useMockApi();
    const late = row({ key: "late", title: "Send documents to the Jobcenter", kind: "task", date: "2026-09-25", date_role: "by", overdue: true, tone: "danger" });
    const now: WeekStep = { id: "now", title: "Act now", summary: "1 overdue", entries: [late], more: 0, total: null, total_other_currencies: {} };
    const quiet = { ...MOCK_WEEK, steps: MOCK_WEEK.steps.map((s) => ({ ...s, entries: s.entries.map((e) => ({ ...e, overdue: false })) })) };
    const week = { ...withStep(quiet, now), overdue: 1 };
    vi.spyOn(api, "week").mockResolvedValue(week);
    vi.spyOn(api, "weekDone").mockResolvedValue({ ...week, last_session: MOCK_WEEK.today, due: false, next_prompt: "2026-10-04" });
    const { user } = await renderWeek("/week?step=file", 8);
    await user.click(screen.getByRole("button", { name: /^Finish/ }));
    const heading = await screen.findByRole("heading", { name: "1 thing is overdue" });
    expect(heading).toHaveFocus();
    expect(screen.queryByText(/All clear/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "See it" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Act now" })).toBeInTheDocument();
  });

  it("with nothing to review, says so instead of seven empty steps", async () => {
    useMockApi();
    const empty = {
      ...MOCK_WEEK,
      last_session: null,
      next_deadline: null,
      overdue: 0,
      steps: MOCK_WEEK.steps.map((s) => ({ ...s, entries: [], more: 0 })),
    };
    vi.spyOn(api, "week").mockResolvedValue(empty);
    renderWithProviders(
      <AddLettersProvider>
        <WeekView />
      </AddLettersProvider>,
      { route: "/week" },
    );
    expect(await screen.findByRole("heading", { name: "Nothing to review yet" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add letters" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Today" })).toHaveAttribute("href", "/");
    expect(screen.queryByText(/^Step \d/)).toBeNull();
  });

  it("shows how many more a long step has, and where to see them", async () => {
    useMockApi();
    const many = { ...MOCK_WEEK, steps: MOCK_WEEK.steps.map((s) => (s.id === "new" ? { ...s, more: 4 } : s)) };
    vi.spyOn(api, "week").mockResolvedValue(many);
    await renderWeek();
    expect(screen.getByText(/And 4 more\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See all in the Inbox" })).toHaveAttribute("href", "/inbox");
  });
});

describe("Today's prompt", () => {
  it("suggests the session once, and “Not now” leaves a quiet link", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <WeeklyPrompt />
        <h2 id="coming-up-title">Coming up</h2>
        <WeeklyLink />
        <Toaster />
      </>,
    );
    const prompt = await screen.findByRole("region", { name: "Time for your weekly review" });
    expect(within(prompt).getByText(/About 10 minutes: 1 overdue · 8 new letters · 2 to compare · 4 to pay/)).toBeInTheDocument();
    expect(within(prompt).getByRole("link", { name: "Start" })).toHaveAttribute("href", "/week");
    expect(screen.queryByRole("link", { name: /Weekly review/ })).toBeNull();

    await user.click(within(prompt).getByRole("button", { name: "Not now" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Time for your weekly review" })).toBeNull());
    expect(calls.some((c) => c.method === "POST" && c.path === "/week/dismiss")).toBe(true);
    expect(screen.getByRole("link", { name: /Weekly review/ })).toHaveAttribute("href", "/week");
    expect(await screen.findByText(/Today suggests it again on Sun 4 Oct/)).toBeInTheDocument();
    // the prompt is gone: the focus is on the next section, not lost to the page
    await waitFor(() => expect(screen.getByRole("heading", { name: "Coming up" })).toHaveFocus());
  });
});

describe("the static demo's session follows the visitor", () => {
  it("a paid to-do leaves its step and the prompt goes after Finish", () => {
    const { srv } = useMockApi();
    const before = mockWeek(srv.db);
    expect(before.due).toBe(true);
    const pay = before.steps.find((s) => s.id === "pay")!;
    const first = pay.entries[0]!;
    srv.db.state.items.find((i) => i.id === first.ref.id)!.status = "done";
    const after = mockWeek(srv.db).steps.find((s) => s.id === "pay")!;
    expect(after.entries.map((e) => e.key)).not.toContain(first.key);
    expect(after.summary).toBe(`${pay.entries.length - 1} left to look at`);
    srv.handle("POST", "/week/done", new URLSearchParams(), undefined, null);
    const done = mockWeek(srv.db);
    expect(done.due).toBe(false);
    expect(done.last_session).toBe("2026-09-28");
    expect(done.next_prompt).toBe("2026-10-04");
  });

  it("ends on the next day to act once the first is paid, never “Nothing is due”", async () => {
    const { srv } = useMockApi();
    const before = mockWeek(srv.db);
    expect(before.next_deadline?.key).toBe(MOCK_WEEK_DEADLINES[0]!.key);
    srv.db.state.items.find((i) => i.id === before.next_deadline!.ref.id)!.status = "done";
    const after = mockWeek(srv.db);
    expect(after.next_deadline).not.toBeNull();
    expect(after.next_deadline!.key).toBe(MOCK_WEEK_DEADLINES[1]!.key);
    expect(after.next_deadline!.date! >= before.next_deadline!.date!).toBe(true);
    expect(after.due_today).toBe(MOCK_WEEK_DEADLINES.slice(1).filter((e) => e.date === MOCK_WEEK.today).length);
  });

  it("ends saying the phone promise is overdue until it is kept", async () => {
    const { srv } = useMockApi();
    const { user } = await renderWeek("/week?step=file");
    await user.click(screen.getByRole("button", { name: /^Finish/ }));
    expect(await screen.findByRole("heading", { name: "1 thing is overdue" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "See it" }));
    const step = (await screen.findByRole("heading", { level: 2, name: "Waiting for" })).closest("section")!;
    expect(within(step).getByRole("link", { name: "Written confirmation of the cancellation" })).toHaveAttribute("href", "/letters/waiting");
    expect(within(step).getByRole("link", { name: "See everything you're waiting for" })).toHaveAttribute("href", "/letters/waiting");
    srv.db.state.calls[0]!.promise_kept_on = MOCK_WEEK.today;
    expect(mockWeek(srv.db).overdue).toBe(0);
  });

  it("finishes “All clear until” the next transfer after paying the first", async () => {
    const { srv } = useMockApi();
    srv.db.state.calls[0]!.promise_kept_on = MOCK_WEEK.today; // the phone promise was kept
    const first = mockWeek(srv.db).next_deadline!;
    srv.db.state.items.find((i) => i.id === first.ref.id)!.status = "done";
    const { user } = await renderWeek("/week?step=file");
    await user.click(screen.getByRole("button", { name: /^Finish/ }));
    expect(await screen.findByRole("heading", { name: /^All clear until Wed 30 Sep$/ })).toBeInTheDocument();
    expect(screen.queryByText("Nothing is due from today on.")).toBeNull();
  });

  it("“The date looks right” takes a value off Compare with the letter", async () => {
    const { srv } = useMockApi();
    const check = mockWeek(srv.db).steps.find((s) => s.id === "check")!;
    const passport = check.entries.find((e) => e.title === "Passport expires")!;
    await srv.handle("POST", `/items/${passport.ref.id}/confirm`, new URLSearchParams(), undefined, null);
    const after = mockWeek(srv.db).steps.find((s) => s.id === "check")!;
    expect(after.entries.map((e) => e.key)).not.toContain(passport.key);
    expect(after.entries).toHaveLength(check.entries.length - 1);
  });
});
