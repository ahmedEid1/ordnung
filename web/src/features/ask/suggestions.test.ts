/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { SUGGESTED_QUESTIONS as MOCK_SUGGESTED } from "@/mocks/data/ask";
import { SUGGESTED_QUESTIONS, isSuggestedQuestion } from "./suggestions";

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
});
