/**
 * The Inbox's, the upload centre's, the sync banner's, Today's and the weekly review's buttons that change something
 * take one press at a time: two presses before the button is drawn busy send one request, and a failed one takes
 * the next press. "Add" in the add-letters dialog sends one dialog's files once.
 */
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MailTrayItem } from "@/api/types";
import { __resetEventsForTests, seedJob } from "@/api/sse";
import { Toaster, __clearToasts } from "@/components/ui/Toast";
import { makeRow } from "@/features/document/fixtures";
import { FailedPanel } from "@/features/inbox/MailTray";
import { FailedCard } from "@/features/today/FailedCard";
import { WeekView } from "@/features/week/WeekView";
import { WeeklyPrompt } from "@/features/week/WeeklyPrompt";
import { expectOnePressAtATime } from "@/test/busyButton";
import { holdRequests, useMockApi } from "@/test/mockFetch";
import { renderWithProviders } from "@/test/render";
import InboxPage from "@/pages/InboxPage";
import { AddLettersProvider, useAddLetters } from "./AddLetters";
import { SyncBanner } from "./SyncBanner";
import { UploadCenter } from "./UploadCenter";

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  __resetEventsForTests();
  act(() => __clearToasts());
});

const user = () => userEvent.setup();

describe("the Inbox", () => {
  for (const [name, path] of [
    ["Keep private", "/documents/held/keep-private"],
    [/^Read these/, "/documents/held/read"],
  ] as const) {
    it(`“${String(name)}” for the letters from the folder takes one press at a time, and the next once it failed`, async () => {
      useMockApi();
      const held = holdRequests((call) => call.method === "POST" && call.path.startsWith(path.slice(0, "/documents/held/".length)));
      renderWithProviders(
        <AddLettersProvider>
          <InboxPage />
          <Toaster />
        </AddLettersProvider>,
        { route: "/inbox" },
      );
      const group = await screen.findByRole("region", { name: /From your folder — not read yet/ });
      await expectOnePressAtATime({ user: user(), button: () => within(group).getByRole("button", { name }), held });
    });
  }

  it("“Try again” on a letter in New mail that couldn't be read sends one request for two presses in one go", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/documents/doc_parking/reprocess");
    const anchor = createRef<HTMLDivElement>();
    renderWithProviders(
      <AddLettersProvider>
        <FailedPanel item={{ id: "mail_1", photo: false } as unknown as MailTrayItem} docId="doc_parking" message="The photo is blurred." anchor={anchor} />
      </AddLettersProvider>,
    );
    const again = screen.getByRole("button", { name: "Try again" });
    act(() => {
      again.click();
      again.click();
    });
    await waitFor(() => expect(held.count).toBe(1));
    await act(async () => {});
    expect(held.count).toBe(1);
    await act(async () => held.fail());
    await waitFor(() => expect(again).not.toHaveAttribute("aria-busy"));
    act(() => again.click());
    await waitFor(() => expect(held.count).toBe(2));
  });
});

describe("the upload centre and Today", () => {
  it("the upload centre's “Try again” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/documents/doc_parking/reprocess");
    renderWithProviders(<UploadCenter />);
    act(() => seedJob({ job_id: "job_doc_parking", doc_id: "doc_parking", stage: "extract", progress: 0.3, status: "failed", error: "The file is damaged." }));
    await screen.findByRole("button", { name: "Try again" });
    await expectOnePressAtATime({ user: user(), button: () => screen.getByRole("button", { name: "Try again" }), held });
  });

  it("Today's “Try again” for letters that couldn't be read takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path.startsWith("/documents/"));
    renderWithProviders(<FailedCard docs={[makeRow({ id: "doc_parking", status: "failed", title: "Parking fine" })]} />);
    await expectOnePressAtATime({ user: user(), button: () => screen.getByRole("button", { name: "Try again" }), held });
  });

  it("the sync banner's “Use Ordnung here” takes one press at a time, and the next once it failed", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/sync/use-here");
    renderWithProviders(<SyncBanner />);
    const banner = await screen.findByRole("status");
    await expectOnePressAtATime({ user: user(), button: () => within(banner).getByRole("button", { name: "Use Ordnung here" }), held });
  });
});

describe("the weekly review", () => {
  async function renderWeek(route: string) {
    renderWithProviders(
      <>
        <WeekView />
        <Toaster />
      </>,
      { route },
    );
    await screen.findByText(/^Step \d of \d$/);
  }

  it("“Not now” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path.startsWith("/week/"));
    renderWithProviders(
      <>
        <WeeklyPrompt />
        <h2 id="coming-up-title">Coming up</h2>
      </>,
    );
    const prompt = await screen.findByRole("region", { name: "Time for your weekly review" });
    await expectOnePressAtATime({ user: user(), button: () => within(prompt).getByRole("button", { name: "Not now" }), held });
  });

  it("“The date looks right” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && /\/items\/.+\/confirm$/.test(call.path));
    await renderWeek("/week?step=check");
    await expectOnePressAtATime({ user: user(), button: () => screen.getByRole("button", { name: "The date looks right: Pay the parking fine" }), held });
  });

  it("“Finish — all done” takes one press at a time, and the next once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/week/done");
    await renderWeek("/week?step=file");
    await expectOnePressAtATime({ user: user(), button: () => screen.getByRole("button", { name: "Finish — all done" }), held });
  });
});

describe("adding letters", () => {
  function Opener() {
    const { addFiles } = useAddLetters();
    return (
      <button type="button" onClick={() => addFiles([new File(["%PDF-1.4"], "Rechnung.pdf", { type: "application/pdf" })])}>
        Choose
      </button>
    );
  }

  it("“Add” sends one dialog's files once for two presses in one go", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/documents");
    renderWithProviders(
      <AddLettersProvider>
        <Opener />
      </AddLettersProvider>,
    );
    await user().click(screen.getByRole("button", { name: "Choose" }));
    const dialog = await screen.findByRole("dialog");
    const add = within(dialog).getAllByRole("button").find((b) => /^Add/.test(b.textContent ?? ""))!;
    act(() => {
      add.click();
      add.click();
    });
    await waitFor(() => expect(held.count).toBe(1));
    await act(async () => {});
    expect(held.count).toBe(1);
    await act(async () => held.release());
  });
});

describe("New mail", () => {
  it("“Let Ordnung read it” opens a letter once for two presses in one go, and again once it failed", async () => {
    useMockApi();
    const held = holdRequests((call) => call.method === "POST" && call.path === "/demo/mail");
    renderWithProviders(
      <AddLettersProvider>
        <InboxPage />
        <Toaster />
      </AddLettersProvider>,
      { route: "/inbox" },
    );
    const tray = await screen.findByRole("region", { name: /New mail/ });
    const read = within(tray).getAllByRole("button", { name: "Let Ordnung read it" })[0]!;
    act(() => {
      read.click();
      read.click();
    });
    await waitFor(() => expect(held.count).toBe(1));
    await act(async () => {});
    expect(held.count).toBe(1);
    await act(async () => held.fail());
    // back in the tray, unopened: the same envelope opens again
    await waitFor(() => expect(within(tray).getAllByRole("button", { name: "Let Ordnung read it" })).toHaveLength(5));
    act(() => within(tray).getAllByRole("button", { name: "Let Ordnung read it" })[0]!.click());
    await waitFor(() => expect(held.count).toBe(2));
  });
});
