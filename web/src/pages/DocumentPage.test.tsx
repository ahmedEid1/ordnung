/**
 * UI audit round 1 (R1-document-c-7): a letter link that finds nothing, a letter that doesn't load, and the
 * page while it loads — each with its h1 and a way back; the server's words only under "Technical details".
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import { qk } from "@/api/hooks";
import type { MailTrayItem } from "@/api/types";
import { makeTestQueryClient, TEST_HEALTH } from "@/test/render";
import DocumentPage from "./DocumentPage";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function renderPage(fetchImpl: (url: string) => Response | Promise<Response>, { demo = false }: { demo?: boolean } = {}) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => fetchImpl(String(input))));
  const client = makeTestQueryClient();
  client.setQueryData(qk.health, { ...TEST_HEALTH, demo });
  const router = createMemoryRouter([{ path: "/documents/:id", element: <DocumentPage /> }], { initialEntries: ["/documents/doc_gone"] });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

const tray = (opened: boolean): MailTrayItem[] => [
  { id: "stadtwerke", filename: "24.pdf", sender: "Stadtwerke", subject: "Preisanpassung", kind_hint: "price_increase", photo: false, opened, doc_id: null, received_date: "2026-09-26" },
];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DocumentPage", () => {
  it("says a missing letter is gone, as the page's h1, with the way back to the Inbox", async () => {
    renderPage(() => json({ detail: "Document not found" }, 404));
    const h1 = await screen.findByRole("heading", { level: 1, name: "This letter is no longer here" });
    expect(h1).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Inbox" })).toHaveAttribute("href", "/inbox");
    // not "may have been deleted" alone: a link can also be cut short
    expect(screen.getByText(/deleted, or the link is incomplete/)).toBeInTheDocument();
  });

  it("in the demo, says a letter still in New mail hasn't been opened yet", async () => {
    renderPage((url) => (url.includes("/api/demo/mail") ? json(tray(false)) : json({ detail: "Document not found" }, 404)), { demo: true });
    expect(await screen.findByRole("heading", { level: 1, name: "This letter isn't in your inbox" })).toBeInTheDocument();
    expect(screen.getByText(/one of the letters in New mail, it hasn't been opened yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open New mail" })).toHaveAttribute("href", "/inbox");
  });

  it("keeps the server's message under Technical details and offers Try again and the way back", async () => {
    renderPage(() => json({ detail: "Something went wrong (UI audit)" }, 500));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("heading", { level: 1, name: "Couldn't open this letter" })).toBeInTheDocument();
    expect(within(alert).getByText(/Your letters are safe/)).toBeInTheDocument();
    // the raw message is folded away, never the sentence itself
    const details = within(alert).getByText("Technical details").closest("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(within(details).getByText(/Something went wrong \(UI audit\)/)).toBeInTheDocument();
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Inbox" })).toHaveAttribute("href", "/inbox");
  });

  it("has its h1 while the letter loads", () => {
    renderPage(() => new Promise<Response>(() => {}));
    expect(screen.getByRole("heading", { level: 1, name: "Letter" })).toBeInTheDocument();
  });
});
