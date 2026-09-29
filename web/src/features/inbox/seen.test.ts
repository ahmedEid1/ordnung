import { beforeEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { markLetterSeen, resetSeenLetters, useMarkLetterSeen, useSeenLetters } from "./seen";

beforeEach(() => resetSeenLetters());

describe("seen letters", () => {
  it("remembers the letters whose page was shown, in this browser", () => {
    const { result } = renderHook(() => useSeenLetters());
    expect(result.current.has("doc_a")).toBe(false);
    act(() => markLetterSeen("doc_a"));
    expect(result.current.has("doc_a")).toBe(true);
    expect(JSON.parse(localStorage.getItem("ordnung.seen-letters")!)).toEqual(["doc_a"]);
    // seeing it again changes nothing (same snapshot: no re-render loop)
    const before = result.current;
    act(() => markLetterSeen("doc_a"));
    expect(result.current).toBe(before);
  });

  it("marks a letter while its page is on screen, not while it is still loading", () => {
    const { rerender } = renderHook(({ id }: { id: string | null }) => useMarkLetterSeen(id), { initialProps: { id: null as string | null } });
    const seen = renderHook(() => useSeenLetters());
    expect(seen.result.current.size).toBe(0);
    rerender({ id: "doc_b" });
    expect(seen.result.current.has("doc_b")).toBe(true);
  });

  it("keeps the most recent 200", () => {
    act(() => {
      for (let i = 0; i < 205; i++) markLetterSeen(`doc_${i}`);
    });
    const stored = JSON.parse(localStorage.getItem("ordnung.seen-letters")!) as string[];
    expect(stored).toHaveLength(200);
    expect(stored[0]).toBe("doc_5");
    expect(stored.at(-1)).toBe("doc_204");
  });
});
