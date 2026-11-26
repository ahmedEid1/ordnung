/**
 * The letter page's other buttons that change something take one press at a time: two presses before the button is
 * drawn busy send one request (a second reply letter, a second reading, a 404 after "deleted"), and a failed one
 * takes the next press.
 */
import { afterEach, describe, it, vi } from "vitest";
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import type { DocumentDetail } from "@/api/types";
import { ADVICE_BY_KIND } from "@/mocks/data/advice";
import { __clearToasts } from "@/components/ui/Toast";
import { expectOnePressAtATime } from "@/test/busyButton";
import { holdRequests, useMockApi } from "@/test/mockFetch";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { DocumentFooter } from "./DocumentFooter";
import { DocumentView } from "./DocumentView";
import { KindPicker } from "./KindPicker";
import { LetterAdviceCard } from "./LetterAdvice";
import { ProcessingCard } from "./ProcessingCard";
import { TaxToggle } from "./TaxToggle";
import { TracePanel } from "./trace/TracePanel";
import { Route, Routes } from "react-router";
import DocumentPage from "@/pages/DocumentPage";
import { VerdictCard } from "./VerdictCard";
import { makeDetail, makeDoc, makeSuggestion } from "./fixtures";

afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
});

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

async function detailOf(srv: ReturnType<typeof useMockApi>["srv"], id: string): Promise<DocumentDetail> {
  return (await (await srv.handle("GET", `/documents/${id}`, new URLSearchParams(), undefined)).json()) as DocumentDetail;
}

const user = () => userEvent.setup();

describe("the letter's footer", () => {
  it("“Read again” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path.startsWith("/documents/doc_1/"));
    renderWithProviders(<DocumentFooter detail={makeDetail({ document: makeDoc({ kind: "invoice" }) })} />, { client: client() });
    await expectOnePressAtATime({ user: user(), button: () => screen.getByRole("button", { name: "Read again" }), held });
  });

  it("“Draft a reply” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/drafts");
    renderWithProviders(<DocumentFooter detail={makeDetail({ document: makeDoc({ kind: "invoice" }) })} />, { client: client() });
    await expectOnePressAtATime({ user: user(), button: () => screen.getByRole("button", { name: "Draft a reply" }), held });
  });

  it("“Delete letter” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "DELETE" && call.path.startsWith("/documents/doc_1"));
    renderWithProviders(<DocumentFooter detail={makeDetail({ document: makeDoc({ kind: "invoice" }) })} />, { client: client() });
    const u = user();
    await u.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete this letter?" });
    await expectOnePressAtATime({ user: u, button: () => within(dialog).getByRole("button", { name: "Delete letter" }), held });
  });

  it("“For taxes” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/documents/doc_1");
    renderWithProviders(<TaxToggle detail={makeDetail({ document: makeDoc({ kind: "invoice" }) })} />, { client: client() });
    await expectOnePressAtATime({ user: user(), button: () => screen.getByRole("button", { name: "For taxes" }), held });
  });
});

describe("the letter's other answers", () => {
  it("“I've dealt with this” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/documents/doc_notice");
    const doc = makeDoc({ id: "doc_notice", kind: "landlord_notice", area: "home", title: "Kündigung" });
    const closable = { ...ADVICE_BY_KIND.landlord_notice, urgent: true, closable: true, draft: null };
    renderWithProviders(<LetterAdviceCard advice={closable} doc={doc} />, { client: client() });
    await expectOnePressAtATime({ user: user(), button: () => screen.getByRole("button", { name: "I've dealt with this" }), held });
  });

  it("the kind picker's “Save” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/documents/doc_1");
    renderWithProviders(<KindPicker doc={{ id: "doc_1", kind: "dunning" }} />, { client: client() });
    const u = user();
    await u.click(screen.getByRole("button", { name: "Change what kind of letter this is" }));
    await u.selectOptions(screen.getByLabelText(/Kind of letter/), "court_payment_order");
    await expectOnePressAtATime({ user: u, button: () => screen.getByRole("button", { name: "Save" }), held });
  });

  it("“Try again” on a letter that couldn't be read takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path.startsWith("/documents/doc_1/"));
    renderWithProviders(<ProcessingCard doc={makeDoc({ status: "failed", error: "The reading failed." })} />, { client: client() });
    await expectOnePressAtATime({ user: user(), button: () => screen.getByRole("button", { name: "Try again" }), held });
  });

  it("“Read again and compare” takes one press at a time, and the next once it failed", async () => {
    const { srv } = useMockApi();
    const detail = await detailOf(srv, "doc_nebenkosten");
    const held = holdRequests((call) => call.method === "POST" && call.path.startsWith("/documents/doc_nebenkosten/"));
    renderWithProviders(<TracePanel detail={detail} />);
    await screen.findByRole("button", { name: "Read again and compare" });
    await expectOnePressAtATime({ user: user(), button: () => screen.getByRole("button", { name: "Read again and compare" }), held });
  });
});

describe("a letter waiting from the folder", () => {
  for (const name of ["Keep private", /^Read it/]) {
    it(`“${String(name)}” takes one press at a time, and the next once it failed`, async () => {
      const { srv } = useMockApi();
      const detail = await detailOf(srv, "doc_folder_scan");
      const held = holdRequests((call) => call.method === "POST" && call.path.startsWith("/documents/held/"));
      renderWithProviders(<DocumentView detail={detail} />, { client: client() });
      const card = screen.getByRole("article", { name: "Scan_2026-09-28_0914.pdf" });
      await expectOnePressAtATime({ user: user(), button: () => within(card).getByRole("button", { name }), held });
    });
  }
});

describe("the verdict card's other answers", () => {
  it("“Keep it” on a cancel-or-keep decision takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "PATCH" && call.path === "/suggestions/sug_cancel");
    const decision = makeSuggestion({
      id: "sug_cancel",
      kind: "opportunity",
      title: "Cancel or keep?",
      rule_id: "price_increase_right",
      action: { type: "draft", draft_kind: "cancellation", target_type: "contract", target_id: "ctr_1", label: "Draft cancellation" } as never,
    });
    renderWithProviders(<VerdictCard detail={makeDetail({ suggestions: [decision] })} primary={null} />, { client: client() });
    await expectOnePressAtATime({ user: user(), button: () => screen.getByRole("button", { name: "Keep it" }), held });
  });

  it("“Undo “Keep private”” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const u = user();
    renderWithProviders(
      <main>
        <Routes>
          <Route path="/documents/:id" element={<DocumentPage />} />
        </Routes>
      </main>,
      { route: "/documents/doc_folder_scan", client: client() },
    );
    const card = await screen.findByRole("article", { name: "Scan_2026-09-28_0914.pdf" });
    await u.click(within(card).getByRole("button", { name: "Keep private" }));
    const undo = () => screen.getByRole("button", { name: "Undo “Keep private”" });
    await screen.findByRole("button", { name: "Undo “Keep private”" });
    const held = holdRequests((call) => call.method === "POST" && call.path === "/documents/held/wait");
    await expectOnePressAtATime({ user: u, button: undo, held });
  });
});
