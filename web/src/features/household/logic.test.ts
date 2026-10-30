import { describe, expect, it } from "vitest";
import type { Household } from "@/api/types";
import { makeRow } from "@/features/document/fixtures";
import { comingUpMeta } from "@/features/today/helpers";
import {
  MINE,
  actionMember,
  answerOf,
  fileTheseLabel,
  filedMember,
  forLine,
  forOptions,
  matchesFor,
  memberById,
  parseFor,
  suggestedFor,
  undoLetters,
} from "./logic";

const ALEX = { id: "hhm_alexalexalex", name: "Alex Rivera", signs: true, letters: 2 };
const MIA = { id: "hhm_miamiamiamia", name: "Mia Rivera", signs: false, letters: 1 };
const EMPTY: Household = { members: [], filed: {}, mine: [], suggested: {}, version: "4f53cda18c2baa0c" };
const HOUSEHOLD: Household = {
  members: [ALEX, MIA],
  filed: { doc_a1: ALEX.id, doc_a2: ALEX.id, doc_m1: MIA.id },
  mine: ["doc_mine"],
  suggested: { doc_s1: ALEX.id, doc_s2: ALEX.id, doc_s3: MIA.id },
  version: "0123456789abcdef",
};
const docs = ["doc_a1", "doc_a2", "doc_m1", "doc_mine", "doc_s1", "doc_s2", "doc_s3", "doc_plain"].map((id) => makeRow({ id }));
const ids = (list: readonly { id: string }[]) => list.map((d) => d.id);

describe("household logic", () => {
  it("finds a person, and the person a letter is filed for", () => {
    expect(memberById(HOUSEHOLD, ALEX.id)).toEqual(ALEX);
    expect(memberById(HOUSEHOLD, "hhm_gonegonegone")).toBeNull();
    expect(memberById(undefined, ALEX.id)).toBeNull();
    expect(filedMember(HOUSEHOLD, "doc_m1")).toEqual(MIA);
    expect(filedMember(HOUSEHOLD, "doc_mine")).toBeNull();
    expect(filedMember(HOUSEHOLD, "doc_s1")).toBeNull(); // a suggestion is not a filing
    expect(filedMember(undefined, "doc_a1")).toBeNull();
  });

  it("names whose a Today action is by its letter, never a contract's (its decision is the person's, ADR 0025)", () => {
    expect(actionMember(HOUSEHOLD, { source: "item", docId: "doc_a1" })).toEqual(ALEX);
    expect(actionMember(HOUSEHOLD, { source: "item", docId: "doc_mine" })).toBeNull();
    expect(actionMember(HOUSEHOLD, { source: "item", docId: null })).toBeNull();
    // a contract's action carries the letter it came from, filed for Alex: still no one
    expect(actionMember(HOUSEHOLD, { source: "contract", docId: "doc_a1" })).toBeNull();
    expect(actionMember(undefined, { source: "item", docId: "doc_a1" })).toBeNull();
  });

  it("reads ?for=: You, a person, else Everyone — and only while the household has people", () => {
    expect(parseFor(MINE, HOUSEHOLD)).toBe(MINE);
    expect(parseFor(ALEX.id, HOUSEHOLD)).toBe(ALEX.id);
    expect(parseFor("hhm_gonegonegone", HOUSEHOLD)).toBeNull();
    expect(parseFor(null, HOUSEHOLD)).toBeNull();
    expect(parseFor("", HOUSEHOLD)).toBeNull();
    expect(parseFor(MINE, EMPTY)).toBeNull();
    expect(parseFor(ALEX.id, undefined)).toBeNull();
  });

  it("narrows to a person's letters, or to the person's own: every letter not filed for someone", () => {
    expect(ids(docs.filter((d) => matchesFor(d, null, HOUSEHOLD)))).toEqual(ids(docs));
    expect(ids(docs.filter((d) => matchesFor(d, ALEX.id, HOUSEHOLD)))).toEqual(["doc_a1", "doc_a2"]);
    expect(ids(docs.filter((d) => matchesFor(d, MIA.id, HOUSEHOLD)))).toEqual(["doc_m1"]);
    expect(ids(docs.filter((d) => matchesFor(d, MINE, HOUSEHOLD)))).toEqual(["doc_mine", "doc_s1", "doc_s2", "doc_s3", "doc_plain"]);
    expect(ids(docs.filter((d) => matchesFor(d, MINE, undefined)))).toEqual(ids(docs));
  });

  it("offers Everyone, You, then each person with the letters filed for them; nothing without people", () => {
    expect(forOptions(docs, HOUSEHOLD)).toEqual([
      { value: "", label: "Everyone", count: null },
      { value: MINE, label: "You", count: null },
      { value: ALEX.id, label: "Alex Rivera (2)", count: 2 },
      { value: MIA.id, label: "Mia Rivera (1)", count: 1 },
    ]);
    // counted within the letters given, like the kind select
    expect(forOptions(docs.slice(2), HOUSEHOLD).map((o) => o.label)).toEqual(["Everyone", "You", "Alex Rivera (0)", "Mia Rivera (1)"]);
    expect(forOptions(docs, EMPTY)).toEqual([]);
    expect(forOptions(docs, undefined)).toEqual([]);
  });

  it("lists the letters addressed to a person and not answered yet, in their order", () => {
    expect(ids(suggestedFor(docs, ALEX.id, HOUSEHOLD))).toEqual(["doc_s1", "doc_s2"]);
    expect(ids(suggestedFor(docs, MIA.id, HOUSEHOLD))).toEqual(["doc_s3"]);
    expect(ids(suggestedFor(docs.slice(0, 5), ALEX.id, HOUSEHOLD))).toEqual(["doc_s1"]);
    expect(suggestedFor(docs, ALEX.id, undefined)).toEqual([]);
  });

  it("knows each letter's answer, so an Undo puts back exactly what was there", () => {
    expect(answerOf(HOUSEHOLD, "doc_a1")).toBe(ALEX.id);
    expect(answerOf(HOUSEHOLD, "doc_mine")).toBe(MINE);
    expect(answerOf(HOUSEHOLD, "doc_s1")).toBeNull();
    expect(answerOf(undefined, "doc_a1")).toBeNull();
    expect(undoLetters(HOUSEHOLD, ["doc_s1", "doc_mine", "doc_m1"])).toEqual({ doc_s1: null, doc_mine: MINE, doc_m1: MIA.id });
    expect(undoLetters(HOUSEHOLD, [])).toEqual({});
  });

  it("names the button that files the listed letters", () => {
    expect(fileTheseLabel(3, "Alex Rivera")).toBe("File these 3 for Alex Rivera");
    expect(fileTheseLabel(1, "Alex Rivera")).toBe("File it for Alex Rivera");
  });

  it(`forLine says "For <name>", the same words as Today's Coming up`, () => {
    expect(forLine("Alex Rivera")).toBe("For Alex Rivera");
    // a Coming-up row whose date needs no word ("due") and has no time or party: only the name
    expect(forLine("Alex Rivera")).toBe(comingUpMeta({ dateRole: "due", time: null }, undefined, "Alex Rivera"));
  });
});
