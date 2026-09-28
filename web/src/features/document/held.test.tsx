/**
 * A letter that waits for the person (from the watched folder), and e-mails with attachments: the
 * waiting card takes the verdict's place with both answers, an e-mail lists what became of each
 * attachment (linked when it became a letter), an attachment links back to its e-mail.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import userEvent from "@testing-library/user-event";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { qk } from "@/api/hooks";
import type { DocumentDetail } from "@/api/types";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { useMockApi } from "@/test/mockFetch";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import DocumentPage from "@/pages/DocumentPage";
import { DocumentView } from "./DocumentView";
import { waitingAttachments } from "./HeldCard";
import { attachmentLine, reasonClause } from "./EmailParts";
import { provenanceText } from "./DocumentFooter";

afterEach(() => vi.unstubAllGlobals());

async function detail(srv: ReturnType<typeof useMockApi>["srv"], id: string): Promise<DocumentDetail> {
  return (await (await srv.handle("GET", `/documents/${id}`, new URLSearchParams(), undefined)).json()) as DocumentDetail;
}

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

describe("a letter waiting from the folder", () => {
  it("shows the waiting card instead of a verdict, with both answers", async () => {
    const { srv } = useMockApi();
    const d = await detail(srv, "doc_folder_scan");
    const { container } = renderWithProviders(<DocumentView detail={d} />, { client: client() });
    const card = screen.getByRole("article", { name: "Scan_2026-09-28_0914.pdf" });
    expect(within(card).getByRole("heading", { level: 1 })).toHaveTextContent("Scan_2026-09-28_0914.pdf");
    expect(within(card).getByText("Not read yet")).toBeInTheDocument();
    expect(within(card).getByText(/It came from your watched folder\. It is stored on this computer and has not been sent to Claude\./)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Read it with Claude" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Keep private" })).toBeEnabled();
    // nothing was read, so nothing read is shown — and no "Read again" for a letter never read
    expect(screen.queryByRole("button", { name: "Read again" })).toBeNull();
    expect(screen.getByText("Not read yet — not sent to AI · 1 page")).toBeInTheDocument();
    assertNoRawEnumsInElement(container);
  });

  it("“Read it with Claude” answers for this letter", async () => {
    const { srv, calls } = useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<DocumentView detail={await detail(srv, "doc_folder_scan")} />, { client: client() });
    await user.click(screen.getByRole("button", { name: "Read it with Claude" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/documents/held/read")?.body).toEqual({ doc_ids: ["doc_folder_scan"] }));
  });

  it("an e-mail lists what became of each attachment, and says its attachment goes with it", async () => {
    const { srv } = useMockApi();
    const d = await detail(srv, "doc_folder_mail");
    renderWithProviders(<DocumentView detail={d} />, { client: client() });
    expect(screen.getByText(/Its attachment that waits goes with it\./)).toBeInTheDocument();
    // named by its subject and sender (read on this computer), its file name under it
    const card = screen.getByRole("article", { name: "Ihre Rechnung September 2026 · FunkNetz Kundenservice" });
    expect(within(card).getByText("Ihre Rechnung September 2026.eml")).toBeInTheDocument();
    const section = screen.getByRole("region", { name: /Attachments/ });
    const rows = within(section).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByRole("link", { name: "Rechnung_2026-09_FunkNetz.pdf" })).toHaveAttribute("href", "/documents/doc_folder_invoice");
    expect(within(rows[0]!).getByText("Added as its own letter")).toBeInTheDocument();
    expect(within(rows[1]!).queryByRole("link")).toBeNull();
    expect(within(rows[1]!).getByText(/picture inside the e-mail/)).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Not read — Ordnung only reads PDFs and photos from e-mails")).toBeInTheDocument();
  });

  it("an attachment links back to the e-mail it came with", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<DocumentView detail={await detail(srv, "doc_folder_invoice")} />, { client: client() });
    const card = screen.getByRole("article", { name: "Rechnung_2026-09_FunkNetz.pdf" });
    expect(within(card).getByText(/came attached to the e-mail “Ihre Rechnung September 2026 · FunkNetz Kundenservice”/)).toBeInTheDocument();
    const email = screen.getByRole("region", { name: "Came with an e-mail" });
    expect(within(email).getByRole("link")).toHaveAttribute("href", "/documents/doc_folder_mail");
  });
});

describe("what became of an attachment, in words", () => {
  it("adds the reason when one was refused or not read, and never a raw value", () => {
    expect(attachmentLine({ outcome: "refused", detail: "This image is too large to process safely." })).toBe("Not added — this image is too large to process safely.");
    expect(attachmentLine({ outcome: "over_limit", detail: "Only the first 10 attachments of an e-mail are read" })).toBe("Not read — only the first 10 attachments of an e-mail are read");
    expect(attachmentLine({ outcome: "refused", detail: "" })).toBe("Not added");
    expect(attachmentLine({ outcome: "known", detail: "Already in Ordnung" })).toBe("Already in Ordnung");
  });

  it("keeps the capitals of a name or an abbreviation that starts the reason", () => {
    expect(attachmentLine({ outcome: "refused", detail: "Ordnung isn't allowed to read this file. Check its permissions." })).toBe(
      "Not added — Ordnung isn't allowed to read this file. Check its permissions.",
    );
    expect(reasonClause("Ordnung's own letter")).toBe("Ordnung's own letter");
    expect(reasonClause("PDF files over 50 MB are refused")).toBe("PDF files over 50 MB are refused");
    expect(reasonClause("This PDF could not be opened.")).toBe("this PDF could not be opened.");
  });

  it("a waiting letter's provenance says it wasn't read", () => {
    expect(provenanceText({ status: "held", ai_private: true, pages: 2, ai_processed_at: null, text_mode: "text" } as DocumentDetail["document"])).toBe(
      "Not read yet — not sent to AI · 2 pages",
    );
  });
});

describe("answering on the letter's page", () => {
  function renderPage(id: string) {
    const qc = client();
    return renderWithProviders(
      <>
        <main>
          <Routes>
            <Route path="/documents/:id" element={<DocumentPage />} />
          </Routes>
        </main>
        <Toaster />
      </>,
      { route: `/documents/${id}`, client: qc },
    );
  }

  afterEach(() => act(() => __clearToasts()));

  it("“Keep private” says so and moves focus although the card is gone by then — and can be undone", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    renderPage("doc_folder_scan");
    const card = await screen.findByRole("article", { name: "Scan_2026-09-28_0914.pdf" });
    await user.click(within(card).getByRole("button", { name: "Keep private" }));
    // the letter's refetch lands first and the card unmounts: the toast and the focus move still happen
    expect(await screen.findByText("Kept private")).toBeInTheDocument();
    const verdict = await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(verdict).toHaveFocus());
    expect(verdict.className).toContain("outline-none");
    // nothing was read: the verdict says so instead of "nothing to do"
    expect(screen.getByText("Not read — Ordnung can't tell you what this letter asks, or by when.")).toBeInTheDocument();
    expect(screen.queryByText(/Nothing right now/)).toBeNull();
    expect(srv.db.document("doc_folder_scan")!.status).toBe("processed");

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(srv.db.document("doc_folder_scan")!.status).toBe("held"));
    expect(await screen.findByRole("article", { name: "Scan_2026-09-28_0914.pdf" })).toBeInTheDocument();
  });

  it("a letter kept private from the folder can wait again from its page — focus goes to the waiting card", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    await srv.handle("POST", "/documents/held/keep-private", new URLSearchParams(), { doc_ids: ["doc_folder_scan"] });
    renderPage("doc_folder_scan");
    await user.click(await screen.findByRole("button", { name: "Undo “Keep private”" }));
    await waitFor(() => expect(srv.db.document("doc_folder_scan")!.status).toBe("held"));
    expect(await screen.findByText("It's back with the letters not read yet")).toBeInTheDocument();
    // named as the button looks on every screen ("with Claude" is hidden on phones)
    expect(screen.getByText("Choose “Read it” to have Claude read it.")).toBeInTheDocument();
    const card = await screen.findByRole("article", { name: "Scan_2026-09-28_0914.pdf" });
    await waitFor(() => expect(within(card).getByRole("heading", { level: 1 })).toHaveFocus());
  });

  it("an e-mail waits again with the attachment kept private with it", async () => {
    const { srv } = useMockApi();
    const user = userEvent.setup();
    await srv.handle("POST", "/documents/held/keep-private", new URLSearchParams(), { doc_ids: ["doc_folder_mail"] });
    renderPage("doc_folder_mail");
    await user.click(await screen.findByRole("button", { name: "Undo “Keep private”" }));
    await waitFor(() => expect(srv.db.document("doc_folder_invoice")!.status).toBe("held"));
    expect(srv.db.document("doc_folder_mail")!.status).toBe("held");
    expect(await screen.findByText(/Its attachment that waits goes with it\./)).toBeInTheDocument();
  });

  it("a letter kept private when it was added never offers to wait again", async () => {
    const { srv } = useMockApi();
    const d = await detail(srv, "doc_folder_scan");
    const kept = { ...d, document: { ...d.document, status: "processed" as const, ai_private: true }, can_wait_again: false };
    renderWithProviders(<DocumentView detail={kept} />, { client: client() });
    expect(screen.getByText("Not read — Ordnung can't tell you what this letter asks, or by when.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo “Keep private”" })).toBeNull();
  });

  it("an answer keeps focus on its button while it runs (disabling it would drop focus to the page)", async () => {
    useMockApi();
    const mocked = globalThis.fetch;
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("/documents/held/read") ? new Promise<Response>(() => undefined) : mocked(input, init),
    );
    const user = userEvent.setup();
    renderPage("doc_folder_scan");
    const card = await screen.findByRole("article", { name: "Scan_2026-09-28_0914.pdf" });
    const read = within(card).getByRole("button", { name: "Read it with Claude" });
    await user.click(read);
    await waitFor(() => expect(read).toHaveAttribute("aria-busy", "true"));
    expect(read).not.toBeDisabled();
    expect(read).toHaveAttribute("aria-disabled", "true");
    expect(read).toHaveFocus();
    expect(within(card).getByRole("button", { name: "Keep private" })).toBeDisabled(); // the other answer waits
  });

  it("a failed answer leaves focus on its button", async () => {
    const { calls } = useMockApi({ staticDemo: true }); // the online demo can't read new letters
    const user = userEvent.setup();
    renderPage("doc_folder_scan");
    const card = await screen.findByRole("article", { name: "Scan_2026-09-28_0914.pdf" });
    const read = within(card).getByRole("button", { name: "Read it with Claude" });
    await user.click(read);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/documents/held/read")).toBe(true));
    await waitFor(() => expect(read).not.toHaveAttribute("aria-busy"));
    expect(read).toHaveFocus();
    expect(within(card).getByRole("button", { name: "Keep private" })).toBeEnabled();
  });

  it("“Read it with Claude” and “Keep private” come in the Inbox's order, the main answer last", async () => {
    const { srv } = useMockApi();
    renderWithProviders(<DocumentView detail={await detail(srv, "doc_folder_scan")} />, { client: client() });
    const card = screen.getByRole("article", { name: "Scan_2026-09-28_0914.pdf" });
    const names = within(card)
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(names).toEqual(["Keep private", "Read it with Claude"]);
  });

  it("an e-mail's card counts only the attachments that still wait", async () => {
    const { srv } = useMockApi();
    await srv.handle("POST", "/documents/held/keep-private", new URLSearchParams(), { doc_ids: ["doc_folder_invoice"] });
    const d = await detail(srv, "doc_folder_mail");
    expect(waitingAttachments(d)).toBe(0);
    renderWithProviders(<DocumentView detail={d} />, { client: client() });
    expect(screen.queryByText(/goes with it/)).toBeNull();
  });
});
