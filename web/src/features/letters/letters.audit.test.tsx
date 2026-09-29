/**
 * Audit (UI audit round 1, letters-b): the Letters list and the New-letter composer.
 *
 * - Beside the "How letters work" card (from 1024 px) the list's rows lost their titles to a fixed
 *   status column; on phones they lost the sent date; letters in progress kept the API's order.
 * - The composer's lists scrolled inside the scrolling dialog, a chosen contract out of view; names
 *   and pills were cut off on phones; an objection that isn't possible named no letter; an empty
 *   install led to empty lists, an empty search and a picker without people.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Document, Draft, Item } from "@/api/types";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import LettersPage from "@/pages/LettersPage";
import { letterDate, objectionDeadline, splitDrafts, usableDocuments } from "./logic";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

/** An install with nothing in it yet: every list is empty. */
function stubEmptyInstall() {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const path = new URL(String(input instanceof Request ? input.url : input), "http://localhost").pathname;
    const body = /\/profile$/.test(path) ? {} : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

const draft = (over: Partial<Draft>): Draft =>
  ({ id: "drf_x", status: "draft", send_guidance: null, created_at: "2026-09-20T10:00:00Z", sent_at: null, ...over }) as Draft;

describe("the Letters list's order", () => {
  it("puts what is due first, undated letters after them (newest first), sent letters latest first", () => {
    const soon = draft({ id: "soon", send_guidance: { send_by: "2026-10-08" } as Draft["send_guidance"] });
    const later = draft({ id: "later", send_guidance: { send_by: "2027-09-06" } as Draft["send_guidance"] });
    const arrive = draft({ id: "arrive", send_guidance: { send_by: null, must_arrive_by: "2026-10-01" } as Draft["send_guidance"] });
    const undatedOld = draft({ id: "undated-old", created_at: "2026-09-01T10:00:00Z" });
    const undatedNew = draft({ id: "undated-new", created_at: "2026-09-25T10:00:00Z" });
    const sentOld = draft({ id: "sent-old", status: "sent", sent_at: "2026-09-10T10:00:00Z" });
    const sentNew = draft({ id: "sent-new", status: "sent", sent_at: "2026-09-26T10:00:00Z" });
    const { inProgress, sent } = splitDrafts([later, undatedOld, sentOld, soon, undatedNew, arrive, sentNew]);
    expect(inProgress.map((d) => d.id)).toEqual(["arrive", "soon", "later", "undated-new", "undated-old"]);
    expect(sent.map((d) => d.id)).toEqual(["sent-new", "sent-old"]);
  });
});

describe("letters a letter can answer", () => {
  const doc = (over: Partial<Document>): Document =>
    ({ id: "doc_x", status: "processed", deleted_at: null, kind: "invoice", doc_date: "2026-09-01", received_date: null, ...over }) as Document;

  it("never offers an ID document or a payslip, and dates a letter by when it arrived when it has no date", () => {
    const docs = usableDocuments([doc({ id: "id", kind: "identity_document" }), doc({ id: "pay", kind: "payslip" }), doc({ id: "bill" })]);
    expect(docs.map((d) => d.id)).toEqual(["bill"]);
    expect(letterDate({ doc_date: null, received_date: "2026-09-26" })).toBe("2026-09-26");
  });

  it("finds a decision's open objection deadline among its to-dos", () => {
    const item = (over: Partial<Item>) => ({ kind: "deadline", status: "open", due_date: "2026-10-14", date_spec: { nature: "objection" }, ...over }) as Item;
    expect(objectionDeadline([item({ date_spec: null }), item({ due_date: "2026-10-20" }), item({})])?.due_date).toBe("2026-10-14");
    expect(objectionDeadline([item({ status: "done" }), item({ kind: "payment" })])).toBeNull();
  });
});

describe("Letters page (audit)", () => {
  it("rows keep their title (two lines, the whole of it on hover) and show the same facts at every width", async () => {
    useMockApi();
    renderWithProviders(<LettersPage />, { route: "/letters" });
    const sentGroup = await screen.findByRole("region", { name: /Sent/ });
    const row = within(sentGroup).getByRole("link", { name: /Reply to Wohnbau Musterstadt eG/ });
    const title = within(row).getByText("Reply to Wohnbau Musterstadt eG");
    expect(title).toHaveAttribute("title", "Reply to Wohnbau Musterstadt eG");
    expect(title.className).toMatch(/line-clamp-2/);
    // one block of facts (status, then when it went and how) — a phone no longer loses the date
    const meta = row.querySelector<HTMLElement>("[data-draft-meta]")!;
    expect(meta).toHaveTextContent(/Sent.*by email/);
    expect(meta.className).not.toMatch(/(^| )hidden( |$)/);
    // under the subject in a narrow list, a column on the right only in a roomy one
    expect(meta.className).toMatch(/@xl\/drafts:col-start-3/);
    expect(row.closest("ul")!.className).toMatch(/@container\/drafts/);
    // the focus ring is drawn inside the row: the card's clipping no longer cuts it to a line
    expect(row.className).toMatch(/focus-visible:-outline-offset-2/);
  });

  it("puts 'How letters work' beside the list only from 1280 px, lined up with the first card", async () => {
    useMockApi();
    const { container } = renderWithProviders(<LettersPage />, { route: "/letters" });
    await screen.findByRole("region", { name: /In progress/ });
    expect(container.querySelector(".grid")!.className).toMatch(/xl:grid-cols-\[minmax\(0,1fr\)_300px\]/);
    expect(container.querySelector(".grid")!.className).not.toMatch(/(^| )lg:grid-cols/);
    expect(container.querySelector("[data-letters-how]")!.className).toMatch(/xl:pt-\[1\.875rem\]/);
    // the steps promise no translation "right next to it" (a phone has it behind a switch)
    expect(screen.getByRole("complementary", { name: "How letters work" })).not.toHaveTextContent(/next to it/);
  });

  it("an empty page has one primary action, and the card lines up with the empty state", async () => {
    stubEmptyInstall();
    const { container } = renderWithProviders(<LettersPage />, { route: "/letters" });
    expect(await screen.findByRole("heading", { level: 2, name: "No letters yet" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /New letter|Write your first letter/ }).map((b) => b.textContent)).toEqual(["Write your first letter"]);
    expect(container.querySelector("[data-letters-how]")!.className).not.toMatch(/pt-/);
  });

  it("a load error is the app's load error: an alert with Try again and the details", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ detail: "Internal error" }), { status: 500, headers: { "Content-Type": "application/json" } }));
    const { container } = renderWithProviders(<LettersPage />, { route: "/letters" });
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("heading", { level: 2, name: "Couldn't load your letters" })).toBeInTheDocument();
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(within(alert).getByText("Technical details")).toBeInTheDocument();
    expect(container.querySelector("[data-letters-how]")!.className).not.toMatch(/pt-/);
  });
});

