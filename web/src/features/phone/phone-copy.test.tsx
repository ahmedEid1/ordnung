/**
 * Words on a paired phone: the letters are on the computer, not on the phone in the person's hand — so nothing
 * the phone shows says "this computer", and nothing names a command for a terminal the phone doesn't have. The
 * computer's own words stay as they were.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setClientKind } from "@/api/clientKind";
import { BootScreen, BOOT_STUCK_MS, UnreachableScreen } from "@/app/screens";
import { createQueryClient, showOffline, __resetOfflineForTests } from "@/app/queryClient";
import { AppErrorBoundary } from "@/app/ErrorBoundary";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { renderAppAt, stubShellGlobals } from "@/test/app";
import { useMockApi } from "@/test/mockFetch";
import type { MockServer } from "@/mocks/server";
import { PHONE_OFFLINE_DETAIL, PHONE_SAFE } from "./copy";

beforeEach(stubShellGlobals);
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  act(() => __clearToasts());
  __resetOfflineForTests();
});

/** What a phone must never say: where it isn't, or a command it can't run. */
const COMPUTER_WORDS = /this computer|ordnung (serve|demo|restore)|in a terminal/i;

function expectPhoneWords(where: string) {
  const text = document.body.textContent ?? "";
  const found = COMPUTER_WORDS.exec(text);
  expect(found ? text.slice(Math.max(0, found.index - 80), found.index + 60) : null, where).toBeNull();
}

/** A component that breaks while it draws (for the last-resort error screen). */
function ErrorBoundaryProbe(): never {
  throw new Error("broken on purpose");
}

/** An empty Ordnung (a fresh install): every page shows its first-run state. */
function emptyLedger(srv: MockServer) {
  Object.assign(srv.db.state, { documents: [], items: [], contracts: [], suggestions: [], drafts: [], cases: [], proofs: [], calls: [], tray: [] });
}

describe("a paired phone's pages say 'your computer'", () => {
  const pages: [string, string, RegExp | string | undefined][] = [
    ["Today", "/", undefined],
    ["Inbox", "/inbox", "Inbox"],
    ["Tax year", "/inbox/taxes", /^(Tax year 2026|Letters for taxes)$/],
    ["Timeline", "/timeline", "Timeline"],
    ["Contracts", "/contracts", "Contracts"],
    ["My numbers", "/numbers", "My numbers"],
    ["Letters", "/letters", "Letters"],
    ["Ask", "/ask", undefined],
  ];

  it.each(pages)("%s", async (name, path, heading) => {
    useMockApi({ client: "phone" });
    await renderAppAt(path, heading);
    expectPhoneWords(name);
  });

  it.each(pages)("%s, before the first letter", async (name, path, heading) => {
    const { srv } = useMockApi({ client: "phone" });
    emptyLedger(srv);
    await renderAppAt(path, heading);
    expectPhoneWords(`${name} (first run)`);
  });

  it("a letter, a waiting letter, a letter being written and a sent letter's proof", async () => {
    const { srv } = useMockApi({ client: "phone" });
    const st = srv.db.state;
    const letter = st.documents.find((d) => d.status === "processed" && d.pages > 0 && !d.ai_private && d.source !== "proof")!;
    const held = st.documents.find((d) => d.status === "held")!;
    const draft = st.drafts.find((d) => d.status !== "sent")!;
    const sent = st.drafts.find((d) => d.status === "sent" && st.proofs.some((p) => p.draft_id === d.id))!;
    for (const path of [`/documents/${letter.id}`, `/documents/${held.id}`, `/letters/${draft.id}`, `/letters/${sent.id}`]) {
      await renderAppAt(path);
      expectPhoneWords(path);
      cleanup();
    }
  });

  it("adding a letter: the chooser, the camera's pages and the files dialog", async () => {
    useMockApi({ client: "phone" });
    // jsdom has no object URLs (the page thumbnails use them)
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    await renderAppAt("/inbox", "Inbox");
    const user = userEvent.setup();
    await user.click(screen.getAllByRole("button", { name: /Add letters/ })[0]!);
    const chooser = await screen.findByRole("dialog", { name: "Add a letter" });
    expectPhoneWords("the chooser");
    // a page from the camera: "Pages of one letter"
    const camera = document.querySelector<HTMLInputElement>("input[data-camera]")!;
    await user.click(within(chooser).getByRole("button", { name: "Photograph a letter" }));
    await user.upload(camera, new File([new Uint8Array(10)], "image.jpg", { type: "image/jpeg" }));
    const pages = await screen.findByRole("dialog", { name: "Pages of one letter" });
    expectPhoneWords("Pages of one letter");
    await user.click(within(pages).getByRole("switch", { name: /Keep private/ }));
    expectPhoneWords("Pages of one letter, kept private");
  });
});

describe("the phone's full-screen states", () => {
  it("the splash that waits asks about the computer, never for a command", () => {
    vi.useFakeTimers();
    render(<BootScreen phone onRetry={() => {}} />);
    act(() => vi.advanceTimersByTime(BOOT_STUCK_MS));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Still waiting — is your computer on?");
    expectPhoneWords("boot");
  });

  it.each([
    [0, "Can't reach your computer"],
    [401, "This phone isn't paired any more"],
  ])("can't use Ordnung (%i): %s", (status, heading) => {
    render(<UnreachableScreen phone status={status} onRetry={() => {}} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(heading);
    expectPhoneWords(`unreachable ${status}`);
  });

  it("the last-resort error screen", () => {
    setClientKind("phone");
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <AppErrorBoundary>
        <ErrorBoundaryProbe />
      </AppErrorBoundary>,
    );
    expect(screen.getByText(PHONE_SAFE)).toBeInTheDocument();
    expectPhoneWords("error boundary");
  });

  it("the offline toast", () => {
    setClientKind("phone");
    render(<Toaster />);
    act(() => showOffline(createQueryClient()));
    expect(screen.getByText(PHONE_OFFLINE_DETAIL)).toBeInTheDocument();
    expectPhoneWords("offline toast");
  });
});

describe("the computer keeps its words", () => {
  it("Today before the first letter: 'this computer', the watched folder and `ordnung restore`", async () => {
    const { srv } = useMockApi();
    emptyLedger(srv);
    await renderAppAt("/");
    expect(document.body.textContent).toMatch(/Your files stay on this computer\./);
    expect(screen.getByRole("link", { name: "choose a watched folder" })).toBeInTheDocument();
    expect(document.body.textContent).toMatch(/ordnung restore/);
  });

  it("'this computer' and the commands to start Ordnung", () => {
    render(<UnreachableScreen phone={false} status={0} onRetry={() => {}} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Ordnung isn't running");
    expect(document.body.textContent).toMatch(/ordnung serve/);
  });
});
