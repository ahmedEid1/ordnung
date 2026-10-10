/**
 * The Tax year page (`/inbox/taxes?year=YYYY`): a year's letters for taxes by kind with their tax notes, the next
 * year's early statements, the undated ones, both empty states, and Export — on the computer only, and not in the
 * online demo.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import type { Document } from "@/api/types";
import { makeDoc } from "@/features/document/fixtures";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import type { MockServer } from "@/mocks/server";
import TaxYearPage from "./TaxYearPage";

const mode = vi.hoisted(() => ({ staticDemo: false }));
vi.mock("@/mocks/mode", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/mocks/mode")>()), isStaticDemo: () => mode.staticDemo }));

const tax = (id: string, fields: Partial<Document> = {}): Document =>
  makeDoc({ id, title: id, tax_relevant: true, doc_date: null, received_date: null, party_id: null, ...fields });

function useLetters(srv: MockServer, docs: Document[]) {
  srv.db.state.documents = docs;
}

function renderPage(route: string, today?: string) {
  const client = makeTestQueryClient();
  if (today) client.setQueryData(qk.health, { ...TEST_HEALTH, today, simulated_today: today });
  return renderWithProviders(
    <>
      <TaxYearPage />
      <Toaster />
    </>,
    { route, client },
  );
}

/** The page's h1, once its letters have loaded. */
async function heading(name: string) {
  await waitFor(() => expect(screen.queryByText("Loading your letters…")).toBeNull());
  return screen.findByRole("heading", { level: 1, name });
}

