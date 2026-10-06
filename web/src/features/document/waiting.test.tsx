/**
 * A letter that waits in the queue for Claude (not installed, not signed in, its usage limit): its page says
 * why and where to connect Claude, instead of a stepper stuck on "Opening the file…" with placeholders that
 * never fill — and the person can add the dates that matter, as on a letter Claude couldn't read (final check
 * F-M2). After a reload, the reason comes from the queue (`seedFromQueue`), as it does from a live event.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, within } from "@testing-library/react";
import { __resetEventsForTests, handleServerEvent, seedJob } from "@/api/sse";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { DocumentView } from "./DocumentView";
import { ProcessingCard } from "./ProcessingCard";
import { makeDetail, makeDoc } from "./fixtures";

const NOT_INSTALLED =
  "Waiting for Claude: Claude Code isn't installed on this computer yet. Ordnung reads this letter as soon as Claude is connected (Settings → Claude connection).";
const USAGE_LIMIT = "Waiting for Claude: the usage limit was reached. Ordnung continues at about 15:30.";

const waitingJob = (reason: string, docId = "doc_1") => ({ job_id: "job_1", doc_id: docId, stage: "intake" as const, progress: 0, status: "queued" as const, waiting_reason: reason });
const neverRead = makeDoc({ status: "queued", kind: null, title: null, filename: "Stadtwerke.pdf", ai_processed_at: null });

beforeEach(() => {
  vi.stubGlobal("fetch", async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  act(() => __resetEventsForTests());
});

describe("the waiting card", () => {
  it("says the letter waits for Claude, why, and links to Claude connection — no stepper, no 'Try again'", () => {
    act(() => seedJob(waitingJob(NOT_INSTALLED)));
    renderWithProviders(<ProcessingCard doc={neverRead} />, { client: makeTestQueryClient() });
    expect(screen.getByRole("heading", { level: 1, name: "This letter waits for Claude" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Claude Code isn't installed on this computer yet. Ordnung reads this letter as soon as Claude is connected (Settings → Claude connection). Your file is safe.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Claude connection" })).toHaveAttribute("href", "/settings?section=claude");
    expect(screen.queryByText(/Opening the file/)).toBeNull();
    expect(screen.queryByText(/step \d of \d/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
  });

  it("on a letter read before, says the earlier reading shows below, with no heading over the verdict's", () => {
    act(() => seedJob(waitingJob(NOT_INSTALLED)));
    renderWithProviders(<ProcessingCard doc={makeDoc({ status: "queued", title: "Electricity bill" })} />, { client: makeTestQueryClient() });
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.getByText("Waiting for Claude to read it again")).toBeInTheDocument();
    expect(screen.getByText(/^What's shown below is from the earlier reading\. Claude Code isn't installed/)).toBeInTheDocument();
  });

  it("sends nobody to Claude connection for a usage limit, which ends by itself", () => {
    const client = makeTestQueryClient();
    act(() => {
      seedJob(waitingJob(USAGE_LIMIT));
      handleServerEvent(client, { type: "llm.paused", data: { until: "2099-01-05T14:30:00Z", reason: "Usage limit reached." } });
    });
    renderWithProviders(<ProcessingCard doc={neverRead} />, { client });
    expect(screen.getByText("The usage limit was reached. Ordnung continues at about 15:30. Your file is safe.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Claude connection" })).toBeNull();
  });

  it("is only for a letter in the queue: a reading under way shows its steps", () => {
    act(() => seedJob(waitingJob(NOT_INSTALLED)));
    renderWithProviders(<ProcessingCard doc={{ ...neverRead, status: "processing" }} />, { client: makeTestQueryClient() });
    expect(screen.queryByText("This letter waits for Claude")).toBeNull();
    expect(screen.getByText("Reading your letter")).toBeInTheDocument();
  });
});

describe("the page of a letter that waits for Claude", () => {
  it("has no placeholders that never fill, and offers 'Add a date' (as a letter Claude couldn't read does)", () => {
    act(() => seedJob(waitingJob(NOT_INSTALLED)));
    const { container } = renderWithProviders(<DocumentView detail={makeDetail({ document: neverRead })} />, { client: makeTestQueryClient() });
    expect(screen.getByRole("heading", { level: 1, name: "This letter waits for Claude" })).toBeInTheDocument();
    expect(container.querySelector("#doc-view-panel-letter-more .animate-pulse")).toBeNull();
    const todos = screen.getByRole("region", { name: "To-dos & dates" });
    expect(todos).toHaveTextContent("Ordnung hasn't read any dates from this letter. Add the ones that matter to you.");
    expect(within(todos).getByRole("button", { name: "Add a date" })).toBeInTheDocument();
  });

  it("still shows the placeholders while a letter in the queue is simply next to be read", () => {
    act(() => seedJob({ ...waitingJob(NOT_INSTALLED), waiting_reason: null }));
    const { container } = renderWithProviders(<DocumentView detail={makeDetail({ document: neverRead })} />, { client: makeTestQueryClient() });
    expect(container.querySelector("#doc-view-panel-letter-more .animate-pulse")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Add a date" })).toBeNull();
  });
});
