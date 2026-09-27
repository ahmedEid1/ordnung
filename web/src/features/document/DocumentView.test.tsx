import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, makeTestQueryClient } from "@/test/render";
import { qk } from "@/api/hooks";
import type { DocumentDetail } from "@/api/types";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { createMockServer } from "@/mocks/server";
import { toast } from "@/components/ui/Toast";
import { DocumentView } from "./DocumentView";
import { DocumentWarnings } from "./Warnings";
import { makeDetail, makeDoc, makeItem } from "./fixtures";

async function detailFromMock(id: string): Promise<DocumentDetail> {
  const srv = createMockServer({ staticDemo: false, latency: 0 });
  srv.openAllMail();
  const res = await srv.handle("GET", `/documents/${id}`, new URLSearchParams(), undefined);
  return (await res.json()) as DocumentDetail;
}

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

let fetchSpy: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchSpy = vi.fn(async () => new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchSpy);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Document viewer — tax assessment (phone photo, Einspruch)", () => {
  it("shows the verdict: what, what to do, by when (+ Why this date?), if ignored and the objection draft", async () => {
    const detail = await detailFromMock("doc_tax");
    const { container } = renderWithProviders(<DocumentView detail={detail} />, { client: client() });
    const verdict = screen.getByRole("article", { name: "Income tax assessment 2025" });
    expect(within(verdict).getByText("Tax assessment")).toBeInTheDocument();
    expect(within(verdict).getByText(/Decide whether to object/)).toBeInTheDocument();
    expect(within(verdict).getByText("Wed 21 Oct")).toBeInTheDocument();
    expect(within(verdict).getByText("in 23 days")).toBeInTheDocument();
    expect(within(verdict).getByRole("button", { name: /Why this date\?/ })).toBeInTheDocument();
    expect(within(verdict).getByText(/can hardly be changed/)).toBeInTheDocument();
    expect(within(verdict).getByRole("button", { name: "Draft objection" })).toBeInTheDocument();
    expect(within(verdict).queryByRole("button", { name: /^Pay/ })).toBeNull();
    expect(within(verdict).getByText(/Not legal advice/)).toBeInTheDocument();
    // explained simply with the German term explained
    const explained = screen.getByRole("region", { name: "Explained simply" });
    expect(within(explained).getByText("Einspruch", { selector: "[lang=de]" })).toBeInTheDocument();
    // provenance
    expect(screen.getByText(/Read by Claude on .* from a photo, 2 pages/)).toBeInTheDocument();
    assertNoRawEnumsInElement(container);
  });

  it("opens the receipt with the plain sentence first and the rules on demand", async () => {
    const detail = await detailFromMock("doc_tax");
    renderWithProviders(<DocumentView detail={detail} />, { client: client() });
    const user = userEvent.setup();
    await user.click(within(screen.getByRole("article")).getByRole("button", { name: /Why this date\?/ }));
    const pop = await screen.findByRole("dialog", { name: "Why this date?" });
    expect(within(pop).getByText(/counts as delivered on Sat 19 Sep/)).toBeInTheDocument();
    expect(within(pop).getByText(/Medium confidence/)).toBeInTheDocument();
    // the rules are there for "Show the rules" to point at, but hidden until asked for
    expect(within(pop).getByText("§ 122 Abs. 2 Nr. 1 AO")).not.toBeVisible();
    const show = within(pop).getByRole("button", { name: "Show the rules" });
    expect(show).toHaveAttribute("aria-expanded", "false");
    await user.click(show);
    expect(within(pop).getByText("§ 122 Abs. 2 Nr. 1 AO")).toBeVisible();
    // the chevron turns with the state
    expect(within(pop).getByRole("button", { name: "Hide the rules" }).className).toContain("[&_svg]:rotate-180");
    expect(within(pop).getByText(/Germany \+ North Rhine-Westphalia/)).toBeInTheDocument();
    expect(within(pop).getByText(/Not legal advice/)).toBeInTheDocument();
  });

  it("clicking where a fact was found shows what the AI read from the photo", async () => {
    const detail = await detailFromMock("doc_tax");
    renderWithProviders(<DocumentView detail={detail} />, { client: client() });
    const user = userEvent.setup();
    const facts = screen.getByRole("region", { name: "Key facts" });
    await user.click(within(facts).getAllByRole("button", { name: /Read by AI from the photo/ })[0]!);
    const callout = await screen.findByRole("status", { name: "" });
    expect(within(callout).getByText(/Erstattung 324,00 EUR/)).toBeInTheDocument();
    expect(within(callout).getByText(/Worth comparing with the paper letter/)).toBeInTheDocument();
    // the matching highlight on the page is pressed
    expect(screen.getByRole("button", { name: /^Refund: €324\.00/, pressed: true })).toBeInTheDocument();
  });
});

describe("Document viewer — suspected scam", () => {
  it("warns loudly, never offers to pay and shows the hidden-text banner", async () => {
    const detail = await detailFromMock("doc_scam");
    const { container } = renderWithProviders(<DocumentView detail={detail} />, { client: client() });
    expect(screen.getByRole("alert", { name: "" })).toHaveTextContent("This looks like a scam — don't pay");
    expect(screen.getByText(/No warning does not mean it is safe/)).toBeInTheDocument();
    expect(screen.getByText("This document contains hidden text aimed at software — we ignored it")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Pay/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Compare with your real letter/ })).toHaveAttribute("href", "/documents/doc_rundfunk");
    expect(screen.getByText(/don't pay to this account/)).toBeInTheDocument();
    assertNoRawEnumsInElement(container);
  });
});

