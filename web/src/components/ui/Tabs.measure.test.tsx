import { afterEach, describe, expect, it } from "vitest";
import { useState } from "react";
import { fireEvent, screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { Tabs } from "./Tabs";

/** How often the tab row's width was read (each read makes the browser lay out the page first). */
let reads = 0;

afterEach(() => {
  delete (HTMLElement.prototype as { scrollWidth?: number }).scrollWidth;
});

function countReads() {
  reads = 0;
  Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
    configurable: true,
    get(this: HTMLElement) {
      if (this.getAttribute("role") === "tablist") reads++;
      return 0;
    },
  });
}

/** A page that renders again on every key, as the Inbox does while a search is typed, with its tabs inside. */
function Page() {
  const [typed, setTyped] = useState("");
  const [more, setMore] = useState(false);
  return (
    <>
      <input aria-label="Search" value={typed} onChange={(e) => setTyped(e.target.value)} />
      <button type="button" onClick={() => setMore(true)}>
        More tabs
      </button>
      {/* a new array each render, as the pages build it */}
      <Tabs
        label="Filter letters"
        variant="pill"
        value="all"
        onChange={() => {}}
        items={[
          { value: "all", label: "All", count: 3 },
          { value: "check", label: "Please check", count: 1 },
          ...(more ? [{ value: "private", label: "Private", count: 0 }] : []),
        ]}
      />
    </>
  );
}

describe("Tabs: measuring the row", () => {
  it("measures when drawn and when its tabs change, not on every render of the page", () => {
    countReads();
    renderWithProviders(<Page />);
    const drawn = reads;
    expect(drawn).toBeGreaterThan(0);

    const search = screen.getByRole("textbox", { name: "Search" });
    for (const typed of ["M", "Mu", "Mus", "Must", "Muste", "Muster"]) fireEvent.change(search, { target: { value: typed } });
    expect(search).toHaveValue("Muster");
    expect(reads).toBe(drawn);

    // a tab more: the row is measured again
    fireEvent.click(screen.getByRole("button", { name: "More tabs" }));
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(reads).toBeGreaterThan(drawn);
  });
});
