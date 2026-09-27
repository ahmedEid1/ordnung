import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { AddLettersProvider } from "@/components/shell/AddLetters";
import { DemoBadge } from "@/components/shell/DemoBadge";
import AskPage from "@/pages/AskPage";
import InboxPage from "@/pages/InboxPage";
import { Toaster, TOAST_LIFT_VAR, __clearToasts, toast } from "@/components/ui/Toast";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { DemoTour, TOUR_BAR_VAR, TOUR_CLEARANCE_VAR } from "./DemoTour";
import { TOUR_DOCK_ID, TOUR_STEPS, TOUR_TARGETS } from "./steps";
import { SUGGESTED_QUESTIONS } from "@/features/ask/suggestions";

class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}

/** A screen of `width` × `height` CSS px: `matchMedia` answers min-width and min-height queries. */
function viewport(width: number, height = 900) {
  vi.stubGlobal("innerWidth", width);
  vi.stubGlobal("innerHeight", height);
  vi.stubGlobal("matchMedia", (query: string) => {
    const minWidth = Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? 0);
    const minHeight = Number(/min-height:\s*(\d+)px/.exec(query)?.[1] ?? 0);
    return { matches: width >= minWidth && height >= minHeight, media: query, addEventListener() {}, removeEventListener() {} };
  });
}

/** Give the tour (card, bar or pill) a size; everything else has none (jsdom lays nothing out). */
function tourRect(rect: Partial<DOMRect>) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const inTour = this.closest?.('[aria-label="Demo tour"]') || /^Demo tour ·/.test(this.getAttribute?.("aria-label") ?? "");
    return (inTour ? { top: 600, left: 12, width: 366, height: 180, bottom: 780, right: 378, x: 12, y: 600, toJSON() {}, ...rect } : new DOMRect(0, 0, 0, 0)) as DOMRect;
  });
}

/** The sidebar's dock, `room` px tall. */
function addDock(room: number): HTMLElement {
  const dock = document.createElement("div");
  dock.id = TOUR_DOCK_ID;
  document.body.appendChild(dock);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.id === TOUR_DOCK_ID ? room : 0;
  });
  return dock;
}

const cssVar = (name: string) => document.documentElement.style.getPropertyValue(name);
const lift = () => cssVar(TOAST_LIFT_VAR);
const tourRegion = () => screen.findByRole("region", { name: "Demo tour" });

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", RO);
  vi.stubGlobal("scrollTo", () => {});
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  for (const v of [TOAST_LIFT_VAR, TOUR_BAR_VAR, TOUR_CLEARANCE_VAR]) document.documentElement.style.removeProperty(v);
  document.getElementById(TOUR_DOCK_ID)?.remove();
  act(() => __clearToasts());
});

describe("demo tour targets", () => {
  it("every step points at an element the pages mark", () => {
    expect(TOUR_STEPS.map((s) => s.target)).toEqual([TOUR_TARGETS.newMail, TOUR_TARGETS.ideas, TOUR_TARGETS.askChips, TOUR_TARGETS.timelineLanes]);
    expect(Object.values(TOUR_TARGETS)).toEqual(["new-mail-tray", "today-ideas", "ask-chips", "timeline-lanes"]);
  });
});

/** Give every `[data-tour]` element a size (jsdom lays nothing out) so the spotlight can measure it. */
function sizedTargets(rect = new DOMRect(260, 120, 640, 220)) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return (this.hasAttribute?.("data-tour") ? rect : new DOMRect(0, 0, 0, 0)) as DOMRect;
  });
}

function renderInbox() {
  return renderWithProviders(
    <AddLettersProvider>
      <DemoTour />
      <InboxPage />
    </AddLettersProvider>,
    { route: "/inbox" },
  );
}

