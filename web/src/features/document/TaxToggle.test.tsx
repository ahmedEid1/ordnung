/**
 * "For taxes" on a letter's page (D3): one press marks a letter for taxes or takes it off, over Claude's mark;
 * the line under the footer says who decided; the toast's Undo puts back exactly the choice before the press
 * (`null` when there was none, which brings Claude's mark back). Hidden where a choice can't be made.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk, useDocument } from "@/api/hooks";
import { setClientKind } from "@/api/clientKind";
import type { DocumentDetail } from "@/api/types";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { useMockApi, type FetchCall } from "@/test/mockFetch";
import { DocumentFooter } from "./DocumentFooter";
import { makeDetail, makeDoc } from "./fixtures";
import { TaxState, TaxToggle, taxStateLine, taxToggleShown } from "./TaxToggle";

afterEach(() => {
  vi.unstubAllGlobals();
  setClientKind("computer");
  act(() => __clearToasts());
});

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

/** The toggle and its line as the footer places them, for a letter the mock API serves. */
function Letter({ id }: { id: string }) {
  const q = useDocument(id);
  if (!q.data) return null;
  return (
    <>
      <TaxToggle detail={q.data} />
      <TaxState detail={q.data} />
    </>
  );
}

function renderLetter(id: string) {
  return renderWithProviders(
    <>
      <Letter id={id} />
      <Toaster />
    </>,
    { client: client() },
  );
}

const toggle = () => screen.findByRole("button", { name: "For taxes" });
const patches = (calls: FetchCall[], id: string) => calls.filter((c) => c.method === "PATCH" && c.path === `/documents/${id}`).map((c) => c.body);

