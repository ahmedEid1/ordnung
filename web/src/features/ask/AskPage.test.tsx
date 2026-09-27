import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeTestQueryClient, renderWithProviders, TEST_HEALTH } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { qk } from "@/api/hooks";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import AskPage from "@/pages/AskPage";
import { THREAD_STORAGE_KEY } from "./useAskThread";

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("scrollTo", () => {});
  vi.stubGlobal("scrollBy", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __clearToasts());
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
    await screen.findByRole("heading", { name: "Sources" }, { timeout: 6000 });
    const thread = localStorage.getItem(THREAD_STORAGE_KEY);

    await user.type(screen.getByLabelText("Your question"), "What do I have to pay before 15 October?{Enter}");
    await waitFor(() => expect(screen.getAllByRole("heading", { name: "Sources" })).toHaveLength(2), { timeout: 6000 });
    expect(calls.filter((c) => c.path === "/ask")[1]?.body).toMatchObject({ thread_id: thread });
    first.unmount();

    renderWithProviders(<AskPage />, { route: "/ask" });
    expect(await screen.findByRole("article", { name: "Question: Which deadlines are coming up in October?" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Question: What do I have to pay before 15 October?" })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "GET" && c.path === `/chat/${thread}`)).toBe(true);

    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.getByRole("heading", { level: 1, name: "Ask about your letters" })).toBeInTheDocument();
    expect(localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
  }, 20_000); // two recorded answers stream word by word: slow on a busy machine

  it("a question the demo has no recording for gets a note, not a failure with a Try again that can't work", async () => {
    // UI audit round 1: an amber "Couldn't answer this one" and a "Try again" that failed again
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<AskPage />, { route: "/ask" });
    await user.type(screen.getByLabelText("Your question"), "Who won the football?{Enter}");
    const turn = await screen.findByRole("article", { name: "Question: Who won the football?" });
    expect(await within(turn).findByText("No recorded answer for this question")).toBeInTheDocument();
    expect(turn).toHaveTextContent(/try one of the suggested questions/);
    expect(within(turn).queryByRole("button", { name: "Try again" })).toBeNull();
    expect(turn).not.toHaveTextContent(/Couldn't answer/);
    expect(screen.getByRole("status")).toHaveTextContent("No recorded answer for this question.");
    // the suggested questions are right there
    expect(screen.getByRole("list", { name: "Suggested questions" })).toBeInTheDocument();
  });

  it("the online demo explains an unknown question once, in its note — no repeated answer to copy", async () => {
    vi.stubEnv("VITE_STATIC_DEMO", "1");
    try {
      useMockApi({ staticDemo: true });
      const user = userEvent.setup();
      renderWithProviders(<AskPage />, { route: "/ask" });
      await user.type(screen.getByLabelText("Your question"), "Who won the football?{Enter}");
      await screen.findByText("No recorded answer for this question", {}, { timeout: 3000 });
      expect(screen.getAllByText(/To ask about your own letters, install Ordnung/)).toHaveLength(1);
      expect(screen.queryByText(/there is none for this question/)).toBeNull();
      expect(screen.queryByRole("button", { name: /Copy answer/ })).toBeNull();
      expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("offers two suggested questions in a row from the answer's chips", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<AskPage />, { route: "/ask" });
    await user.click(screen.getByRole("button", { name: "Which deadlines are coming up in October?" }));
    await screen.findByText("Answer ready.", {}, { timeout: 6000 });
    const row = screen.getByRole("list", { name: "Suggested questions" });
    const next = within(row).getByRole("button", { name: "What do I have to pay in the next four weeks?" });
    // a row chip wraps instead of cutting the question off, and holds all of it in its title
    expect(next).toHaveAttribute("title", "What do I have to pay in the next four weeks?");
    expect(next.querySelector("span")?.className).toContain("line-clamp-3");
    expect(next.querySelector("span")?.className).not.toContain("truncate");
    await user.click(next);
    await waitFor(() => expect(screen.getAllByRole("heading", { name: "Sources" })).toHaveLength(2), { timeout: 6000 });
    expect(screen.queryByText(/Couldn't answer/)).toBeNull();
  }, 20_000);

  it("puts each question in a heading, so the answers' Sources sit under it", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<AskPage />, { route: "/ask" });
    const phone = "When does my phone contract end, and by when do I have to cancel it?";
    await user.click(screen.getByRole("button", { name: phone }));
    const turn = await screen.findByRole("article", { name: `Question: ${phone}` });
    expect(within(turn).getByRole("heading", { level: 2 })).toHaveTextContent(`You asked: ${phone}`);
    expect(await within(turn).findByRole("heading", { level: 3, name: "Sources" }, { timeout: 3000 })).toBeInTheDocument();
  });

  it("starts a new chat that can be undone, with focus where the next question goes", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <AskPage />
        <Toaster />
      </>,
      { route: "/ask" },
    );
    const question = "Which deadlines are coming up in October?";
    await user.click(screen.getByRole("button", { name: question }));
    await screen.findByText("Answer ready.", {}, { timeout: 6000 });
    const thread = localStorage.getItem(THREAD_STORAGE_KEY);

    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.queryByRole("article")).toBeNull();
    expect(localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
    // focus is not lost with the button that went: it waits at the start (touch) or in the box (mouse)
    await waitFor(() => expect([screen.getByRole("heading", { level: 1, name: "Ask about your letters" }), screen.getByLabelText("Your question")]).toContain(document.activeElement));

    const note = await screen.findByText("Started a new chat");
    await user.click(within(note.closest("li")!).getByRole("button", { name: /Undo/ }));
    expect(await screen.findByRole("article", { name: `Question: ${question}` })).toBeInTheDocument();
    expect(localStorage.getItem(THREAD_STORAGE_KEY)).toBe(thread);
  }, 20_000);

  it("says so when the stored conversation can't be loaded, with Try again and Start a new chat", async () => {
    localStorage.setItem(THREAD_STORAGE_KEY, "thr_broken01");
    useMockApi();
    const base = globalThis.fetch;
    let fail = true;
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input instanceof Request ? input.url : input);
      if (fail && url.includes("/chat/thr_broken01")) return Promise.resolve(new Response(JSON.stringify({ detail: "Database is busy" }), { status: 500 }));
      return base(input, init);
    });
    const user = userEvent.setup();
    renderWithProviders(<AskPage />, { route: "/ask" });
    const callout = (await screen.findByText("Couldn't load your last conversation")).parentElement!.parentElement!;
    fail = false;
    await user.click(within(callout).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByText("Couldn't load your last conversation")).toBeNull());
  });

  it("with no letters yet (outside the demo) it offers to add some, and questions that fit the person", async () => {
    useMockApi();
    const client = makeTestQueryClient();
    client.setQueryData(qk.health, { ...TEST_HEALTH, demo: false, backend: "claude_cli" });
    client.setQueryData(qk.documents.list({}), []);
    client.setQueryData(qk.profile, { ...(client.getQueryData(qk.profile) ?? {}), is_student_visa: false });
    renderWithProviders(<AskPage />, { route: "/ask", client });
    expect(screen.getByRole("heading", { name: "Add a few letters first" })).toBeInTheDocument();
    const chips = within(screen.getByRole("list", { name: "Suggested questions" })).getAllByRole("button");
    // the demo's "October" was fixed; here it is the month ahead (28 Sep → October), no residence permit
    expect(chips.map((c) => c.textContent)).toEqual([
      "When does my phone contract end, and by when do I have to cancel it?",
      "What do I have to pay in the next four weeks?",
      "Which deadlines are coming up in October?",
    ]);
    for (const chip of chips) expect(chip).toBeDisabled();
    expect(screen.queryByText(/replay answers recorded/)).toBeNull();
  });
});

