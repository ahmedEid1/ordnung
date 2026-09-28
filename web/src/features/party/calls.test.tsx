import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { PartyDrawer } from "./PartyDrawer";
import { formatMoney } from "@/lib/format";
import { callNoteProblems, promisedAmount, type CallNoteDraft } from "./calls";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

const TODAY = "2026-09-28";
const blank: CallNoteDraft = { calledOn: TODAY, contact: "", summary: "Asked about the refund.", promise: "", promiseDue: "", amount: "", caseId: "" };

describe("call note checks", () => {
  it("accepts a note without a promise", () => {
    expect(callNoteProblems(blank, TODAY)).toEqual({});
  });

  it("needs a day that isn't in the future, and what was said", () => {
    expect(callNoteProblems({ ...blank, calledOn: "" }, TODAY)).toHaveProperty("calledOn");
    expect(callNoteProblems({ ...blank, calledOn: "2026-09-29" }, TODAY).calledOn).toMatch(/future/);
    expect(callNoteProblems({ ...blank, summary: "   " }, TODAY).summary).toMatch(/what was said/);
  });

  it("asks what was promised when a day or an amount is given", () => {
    expect(callNoteProblems({ ...blank, promiseDue: "2026-10-05" }, TODAY).promise).toBeDefined();
    expect(callNoteProblems({ ...blank, amount: "29,90" }, TODAY).promise).toBeDefined();
    expect(callNoteProblems({ ...blank, promise: "Refund", promiseDue: "2026-10-05", amount: "29,90" }, TODAY)).toEqual({});
  });

  it("refuses a promised day before the call and amounts that aren't amounts", () => {
    expect(callNoteProblems({ ...blank, promise: "Refund", promiseDue: "2026-09-01" }, TODAY).promiseDue).toMatch(/before the call/);
    expect(callNoteProblems({ ...blank, promise: "Refund", amount: "abc" }, TODAY).amount).toMatch(/euros/);
    expect(callNoteProblems({ ...blank, promise: "Refund", amount: "-5" }, TODAY).amount).toBeDefined();
    expect(callNoteProblems({ ...blank, promise: "Refund", amount: "1e308" }, TODAY).amount).toBeDefined();
    expect(callNoteProblems({ ...blank, promise: "Refund", amount: "2.000.000" }, TODAY).amount).toMatch(/up to/);
  });

  it("reads amounts the German way: 1.500 is fifteen hundred, never 1,50", () => {
    const amount = (typed: string) => promisedAmount({ amount: typed });
    expect(amount("1.500")).toBe(1500);
    expect(amount("2.000")).toBe(2000);
    expect(amount("1.234,56")).toBe(1234.56);
    expect(amount("29,90")).toBe(29.9);
    expect(amount("1,5")).toBe(1.5);
    expect(amount("29.90")).toBe(29.9);
    expect(amount("")).toBeNull();
    expect(callNoteProblems({ ...blank, promise: "Refund", amount: "1.234,56" }, TODAY)).toEqual({});
  });
});

function renderDrawer(party = "pty_fitwell", extra = "") {
  return renderWithProviders(
    <>
      <PartyDrawer />
      <Toaster />
    </>,
    { route: `/?party=${party}${extra}` },
  );
}