describe("the For taxes toggle", () => {
  it("the For taxes toggle shows its state with aria-pressed and says who decided", () => {
    const year = (doc: Partial<DocumentDetail["document"]>, choice: boolean | null) => {
      const detail = makeDetail({ document: makeDoc({ id: "doc_x", doc_date: "2025-11-03", ...doc }), tax_choice: choice });
      const view = renderWithProviders(
        <>
          <TaxToggle detail={detail} />
          <TaxState detail={detail} />
        </>,
        { client: client() },
      );
      const button = screen.getByRole("button", { name: "For taxes" });
      const line = document.getElementById("tax-state-doc_x");
      const out = { pressed: button.getAttribute("aria-pressed"), line: line?.textContent ?? null, describedBy: button.getAttribute("aria-describedby") };
      view.unmount();
      return out;
    };
    // Claude marked it, without a note of its own: the line says so ("Explained simply" has no box for it)
    expect(year({ tax_relevant: true }, null)).toEqual({
      pressed: "true",
      line: "Claude marked this letter for taxes when it read it. All letters for taxes from 2025",
      describedBy: "tax-state-doc_x",
    });
    // with Claude's note, "Explained simply" says it and links the year: no line
    expect(year({ tax_relevant: true, tax_note: "Keep it." }, null)).toEqual({ pressed: "true", line: null, describedBy: null });
    expect(year({ tax_relevant: false }, null)).toEqual({ pressed: "false", line: null, describedBy: null });
    expect(year({ tax_relevant: false }, true)).toEqual({
      pressed: "true",
      line: "You marked this letter for taxes. All letters for taxes from 2025",
      describedBy: "tax-state-doc_x",
    });
    expect(year({ tax_relevant: true, tax_note: "Keep it." }, false)).toEqual({
      pressed: "false",
      line: "You took this letter off your letters for taxes. Claude had marked it.",
      describedBy: "tax-state-doc_x",
    });
    // taking off a letter Claude never marked: nothing to say
    expect(year({ tax_relevant: false }, false)).toEqual({ pressed: "false", line: null, describedBy: null });
    // the link goes to the letter's tax year, by its date, else the day it arrived; none without either
    expect(taxStateLine(makeDoc({ tax_relevant: false }), true)).toBe("You marked this letter for taxes.");
    renderWithProviders(<TaxState detail={makeDetail({ document: makeDoc({ id: "doc_y", doc_date: null, received_date: "2024-12-30" }), tax_choice: true })} />, { client: client() });
    expect(screen.getByRole("link", { name: "All letters for taxes from 2024" })).toHaveAttribute("href", "/inbox/taxes?year=2024");
  });

  it("pressing sends the opposite of what is shown; Undo sends exactly the choice before, null when there was none", async () => {
    const { srv, calls } = useMockApi({ full: true }); // the tax assessment is in New mail
    const user = userEvent.setup();
    renderLetter("doc_tax");
    // Claude marked it: on, no choice of the person's
    expect(await toggle()).toHaveAttribute("aria-pressed", "true");
    await user.click(await toggle());
    await waitFor(() => expect(screen.getByText("Not marked for taxes")).toBeInTheDocument());
    expect(screen.getByText("It's no longer on your Tax year 2026 page.")).toBeInTheDocument();
    await waitFor(async () => expect(await toggle()).toHaveAttribute("aria-pressed", "false"));
    expect(screen.getByText("You took this letter off your letters for taxes. Claude had marked it.")).toBeInTheDocument();
    expect(srv.db.state.taxChoices).toEqual({ doc_tax: false });
    // Claude's own mark stays on the letter
    expect(srv.db.document("doc_tax")!.tax_relevant).toBe(true);

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(async () => expect(await toggle()).toHaveAttribute("aria-pressed", "true"));
    expect(patches(calls, "doc_tax")).toEqual([{ tax_choice: false }, { tax_choice: null }]);
    expect(srv.db.state.taxChoices).toEqual({});
    // no second toast, and focus is back on the toggle (it was in the toast)
    expect(screen.queryByText("Marked for taxes")).toBeNull();
    await waitFor(async () => expect(await toggle()).toHaveFocus());
  });

  it("Undo puts back a choice the person had made before, not Claude's mark", async () => {
    const { srv, calls } = useMockApi();
    srv.db.state.taxChoices.doc_dentist = false;
    const user = userEvent.setup();
    renderLetter("doc_dentist");
    expect(await toggle()).toHaveAttribute("aria-pressed", "false");
    await user.click(await toggle());
    await waitFor(async () => expect(await toggle()).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByText("Marked for taxes")).toBeInTheDocument();
    expect(screen.getByText("It's on your Tax year 2026 page.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(srv.db.state.taxChoices).toEqual({ doc_dentist: false }));
    expect(patches(calls, "doc_dentist")).toEqual([{ tax_choice: true }, { tax_choice: false }]);
  });

  it("a second press replaces the toast, so only the newest Undo is offered", async () => {
    const { srv, calls } = useMockApi();
    const user = userEvent.setup();
    renderLetter("doc_dentist");
    await user.click(await toggle());
    await waitFor(async () => expect(await toggle()).toHaveAttribute("aria-pressed", "true"));
    await user.click(await toggle());
    await waitFor(async () => expect(await toggle()).toHaveAttribute("aria-pressed", "false"));
    await waitFor(() => expect(screen.getByText("Not marked for taxes")).toBeInTheDocument());
    expect(screen.queryByText("Marked for taxes")).toBeNull();
    expect(screen.getAllByRole("button", { name: "Undo" })).toHaveLength(1);
    // the newest Undo puts back what the second press found: the person's "for taxes"
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(srv.db.state.taxChoices).toEqual({ doc_dentist: true }));
    expect(patches(calls, "doc_dentist")).toEqual([{ tax_choice: true }, { tax_choice: false }, { tax_choice: true }]);
  });

  it("it is hidden for a waiting letter, one being read and one in the trash, and shown for a private letter and on a phone", async () => {
    const shown = (doc: Partial<DocumentDetail["document"]>) => taxToggleShown(makeDoc(doc));
    expect(shown({ status: "held", ai_private: true })).toBe(false);
    expect(shown({ status: "queued" })).toBe(false);
    expect(shown({ status: "processing" })).toBe(false);
    expect(shown({ deleted_at: "2026-09-28T07:00:00Z" })).toBe(false);
    expect(shown({ source: "proof", direction: "outgoing" })).toBe(false);
    for (const status of ["processed", "needs_review", "failed"] as const) expect(shown({ status }), status).toBe(true);
    expect(shown({ ai_private: true, ai_processed_at: null })).toBe(true);

    const footer = (doc: Partial<DocumentDetail["document"]>) => {
      const view = renderWithProviders(<DocumentFooter detail={makeDetail({ document: makeDoc(doc) })} />, { client: client() });
      const found = screen.queryByRole("button", { name: "For taxes" });
      view.unmount();
      return found !== null;
    };
    useMockApi();
    expect(footer({ status: "held", ai_private: true, ai_processed_at: null })).toBe(false);
    expect(footer({ status: "processing", ai_processed_at: null })).toBe(false);
    expect(footer({ deleted_at: "2026-09-28T07:00:00Z" })).toBe(false);
    expect(footer({ ai_private: true, ai_processed_at: null })).toBe(true);

    // on a paired phone: the same toggle, outside what stays on the computer
    const { calls, srv } = useMockApi({ client: "phone" });
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <DocumentFooter detail={makeDetail({ document: { ...srv.db.document("doc_dentist")! } })} />
        <Toaster />
      </>,
    );
    expect(screen.queryByRole("link", { name: /Download original/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "For taxes" }));
    await waitFor(() => expect(srv.db.state.taxChoices).toEqual({ doc_dentist: true }));
    expect(patches(calls, "doc_dentist")).toEqual([{ tax_choice: true }]);
    expect(srv.refused).toEqual([]);
  });

  it("the toast names the tax year, or says an undated letter is in none", async () => {
    const { srv } = useMockApi();
    const letter = srv.db.document("doc_dentist")!;
    letter.doc_date = null;
    letter.received_date = null;
    const user = userEvent.setup();
    renderLetter("doc_dentist");
    await user.click(await toggle());
    await waitFor(() => expect(screen.getByText("Marked for taxes")).toBeInTheDocument());
    const marked = screen.getByText("Marked for taxes").closest("li")!;
    expect(within(marked).getByText("It has no date, so it isn't in any tax year.")).toBeInTheDocument();
    await waitFor(async () => expect(await toggle()).toHaveAttribute("aria-pressed", "true"));
    // no year to link to
    expect(screen.getByText("You marked this letter for taxes.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /All letters for taxes/ })).toBeNull();
    await user.click(await toggle());
    await waitFor(() => expect(screen.getByText("Not marked for taxes")).toBeInTheDocument());
    const unmarked = screen.getByText("Not marked for taxes").closest("li")!;
    expect(within(unmarked).queryByText(/tax year/)).toBeNull();
  });
});