describe("the tour spotlights each page's element", () => {
  it("step 1 · the Inbox's New-mail tray, 8 px around it", async () => {
    const { srv } = useMockApi();
    srv.db.state.tour = { active: true, step: 0, completed: false };
    viewport(1440);
    sizedTargets();
    renderInbox();
    const tray = await screen.findByRole("region", { name: /New mail/ });
    expect(tray).toHaveAttribute("data-tour", TOUR_TARGETS.newMail);
    await waitFor(() => expect(screen.getByTestId("tour-spotlight")).toHaveAttribute("data-target", "new-mail-tray"));
    expect(screen.getByTestId("tour-spotlight")).toHaveStyle({ top: "112px", left: "252px", width: "656px", height: "236px" });
    // under the sticky top bar (z-30) and the Ask composer (z-10): it marks the page, never covers a control
    expect(screen.getByTestId("tour-spotlight").className).toContain("z-[5]");
  });

  it("step 3 · Ask's suggested questions", async () => {
    const { srv } = useMockApi();
    srv.db.state.tour = { active: true, step: 2, completed: false };
    vi.stubGlobal("scrollBy", () => {});
    viewport(1440);
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

  it("scrolls to the step's element once per step, not on every visit", async () => {
    const { srv } = useMockApi();
    srv.db.state.tour = { active: true, step: 0, completed: false };
    viewport(1440);
    sizedTargets(new DOMRect(260, 2000, 640, 220)); // far below the fold
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    const first = renderInbox();
    await screen.findByRole("region", { name: /New mail/ });
    await waitFor(() => expect(scrollTo).toHaveBeenCalledTimes(1));
    first.unmount();

    renderInbox(); // back on the Inbox later in the session
    await screen.findByRole("region", { name: /New mail/ });
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(scrollTo).toHaveBeenCalledTimes(1);
  });

  it("a minimised tour neither scrolls the page nor draws the spotlight", async () => {
    const { srv } = useMockApi();
    srv.db.state.tour = { active: true, step: 0, completed: false };
    localStorage.setItem("ordnung.tour.minimised", "true");
    viewport(1440);
    sizedTargets(new DOMRect(260, 2000, 640, 220));
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    renderInbox();
    expect(await screen.findByRole("button", { name: /^Demo tour · 1 of 4 — resume/ })).toBeInTheDocument();
    await screen.findByRole("region", { name: /New mail/ });
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(scrollTo).not.toHaveBeenCalled();
    expect(screen.queryByTestId("tour-spotlight")).not.toBeInTheDocument();
  });
});

describe("the tour tells the page what it covers", () => {
  it("phones: the bar lifts the toasts and sets --ordnung-tour-bar (its height + the gap above the tab bar)", async () => {
    useMockApi();
    viewport(390, 844);
    tourRect({ height: 60, right: 378 });
    const view = renderWithProviders(
      <>
        <DemoTour />
        <Toaster />
      </>,
    );
    expect(await tourRegion()).toBeInTheDocument();
    expect(lift()).toBe("68px");
    expect(cssVar(TOUR_BAR_VAR)).toBe("72px");
    expect(cssVar(TOUR_CLEARANCE_VAR)).toBe("");
    act(() => {
      toast({ title: "Saved" });
    });
    expect(screen.getByTestId("toaster").className).toContain("var(--ordnung-toast-lift,0px)");
    view.unmount();
    expect(lift()).toBe("");
    expect(cssVar(TOUR_BAR_VAR)).toBe("");
  });

  it("a wide, tall screen without the dock: the card floats clear of the toast column and sets --ordnung-tour-clearance", async () => {
    useMockApi();
    viewport(1440, 900);
    tourRect({ height: 180, left: 280, right: 632 });
    renderWithProviders(<DemoTour />);
    const card = await tourRegion();
    expect(within(card).getByRole("heading", { name: "You have new mail" })).toBeInTheDocument();
    expect(lift()).toBe("0px");
    expect(cssVar(TOUR_CLEARANCE_VAR)).toBe("180px");
    expect(cssVar(TOUR_BAR_VAR)).toBe("");
  });

  it("tablets get the slim bar, not the card; where it reaches the toast column it lifts them", async () => {
    useMockApi();
    viewport(820, 1180);
    tourRect({ height: 58, left: 240, right: 592 });
    renderWithProviders(<DemoTour />);
    const bar = await tourRegion();
    expect(within(bar).getByRole("button", { name: /show the whole step$/ })).toBeInTheDocument();
    expect(within(bar).queryByRole("heading")).not.toBeInTheDocument();
    expect(lift()).toBe("66px");
    expect(cssVar(TOUR_CLEARANCE_VAR)).toBe("58px");
  });
});

describe("the card never covers the page", () => {
  it("docks in the sidebar's free space when the whole card fits there (and sets nothing)", async () => {
    useMockApi();
    viewport(1440, 900);
    const dock = addDock(400);
    tourRect({ height: 300 });
    renderWithProviders(<DemoTour />);
    const card = await tourRegion();
    expect(dock.contains(card)).toBe(true);
    // a section: the sidebar is already a landmark (no aside inside the aside)
    expect(card.tagName).toBe("SECTION");
    expect(lift()).toBe("");
    expect(cssVar(TOUR_CLEARANCE_VAR)).toBe("");
  });

  it("a short laptop (1280×720): a card taller than the dock's room is never docked (cut off at the top) — the bar instead", async () => {
    useMockApi();
    viewport(1280, 720);
    const dock = addDock(280); // 248 px inside its padding
    tourRect({ height: 300 });
    renderWithProviders(<DemoTour />);
    await waitFor(() => expect(dock.childElementCount).toBe(0));
    const bar = await tourRegion();
    expect(dock.contains(bar)).toBe(false);
    expect(within(bar).getByRole("button", { name: /^Demo tour · 1 of 4: You have new mail/ })).toBeInTheDocument();
  });

  it("a floating card that would cover the step's highlighted element steps aside to the slim bar", async () => {
    const { srv } = useMockApi();
    srv.db.state.tour = { active: true, step: 0, completed: false };
    viewport(1440, 900); // no dock (collapsed sidebar): the card floats bottom right
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      if (this.hasAttribute?.("data-tour")) return new DOMRect(260, 500, 1100, 300); // the tray, down to y 800
      if (this.closest?.('[aria-label="Demo tour"]')) return new DOMRect(1068, 620, 352, 260); // the card, bottom right
      return new DOMRect(0, 0, 0, 0);
    });
    renderInbox();
    await screen.findByRole("region", { name: /New mail/ });
    const bar = await screen.findByRole("button", { name: /^Demo tour · 1 of 4: You have new mail — show the whole step$/ });
    // it opens again on request, and stays open
    fireEvent.click(bar);
    expect(await screen.findByRole("heading", { name: "You have new mail" })).toBeInTheDocument();
  });

  it("is a slim bar on phones; tapping it shows the whole step (and focuses its title)", async () => {
    useMockApi();
    viewport(390, 844);
    renderWithProviders(<DemoTour />);
    const open = await screen.findByRole("button", { name: /^Demo tour · 1 of 4: You have new mail — show the whole step$/ });
    // it says what it shows first (WCAG 2.5.3), and that it opens something
    expect(open.textContent).toMatch(/^Demo tour · 1 of 4/);
    expect(open).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("heading", { name: "You have new mail" })).not.toBeInTheDocument();
    fireEvent.click(open);
    const title = await screen.findByRole("heading", { name: "You have new mail" });
    await waitFor(() => expect(title).toHaveFocus());
  });

  it("the Ask step's example is one of the suggested questions, word for word", () => {
    const ask = TOUR_STEPS.find((s) => s.id === "ask")!;
    const quoted = /“([^”]+)”/.exec(ask.body)?.[1];
    expect(SUGGESTED_QUESTIONS.map((q) => q.question)).toContain(quoted);
  });
});

