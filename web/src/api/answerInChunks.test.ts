/** Answers for many waiting letters go in requests of at most 500 ids (the API's limit), merged into one result. */
import { describe, expect, it } from "vitest";
import type { Document, HeldResult } from "./types";
import { HELD_CHUNK, answerInChunks } from "./hooks";

describe("answering for many waiting letters", () => {
  it("sends at most 500 ids a request, in order, and merges the results", async () => {
    const ids = Array.from({ length: 1201 }, (_, i) => `doc_${i}`);
    const sent: string[][] = [];
    const result = await answerInChunks(ids, (chunk) => {
      sent.push(chunk);
      return Promise.resolve({ documents: chunk.slice(0, 1).map((id) => ({ id }) as Document), jobs: [], skipped: chunk.slice(1, 2) } satisfies HeldResult);
    });
    expect(HELD_CHUNK).toBe(500);
    expect(sent.map((c) => c.length)).toEqual([500, 500, 201]);
    expect(sent.flat()).toEqual(ids);
    expect(result.documents.map((d) => d.id)).toEqual(["doc_0", "doc_500", "doc_1000"]);
    expect(result.skipped).toEqual(["doc_1", "doc_501", "doc_1001"]);
  });

  it("stops at the first failed request", async () => {
    const ids = Array.from({ length: 1100 }, (_, i) => `doc_${i}`);
    let calls = 0;
    await expect(
      answerInChunks(ids, () => {
        calls += 1;
        return calls === 2 ? Promise.reject(new Error("offline")) : Promise.resolve({ documents: [], jobs: [], skipped: [] });
      }),
    ).rejects.toThrow("offline");
    expect(calls).toBe(2);
  });
});