describe("Calls in the party drawer", () => {
  it("lists the noted calls with their promise", async () => {
    useMockApi();
    const { container } = renderDrawer();
    const calls = await screen.findByRole("region", { name: /^Calls/ });
    expect(await within(calls).findByText(/Herr Brandt, member services/)).toBeInTheDocument();
    expect(within(calls).getByText("Written confirmation of the cancellation")).toBeInTheDocument();
    expect(within(calls).getByRole("button", { name: "They kept it" })).toBeInTheDocument();
    assertNoRawEnumsInElement(container);
  });

  it("notes a call with a dated promise — no AI involved — and puts it on Waiting for", async () => {
    const { calls, srv } = useMockApi();
    const user = userEvent.setup();
    renderDrawer();
    const section = await screen.findByRole("region", { name: /^Calls/ });
    await user.click(within(section).getByRole("button", { name: "Note a call" }));
    const form = within(section).getByRole("form", { name: "Note a call" });
    expect(within(form).getByLabelText("When")).toHaveFocus(); // the form opens where you start
    // nothing written yet: the form says what's missing, and takes you there
    await user.clear(within(form).getByLabelText("What was said"));
    await user.click(within(form).getByRole("button", { name: "Save note" }));
    expect(within(form).getByText("Write down what was said.")).toBeInTheDocument();
    expect(within(form).getByLabelText("What was said")).toHaveFocus();
    expect(calls.some((c) => c.method === "POST" && c.path === "/calls")).toBe(false);

    await user.type(within(form).getByLabelText(/Who you spoke to/), "Frau Weber");
    await user.type(within(form).getByLabelText("What was said"), "They will refund the September fee.");
    await user.type(within(form).getByLabelText(/What they promised/), "Refund of the September fee");
    await user.type(within(form).getByLabelText(/^By/), "2026-10-05");
    await user.type(within(form).getByLabelText(/Amount/), "1.234,56");
    expect(within(form).getByText(`= ${formatMoney(1234.56)}`)).toBeInTheDocument(); // how it was read
    await user.click(within(form).getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/calls")).toBe(true));
    expect(calls.find((c) => c.method === "POST" && c.path === "/calls")?.body).toEqual({
      party_id: "pty_fitwell",
      case_id: null,
      called_on: TODAY,
      contact: "Frau Weber",
      summary: "They will refund the September fee.",
      promise: "Refund of the September fee",
      promise_due: "2026-10-05",
      promise_amount: 1234.56,
    });
    expect(await screen.findByText("Call noted")).toBeInTheDocument();
    // the form is gone: back to the button that opened it
    await waitFor(() => expect(within(section).getByRole("button", { name: "Note a call" })).toHaveFocus());
    expect(screen.getByText("Its promise is on your Waiting for list.")).toBeInTheDocument();
    expect(await within(section).findByText("They will refund the September fee.")).toBeInTheDocument();
    // the promise is waited for
    const waiting = (await (await srv.handle("GET", "/waiting", new URLSearchParams(), undefined)).json()) as { title: string; source: string }[];
    expect(waiting).toContainEqual(expect.objectContaining({ source: "call", title: "Refund of the September fee" }));
    // and nothing asked AI anything
    expect(calls.some((c) => c.path.startsWith("/ask") || c.path.startsWith("/chat"))).toBe(false);
  });

  it("opens with the form and the thread chosen when Waiting for asks to note a call", async () => {
    const { calls, srv } = useMockApi();
    srv.db.state.cases.push({ ...srv.db.state.cases[0]!, id: "cas_fitwell", title: "Membership FW-20931", party_id: "pty_fitwell", reference: "FW-20931" });
    const user = userEvent.setup();
    const { router } = renderDrawer("pty_fitwell", "&call=cas_fitwell");
    const section = await screen.findByRole("region", { name: /^Calls/ });
    const form = await within(section).findByRole("form", { name: "Note a call" });
    expect(within(form).getByLabelText(/Thread/)).toHaveValue("cas_fitwell");
    await waitFor(() => expect(within(form).getByLabelText("When")).toHaveFocus());
    await user.type(within(form).getByLabelText("What was said"), "Still nothing in writing; they'll send it Friday.");
    await user.click(within(form).getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/calls")?.body).toMatchObject({ party_id: "pty_fitwell", case_id: "cas_fitwell" }));
    // done: a reload doesn't open the form again, and the drawer stays
    await waitFor(() => expect(router.state.location.search).toBe("?party=pty_fitwell"));
    expect(await within(section).findByRole("button", { name: "Note a call" })).toBeInTheDocument();
  });

  it("opens the form without a thread when the call is about none", async () => {
    useMockApi();
    const user = userEvent.setup();
    const { router } = renderDrawer("pty_fitwell", "&call=new");
    const section = await screen.findByRole("region", { name: /^Calls/ });
    const form = await within(section).findByRole("form", { name: "Note a call" });
    await user.click(within(form).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(router.state.location.search).toBe("?party=pty_fitwell"));
    await waitFor(() => expect(within(section).queryByRole("form", { name: "Note a call" })).not.toBeInTheDocument());
  });

  it("deletes a note after asking", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderDrawer();
    const section = await screen.findByRole("region", { name: /^Calls/ });
    await user.click(await within(section).findByRole("button", { name: "Delete the note of the call on Wed 23 Sep" }));
    const confirm = within(section).getByRole("group", { name: "Delete this note?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/calls/cal_fitwell")).toBe(true));
    expect(await within(section).findByText(/No calls noted/)).toBeInTheDocument();
    await waitFor(() => expect(within(section).getByRole("heading", { name: /^Calls/ })).toHaveFocus()); // not <body>
  });
});
