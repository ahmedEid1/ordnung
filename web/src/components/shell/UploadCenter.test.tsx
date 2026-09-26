/**
 * Letters being read (audit round 1, bucket "shell-b"): a filed letter's card waits while it is
 * pointed at or focused, a card that goes hands focus on, a failed letter says why in full and
 * offers "Try again" and "Open letter" until dismissed, and several letters share one compact
 * card that opens into a list capped for phones.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { createMockServer, type MockServer } from "@/mocks/server";
import { __resetEventsForTests, seedJob, useEvents } from "@/api/sse";
import type { JobProgressEvent } from "@/api/types";
import { DONE_LINGER_MS, UploadCenter, uploadSummary } from "./UploadCenter";

let srv: MockServer;
let calls: { method: string; path: string }[];

beforeEach(() => {
  srv = createMockServer({ staticDemo: false, latency: 0 });
  calls = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace(/^\/api/, "");
    calls.push({ method: init?.method ?? "GET", path });
    return srv.handle(init?.method ?? "GET", path, url.searchParams, undefined);
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  __resetEventsForTests();
});

/** Which documents have a job in the store (the cards come and go with them). */
function Jobs() {
  const { jobs } = useEvents();
  return <output data-testid="jobs">{Object.keys(jobs).sort().join(",")}</output>;
}

function renderCenter() {
  return renderWithProviders(
    <>
      <main tabIndex={-1}>page</main>
      <UploadCenter />
      <Jobs />
    </>,
  );
}

const job = (doc_id: string, status: JobProgressEvent["status"], extra: Partial<JobProgressEvent> = {}): JobProgressEvent => ({
  job_id: `job_${doc_id}`,
  doc_id,
  stage: status === "done" ? "done" : "extract",
  progress: status === "done" ? 1 : 0.3,
  status,
  error: null,
  ...extra,
});

const jobs = () => screen.getByTestId("jobs").textContent;

describe("a filed letter's card", () => {
  it("waits while it is pointed at or focused, then goes", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    renderCenter();
    act(() => seedJob(job("doc_parking", "done")));
    const list = screen.getByRole("list", { name: "Letters being read" });

    fireEvent.mouseEnter(list);
    act(() => vi.advanceTimersByTime(DONE_LINGER_MS * 3));
    expect(jobs()).toBe("doc_parking");
    fireEvent.mouseLeave(list);

    const hide = within(list).getByRole("button", { name: /^Hide progress for/ });
    act(() => hide.focus());
    act(() => vi.advanceTimersByTime(DONE_LINGER_MS * 3));
    expect(jobs()).toBe("doc_parking");
    act(() => hide.blur());

    act(() => vi.advanceTimersByTime(DONE_LINGER_MS + 10));
    expect(jobs()).toBe("");
  });
});

describe("a failed letter's card", () => {
  it("says why in full, offers 'Try again' and 'Open letter', and stays until dismissed", async () => {
    const reason = "Couldn't read this letter — the file is damaged. Try exporting it again as a PDF from the scanner app.";
    renderCenter();
    act(() => seedJob(job("doc_parking", "failed", { error: reason })));
    const status = screen.getByText(reason);
    expect(status).not.toHaveClass("truncate");
    expect(status).not.toHaveClass("line-clamp-2");
    expect(screen.getByRole("link", { name: /Open letter/ })).toHaveAttribute("href", "/documents/doc_parking");

    screen.getByRole("button", { name: "Try again" }).click();
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/documents/doc_parking/reprocess")).toBe(true));
    // it is being read again: the card says so instead of the error
    await waitFor(() => expect(screen.queryByText(reason)).toBeNull());
    expect(jobs()).toBe("doc_parking");
  });

  it("is not taken away by the timer", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    renderCenter();
    act(() => seedJob(job("doc_parking", "failed", { error: "The file is damaged." })));
    act(() => vi.advanceTimersByTime(DONE_LINGER_MS * 10));
    expect(jobs()).toBe("doc_parking");
  });
});

describe("several letters", () => {
  it("share one compact card that opens into their cards, in a list capped for phones", async () => {
    renderCenter();
    act(() => {
      seedJob(job("doc_parking", "running"));
      seedJob(job("doc_phone", "done"));
      seedJob(job("doc_nebenkosten", "failed", { error: "The file is damaged." }));
    });
    const summary = screen.getByRole("button", { name: /^Reading 1 letter/ });
    expect(summary).toHaveAttribute("aria-expanded", "false");
    expect(summary).toHaveTextContent("1 filed · 1 couldn't be read");
    expect(within(summary).getByText(/couldn't be read/)).toHaveClass("text-danger-ink");
    // one card, not three
    expect(screen.queryAllByRole("button", { name: /^Hide progress for/ })).toHaveLength(0);
    const card = summary.closest("li")!;
    expect(card).toHaveClass("dark:border-line-strong");

    act(() => summary.click());
    expect(summary).toHaveAttribute("aria-expanded", "true");
    const each = screen.getByRole("list", { name: "Each letter" });
    // open, the card stays within 40 % of a phone's height and its list scrolls
    expect(card).toHaveClass("flex", "flex-col", "max-h-[40dvh]");
    expect(each).toHaveClass("min-h-0", "overflow-y-auto");
    expect(within(each).getAllByRole("button", { name: /^Hide progress for/ })).toHaveLength(3);
  });

  it("hand focus to the next card when one is dismissed", async () => {
    renderCenter();
    act(() => {
      seedJob(job("doc_parking", "running"));
      seedJob(job("doc_phone", "running"));
      seedJob(job("doc_nebenkosten", "running"));
    });
    act(() => screen.getByRole("button", { name: /^Reading 3 letters/ }).click());
    const each = screen.getByRole("list", { name: "Each letter" });
    const [first, second] = within(each).getAllByRole("button", { name: /^Hide progress for/ });
    act(() => first!.focus());
    act(() => first!.click());
    expect(second).toHaveFocus();
    expect(document.activeElement).not.toBe(document.body);
  });
});

describe("uploadSummary", () => {
  it("names what is going on first, then the other counts", () => {
    expect(uploadSummary([{ status: "running" }, { status: "running" }])).toMatchObject({ title: "Reading 2 letters", parts: [] });
    expect(uploadSummary([{ status: "running" }, { status: "done" }, { status: "failed" }]).parts).toEqual([
      { text: "1 filed" },
      { text: "1 couldn't be read", danger: true },
    ]);
    expect(uploadSummary([{ status: "failed" }, { status: "done" }])).toMatchObject({ title: "1 letter couldn't be read", parts: [{ text: "1 filed" }] });
    expect(uploadSummary([{ status: "done" }, { status: "done" }])).toMatchObject({ title: "2 letters filed", parts: [] });
  });
});
