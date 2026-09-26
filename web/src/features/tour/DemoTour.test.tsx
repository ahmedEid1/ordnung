import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import AskPage from "@/pages/AskPage";
import InboxPage from "@/pages/InboxPage";
import { Toaster, TOAST_LIFT_VAR, __clearToasts, toast } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { DemoTour } from "./DemoTour";
import { TOUR_DOCK_ID, TOUR_STEPS, TOUR_TARGETS } from "./steps";
import { SUGGESTED_QUESTIONS } from "@/features/ask/suggestions";

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function mediaWidth(px: number) {
  vi.stubGlobal("innerWidth", px);
  vi.stubGlobal("matchMedia", (query: string) => {
    const min = Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0);
    return { matches: px >= min, media: query, addEventListener() {}, removeEventListener() {} };
  });
}

function cardRect(rect: Partial<DOMRect>) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const inTour = this.closest?.('[aria-label="Demo tour"]') || this.getAttribute?.("aria-label")?.startsWith("Resume the demo tour");
    return (inTour ? { top: 600, left: 12, width: 366, bottom: 780, x: 12, y: 600, toJSON() {}, ...rect } : new DOMRect(0, 0, 0, 0)) as DOMRect;
  });
}

const lift = () => document.documentElement.style.getPropertyValue(TOAST_LIFT_VAR);

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", RO);
  vi.stubGlobal("scrollTo", () => {});
  localStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.documentElement.style.removeProperty(TOAST_LIFT_VAR);
  act(() => __clearToasts());
});

describe("demo tour targets", () => {
  it("every step points at an element the pages mark", () => {
    expect(TOUR_STEPS.map((s) => s.target)).toEqual([TOUR_TARGETS.newMail, TOUR_TARGETS.ideas, TOUR_TARGETS.askChips, TOUR_TARGETS.timelineLanes]);
    expect(Object.values(TOUR_TARGETS)).toEqual(["new-mail-tray", "today-ideas", "ask-chips", "timeline-lanes"]);
  });
});

/** Give every `[data-tour]` element a size (jsdom lays nothing out) so the spotlight can measure it. */
function sizedTargets() {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return (this.hasAttribute?.("data-tour") ? new DOMRect(260, 120, 640, 220) : new DOMRect(0, 0, 0, 0)) as DOMRect;
  });
}

describe("the tour spotlights each page's element", () => {
  it("step 1 · the Inbox's New-mail tray", async () => {
    const { srv } = useMockApi();
    srv.db.state.tour = { active: true, step: 0, completed: false };
    mediaWidth(1440);
    sizedTargets();
    renderWithProviders(
      <AddLettersProvider>
        <DemoTour />
        <InboxPage />
      </AddLettersProvider>,
      { route: "/inbox" },
    );
    const tray = await screen.findByRole("region", { name: /New mail/ });
    expect(tray).toHaveAttribute("data-tour", TOUR_TARGETS.newMail);
    await waitFor(() => expect(screen.getByTestId("tour-spotlight")).toHaveAttribute("data-target", "new-mail-tray"));
    expect(screen.getByTestId("tour-spotlight")).toHaveStyle({ top: "114px", left: "254px", width: "652px", height: "232px" });
  });

  it("step 3 · Ask's suggested questions", async () => {
    const { srv } = useMockApi();
    srv.db.state.tour = { active: true, step: 2, completed: false };
    vi.stubGlobal("scrollBy", () => {});
    mediaWidth(1440);
    sizedTargets();
    renderWithProviders(
      <>
        <DemoTour />
        <AskPage />
      </>,
      { route: "/ask" },
    );
    expect(await screen.findByRole("list", { name: "Suggested questions" })).toHaveAttribute("data-tour", TOUR_TARGETS.askChips);
    await waitFor(() => expect(screen.getByTestId("tour-spotlight")).toHaveAttribute("data-target", "ask-chips"));
  });
});

describe("toasts never cover the tour card", () => {
  it("on phones the toast column is lifted above the card and drops back when the tour goes", async () => {
    useMockApi();
    mediaWidth(390);
    cardRect({ height: 180, right: 378 });
    const view = renderWithProviders(
      <>
        <DemoTour />
        <Toaster />
      </>,
    );
    expect(await screen.findByRole("complementary", { name: "Demo tour" })).toBeInTheDocument();
    expect(lift()).toBe("188px");
    act(() => {
      toast({ title: "Saved" });
    });
    const column = screen.getByTestId("toaster");
    expect(column.className).toContain("var(--ordnung-toast-lift,0px)");
    view.unmount();
    expect(lift()).toBe("");
  });

  it("on a wide screen without the sidebar dock the card floats clear of the toast column: nothing to lift", async () => {
    useMockApi();
    mediaWidth(1440);
    cardRect({ height: 180, left: 280, right: 632 });
    renderWithProviders(<DemoTour />);
    expect(await screen.findByRole("complementary", { name: "Demo tour" })).toBeInTheDocument();
    expect(lift()).toBe("0px");
  });

  it("a narrow tablet where the card reaches the toast column lifts them too", async () => {
    useMockApi();
    mediaWidth(820);
    cardRect({ height: 170, left: 240, right: 592 });
    renderWithProviders(<DemoTour />);
    expect(await screen.findByRole("complementary", { name: "Demo tour" })).toBeInTheDocument();
    expect(lift()).toBe("178px");
  });
});

describe("the card never covers the page", () => {
  it("docks in the sidebar's free space on desktop (and lifts no toasts)", async () => {
    useMockApi();
    mediaWidth(1440);
    const dock = document.createElement("div");
    dock.id = TOUR_DOCK_ID;
    document.body.appendChild(dock);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (this: HTMLElement) {
      return this.id === TOUR_DOCK_ID ? 400 : 0;
    });
    try {
      renderWithProviders(<DemoTour />);
      const card = await screen.findByRole("complementary", { name: "Demo tour" });
      expect(dock.contains(card)).toBe(true);
      expect(lift()).toBe("");
    } finally {
      dock.remove();
    }
  });

  it("is a one-line bar on phones; tapping it shows the whole step", async () => {
    useMockApi();
    mediaWidth(390);
    renderWithProviders(<DemoTour />);
    const open = await screen.findByRole("button", { name: /Demo tour, step 1 of 4: You have new mail/ });
    expect(screen.queryByRole("heading", { name: "You have new mail" })).not.toBeInTheDocument();
    act(() => open.click());
    expect(await screen.findByRole("heading", { name: "You have new mail" })).toBeInTheDocument();
  });

  it("the Ask step's example is one of the suggested questions, word for word", () => {
    const ask = TOUR_STEPS.find((s) => s.id === "ask")!;
    const quoted = /“([^”]+)”/.exec(ask.body)?.[1];
    expect(SUGGESTED_QUESTIONS.map((q) => q.question)).toContain(quoted);
  });
});

describe("toast column", () => {
  it("stacks toasts above the upload progress, in one column", () => {
    renderWithProviders(
      <Toaster>
        <ul aria-label="Letters being read">
          <li>Reading…</li>
        </ul>
      </Toaster>,
    );
    act(() => {
      toast({ title: "Letter saved" });
    });
    const column = screen.getByTestId("toaster");
    const list = screen.getByTestId("toast-list");
    const uploads = screen.getByRole("list", { name: "Letters being read" });
    expect(column.contains(list) && column.contains(uploads)).toBe(true);
    // toasts come first (on top), the upload panel below — both in the same flex column
    expect(list.compareDocumentPosition(uploads) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("Letter saved")).toBeInTheDocument();
  });
});
