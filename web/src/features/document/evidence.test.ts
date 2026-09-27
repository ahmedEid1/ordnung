import { describe, expect, it } from "vitest";
import type { Box, DocumentDetail, Evidence } from "@/api/types";
import { boxToStyle, boxesByPage, centerScrollOffset, collectAnchors, highlightGroups, hitBoxStyle, hitBoxes, labelPlacement, normalizeBox, unionBox } from "./evidence";
import { makeDetail, makeDoc, makeItem } from "./fixtures";

const box = (page: number, x0: number, y0: number, x1: number, y1: number): Box => ({ page, x0, y0, x1, y1 });
const ev = (quote: string, boxes: Box[], extra: Partial<Evidence> = {}): Evidence => ({
  doc_id: "doc_1",
  page: boxes[0]?.page ?? null,
  quote,
  grounding: "verified",
  value_consistent: true,
  score: 0.97,
  boxes,
  ...extra,
});

describe("overlay positioning math", () => {
  it("maps relative coordinates to percentages of the page", () => {
    expect(boxToStyle(box(1, 0.1, 0.25, 0.6, 0.3))).toEqual({ left: "10%", top: "25%", width: "50%", height: "5%" });
  });

  it("pads the highlighter without leaving the page", () => {
    const s = boxToStyle(box(1, 0.001, 0.5, 0.999, 0.52), 0.004, 0.002);
    expect(s.left).toBe("0%");
    expect(s.top).toBe("49.8%");
    expect(s.width).toBe("100%");
    expect(s.height).toBe("2.4%");
  });

  it("normalises swapped corners and clamps out-of-range values", () => {
    expect(normalizeBox(box(2, 0.8, 0.9, 0.2, 0.1))).toEqual(box(2, 0.2, 0.1, 0.8, 0.9));
    expect(normalizeBox(box(1, -0.2, 0.4, 1.3, Number.NaN))).toEqual(box(1, 0, 0, 1, 0.4));
  });

  it("stays aligned at any zoom (percentages don't depend on the rendered size)", () => {
    const b = box(1, 0.12, 0.4, 0.88, 0.42);
    const s = boxToStyle(b);
    for (const width of [358, 520, 780]) {
      const height = width * (1754 / 1240);
      expect((parseFloat(s.left) / 100) * width).toBeCloseTo(0.12 * width);
      expect((parseFloat(s.top) / 100) * height).toBeCloseTo(0.4 * height);
    }
  });

  it("unions multi-line quotes and groups boxes by page", () => {
    const lines = [box(1, 0.12, 0.40, 0.88, 0.42), box(1, 0.12, 0.42, 0.5, 0.44)];
    expect(unionBox(lines)).toEqual(box(1, 0.12, 0.4, 0.88, 0.44));
    expect(unionBox([])).toBeNull();
    const byPage = boxesByPage([...lines, box(2, 0.1, 0.1, 0.2, 0.2)]);
    expect([...byPage.keys()]).toEqual([1, 2]);
    expect(byPage.get(1)).toHaveLength(2);
  });

  it("centres a highlight in the scroll container and clamps at the edges", () => {
    const g = { pageTop: 1000, pageLeft: 16, pageWidth: 500, pageHeight: 707, viewportWidth: 532, viewportHeight: 600, contentWidth: 532, contentHeight: 2000 };
    // box centre y = 1000 + 0.5 * 707 = 1353.5 → top = 1353.5 - 300
    expect(centerScrollOffset(box(2, 0.2, 0.49, 0.8, 0.51), g)).toEqual({ top: 1054, left: 0 });
    // near the top of the first page → clamped to 0
    expect(centerScrollOffset(box(1, 0.2, 0.01, 0.8, 0.02), { ...g, pageTop: 16 }).top).toBe(0);
    // near the end → clamped to the maximum scroll
    expect(centerScrollOffset(box(2, 0.2, 0.98, 0.8, 0.99), { ...g, pageTop: 1293 }).top).toBe(1400);
    // zoomed in: horizontal centring
    const zoomed = { ...g, pageWidth: 750, contentWidth: 782 };
    expect(centerScrollOffset(box(1, 0.8, 0.5, 0.9, 0.52), zoomed).left).toBe(250);
  });
});