describe("keyboard and screen readers", () => {
  /** The floating card on a wide screen at step 1, on its page (call `useMockApi()` first). */
  function renderCard(route = "/inbox") {
    viewport(1440, 900);
    return renderWithProviders(
      <>
        <main id="main" tabIndex={-1} />
        <DemoTour />
        <Toaster />
      </>,
      { route },
    );
  }

  it("Next moves focus to the new step's title; Minimise to the pill; the pill back to the title", async () => {
    useMockApi();
    renderCard();
    const card = await tourRegion();
    fireEvent.click(within(card).getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Ideas from your secretary" })).toHaveFocus());

    fireEvent.click(screen.getByRole("button", { name: "Minimise the tour" }));
    const pill = await screen.findByRole("button", { name: "Demo tour · 2 of 4 — resume: Ideas from your secretary" });
    expect(pill.textContent).toBe("Demo tour · 2 of 4");
    await waitFor(() => expect(pill).toHaveFocus());

    fireEvent.click(pill);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Ideas from your secretary" })).toHaveFocus());
  });

  it("Escape in the card minimises it and focus goes to the pill", async () => {
    useMockApi();
    renderCard();
    const card = await tourRegion();
    fireEvent.keyDown(within(card).getByRole("button", { name: "Next" }), { key: "Escape" });
    await waitFor(() => expect(screen.getByRole("button", { name: /^Demo tour · 1 of 4 — resume/ })).toHaveFocus());
  });

  it("End the tour: focus goes to the page, a toast says how to get it back, and Undo restores it at the same step", async () => {
    const { srv } = useMockApi();
    srv.db.state.tour = { active: true, step: 2, completed: false };
    viewport(1440, 900);
    renderWithProviders(
      <>
        <main id="main" tabIndex={-1} />
        <DemoTour />
        <Toaster />
      </>,
    );
    const card = await tourRegion();
    fireEvent.click(within(card).getByRole("button", { name: "End the tour" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Demo tour" })).not.toBeInTheDocument());
    expect(document.getElementById("main")).toHaveFocus();
    expect(screen.getByText("Tour hidden")).toBeInTheDocument();
    expect(screen.getByText(/restart it any time from the Demo badge/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    const back = await tourRegion();
    expect(within(back).getByRole("heading", { name: "Ask anything" })).toBeInTheDocument();
    await waitFor(() => expect(within(back).getByRole("heading", { name: "Ask anything" })).toHaveFocus());
  });

  it("the Finish toast offers to restart the tour", async () => {
    const { srv } = useMockApi();
    srv.db.state.tour = { active: true, step: 3, completed: false };
    viewport(1440, 900);
    renderWithProviders(
      <>
        <main id="main" tabIndex={-1} />
        <DemoTour />
        <Toaster />
      </>,
      { route: "/timeline" },
    );
    fireEvent.click(within(await tourRegion()).getByRole("button", { name: "Finish" }));
    expect(await screen.findByText("That's the tour")).toBeInTheDocument();
    expect(document.getElementById("main")).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Restart the tour" }));
    expect(within(await tourRegion()).getByRole("heading", { name: "You have new mail" })).toBeInTheDocument();
  });

  it("step changes made outside the card (here: the phone bar's Next) are read out once, in one live region", async () => {
    useMockApi();
    viewport(390, 844);
    renderWithProviders(<DemoTour />, { route: "/inbox" });
    const bar = await tourRegion();
    const status = screen.getByRole("status");
    expect(status).toBeEmptyDOMElement();
    fireEvent.click(within(bar).getByRole("button", { name: "Next" }));
    await waitFor(() => expect(status).toHaveTextContent("Demo tour · 2 of 4: Ideas from your secretary"));
    // the same element: a remounted live region is not reliably announced
    expect(screen.getByRole("status")).toBe(status);
  });

  it("step dots name their step (also as a tooltip) and mark the current one", async () => {
    useMockApi();
    renderCard();
    const card = await tourRegion();
    const dots = within(card).getByRole("list", { name: "Steps (1 of 4)" });
    const buttons = within(dots).getAllByRole("button");
    expect(buttons.map((b) => b.getAttribute("title"))).toEqual(TOUR_STEPS.map((s, i) => `Step ${i + 1}: ${s.title}`));
    expect(buttons[0]).toHaveAttribute("aria-current", "step");
  });
});

describe("restarting the tour", () => {
  it("the Demo badge restarts an ended tour at its first step", async () => {
    const { srv } = useMockApi();
    srv.db.state.tour = { active: false, step: 2, completed: true };
    viewport(1440, 900);
    renderWithProviders(
      <>
        <DemoBadge />
        <DemoTour />
      </>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /about the demo$/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Restart the demo tour" }));
    const card = await tourRegion();
    expect(within(card).getByRole("heading", { name: "You have new mail" })).toBeInTheDocument();
    await waitFor(() => expect(srv.db.state.tour).toEqual({ active: true, step: 0, completed: false }));
  });

  it("a minimised tour opens again when restarted", async () => {
    const { srv } = useMockApi();
    srv.db.state.tour = { active: true, step: 1, completed: false };
    localStorage.setItem("ordnung.tour.minimised", "true");
    viewport(1440, 900);
    renderWithProviders(
      <>
        <DemoBadge />
        <DemoTour />
      </>,
    );
    await screen.findByRole("button", { name: /^Demo tour · 2 of 4 — resume/ });
    fireEvent.click(screen.getByRole("button", { name: /about the demo$/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Restart the demo tour" }));
    expect(within(await tourRegion()).getByRole("heading", { name: "You have new mail" })).toBeInTheDocument();
    expect(localStorage.getItem("ordnung.tour.minimised")).toBe("false");
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
