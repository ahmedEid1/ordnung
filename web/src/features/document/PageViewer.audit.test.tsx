/**
 * UI audit round 1, the page viewer: no scroll box of its own on phones and tablets (one page at a time
 * with a pager), a toolbar that never wraps, the photo quote under the page and closing with Escape,
 * highlights with a visible focus outline and one target per line.
 */
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, makeTestQueryClient } from "@/test/render";
import type { Box, Evidence, PageInfo } from "@/api/types";
import { EvidenceProvider, useEvidence } from "./EvidenceContext";
import { PageViewer } from "./PageViewer";
import type { EvidenceAnchor } from "./evidence";

const box = (page: number, x0: number, y0: number, x1: number, y1: number): Box => ({ page, x0, y0, x1, y1 });
const ev = (boxes: Box[], extra: Partial<Evidence> = {}): Evidence => ({
  doc_id: "doc_1",
  page: boxes[0]?.page ?? 1,
  quote: "Bitte überweisen Sie 94,99 €",
  grounding: "verified",
  value_consistent: true,
  score: 1,
  boxes,
  ...extra,
});
const PAGES: PageInfo[] = [
  { page: 1, width: 1240, height: 1754, text_source: "text" },
  { page: 2, width: 1240, height: 1754, text_source: "text" },
];

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } })),
  );
});
afterEach(() => vi.unstubAllGlobals());

let api: ReturnType<typeof useEvidence> | null = null;
/** Hands the evidence state to the test (hovered, selected, select). */
function Grab({ onApi }: { onApi: (e: ReturnType<typeof useEvidence>) => void }) {
  const e = useEvidence();
  useEffect(() => {
    onApi(e);
  });
  return null;
}

function renderViewer(anchors: EvidenceAnchor[], opts: { paged?: boolean; photo?: boolean } = {}) {
  return renderWithProviders(
    <EvidenceProvider anchors={anchors}>
      <Grab
        onApi={(e) => {
          api = e;
        }}
      />
      <PageViewer docId="doc_1" pages={PAGES} pageCount={2} paged={opts.paged} photo={opts.photo} />
    </EvidenceProvider>,
    { client: makeTestQueryClient() },
  );
}

describe("paged (phones and tablets)", () => {
  it("shows one page at a time with a pager, and has no scroll box of its own", async () => {
    renderViewer([], { paged: true });
    const viewer = screen.getByRole("region", { name: "Letter pages" });
    expect(within(viewer).getAllByRole("img", { name: /^Page \d of 2$/ })).toHaveLength(1);
    const images = within(viewer).getByRole("group", { name: "Page images" });
    expect(images.className).not.toMatch(/overscroll-contain|overflow-auto|max-h/);
    const pager = within(viewer).getByRole("navigation", { name: "Turn pages" });
    expect(within(pager).getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.click(within(pager).getByRole("button", { name: "Next" }));
    expect(within(viewer).getByRole("img", { name: "Page 2 of 2" })).toBeInTheDocument();
    expect(within(viewer).getByRole("button", { name: /^Go to page 2/ })).toHaveAttribute("aria-current", "page");
  });

  it("the tall column keeps every page in its scroll box", () => {
    renderViewer([]);
    const viewer = screen.getByRole("region", { name: "Letter pages" });
    expect(within(viewer).getAllByRole("img", { name: /^Page \d of 2$/ })).toHaveLength(2);
    expect(within(viewer).getByRole("group", { name: "Page images" })).toHaveClass("overflow-auto", "overscroll-contain");
    expect(within(viewer).queryByRole("navigation", { name: "Turn pages" })).toBeNull();
  });
});

describe("the toolbar", () => {
  it("never wraps the zoom control, says 150% and lets the thumbnails take the room left", () => {
    renderViewer([], { photo: true });
    const zoom = screen.getByRole("radiogroup", { name: "Zoom" });
    expect(within(zoom).getByRole("radio", { name: "150%" })).toBeInTheDocument();
    expect(zoom.parentElement).toHaveClass("shrink-0");
    const thumbs = screen.getByRole("list", { name: "Pages" });
    expect(thumbs).toHaveClass("min-w-0", "flex-1", "@min-[340px]:flex");
    // the highlight dot sits outside the clipped thumbnail; the thumbnail dims in dark mode like the page
    const thumb = within(thumbs).getAllByRole("button")[0]!;
    expect(thumb).not.toHaveClass("overflow-hidden");
    expect(thumb.querySelector("img")).toHaveClass("dark:brightness-[0.93]");
    expect(screen.getByRole("img", { name: "Phone photo" })).toBeInTheDocument();
  });
});

describe("highlights", () => {
  const two: EvidenceAnchor[] = [
    { id: "fact:0", source: "fact", label: "Hourly wage", value: "€15.00", evidence: ev([box(1, 0.1, 0.5, 0.4, 0.51)]), group: "g1" },
    { id: "item:x:0", source: "item", label: "Monthly salary payment", evidence: ev([box(1, 0.1, 0.49, 0.9, 0.5), box(1, 0.1, 0.51, 0.7, 0.52)]), group: "g2" },
  ];

  it("has a visible focus outline and one pointer target per line", () => {
    const { container } = renderViewer(two);
    const buttons = container.querySelectorAll("button[data-highlight]");
    expect(buttons).toHaveLength(2);
    for (const b of buttons) {
      expect(b).toHaveClass("focus-visible:outline-2", "focus-visible:outline-accent", "pointer-events-none");
      expect(b.className).not.toMatch(/focus-visible:ring/);
    }
    expect(container.querySelectorAll('[data-hit="g2"]')).toHaveLength(2);
    expect(container.querySelectorAll('[data-hit="g1"]')).toHaveLength(1);
  });

  it("hovering a line target lights up its own fact, never the neighbour's", async () => {
    const { container } = renderViewer(two);
    await userEvent.hover(container.querySelector('[data-hit="g1"]')!);
    expect(api!.hovered).toBe("fact:0");
  });
});

describe("the photo quote", () => {
  const photo: EvidenceAnchor[] = [
    { id: "fact:0", source: "fact", label: "Passport number", evidence: ev([], { grounding: "model_read", quote: "X1234567" }), group: "q" },
  ];

  it("sits under the page on phones and closes with Escape", async () => {
    renderViewer(photo, { paged: true, photo: true });
    act(() => api!.select("fact:0"));
    const quote = await screen.findByTestId("evidence-quote");
    expect(quote.parentElement).not.toHaveClass("absolute");
    await userEvent.keyboard("{Escape}");
    expect(api!.selected).toBeNull();
  });
});