beforeEach(() => {
  mode.staticDemo = false;
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

describe("TaxYearPage", () => {
  it("lists the year's letters for taxes by kind, each with its tax note", async () => {
    // the demo's payslip (with Claude's note), and an assessment marked without one
    const { srv } = useMockApi();
    srv.db.state.documents.push(tax("Tax assessment 2025", { kind: "tax_assessment", doc_date: "2026-09-15", party_id: "pty_finanzamt" }));
    const { container } = renderPage("/inbox/taxes?year=2026");
    await heading("Tax year 2026");
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Payslip· 1 (1 letter)", "Tax assessment· 1 (1 letter)"]);
    const payslip = screen.getByRole("link", { name: "Payslip August 2026" }).closest("li")!;
    expect(within(payslip).getByText(/For your tax return:/)).toBeInTheDocument();
    expect(within(payslip).getByText(/Keep for your 2026 tax return/)).toBeInTheDocument();
    const assessment = screen.getByRole("link", { name: "Tax assessment 2025" }).closest("li")!;
    expect(within(assessment).getByText("Marked for taxes.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2 letters dated 2026.");
    expect(screen.getByRole("button", { name: "Export these letters…" })).toBeEnabled();
    assertNoRawEnumsInElement(container);
  });

  it("shows the year chosen, and a change of year goes into the address", async () => {
    const { srv } = useMockApi();
    useLetters(srv, [tax("Payslip March", { kind: "payslip", doc_date: "2025-03-31" }), tax("Payslip July", { kind: "payslip", doc_date: "2025-07-31" }), tax("Payslip 2026", { kind: "payslip", doc_date: "2026-08-31" })]);
    const { router } = renderPage("/inbox/taxes");
    // September: this year first
    await heading("Tax year 2026");
    const year = screen.getByRole("combobox", { name: "Year" });
    expect(within(year).getAllByRole("option").map((o) => o.textContent)).toEqual(["2026 · 1 letter", "2025 · 2 letters"]);
    await userEvent.selectOptions(year, "2025");
    await heading("Tax year 2025");
    expect(router.state.location.search).toBe("?year=2025");
    expect(screen.getByRole("link", { name: "Payslip March" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Payslip 2026" })).toBeNull();
  });

  it("during the tax season shows last year first, with the tax Idea's own sentence", async () => {
    const { srv } = useMockApi();
    useLetters(srv, [tax("Payslip 2025", { kind: "payslip", doc_date: "2025-12-31" }), tax("Payslip 2026", { kind: "payslip", doc_date: "2026-02-28" })]);
    renderPage("/inbox/taxes", "2026-03-01");
    await heading("Tax year 2025");
    expect(screen.getByRole("status")).toHaveTextContent(
      "1 letter dated 2025. If you have to file a return it is usually due by the end of July; filing voluntarily is possible for four years and often brings money back.",
    );
  });

  it("lists the next year's statements dated January to May too, to be checked", async () => {
    const { srv } = useMockApi();
    useLetters(srv, [
      tax("Payslip December", { kind: "payslip", doc_date: "2025-12-31" }),
      tax("Lohnsteuerbescheinigung 2025", { kind: "payslip", doc_date: "2026-02-10" }),
      tax("Insurance June", { kind: "insurance", doc_date: "2026-06-01" }),
    ]);
    renderPage("/inbox/taxes?year=2025");
    await heading("Tax year 2025");
    const callout = screen.getByText("Papers for 2025 that come in 2026").closest("[data-callout], div")!;
    expect(callout).toBeInTheDocument();
    expect(screen.getByText(/The letter for taxes dated January–May 2026 is listed below too; check which year it is for\./)).toBeInTheDocument();
    expect(screen.getByText("Lohnsteuerbescheinigung", { selector: "[lang='de']" })).toBeInTheDocument();
    const early = screen.getByRole("heading", { level: 3, name: /^Dated January–May 2026/ }).closest("section")!;
    expect(within(early).getByRole("link", { name: "Lohnsteuerbescheinigung 2025" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Insurance June" })).toBeNull();
  });

  it("shows each row's date on the letter, the date it is filed by", async () => {
    const { srv } = useMockApi();
    useLetters(srv, [
      tax("Statement", { kind: "insurance", doc_date: "2026-05-29", received_date: "2026-06-02" }),
      tax("Payslip", { kind: "payslip", doc_date: null, received_date: "2025-12-01" }),
    ]);
    renderPage("/inbox/taxes?year=2025", "2026-09-28");
    await heading("Tax year 2025");
    const early = screen.getByRole("heading", { level: 3, name: /^Dated January–May 2026/ }).closest("section")!;
    const statement = within(early).getByRole("link", { name: "Statement" }).closest("li")!;
    expect(within(statement).getAllByTitle("Dated Fri 29 May · arrived Tue 2 Jun")[0]).toHaveTextContent("Dated 29 May");
    // a letter without a date of its own is filed by the day it arrived, and says so
    const payslip = screen.getByRole("link", { name: "Payslip" }).closest("li")!;
    expect(within(payslip).getAllByTitle(/^Arrived Mon 1 Dec/)[0]).toBeInTheDocument();
  });

  it("names the letters for taxes that have no date, which belong to no year", async () => {
    const { srv } = useMockApi();
    useLetters(srv, [tax("Payslip", { kind: "payslip", doc_date: "2026-08-31" }), tax("Laptop receipt", { id: "doc_laptop", kind: "receipt" })]);
    renderPage("/inbox/taxes?year=2026");
    await heading("Tax year 2026");
    const line = screen.getByText(/1 letter for taxes has no date, so it isn't in any year:/);
    expect(within(line).getByRole("link", { name: "Laptop receipt" })).toHaveAttribute("href", "/documents/doc_laptop");
  });

  it("says when there are no letters for taxes yet", async () => {
    const { srv } = useMockApi();
    useLetters(srv, [makeDoc({ id: "rent", title: "Rent", tax_relevant: false })]);
    renderPage("/inbox/taxes");
    await heading("Letters for taxes");
    expect(await screen.findByRole("heading", { name: "No letters for taxes yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the Inbox" })).toHaveAttribute("href", "/inbox");
    expect(screen.queryByRole("button", { name: "Export these letters…" })).toBeNull();
  });

  it("says when the year chosen has none", async () => {
    const { srv } = useMockApi();
    useLetters(srv, [tax("Payslip", { kind: "payslip", doc_date: "2026-08-31" })]);
    renderPage("/inbox/taxes?year=2023");
    await heading("Tax year 2023");
    expect(screen.getByRole("heading", { name: "No letters for taxes dated 2023" })).toBeInTheDocument();
    expect(screen.getByText("Choose another year above.")).toBeInTheDocument();
    expect(within(screen.getByRole("combobox", { name: "Year" })).getAllByRole("option").map((o) => o.textContent)).toEqual(["2026 · 1 letter", "2023 · 0 letters"]);
    // nothing to export for that year
    expect(screen.queryByRole("button", { name: "Export these letters…" })).toBeNull();
  });

  it("opens the export with this year, the letters for taxes and the early statements", async () => {
    const { srv } = useMockApi();
    useLetters(srv, [tax("Payslip", { kind: "payslip", doc_date: "2025-08-31" }), tax("Statement", { kind: "insurance", doc_date: "2026-02-10" })]);
    renderPage("/inbox/taxes?year=2025");
    await userEvent.click(await screen.findByRole("button", { name: "Export these letters…" }));
    const dialog = await screen.findByRole("dialog", { name: "Export letters" });
    expect(within(dialog).getByRole("status")).toHaveTextContent("2 letters will be in the ZIP.");
    const link = within(dialog).getByRole("link", { name: "Download ZIP" });
    expect(new URL(link.getAttribute("href")!, "http://x").search).toBe("?year=2025&until=2026-05-31&tax=true");
  });

  it("on a paired phone, says to export on the computer instead of offering it", async () => {
    const { srv } = useMockApi({ client: "phone" });
    useLetters(srv, [tax("Payslip", { kind: "payslip", doc_date: "2026-08-31" })]);
    renderPage("/inbox/taxes?year=2026");
    await heading("Tax year 2026");
    expect(screen.queryByRole("button", { name: "Export these letters…" })).toBeNull();
    expect(screen.getByText("Export them on your computer.")).toBeInTheDocument();
    await waitFor(() => expect(srv.refused).toEqual([]));
  });

  it("in the online demo, keeps Export off and says why", async () => {
    mode.staticDemo = true;
    useMockApi({ full: true, staticDemo: true });
    renderPage("/inbox/taxes?year=2026");
    await heading("Tax year 2026");
    expect(screen.getByRole("button", { name: "Export these letters…" })).toBeDisabled();
    expect(screen.getByText("Exporting isn't available in the online demo — it keeps no files. Install Ordnung to export your own letters.")).toBeInTheDocument();
  });
});
