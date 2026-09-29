/**
 * "From your folder — not read yet" on the Inbox (mock API): the waiting letters are listed with
 * an e-mail's attachment under it, "Read these 3" answers for exactly the letters shown, "Keep
 * private" keeps them here, and the online demo explains that it can't read new letters.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { __resetEventsForTests } from "@/api/sse";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import InboxPage from "@/pages/InboxPage";

afterEach(() => {
  vi.unstubAllGlobals();
  __resetEventsForTests();
  act(() => __clearToasts());
});

function renderInbox() {
  return renderWithProviders(
    <AddLettersProvider>
      <InboxPage />
      <Toaster />
    </AddLettersProvider>,
    { route: "/inbox" },
  );
}

const group = () => screen.findByRole("region", { name: /From your folder — not read yet/ });

describe("the letters waiting from the folder", () => {
  it("lists them apart from the letters, an e-mail's attachment under it", async () => {
    useMockApi();
    renderInbox();
    const g = await group();
    const list = within(g).getByRole("list", { name: "Letters not read yet" });
    const names = within(list)
      .getAllByRole("link")
      .map((a) => a.textContent);
    // an e-mail is named by its subject and sender (read on this computer, no model)
    expect(names).toEqual(["Scan_2026-09-28_0914.pdf", "Ihre Rechnung September 2026 · FunkNetz Kundenservice", "Rechnung_2026-09_FunkNetz.pdf"]);
    expect(within(list).getByText("Attached to “Ihre Rechnung September 2026 · FunkNetz Kundenservice”")).toBeInTheDocument();
    expect(within(g).getByText(/nothing has been sent to Claude/)).toBeInTheDocument();
    expect(within(g).getByRole("link", { name: "Watched folder settings" })).toHaveAttribute("href", "/settings?section=folder");
    // not in the letters list below, nor counted there
    const lettersPanel = screen.getByRole("tabpanel");
    expect(within(lettersPanel).queryByText("Scan_2026-09-28_0914.pdf")).toBeNull();
  });

  it("“Read these 3” answers for exactly the letters shown, and the group goes", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    renderInbox();
    const g = await group();
    await user.click(within(g).getByRole("button", { name: "Read these 3 with Claude" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: /From your folder/ })).toBeNull());
    const post = calls.find((c) => c.method === "POST" && c.path === "/documents/held/read");
    expect(post?.body).toEqual({ doc_ids: ["doc_folder_scan", "doc_folder_mail", "doc_folder_invoice"] });
    expect(await screen.findByText("Claude is reading 3 letters")).toBeInTheDocument();
  });

  it("“Keep private” keeps them on this computer", async () => {
    const { calls, srv } = useMockApi();
    const user = userEvent.setup();
    renderInbox();
    const g = await group();
    await user.click(within(g).getByRole("button", { name: "Keep private" }));
    expect(await screen.findByText("Kept 3 letters private")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/documents/held/keep-private")).toBe(true);
    const doc = srv.db.document("doc_folder_scan")!;
    expect([doc.status, doc.ai_private]).toEqual(["processed", true]);
    await waitFor(() => expect(screen.queryByRole("region", { name: /From your folder/ })).toBeNull());
  });

  it("“Keep private” can be undone from its toast: they wait again", async () => {
    const { calls, srv } = useMockApi();
    const user = userEvent.setup();
    renderInbox();
    await user.click(within(await group()).getByRole("button", { name: "Keep private" }));
    expect(await screen.findByText(/nothing in them was read/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(srv.db.document("doc_folder_scan")!.status).toBe("held"));
    expect(calls.find((c) => c.method === "POST" && c.path === "/documents/held/wait")?.body).toEqual({
      doc_ids: ["doc_folder_scan", "doc_folder_mail", "doc_folder_invoice"],
    });
    expect(await group()).toBeInTheDocument();
    expect(await screen.findByText("They're back with the letters not read yet")).toBeInTheDocument();
  });

  it("the online demo can't read new letters: it says so beforehand, and they keep waiting", async () => {
    const { calls, srv } = useMockApi({ staticDemo: true });
    const user = userEvent.setup();
    renderInbox();
    const g = await group();
    expect(await within(g).findByText(/This demo can't read new letters/)).toBeInTheDocument();
    expect(within(g).queryByText(/Claude reads them like letters you add/)).toBeNull();
    const read = within(g).getByRole("button", { name: "Read these 3 with Claude" });
    await user.click(read);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/documents/held/read")).toBe(true));
    await waitFor(() => expect(read).not.toHaveAttribute("aria-busy"));
    // it stayed focusable while it ran: a keyboard user is still on it and can try again
    expect(read).toHaveFocus();
    expect(read).toBeEnabled();
    expect(screen.getByRole("region", { name: /From your folder/ })).toBeInTheDocument();
    expect(srv.db.document("doc_folder_scan")!.status).toBe("held");
  });

  it("an answer keeps focus on its button while it runs", async () => {
    useMockApi();
    const mocked = globalThis.fetch;
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("/documents/held/keep-private") ? new Promise<Response>(() => undefined) : mocked(input, init),
    );
    const user = userEvent.setup();
    renderInbox();
    const keep = within(await group()).getByRole("button", { name: "Keep private" });
    await user.click(keep);
    await waitFor(() => expect(keep).toHaveAttribute("aria-busy", "true"));
    expect(keep).not.toBeDisabled();
    expect(keep).toHaveFocus();
  });

  it("one waiting letter is spoken of as one", async () => {
    const { srv } = useMockApi();
    await srv.handle("POST", "/documents/held/keep-private", new URLSearchParams(), { doc_ids: ["doc_folder_mail"] });
    renderInbox();
    const g = await group();
    expect(within(g).getByRole("button", { name: "Read it with Claude" })).toBeInTheDocument();
    expect(within(g).getByText(/Claude reads it like a letter you add\./)).toBeInTheDocument();
    expect(within(g).queryByText(/reads them/)).toBeNull();
  });
});
