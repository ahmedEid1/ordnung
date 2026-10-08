import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DocumentDetail, Item, Party, RegionSuggestion } from "@/api/types";
import { qk, useDocument } from "@/api/hooks";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { makeDetail, makeDoc, makeItem, makeReceipt, makeSuggestion } from "./fixtures";
import { DocumentWarnings } from "./Warnings";
import { ReceiptView, senderLandUnknown, WhyThisDate } from "./WhyThisDate";

const party = (p: Partial<Party> = {}): Party => ({
  id: "pty_city",
  name: "Stadt Musterstadt",
  kind: "authority",
  aliases: [],
  identifiers: [],
  address: "Rathausplatz 1, 12345 Musterstadt",
  email: null,
  phone: null,
  website: null,
  notes: null,
  region: null,
  ibans: [],
  created_at: "2026-09-01T07:00:00Z",
  updated_at: "2026-09-01T07:00:00Z",
  ...p,
});

const NATIONWIDE = "Germany (nationwide holidays only)";

/** The engine without the sender's Land, for a Land authority's letter: the 3-day rule, at lower confidence. */
const threeDays = makeReceipt({
  due_date: "2026-11-17",
  holiday_calendar: NATIONWIDE,
  confidence: "medium",
  warnings: ["Some Länder may still use the 3-day rule for their authorities and we couldn't confirm this sender's, so we counted 3 days (the earlier date)."],
});

/** … or where a Land's holiday may make the date later. */
const holiday = makeReceipt({
  due_date: "2027-11-01",
  holiday_calendar: NATIONWIDE,
  confidence: "low",
  warnings: [
    "Holiday region unknown — Mon 1 Nov 2027 is a public holiday in some Länder (e.g. Baden-Württemberg, Bayern, Nordrhein-Westfalen), where the deadline would be later. We used nationwide holidays only.",
  ],
});

