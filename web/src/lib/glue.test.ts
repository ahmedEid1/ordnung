import { afterEach, describe, expect, it, vi } from "vitest";
import { copyWithoutGlue, plainText, protectRefs } from "./glue";

/** A `copy` event as the browser hands it to the handler (jsdom has no ClipboardEvent data). */
function copyEvent(target: Element) {
  const data = new Map<string, string>();
  const event = {
    target,
    clipboardData: { setData: (type: string, value: string) => data.set(type, value) },
    preventDefault: vi.fn(),
  };
  return { event: event as unknown as ClipboardEvent, data, prevented: event.preventDefault };
}

function select(text: string) {
  vi.spyOn(window, "getSelection").mockReturnValue({ toString: () => text } as Selection);
}

afterEach(() => vi.restoreAllMocks());

describe("copying glued text", () => {
  it("copies a reference with plain hyphens and spaces", () => {
    const p = document.createElement("p");
    select(`Invoice ${protectRefs("TM-2026-0048213")} by Wed\u00a014\u00a0Oct`);
    const { event, data, prevented } = copyEvent(p);
    copyWithoutGlue(event);
    expect(data.get("text/plain")).toBe("Invoice TM-2026-0048213 by Wed 14 Oct");
    expect(prevented).toHaveBeenCalled();
  });

  it("leaves plain selections and fields to the browser", () => {
    select("nothing glued here");
    const plain = copyEvent(document.createElement("p"));
    copyWithoutGlue(plain.event);
    expect(plain.data.size).toBe(0);
    expect(plain.prevented).not.toHaveBeenCalled();

    select("TM\u20112026");
    const field = copyEvent(document.createElement("textarea"));
    copyWithoutGlue(field.event);
    expect(field.data.size).toBe(0);
  });

  it("undoes every kind of glue", () => {
    expect(plainText("a\u00a0b\u202fc\u2011d")).toBe("a b c-d");
  });
});
