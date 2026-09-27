/**
 * A letter that waits for the person (from the watched folder), and e-mails with attachments: the
 * waiting card takes the verdict's place with both answers, an e-mail lists what became of each
 * attachment (linked when it became a letter), an attachment links back to its e-mail.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { qk } from "@/api/hooks";
import type { DocumentDetail } from "@/api/types";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { useMockApi } from "@/test/mockFetch";
import { DocumentView } from "./DocumentView";
import { attachmentLine } from "./EmailParts";
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
    expect(within(card).getByText("Waiting for you")).toBeInTheDocument();
    expect(within(card).getByText(/It came from your watched folder\. It is stored on this computer and has not been sent to Claude\./)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Read it with Claude" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Keep private" })).toBeEnabled();
    // nothing was read, so nothing read is shown — and no "Read again" for a letter never read
    expect(screen.queryByRole("button", { name: "Read again" })).toBeNull();
    expect(screen.getByText("Waiting for you — not read by AI yet · 1 page")).toBeInTheDocument();
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
    expect(screen.getByText(/Its attachment goes with it\./)).toBeInTheDocument();
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
    expect(within(card).getByText(/came attached to the e-mail “Ihre Rechnung September 2026\.eml”/)).toBeInTheDocument();
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

  it("a waiting letter's provenance says it wasn't read", () => {
    expect(provenanceText({ status: "held", ai_private: true, pages: 2, ai_processed_at: null, text_mode: "text" } as DocumentDetail["document"])).toBe(
      "Waiting for you — not read by AI yet · 2 pages",
    );
  });
});