describe("anchors & highlight groups", () => {
  const shared = ev("Erstattung 324,00 EUR", [box(1, 0.1, 0.3, 0.5, 0.32)]);
  const detail: DocumentDetail = makeDetail({
    document: makeDoc({
      key_facts: [
        { label: "Refund", value: "€324.00", evidence: shared },
        { label: "No evidence", value: "x", evidence: null },
        { label: "Photo fact", value: "15 Sep", evidence: ev("Datum 15.09.2026", [], { grounding: "model_read", page: 1 }) },
      ],
    }),
    items: [
      makeItem({ id: "itm_a", title: "Refund arrives", evidence: [shared] }),
      makeItem({ id: "itm_b", title: "Other letter", evidence: [{ ...shared, doc_id: "doc_other" }] }),
      makeItem({ id: "itm_c", title: "Two pages", evidence: [ev("spans pages", [box(1, 0.1, 0.9, 0.9, 0.92), box(2, 0.1, 0.1, 0.6, 0.12)])] }),
    ],
  });

  it("collects facts and to-dos of this letter only", () => {
    const anchors = collectAnchors(detail);
    expect(anchors.map((a) => a.id)).toEqual(["fact:0", "fact:2", "item:itm_a:0", "item:itm_c:0"]);
    expect(anchors[0]).toMatchObject({ source: "fact", label: "Refund", value: "€324.00" });
  });

  it("shares one highlight between a fact and a to-do quoting the same sentence", () => {
    const groups = highlightGroups(collectAnchors(detail));
    const refund = groups.find((g) => g.anchors.some((a) => a.id === "fact:0"))!;
    expect(refund.anchors.map((a) => a.id)).toEqual(["fact:0", "item:itm_a:0"]);
    // photo evidence without boxes is not drawn (shown as a quote callout instead)
    expect(groups.some((g) => g.anchors.some((a) => a.id === "fact:2"))).toBe(false);
    // a quote spanning two pages yields one group per page
    const spans = groups.filter((g) => g.anchors.some((a) => a.id === "item:itm_c:0"));
    expect(spans.map((g) => g.page)).toEqual([1, 2]);
    expect(new Set(spans.map((g) => g.key)).size).toBe(2);
  });
});

describe("UI audit round 1: highlight targets and labels", () => {
  // a payslip: "Hourly wage" on one line, the two-line "Monthly salary payment" quote around it
  const detail = (): DocumentDetail =>
    makeDetail({
      document: makeDoc({
        key_facts: [{ label: "Hourly wage", value: "€15.00", evidence: ev("Stundenlohn 15,00 €", [box(1, 0.1, 0.5, 0.4, 0.51)]) }] as DocumentDetail["document"]["key_facts"],
      }),
      items: [
        makeItem({
          id: "itm_salary",
          title: "Monthly salary payment",
          evidence: [ev("Auszahlung … monatlich", [box(1, 0.1, 0.49, 0.9, 0.5), box(1, 0.1, 0.51, 0.7, 0.52)])],
        }),
      ],
    });

  it("gives every line its own target, kept clear of the neighbouring highlight's lines", () => {
    const groups = highlightGroups(collectAnchors(detail()));
    const salary = groups.find((g) => g.anchors[0]!.label === "Monthly salary payment")!;
    const wage = groups.find((g) => g.anchors[0]!.label === "Hourly wage")!;
    const hits = hitBoxes(salary, groups);
    expect(hits).toHaveLength(2); // one per line, not the union rectangle over "Hourly wage"
    expect(hits[0]!.below).toBeCloseTo(0.5); // half-way to the wage line below
    expect(hits[1]!.above).toBeCloseTo(0.51);
    const [wageHit] = hitBoxes(wage, groups);
    expect(wageHit!.above).toBeCloseTo(0.5);
    expect(wageHit!.below).toBeCloseTo(0.51);
    // a finger-sized pad, clamped at the half-way lines
    expect(hitBoxStyle(wageHit!)).toMatchObject({ top: "max(50%, calc(50% - 8px))", height: "calc(min(51%, calc(51% + 8px)) - max(50%, calc(50% - 8px)))" });
    expect(hitBoxStyle({ box: box(1, 0.1, 0.2, 0.3, 0.21), above: null, below: null })).toMatchObject({ top: "calc(20% - 8px)", height: "calc(calc(21% + 8px) - calc(20% - 8px))" });
  });

  it("puts a label right-aligned in the right half, and under the box when a highlight sits just above", () => {
    const groups = highlightGroups(collectAnchors(detail()));
    const wage = groups.find((g) => g.anchors[0]!.label === "Hourly wage")!;
    expect(labelPlacement(wage, groups)).toEqual({ align: "left", side: "below" });
    const right = { ...wage, key: "r", bounds: box(1, 0.6, 0.3, 0.95, 0.31), boxes: [box(1, 0.6, 0.3, 0.95, 0.31)] };
    expect(labelPlacement(right, [right])).toEqual({ align: "right", side: "above" });
    const top = { ...right, bounds: box(1, 0.1, 0.02, 0.3, 0.03) };
    expect(labelPlacement(top, [top]).side).toBe("below");
  });
});
