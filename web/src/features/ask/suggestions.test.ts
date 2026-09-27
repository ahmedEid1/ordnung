/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { SUGGESTED_QUESTIONS as MOCK_SUGGESTED } from "@/mocks/data/ask";
import { SUGGESTED_QUESTIONS, isSuggestedQuestion, suggestedQuestions } from "./suggestions";

describe("suggested questions", () => {
  it("are exactly the questions the demo has recorded answers for", () => {
    // outside the web root, so read from disk rather than through Vite
    const recorded = JSON.parse(readFileSync(resolve(__dirname, "../../../../src/ordnung/demo/asks.json"), "utf8")) as string[];
    expect(SUGGESTED_QUESTIONS.map((s) => s.question)).toEqual(recorded);
    expect(MOCK_SUGGESTED).toEqual(recorded);
  });

  it("recognises a suggested question regardless of case and spacing", () => {
    expect(isSuggestedQuestion("  which deadlines are coming up in october? ")).toBe(true);
    expect(isSuggestedQuestion("What is the meaning of life?")).toBe(false);
  });

  it("outside the demo fit the person: the month ahead, the residence permit only with a student visa", () => {
    // UI audit round 1: a fresh install offered the demo's "October" and a residence permit to everyone
    const q = (today: string, studentVisa: boolean) => suggestedQuestions({ today: new Date(`${today}T12:00:00`), studentVisa }).map((s) => s.question);
    expect(q("2027-03-04", false)).toEqual([
      "When does my phone contract end, and by when do I have to cancel it?",
      "What do I have to pay in the next four weeks?",
      "Which deadlines are coming up in March?",
    ]);
    // after mid-month the next month is the one ahead (December → January)
    expect(q("2027-12-20", true)).toEqual([
      "When does my phone contract end, and by when do I have to cancel it?",
      "What do I have to pay in the next four weeks?",
      "Which deadlines are coming up in January?",
      "When does my residence permit expire, and what should I do before then?",
    ]);
  });
});