describe("the question box", () => {
  it("says to wait or stop when Enter is pressed during an answer, and keeps focus on its one button", async () => {
    useMockApi();
    const base = globalThis.fetch;
    // an answer that is still being written (its stream stays open)
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input instanceof Request ? input.url : input);
      if (!url.endsWith("/api/ask")) return base(input, init);
      const enc = new TextEncoder();
      const body = new ReadableStream({
        start(ctrl) {
          ctrl.enqueue(enc.encode(`data: ${JSON.stringify({ type: "tool_use", name: "today", input: {}, text: "Checked today's date" })}\n\n`));
          ctrl.enqueue(enc.encode(`data: ${JSON.stringify({ type: "text" })}\n\n`));
          init?.signal?.addEventListener("abort", () => ctrl.error(new DOMException("aborted", "AbortError")));
        },
      });
      return Promise.resolve(new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }));
    });
    const user = userEvent.setup();
    renderWithProviders(<AskPage />, { route: "/ask" });
    const box = screen.getByLabelText("Your question");
    await user.type(box, "Which deadlines do I have?{Enter}");
    await screen.findByText(/^Writing the answer/, { selector: "p:not(.sr-only)" });
    await user.type(box, "And my contracts?{Enter}");
    expect(screen.getByText("Wait for this answer, or press Stop to ask something else.", { selector: "#ask-hint span" })).toBeInTheDocument();
    expect(box).toHaveValue("And my contracts?");

    const button = screen.getByRole("button", { name: "Stop the answer" });
    button.focus();
    await user.keyboard("{Enter}");
    await screen.findByText(/Stopped before Ordnung checked an answer/);
    // the same button, now "Ask", still has focus (UI audit round 1: focus fell back to the page)
    expect(document.activeElement).toBe(button);
    expect(button).toHaveAccessibleName("Ask");
    expect(screen.queryByText("Wait for this answer, or press Stop to ask something else.")).toBeNull();
  });

  it("with nothing typed the Ask button says it is unavailable without losing focus (aria-disabled)", () => {
    useMockApi();
    renderWithProviders(<AskPage />, { route: "/ask" });
    const button = screen.getByRole("button", { name: "Ask" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    // the placeholder is the muted text colour, at full strength (UI audit round 1: 3.72:1 at 80 %)
    expect(screen.getByLabelText("Your question").className).toContain("placeholder:text-muted ");
  });
});
