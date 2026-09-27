import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import AskPage from "@/pages/AskPage";
import { THREAD_STORAGE_KEY } from "./useAskThread";

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("scrollTo", () => {});
  vi.stubGlobal("scrollBy", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Ask page", () => {
  it("offers the suggested questions and the privacy note", () => {
    useMockApi();
    renderWithProviders(<AskPage />, { route: "/ask" });
    const chips = screen.getByRole("list", { name: "Suggested questions" });
    expect(within(chips).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "When does my phone contract end, and by when do I have to cancel it?",
      "What do I have to pay in the next four weeks?",
      "Which deadlines are coming up in October?",
      "When does my residence permit expire, and what should I do before then?",
    ]);
    expect(screen.getByText(/Only the letters it opens are sent to Anthropic/)).toBeInTheDocument();
    expect(screen.getByText(/Not legal advice/)).toBeInTheDocument();
  });

  it("streams a recorded answer with its tool trace and numbered, validated sources", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const { container } = renderWithProviders(<AskPage />, { route: "/ask" });
    const phone = "When does my phone contract end, and by when do I have to cancel it?";
    await user.click(screen.getByRole("button", { name: phone }));

    const turn = await screen.findByRole("article", { name: `Question: ${phone}` });
    await within(turn).findByRole("heading", { name: "Sources" }, { timeout: 3000 });
    expect(calls.find((c) => c.path === "/ask")?.body).toMatchObject({ question: phone, thread_id: null });

    // the trace, folded once done
    await user.click(within(turn).getByRole("button", { name: /Looked at 3 things/ }));
    expect(within(turn).getByText("Searched your letters for “FunkNetz Kündigung”")).toBeInTheDocument();
    expect(within(turn).getByText("Looked at your contracts")).toBeInTheDocument();

    // inline markers became numbered links; no raw [doc:…] text is left
    expect(turn.textContent).not.toMatch(/\[(doc|item|contract):/);
    // the inline marker and the source list entry both lead to the to-do's letter
    const [marker] = within(turn).getAllByRole("link", { name: /^Source 2: To-do & date/ });
    expect(marker).toHaveTextContent(/^2$/);
    expect(marker).toHaveAttribute("href", "/documents/doc_phone");
    const sources = within(turn).getByRole("heading", { name: "Sources" }).parentElement!;
    expect(within(sources).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      "/contracts?contract=ctr_phone",
      "/documents/doc_phone",
      "/documents/doc_phone",
    ]);
    expect(screen.getByRole("status")).toHaveTextContent("Answer ready.");
    expect(localStorage.getItem(THREAD_STORAGE_KEY)).toMatch(/^thr_/);
    assertNoRawEnumsInElement(container);
  });

  it("continues the same thread and restores it after a reload", async () => {
    const { calls } = useMockApi();
    const user = userEvent.setup();
    const first = renderWithProviders(<AskPage />, { route: "/ask" });
    await user.click(screen.getByRole("button", { name: "Which deadlines are coming up in October?" }));
    await screen.findByRole("heading", { name: "Sources" }, { timeout: 3000 });
    const thread = localStorage.getItem(THREAD_STORAGE_KEY);

    await user.type(screen.getByLabelText("Your question"), "What do I have to pay before 15 October?{Enter}");
    await waitFor(() => expect(screen.getAllByRole("heading", { name: "Sources" })).toHaveLength(2), { timeout: 3000 });
    expect(calls.filter((c) => c.path === "/ask")[1]?.body).toMatchObject({ thread_id: thread });
    first.unmount();

    renderWithProviders(<AskPage />, { route: "/ask" });
    expect(await screen.findByRole("article", { name: "Question: Which deadlines are coming up in October?" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Question: What do I have to pay before 15 October?" })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "GET" && c.path === `/chat/${thread}`)).toBe(true);

    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.getByRole("heading", { level: 1, name: "Ask about your letters" })).toBeInTheDocument();
    expect(localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
  });

  it("an unknown question in the demo gets the friendly 'install to ask your own' answer", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<AskPage />, { route: "/ask" });
    await user.type(screen.getByLabelText("Your question"), "Who won the football?{Enter}");
    expect(await screen.findByText(/install Ordnung to ask anything about your own letters/, {}, { timeout: 3000 })).toBeInTheDocument();
  });

  it("the online demo explains an unknown question once, in its note — no repeated answer to copy", async () => {
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    try {
      useMockApi({ staticDemo: true });
      const user = userEvent.setup();
      renderWithProviders(<AskPage />, { route: "/ask" });
      await user.type(screen.getByLabelText("Your question"), "Who won the football?{Enter}");
      await screen.findByText("Answer ready.", {}, { timeout: 3000 });
      expect(screen.getAllByText(/install Ordnung to ask anything about your own letters/)).toHaveLength(1);
      expect(screen.queryByText(/I can only replay a few questions/)).toBeNull();
      expect(screen.queryByRole("button", { name: /Copy answer/ })).toBeNull();
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