describe("composer (audit)", () => {
  it("shows a chosen contract first, in the dialog's own scroll, with the resignation note under it", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<LettersPage />, { route: "/letters?kind=cancellation&contract=ctr_job" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    const group = await within(dialog).findByRole("radiogroup", { name: /Which contract/ });
    const radios = within(group).getAllByRole("radio");
    expect(radios[0]).toBeChecked();
    expect(radios[0]!.closest("label")).toHaveTextContent(/Muster Tech/);
    // no scrolling box inside the scrolling dialog
    for (const el of [group, ...Array.from(group.querySelectorAll("*"))]) expect(el.className.toString()).not.toMatch(/overflow-y-auto|max-h-/);
    // the first five, then all of them on request
    expect(radios).toHaveLength(5);
    const all = within(dialog).getByRole("button", { name: /^Show all \d+ contracts$/ });
    expect(all).toHaveAttribute("aria-expanded", "false");
    await user.click(all);
    expect(within(group).getAllByRole("radio").length).toBeGreaterThan(5);
    expect(within(dialog).getByRole("button", { name: "Show fewer" })).toHaveAttribute("aria-expanded", "true");
    // the note about the choice follows the list
    const note = within(dialog).getByText("This drafts your resignation");
    expect(group.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("gives names two lines and keeps the send-by date and 'possible' on phones", async () => {
    useMockApi({ full: true });
    renderWithProviders(<LettersPage />, { route: "/letters?kind=cancellation&contract=ctr_phone" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    const phone = await within(dialog).findByRole("radio", { name: /FunkNetz Allnet L/ });
    const label = phone.closest("label")!;
    const name = within(label).getByText("FunkNetz Allnet L");
    expect(name.className).toMatch(/line-clamp-2/);
    expect(name).toHaveAttribute("title", "FunkNetz Allnet L");
    const dates = label.querySelectorAll("time[data-urgency]");
    expect(Array.from(dates, (t) => t.className)).toEqual([expect.stringMatching(/(^| )sm:hidden( |$)/), expect.stringMatching(/(^| )hidden .*sm:inline-flex/)]);
  });

  it("names the letter that can't be objected to, and lists the decisions that can apart from it", async () => {
    useMockApi({ full: true });
    renderWithProviders(<LettersPage />, { route: "/letters?kind=objection&doc=doc_parking" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    const chosen = await waitFor(() => {
      const el = dialog.querySelector<HTMLElement>("[data-chosen-letter]");
      expect(el).toBeTruthy();
      return el!;
    });
    expect(chosen).toHaveTextContent(/The letter you chose:/);
    expect(within(chosen).queryByRole("radio")).toBeNull();
    expect(within(dialog).getByRole("radiogroup", { name: "Or choose a decision you can object to" })).toBeInTheDocument();
    const write = within(dialog).getByRole("button", { name: /Write the letter/ });
    expect(write).toBeDisabled();
    expect(write).toHaveAccessibleDescription(/You can't object to this letter — reply to it instead/);
  });

  it("says 'a Widerspruch' / 'an Einspruch', gives the deadline in plain words and doesn't repeat the To card's address", async () => {
    useMockApi({ full: true });
    renderWithProviders(<LettersPage />, { route: "/letters?kind=objection&doc=doc_tax" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    const note = await waitFor(() => {
      const el = dialog.querySelector<HTMLElement>("[data-objection-note]");
      expect(el).toBeTruthy();
      return el!;
    });
    expect(note).toHaveTextContent(/The letter allows an Einspruch/);
    expect(note).not.toHaveTextContent(/Steuerring/);
    // the date first, in words the person reads; the letter's German wording only as its quote
    await waitFor(() => expect(note).toHaveTextContent(/Deadline: \w{3} \d{1,2} \w{3}/));
    expect(within(note).getByText((_, el) => el?.tagName === "TIME")).toHaveAttribute("data-urgency");
    expect(note).not.toHaveTextContent(/allows a Einspruch|allows an Widerspruch/);
  });

  it("reads each step as 'Step n: …' and marks every choice with a radio circle", async () => {
    useMockApi();
    renderWithProviders(<LettersPage />, { route: "/letters?new=1" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    // (jsdom joins the parts without the space a browser keeps)
    expect(within(dialog).getByRole("heading", { level: 3, name: /^Step 1:\s*What do you want to do\?$/ })).toBeInTheDocument();
    for (const name of [/Cancel a contract/, /Object to a decision/, /Reply to a letter/, /Ask for your data/]) {
      const label = within(dialog).getByRole("radio", { name }).closest("label")!;
      expect(label.querySelector("[data-radio-dot]")).toBeTruthy();
      // only the radio's own keyboard focus rings the card
      expect(label.className).toMatch(/has-\[input:focus-visible\]:outline-2/);
      expect(label.className).not.toMatch(/has-\[:focus-visible\]/);
    }
    // no glossary term inside a card: no extra tab stops that also pick the card
    const kinds = within(dialog).getByRole("group", { name: "What do you want to do?" });
    expect(kinds.querySelectorAll("button, [tabindex='0']")).toHaveLength(0);
  });

  it("an empty install: kinds with nothing to act on say why, and step 2 offers 'Add letters' — no empty list, search or picker", async () => {
    stubEmptyInstall();
    const user = userEvent.setup();
    const { router } = renderWithProviders(
      <AddLettersProvider>
        <LettersPage />
        <Toaster />
      </AddLettersProvider>,
      { route: "/letters?kind=cancellation" },
    );
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    expect(await within(dialog).findByText("No contracts to cancel yet")).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: /Reply to a letter/ })).toBeDisabled();
    expect(within(dialog).getByRole("radio", { name: /Reply to a letter/ }).closest("label")).toHaveTextContent("No letters yet — add a letter first.");
    expect(within(dialog).getByRole("radio", { name: /Object to a decision/ })).toBeDisabled();
    // nothing after a step with nothing to choose
    expect(within(dialog).queryByLabelText(/Your wishes/)).toBeNull();
    expect(within(dialog).queryByRole("searchbox")).toBeNull();
    expect(within(dialog).queryByRole("textbox", { name: "Find a letter" })).toBeNull();
    expect(within(dialog).queryByText(/No letters match/)).toBeNull();
    expect(within(dialog).getByRole("button", { name: /Write the letter/ })).toHaveAccessibleDescription(/Add a contract letter first/);
    // the way on: add letters (the composer closes for the file picker)
    await user.click(within(dialog).getByRole("button", { name: "Add letters" }));
    await waitFor(() => expect(router.state.location.search).not.toMatch(/kind=/));
  });

  it("a reply on an empty install has no search box, no 'No letters match “”' and no picker without people", async () => {
    stubEmptyInstall();
    renderWithProviders(<LettersPage />, { route: "/letters?kind=general_reply" });
    const dialog = await screen.findByRole("dialog", { name: "New letter" });
    expect(await within(dialog).findByText("No letters to answer yet")).toBeInTheDocument();
    expect(within(dialog).queryByRole("textbox", { name: "Find a letter" })).toBeNull();
    expect(within(dialog).queryByText(/No letters match/)).toBeNull();
    expect(within(dialog).queryByRole("combobox")).toBeNull();
    // outside the app's shell (no Add-letters flow) the way on is the inbox
    expect(within(dialog).getByRole("link", { name: "Go to the inbox" })).toHaveAttribute("href", "/inbox");
  });
});