describe("warnings & Please check", () => {
  it("asks for advice (no computed date) when the letter can only be challenged in court", () => {
    const d = makeDetail({ document: makeDoc({ remedy: { type: "klage", addressee: "Sozialgericht Musterstadt", period_text: null, form_text: null, quote: null } }) });
    renderWithProviders(<DocumentWarnings detail={d} />, { client: client() });
    expect(screen.getByText(/only be challenged in court — get advice/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Verbraucherzentrale/ })).toHaveAttribute("target", "_blank");
  });

  it("flags unclear objection instructions with the 1-year hint, without claiming it applies", () => {
    const d = makeDetail({ document: makeDoc({ remedy: { type: "unclear", addressee: null, period_text: null, form_text: null, quote: null } }) });
    renderWithProviders(<DocumentWarnings detail={d} />, { client: client() });
    expect(screen.getByText(/couldn't tell how to object/)).toBeInTheDocument();
    expect(screen.getByText(/don't rely on it/)).toBeInTheDocument();
  });

  it("lets the person correct, re-date or dismiss a to-do whose sentence wasn't found", async () => {
    const it1 = makeItem({
      id: "itm_x",
      title: "Pay the back payment",
      due_date: "2026-10-09",
      grounding: "unverified",
      evidence: [{ doc_id: "doc_1", page: null, quote: "bis zum 09.10.2026", grounding: "unverified", value_consistent: true, score: 0.4, boxes: [] }],
    });
    const { container } = renderWithProviders(<DocumentWarnings detail={makeDetail({ items: [it1] })} />, { client: client() });
    expect(screen.getByText("Please check")).toBeInTheDocument();
    expect(screen.getByText("Couldn't find this — please check.")).toBeInTheDocument();
    expect(screen.getByText("“bis zum 09.10.2026”")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Not a real to-do" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [url, init] = fetchSpy.mock.calls[0]! as [string, RequestInit];
    expect(url).toBe("/api/items/itm_x");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ status: "dismissed" });

    await user.click(screen.getByRole("button", { name: "Change date" }));
    const input = screen.getByLabelText(/New date for/);
    await user.clear(input);
    await user.type(input, "2026-10-12");
    await user.click(screen.getByRole("button", { name: "Save date" }));
    await waitFor(() => expect(fetchSpy.mock.calls.some(([, i]) => (i as RequestInit).body === JSON.stringify({ due_date: "2026-10-12" }))).toBe(true));
    assertNoRawEnumsInElement(container);
  });

  it("asks when a letter arrived when the period starts on receipt", async () => {
    const detail = await detailFromMock("doc_parking");
    renderWithProviders(<DocumentWarnings detail={detail} />, { client: client() });
    expect(screen.getByText("When did this letter arrive?")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Yesterday" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [url, init] = fetchSpy.mock.calls[0]! as [string, RequestInit];
    expect(url).toBe("/api/documents/doc_parking");
    expect(JSON.parse(String(init.body))).toEqual({ received_date: "2026-09-27" });
  });

  it("says a late arrival may not move a company's date, and what saving the day did", async () => {
    // reviewer repro: the engine still counted from the day the letter usually counts as delivered,
    // but the toast said "Counting from <arrival>, when the letter arrived"
    const gym = await detailFromMock("doc_gym_price");
    const company = { ...gym, party: { ...gym.party!, kind: "company" as const } };
    const item = company.items.find((i) => i.id === "itm_gym_price")!;
    const late = { label: "It arrived on Sun 27 Sep 2026, later than …", date: "2026-09-21", rule_id: "private_sender_late_arrival", citation: null };
    const recomputed = {
      ...company,
      items: [{ ...item, computation: { ...item.computation!, rule_ids: ["private_sender_late_arrival", "bgb_187_1"], steps: [late] } }],
    };
    fetchSpy.mockImplementation(async (url: string, init?: RequestInit) => {
      const body = init?.method === "PATCH" ? company.document : url === "/api/documents/doc_gym_price" ? recomputed : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    const success = vi.spyOn(toast, "success");
    renderWithProviders(<DocumentWarnings detail={company} />, { client: client() });
    expect(screen.getByText(/unless it took longer than letters usually do: this sender may be an authority/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Yesterday" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(success).toHaveBeenCalled());
    expect(success.mock.calls[0]![1]!.description).toMatch(/^The letter arrived later than letters usually take, so to be safe we still count from Mon 21 Sep/);
    success.mockRestore();
  });

  it("asks a gym's letter's arrival day plainly: it always counts from that day", async () => {
    renderWithProviders(<DocumentWarnings detail={await detailFromMock("doc_gym_price")} />, { client: client() });
    expect(screen.getByText("When did this letter arrive?")).toBeInTheDocument();
    expect(screen.queryByText(/may be an authority/)).toBeNull();
  });

  it("renders nothing when all is well", () => {
    const { container } = renderWithProviders(<DocumentWarnings detail={makeDetail()} />, { client: client() });
    expect(container.querySelector("section")).toBeNull();
  });
});
