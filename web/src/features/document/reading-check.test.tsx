/**
 * The to-do Ordnung files itself when Claude's reading of a letter came back incomplete (`check:reading`,
 * `src/ordnung/ingest/gaps.py`): its "Please check" card says where its date came from — or, without one, that
 * the reading came back almost blank — instead of "doesn't match the sentence it came from" or "Couldn't find
 * this — please check".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { qk } from "@/api/hooks";
import { DocumentWarnings, READING_CHECK_SLOT } from "./Warnings";
import { makeDetail, makeDoc, makeItem } from "./fixtures";

function client() {
  const qc = makeTestQueryClient();
  qc.setQueryData(qk.rules, []);
  return qc;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })));
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const NOTICE = "Gegen diesen Gebührenbescheid können Sie binnen eines Monats nach seiner Bekanntgabe Widerspruch einlegen.";

const dated = makeItem({
  id: "itm_check",
  kind: "deadline",
  title: "Deadline to object (Widerspruch)",
  due_date: "2026-12-09",
  slot_key: READING_CHECK_SLOT,
  grounding: "verified",
  evidence: [{ doc_id: "doc_1", page: 1, quote: NOTICE, grounding: "verified", value_consistent: false, score: 100, boxes: [] }],
});

const undated = makeItem({
  id: "itm_read",
  kind: "task",
  title: "Read this letter yourself",
  due_date: null,
  slot_key: READING_CHECK_SLOT,
  grounding: "unverified",
  evidence: [{ doc_id: "doc_1", page: null, quote: "", grounding: "unverified", value_consistent: false, score: 0, boxes: [] }],
});

describe("the to-do Ordnung adds for an incomplete reading", () => {
  it("says a dated one was worked out from the letter's instructions on how to object", () => {
    const doc = makeDoc({ status: "needs_review" });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc, items: [dated] })} />, { client: client() });
    expect(screen.getByText("Deadline to object (Widerspruch)", { exact: false })).toBeInTheDocument();
    expect(
      screen.getByText("Ordnung worked this date out from the letter's own instructions on how to object, because Claude's reading left it out."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/doesn't match the sentence it came from/)).toBeNull();
    expect(screen.getByRole("button", { name: "Correct" })).toBeInTheDocument();
  });

  it("asks the person to read the letter when it has no date", () => {
    const doc = makeDoc({ status: "needs_review" });
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: doc, items: [undated] })} />, { client: client() });
    expect(screen.getByText("Read this letter yourself", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Claude's reading of this letter came back almost blank: read the letter and add any date it sets.")).toBeInTheDocument();
    expect(screen.queryByText(/Couldn't find this/)).toBeNull();
    expect(screen.getByRole("button", { name: "Change date" })).toBeInTheDocument();
  });

  it("leaves every other to-do's card as it was", () => {
    const other = { ...dated, id: "itm_other", slot_key: "a".repeat(40), title: "Pay the fee" };
    renderWithProviders(<DocumentWarnings detail={makeDetail({ document: makeDoc({ status: "needs_review" }), items: [other] })} />, { client: client() });
    expect(screen.getByText("The date or amount doesn't match the sentence it came from.")).toBeInTheDocument();
  });
});