describe("a date that waits for the sender's state", () => {
  it("is one the engine says its Land would change, for a sender in Germany whose state isn't set", () => {
    expect(senderLandUnknown(threeDays, party())?.id).toBe("pty_city");
    expect(senderLandUnknown(holiday, party())?.id).toBe("pty_city");
    expect(senderLandUnknown(threeDays, party({ region: "SN" }))).toBeNull(); // the person said
    expect(senderLandUnknown(threeDays, party({ address: "1 Example Road, Examplia" }))).toBeNull(); // abroad
    expect(senderLandUnknown(threeDays, null)).toBeNull();
    // nationwide holidays and lower confidence for another reason (the demo's appointment read from a photo)
    const photo = makeReceipt({ holiday_calendar: NATIONWIDE, confidence: "medium", warnings: ["This was read by AI from a photo or scan — compare the date with the paper letter."] });
    expect(senderLandUnknown(photo, party())).toBeNull();
  });

  it("says so on “Why this date?” and opens the sender's drawer to choose it", async () => {
    const user = userEvent.setup();
    const client = makeTestQueryClient();
    client.setQueryData(qk.documents.detail("doc_1"), makeDetail({ document: makeDoc({ party_id: "pty_city" }), party: party() }));
    const item = makeItem({ due_date: "2026-11-17", computation: threeDays });
    const { router } = renderWithProviders(<ReceiptView receipt={threeDays} item={item} />, { client });
    expect(screen.getByText(/Ordnung doesn't know which state Stadt Musterstadt is in, so this date may be a few days early\./)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Choose their state" }));
    expect(router.state.location.search).toBe("?party=pty_city");
  });

  it("closes “Why this date?” before the drawer opens: on a phone its sheet kept the keyboard from the State picker", async () => {
    const user = userEvent.setup();
    const client = makeTestQueryClient();
    client.setQueryData(qk.documents.detail("doc_1"), makeDetail({ document: makeDoc({ party_id: "pty_city" }), party: party() }));
    const item = makeItem({ due_date: "2026-11-17", computation: threeDays });
    // jsdom has no media queries: the phone's bottom sheet, modal
    const { router } = renderWithProviders(<WhyThisDate receipt={threeDays} item={item} context="Pay the fee" />, { client });
    const trigger = screen.getByRole("button", { name: "Why this date? (Pay the fee)" });
    await user.click(trigger);
    const sheet = await screen.findByRole("dialog", { name: "Why this date? Pay the fee" });
    expect(sheet).toHaveAttribute("aria-modal", "true");
    await user.click(within(sheet).getByRole("button", { name: "Choose their state" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Why this date? Pay the fee" })).toBeNull());
    expect(router.state.location.search).toBe("?party=pty_city");
    // where the drawer gives the keyboard back when it closes
    expect(trigger).toHaveFocus();
  });

  it("is not mentioned once the sender's state is set", () => {
    const client = makeTestQueryClient();
    client.setQueryData(qk.documents.detail("doc_1"), makeDetail({ party: party({ region: "SN" }) }));
    renderWithProviders(<ReceiptView receipt={threeDays} item={makeItem({ computation: threeDays })} />, { client });
    expect(screen.queryByRole("button", { name: "Choose their state" })).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------
// The letter's "Please check" card: the state the postcode on their letter suggests (ADR 0019)
// ------------------------------------------------------------------------------------------------

/** Counted backwards without the sender's Land (`rules.deadlines.REGION_EARLIER`): the date may be a day late. */
const earlier = makeReceipt({
  holiday_calendar: NATIONWIDE,
  confidence: "low",
  warnings: [
    "Holiday region unknown — Sat 31 Oct 2026 is a public holiday in some Länder (e.g. Brandenburg, Bremen, Hamburg), where the deadline would be earlier — act a working day before it to be safe. We used nationwide holidays only.",
  ],
});

const TECHMARKT = party({ id: "pty_techmarkt", name: "TechMarkt Online GmbH", kind: "retailer", address: "Handelsstraße 88, 12353 Beispielburg" });
const QUESTION = "Is TechMarkt Online GmbH in Berlin? (12353 on their letter)";

/** What the server answers for the letter: Berlin, from the postcode on it, and one of its dates may change. */
const asked = (s: Partial<RegionSuggestion> = {}): RegionSuggestion => ({
  region: "BE",
  postcode: "12353",
  doc_id: "doc_1",
  waiting: 1,
  may_be_late: false,
  idea_id: null,
  declined: false,
  ...s,
});

/** A TechMarkt letter with one open date counted with `receipt`'s warnings, and the server's question. */
function landLetter({ receipt = holiday, suggestion = asked(), sender = TECHMARKT }: { receipt?: typeof holiday; suggestion?: RegionSuggestion | null; sender?: Party } = {}) {
  const item = makeItem({ id: "itm_pay", kind: "payment", title: "Pay the reminder", due_date: "2026-11-02", party_id: sender.id, computation: receipt });
  return makeDetail({ document: makeDoc({ party_id: sender.id }), party: sender, items: [item], region_suggestion: suggestion });
}

/** The letter's warnings and the headings focus goes to (the verdict's title, the to-dos'). */
function Warned({ detail }: { detail: DocumentDetail }) {
  return (
    <>
      <h1 id="verdict-title" tabIndex={-1}>
        Pay the reminder
      </h1>
      <DocumentWarnings detail={detail} />
      <section aria-labelledby="todos-title">
        <h2 id="todos-title">To-dos & dates</h2>
      </section>
      <Toaster />
    </>
  );
}

function renderLetter(detail: DocumentDetail) {
  const client = makeTestQueryClient();
  client.setQueryData(qk.rules, []);
  return renderWithProviders(<Warned detail={detail} />, { client });
}

/** A letter as its page loads it. */
function LoadedLetter({ id }: { id: string }) {
  const { data } = useDocument(id);
  return data ? <Warned detail={data} /> : null;
}

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

/**
 * The mock's TechMarkt reminder served as the API would with the postcode question (`extra` on top): its payment
 * counted without the Land, a holiday that may move it, and — once their state is set — recomputed a day later.
 */
function serveLandLetter(srv: ReturnType<typeof useMockApi>["srv"], extra: Partial<RegionSuggestion> = {}, { moves = true } = {}) {
  const answer = globalThis.fetch;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const response = await answer(input, init);
    if ((init?.method ?? "GET") !== "GET" || !String(input).endsWith("/api/documents/doc_tm_dunning")) return response;
    const detail = (await response.json()) as DocumentDetail;
    const set = Boolean(detail.party?.region);
    const moved = set && moves;
    const items = detail.items.map((i: Item) =>
      i.id === "itm_tm_dunning" ? { ...i, send_by: null, due_date: moved ? "2026-10-01" : "2026-09-30", computation: moved ? makeReceipt() : holiday } : i,
    );
    const idea = srv.db.state.suggestions.find((x) => x.id === extra.idea_id);
    return json({ ...detail, items, region_suggestion: set ? null : asked({ doc_id: "doc_tm_dunning", ...extra, declined: idea?.status === "dismissed" }) });
  });
}

describe("the letter asks for the sender's state the postcode on it suggests", () => {
  afterEach(() => act(() => __clearToasts()));

  it("asks only while one of the letter's dates may change, their state isn't set, they didn't say “Don't know” and the letter shows no scam signs", () => {
    const shown = (detail: DocumentDetail) => {
      const { unmount } = renderLetter(detail);
      const question = screen.queryByRole("group", { name: QUESTION });
      unmount();
      return question !== null;
    };
    expect(shown(landLetter())).toBe(true);
    expect(shown(landLetter({ suggestion: asked({ waiting: 0 }) }))).toBe(false); // asked in their details only
    expect(shown(landLetter({ suggestion: asked({ idea_id: "sug_land", declined: true }) }))).toBe(false);
    expect(shown(landLetter({ sender: { ...TECHMARKT, region: "BE" } }))).toBe(false);
    expect(shown(landLetter({ suggestion: null }))).toBe(false);
    const scam = makeSuggestion({ kind: "scam", refs: [{ type: "document", id: "doc_1" }] });
    expect(shown({ ...landLetter(), suggestions: [scam] })).toBe(false);
  });

  it("is a “Please check” card with the postcode it comes from; Yes is not focused, and “Don't know” waits for their Idea", () => {
    renderLetter(landLetter());
    const question = screen.getByRole("group", { name: QUESTION });
    const card = question.closest<HTMLElement>(".rounded-2xl")!;
    expect(within(card).getByRole("heading", { name: "Please check" })).toHaveAttribute("id", "check-land");
    expect(within(question).getAllByRole("button").map((b) => b.textContent)).toEqual(["Yes", "Other state…"]);
    expect(within(question).getByRole("button", { name: "Yes" })).not.toHaveFocus();
  });

  it("says why from the letter's own dates: counted backwards first, then 3 or 4 days for a state with the 4-day rule, then holidays", () => {
    const reason = (receipt: typeof holiday, region = "BE") => {
      const { unmount } = renderLetter(landLetter({ receipt, suggestion: asked({ region }) }));
      const text = screen.getByRole("group", { name: /^Is TechMarkt Online GmbH in/ }).textContent;
      unmount();
      return text;
    };
    const HOLIDAYS = "Their state's public holidays may move this letter's dates. Until you answer, Ordnung counts only nationwide holidays, so a date may be a day or two early.";
    const DAYS = "Their state decides whether this letter counts as delivered after 3 or 4 days. Until you answer, Ordnung counts 3, so the date may be a day early.";
    const BACKWARDS = "A holiday in their state could make a date earlier. Until you answer, act a working day before it.";
    expect(reason(holiday)).toContain(HOLIDAYS);
    expect(reason(threeDays)).toContain(DAYS);
    const both = makeReceipt({ warnings: [...threeDays.warnings, ...holiday.warnings] });
    expect(reason(both)).toContain(DAYS);
    // Thuringia's authorities count 3 days anyway: only its holidays may move the date
    expect(reason(both, "TH")).toContain(HOLIDAYS);
    expect(reason(makeReceipt({ warnings: [...threeDays.warnings, ...earlier.warnings] }))).toContain(BACKWARDS);
  });

  it("Yes saves their state, takes the keyboard to the verdict and says which of the letter's dates moved; Undo takes it back", async () => {
    const { srv, calls } = useMockApi();
    serveLandLetter(srv);
    const region = () => srv.db.state.parties.find((p) => p.id === "pty_techmarkt")!.region;
    const user = userEvent.setup();
    renderWithProviders(<LoadedLetter id="doc_tm_dunning" />);
    const question = await screen.findByRole("group", { name: QUESTION });
    await user.click(within(question).getByRole("button", { name: "Yes" }));
    await waitFor(() => expect(region()).toBe("BE"));
    expect(calls.filter((c) => c.method !== "GET")).toEqual([{ method: "PATCH", path: "/parties/pty_techmarkt", body: { region: "BE" } }]);
    expect(await screen.findByText("Saved: TechMarkt Online GmbH is in Berlin")).toBeInTheDocument();
    expect(screen.getByText("Their dates now skip the public holidays of Berlin. “Pay TechMarkt reminder” moved from Wed 30 Sep to Thu 1 Oct.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Pay the reminder" })).toHaveFocus());
    expect(screen.queryByRole("group", { name: QUESTION })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(region()).toBeNull());
    expect(calls.filter((c) => c.method !== "GET").at(-1)).toEqual({ method: "PATCH", path: "/parties/pty_techmarkt", body: { region: null } });
    expect(await screen.findByRole("group", { name: QUESTION })).toBeInTheDocument();
  });

  it("says so when no date on the letter moved", async () => {
    const { srv } = useMockApi();
    serveLandLetter(srv, {}, { moves: false });
    const user = userEvent.setup();
    renderWithProviders(<LoadedLetter id="doc_tm_dunning" />);
    await user.click(within(await screen.findByRole("group", { name: QUESTION })).getByRole("button", { name: "Yes" }));
    expect(await screen.findByText("Their dates now skip the public holidays of Berlin. No date on this letter moved.")).toBeInTheDocument();
  });

  it("“Other state…” opens their details to choose (`state=choose`); nothing is saved", async () => {
    const user = userEvent.setup();
    const { router } = renderLetter(landLetter());
    await user.click(within(screen.getByRole("group", { name: QUESTION })).getByRole("button", { name: "Other state…" }));
    expect(router.state.location.search).toBe("?party=pty_techmarkt&state=choose");
  });

  it("“Don't know” dismisses their Idea: the card goes, the keyboard moves on, and Undo brings it back", async () => {
    const { srv, calls } = useMockApi();
    srv.db.state.suggestions.push(
      makeSuggestion({
        id: "sug_land_techmarkt",
        kind: "deadline",
        title: "Is TechMarkt Online GmbH in Berlin?",
        rule_id: "sender_land",
        refs: [{ type: "party", id: "pty_techmarkt" }],
        action: { type: "open", draft_kind: null, target_type: "party", target_id: "pty_techmarkt", label: "Answer" },
      }),
    );
    serveLandLetter(srv, { idea_id: "sug_land_techmarkt" });
    const user = userEvent.setup();
    renderWithProviders(<LoadedLetter id="doc_tm_dunning" />);
    const question = await screen.findByRole("group", { name: QUESTION });
    expect(within(question).getAllByRole("button").map((b) => b.textContent)).toEqual(["Yes", "Other state…", "Don't know"]);
    await user.click(within(question).getByRole("button", { name: "Don't know" }));
    await waitFor(() => expect(screen.queryByRole("group", { name: QUESTION })).toBeNull());
    expect(calls.filter((c) => c.method !== "GET")).toEqual([{ method: "PATCH", path: "/suggestions/sug_land_techmarkt", body: { status: "dismissed" } }]);
    expect(srv.db.state.parties.find((p) => p.id === "pty_techmarkt")!.region).toBeNull();
    expect(await screen.findByText("Okay — nationwide holidays for TechMarkt Online GmbH")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "To-dos & dates" })).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByRole("group", { name: QUESTION })).toBeInTheDocument();
    expect(srv.db.state.suggestions.find((x) => x.id === "sug_land_techmarkt")!.status).toBe("new");
  });
});
