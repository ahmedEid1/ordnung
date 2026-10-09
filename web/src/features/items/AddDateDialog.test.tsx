import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DocumentDetail } from "@/api/types";
import { toast } from "@/components/ui/Toast";
import { DocumentView } from "@/features/document/DocumentView";
import { makeDetail, makeDoc, makeItem } from "@/features/document/fixtures";
import { TimelineView } from "@/features/timeline/TimelineView";
import { useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { AddDateDialog, dateBody, dateProblems, type DateDraft } from "./AddDateDialog";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: /min-width/.test(query), media: query, addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const DRAFT: DateDraft = { title: "Call the landlord", date: "2026-10-12", kind: "reminder", amount: "", docId: "", repeat: "never", workingDay: 3, moves: "this" };

/** Fill the dialog: what, when, the kind and (optionally) an amount. */
async function fill(user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement, { title, date, kind, amount }: { title: string; date: string; kind?: string; amount?: string }) {
  await user.type(within(dialog).getByLabelText("What is it?"), title);
  fireEvent.change(within(dialog).getByLabelText("When?"), { target: { value: date } });
  if (kind) await user.click(within(dialog).getByRole("radio", { name: kind }));
  if (amount) await user.type(within(dialog).getByLabelText(/^Amount/), amount);
}

describe("what is checked and sent", () => {
  it("asks for what it is and the day; an amount it can read, or none", () => {
    expect(dateProblems({ ...DRAFT, title: "  ", date: "" })).toEqual({ title: expect.stringMatching(/Say what it is/), date: "Choose the day." });
    expect(dateProblems({ ...DRAFT, amount: "twelve" })).toEqual({ amount: expect.stringMatching(/like 29,90/) });
    expect(dateProblems({ ...DRAFT, amount: "1.500" })).toEqual({});
    expect(dateProblems(DRAFT)).toEqual({});
  });

  it("is the person's to-do: a payment one they make, in euros; with a letter, that letter's sender, thread and area", () => {
    expect(dateBody({ ...DRAFT, kind: "payment", amount: "1.500,50", title: "  Pay  the deposit " }, null)).toEqual({
      kind: "payment",
      title: "Pay the deposit",
      due_date: "2026-10-12",
      amount: 1500.5,
      currency: "EUR",
      direction: "out",
      doc_id: null,
      party_id: null,
      case_id: null,
      area: "other",
    });
    const letter = { id: "doc_x", title: null, filename: "scan.pdf", party_id: "pty_x", case_id: "cas_x", area: "home" as const };
    expect(dateBody(DRAFT, letter)).toMatchObject({ kind: "reminder", amount: null, currency: null, direction: null, doc_id: "doc_x", party_id: "pty_x", case_id: "cas_x", area: "home" });
  });

  it("sends how it repeats only when it repeats", () => {
    expect(dateBody(DRAFT, null)).not.toHaveProperty("recurrence");
    expect(dateBody({ ...DRAFT, repeat: "quarter" }, null).recurrence).toEqual({ interval: 3, unit: "months", working_day: null, day_of_month: null });
    expect(dateBody({ ...DRAFT, repeat: "working_day", workingDay: -1 }, null).recurrence).toEqual({ interval: 1, unit: "months", working_day: -1, day_of_month: null });
  });
});

describe("Repeats", () => {
  it("doesn't repeat unless chosen, and comes right after When? from the keyboard", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<AddDateDialog open onClose={() => {}} />, { client: makeTestQueryClient() });
    const dialog = await screen.findByRole("dialog", { name: "Add a date" });
    const repeats = within(dialog).getByLabelText("Repeats");
    expect(repeats).toHaveValue("never");
    // before a day is chosen, no "on the …"
    expect(within(repeats).getAllByRole("option").map((o) => o.textContent)).toEqual(["Doesn't repeat", "Every month", "Every month on a working day", "Every 3 months", "Every 6 months", "Every year"]);
    const when = within(dialog).getByLabelText("When?");
    fireEvent.change(when, { target: { value: "2026-10-20" } });
    expect(within(repeats).getAllByRole("option").map((o) => o.textContent)).toContain("Every 3 months on the 20th");
    // the next control after the day (the e2e test goes there with Tab)
    const controls = Array.from(dialog.querySelectorAll("input, select, textarea, button"));
    expect(controls.indexOf(repeats)).toBe(controls.indexOf(when) + 1);
    expect(within(dialog).queryByLabelText("Which working day?")).toBeNull();
    await user.selectOptions(repeats, "Every month on a working day");
    expect(controls.length + 1).toBe(dialog.querySelectorAll("input, select, textarea, button").length);
  });

  it("every 3 months on the 20th: sends the rule, and the toast says how it repeats", async () => {
    const { calls } = useMockApi();
    const success = vi.spyOn(toast, "success");
    const user = userEvent.setup();
    renderWithProviders(<AddDateDialog open onClose={() => {}} />, { client: makeTestQueryClient() });
    const dialog = await screen.findByRole("dialog", { name: "Add a date" });
    await fill(user, dialog, { title: "Pay the quarterly fee", date: "2026-10-20" });
    await user.selectOptions(within(dialog).getByLabelText("Repeats"), "Every 3 months on the 20th");
    await user.click(within(dialog).getByRole("button", { name: "Add date" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/items")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ due_date: "2026-10-20", recurrence: { interval: 3, unit: "months" } });
    await waitFor(() => expect(success).toHaveBeenCalledWith("Date added", expect.objectContaining({ description: "Pay the quarterly fee — Tue 20 Oct, repeats every 3 months" })));
  });

  it("every month on a working day: asks which one (the 3rd unless chosen), says how they are counted, and names the day it falls on", async () => {
    const { calls } = useMockApi();
    const success = vi.spyOn(toast, "success");
    const user = userEvent.setup();
    renderWithProviders(<AddDateDialog open onClose={() => {}} />, { client: makeTestQueryClient() });
    const dialog = await screen.findByRole("dialog", { name: "Add a date" });
    await fill(user, dialog, { title: "UStVA", date: "2026-10-14" });
    await user.selectOptions(within(dialog).getByLabelText("Repeats"), "Every month on a working day");
    const which = within(dialog).getByLabelText("Which working day?");
    expect(which).toHaveValue("3");
    expect(within(which).getAllByRole("option").map((o) => o.textContent)).toEqual(["1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th", "Last"]);
    expect(which).toHaveAccessibleDescription(/^Counted from the 1st of each month: Monday to Saturday, without public holidays \(rent: Monday to Friday\)\. The first one is in October 2026, or in the next month once October's has passed\.$/);
    await user.click(within(dialog).getByRole("button", { name: "Add date" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/items")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ recurrence: { interval: 1, unit: "months", working_day: 3 } });
    // the day it falls on (the server's, here the mock's), not the day typed
    await waitFor(() => expect(success).toHaveBeenCalledWith("Date added", expect.objectContaining({ description: "UStVA — Mon 5 Oct, repeats every month on the 3rd working day" })));
  });
});

describe("Add a date on Timeline", () => {
  it("adds a date of your own — with a letter kept private if you choose one — and it is on the timeline", async () => {
    const { calls, srv } = useMockApi();
    const success = vi.spyOn(toast, "success");
    const user = userEvent.setup();
    renderWithProviders(<TimelineView />, { client: makeTestQueryClient(), route: "/timeline" });
    await screen.findByRole("heading", { level: 2, name: "Every date" });

    await user.click(screen.getByRole("button", { name: "Add a date" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a date" });
    // the first field takes focus; every kind can be chosen, the reminder first and chosen
    expect(within(dialog).getByLabelText("What is it?")).toHaveFocus();
    expect(within(dialog).getAllByRole("radio").map((r) => r.getAttribute("value"))).toEqual(["reminder", "deadline", "payment", "appointment", "task", "expiry"]);
    expect(within(dialog).getByRole("radio", { name: "Reminder" })).toBeChecked();
    await fill(user, dialog, { title: "Pay the caretaker", date: "2026-10-20", kind: "Payment", amount: "45" });
    // a letter nobody read can be chosen (it waits in the folder, private)
    const letter = within(dialog).getByLabelText(/^Letter/);
    await waitFor(() => expect(within(letter).getByRole("option", { name: "Scan_2026-09-28_0914.pdf" })).toBeInTheDocument());
    await user.selectOptions(letter, "doc_folder_scan");
    await user.click(within(dialog).getByRole("button", { name: "Add date" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add a date" })).toBeNull());
    expect(calls.find((c) => c.method === "POST" && c.path === "/items")?.body).toMatchObject({
      kind: "payment",
      title: "Pay the caretaker",
      due_date: "2026-10-20",
      amount: 45,
      currency: "EUR",
      direction: "out",
      doc_id: "doc_folder_scan",
    });
    expect(success).toHaveBeenCalledWith("Date added", expect.objectContaining({ description: "Pay the caretaker — Tue 20 Oct" }));
    const added = srv.db.state.items.find((i) => i.title === "Pay the caretaker")!;
    expect(added).toMatchObject({ origin: "manual", grounding: "user", due_date_source: "manual", doc_id: "doc_folder_scan" });
    // on the timeline once it has loaded again
    expect(await screen.findByText("Pay the caretaker")).toBeInTheDocument();

    // "Undo" takes it away again
    const undo = success.mock.calls.at(-1)![1]!.undo!;
    await undo();
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === `/items/${added.id}`)).toBe(true));
  });

  it("says what is missing and sends nothing until it is there", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<AddDateDialog open onClose={() => {}} />, { client: makeTestQueryClient() });
    const dialog = await screen.findByRole("dialog", { name: "Add a date" });
    await user.click(within(dialog).getByRole("button", { name: "Add date" }));
    const title = within(dialog).getByLabelText("What is it?");
    expect(title).toHaveFocus();
    expect(title).toHaveAccessibleDescription(/Say what it is/);
    expect(within(dialog).getByLabelText("When?")).toHaveAccessibleDescription("Choose the day.");
    await user.type(within(dialog).getByLabelText(/^Amount/), "lots");
    expect(within(dialog).getByText(/like 29,90/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});

describe("Add a date on a letter's page", () => {
  async function detailOf(srv: ReturnType<typeof useMockApi>["srv"], id: string): Promise<DocumentDetail> {
    return (await (await srv.handle("GET", `/documents/${id}`, new URLSearchParams(), undefined)).json()) as DocumentDetail;
  }

  it("is there on a letter kept private, which has no dates of its own, and adds one to it", async () => {
    const { calls, srv } = useMockApi();
    const user = userEvent.setup();
    const detail = await detailOf(srv, "doc_folder_scan");
    const client = makeTestQueryClient();
    const view = renderWithProviders(<DocumentView detail={detail} />, { client });

    const todos = screen.getByRole("region", { name: "To-dos & dates" });
    expect(todos).toHaveTextContent("Claude didn't read this letter, so Ordnung found no dates in it. Add the ones that matter to you.");
    await user.click(within(todos).getByRole("button", { name: "Add a date" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a date" });
    // the letter is the page's: not asked for
    expect(dialog).toHaveAccessibleDescription(/For “Scan_2026-09-28_0914\.pdf”/);
    expect(within(dialog).queryByLabelText(/^Letter/)).toBeNull();
    await fill(user, dialog, { title: "Reply to the building management", date: "2026-10-09", kind: "Deadline" });
    await user.click(within(dialog).getByRole("button", { name: "Add date" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/items")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ kind: "deadline", doc_id: "doc_folder_scan", due_date: "2026-10-09" });

    // the letter's page lists it, with the person's own to-dos' actions
    view.unmount();
    renderWithProviders(<DocumentView detail={await detailOf(srv, "doc_folder_scan")} />, { client });
    const listed = screen.getByRole("region", { name: /To-dos & dates/ });
    expect(within(listed).getByRole("button", { name: "Mark “Reply to the building management” as done" })).toBeInTheDocument();
    expect(within(listed).getByText("Date set by you")).toBeInTheDocument();
  });

  it("is there on a letter Claude couldn't read — no placeholders that never fill, one 'Try again'", async () => {
    vi.stubGlobal("fetch", async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
    const doc = makeDoc({ status: "failed", kind: null, title: null, filename: "Stadtwerke.pdf", error: "The 'claude' command was not found.", ai_processed_at: null });
    const { container } = renderWithProviders(<DocumentView detail={makeDetail({ document: doc })} />, { client: makeTestQueryClient() });
    expect(screen.getByRole("heading", { level: 1, name: "Ordnung couldn't read this letter" })).toBeInTheDocument();
    const todos = screen.getByRole("region", { name: "To-dos & dates" });
    expect(within(todos).getByRole("button", { name: "Add a date" })).toBeInTheDocument();
    // the letter's panel (beside the page image, which loads as it does) has nothing waiting to load
    expect(container.querySelector("#doc-view-panel-letter-more .animate-pulse")).toBeNull();
    expect(screen.getAllByRole("button", { name: /Try again|Read again/ }).map((b) => b.textContent)).toEqual(["Try again"]);
  });

  it("is there under a read letter's own to-dos too", async () => {
    vi.stubGlobal("fetch", async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
    const detail = makeDetail({ items: [makeItem({ id: "itm_1", doc_id: "doc_1", title: "Pay the fee" })] });
    renderWithProviders(<DocumentView detail={detail} />, { client: makeTestQueryClient() });
    const todos = screen.getByRole("region", { name: /To-dos & dates/ });
    expect(within(todos).getByRole("button", { name: "Add a date" })).toBeInTheDocument();
    expect(within(todos).getByRole("button", { name: "Mark “Pay the fee” as done" })).toBeInTheDocument();
  });
});
