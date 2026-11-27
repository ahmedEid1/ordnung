/**
 * "Open the letter's card" (the composer, when it refuses a letter the card says to handle otherwise) opens the
 * letter with `{ focus: "advice" }`: a frame later the card is scrolled to and its title focused. Focus is lost as
 * the page is drawn (the link went with its dialog), and the new page's heading takes it at once (PageAnnouncer):
 * from either, the card takes it. Someone who pressed Tab inside that frame stays where they went, the page with them
 * (the title once took focus back, and the page scrolled away).
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { qk } from "@/api/hooks";
import { __resetEventsForTests } from "@/api/sse";
import type { DocumentDetail } from "@/api/types";
import { holdFrames } from "@/test/frames";
import { DocumentView } from "./DocumentView";

const ID = "doc_nebenkosten";
let scrolled: Mock<(arg?: boolean | ScrollIntoViewOptions) => void>;

beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
  // jsdom has no scrollIntoView
  scrolled = vi.fn<(arg?: boolean | ScrollIntoViewOptions) => void>();
  Element.prototype.scrollIntoView = scrolled;
  __resetEventsForTests();
});
afterEach(() => {
  vi.unstubAllGlobals();
  delete (Element.prototype as Partial<Element>).scrollIntoView;
});

/** The letter on its page (`srv`: the mock API's), frames held; `arrive` opens it for its card, as the composer's link does. */
async function letterPage(srv: ReturnType<typeof useMockApi>["srv"]) {
  srv.openAllMail();
  const detail = (await (await srv.handle("GET", `/documents/${ID}`, new URLSearchParams(), undefined)).json()) as DocumentDetail;
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  const { router } = renderWithProviders(
    <>
      <main id="main" tabIndex={-1}>
        <DocumentView detail={detail} />
      </main>
      {/* something of the shell's, outside the page */}
      <button type="button" id="elsewhere">
        Elsewhere
      </button>
    </>,
    { client: qc },
  );
  const frames = holdFrames();
  return {
    frames,
    arrive: () => act(() => router.navigate(`/documents/${ID}`, { state: { focus: "advice" } })),
    title: () => document.getElementById(`advice-${ID}`),
    heading: () => document.querySelector<HTMLElement>("main h1:not([data-loading])"),
  };
}

describe("opened at its advice card", () => {
  it("lands on the card's title, the card scrolled to, when nobody moved", async () => {
    const page = await letterPage(useMockApi().srv);
    await page.arrive();
    expect(page.title()).not.toBeNull();
    expect(scrolled).not.toHaveBeenCalled(); // a frame later, once the page is laid out
    page.frames.run();
    expect(page.title()).toHaveFocus();
    expect(scrolled).toHaveBeenCalledTimes(1);
    expect(scrolled.mock.contexts[0]).toBe(document.getElementById(`advice-card-${ID}`));
    expect(scrolled).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
  });

  it.each([
    ["before the card's effect", true],
    ["after it", false],
  ])("still lands when the page's heading took the lost focus %s (the composer's way in)", async (_, first) => {
    const page = await letterPage(useMockApi().srv);
    const heading = page.heading()!;
    heading.tabIndex = -1;
    if (first) act(() => heading.focus());
    await page.arrive();
    if (!first) act(() => heading.focus());
    page.frames.run();
    expect(page.title()).toHaveFocus();
    expect(scrolled).toHaveBeenCalledTimes(1);
  });

  it("leaves focus the person had put elsewhere before the page drew where it is, and the page too", async () => {
    const page = await letterPage(useMockApi().srv);
    const elsewhere = document.getElementById("elsewhere")!;
    act(() => elsewhere.focus());
    await page.arrive();
    page.frames.run(3);
    expect(elsewhere).toHaveFocus();
    expect(scrolled).not.toHaveBeenCalled();
  });

  it("leaves a Tab pressed inside the arrival frame where it went, and the page where it was", async () => {
    const page = await letterPage(useMockApi().srv);
    const user = userEvent.setup();
    await page.arrive();
    await user.tab();
    const went = document.activeElement;
    expect(went).not.toBe(document.body);
    expect(went?.tagName).not.toBe("MAIN");
    page.frames.run(3);
    expect(went).toHaveFocus();
    expect(scrolled).not.toHaveBeenCalled();
  });

  it("leaves a Tab from the page's heading where it went too", async () => {
    const page = await letterPage(useMockApi().srv);
    const user = userEvent.setup();
    const heading = page.heading()!;
    heading.tabIndex = -1;
    await page.arrive();
    act(() => heading.focus());
    await user.tab();
    const went = document.activeElement;
    expect(went).not.toBe(heading);
    expect(screen.getByRole("main").contains(went)).toBe(true);
    page.frames.run(3);
    expect(went).toHaveFocus();
    expect(scrolled).not.toHaveBeenCalled();
  });
});
