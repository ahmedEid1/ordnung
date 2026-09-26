import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Document, Draft } from "@/api/types";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { assertNoRawEnumsInElement } from "@/lib/copy";
import { PartyDrawer } from "./PartyDrawer";
import { byYear, letterTimeline, mailtoUrl, regionName, websiteUrl } from "./timeline";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("party helpers", () => {
  it("merges their letters and yours, newest first, grouped by year", () => {
    const docs = [
      { id: "doc_a", title: "Lease", filename: "a.pdf", doc_date: "2025-09-15", received_date: null, created_at: "2025-09-16T10:00:00Z", direction: "incoming", kind: "rent_lease" },
      { id: "doc_b", title: null, filename: "b.pdf", doc_date: null, received_date: "2026-09-09", created_at: "2026-09-10T10:00:00Z", direction: "incoming", kind: "utility_bill" },
    ] as Document[];
    const drafts = [{ id: "drf_a", kind: "general_reply", subject: "Belegeinsicht", sent_at: "2026-09-15T17:00:00Z", created_at: "2026-09-15T16:50:00Z", status: "sent" }] as Draft[];
    const t = letterTimeline(docs, drafts);
    expect(t.map((e) => [e.id, e.direction, e.date])).toEqual([
      ["drf_a", "out", "2026-09-15"],
      ["doc_b", "in", "2026-09-09"],
      ["doc_a", "in", "2025-09-15"],
    ]);
    expect(t[0]).toMatchObject({ title: "Your reply", subtitle: "Belegeinsicht", href: "/letters/drf_a" });
    expect(t[1]).toMatchObject({ title: "b.pdf", href: "/documents/doc_b" });
    expect(byYear(t).map((g) => [g.year, g.entries.length])).toEqual([
      ["2026", 2],
      ["2025", 1],
    ]);
  });

  it("region names and safe website links", () => {
    expect(regionName("NW")).toBe("North Rhine-Westphalia");
    expect(regionName("BE")).toBe("Berlin");
    expect(regionName(null)).toBeNull();
    expect(websiteUrl("funknetz.example")).toBe("https://funknetz.example");
    expect(websiteUrl("http://a.example/x")).toBe("https://a.example/x");
    expect(websiteUrl("javascript:alert(1)")).toBeNull();
  });

  it("mailto links only for plain e-mail addresses (they come from letters)", () => {
    expect(mailtoUrl("service@funknetz.example")).toBe("mailto:service@funknetz.example");
    expect(mailtoUrl(" kundenservice@stadtwerke-musterstadt.de ")).toBe("mailto:kundenservice@stadtwerke-musterstadt.de");
    expect(mailtoUrl("a@b.example?cc=evil@x.example&body=Pay%20now")).toBeNull();
    expect(mailtoUrl("javascript:alert(1)//@x.example")).toBeNull();
    expect(mailtoUrl(null)).toBeNull();
  });
});

describe("People & organisations drawer", () => {
  it("opens from ?party= with numbers to copy, contact, to-dos, contracts, letters and threads", async () => {
    useMockApi();
    const user = userEvent.setup();
    const writeText = vi.fn(async () => {});
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const { router } = renderWithProviders(<PartyDrawer />, { route: "/?party=pty_wohnbau" });
    const drawer = await screen.findByRole("dialog", { name: "Wohnbau Musterstadt eG" });
    expect(await within(drawer).findByText("Landlord")).toBeInTheDocument();
    expect(within(drawer).getByText("Holidays: North Rhine-Westphalia")).toBeInTheDocument();
    // identifiers & IBANs with copy buttons
    await user.click(within(drawer).getByRole("button", { name: "Copy Mieternummer" }));
    expect(writeText).toHaveBeenCalledWith("12-0412-07");
    expect(within(drawer).getByText("DE44 5001 0517 5407 3249 31")).toBeInTheDocument();
    // sections
    for (const name of ["Contact", /To-dos & dates/, /Contracts/, /Letters/, /Threads/]) {
      expect(within(drawer).getByRole("region", { name })).toBeInTheDocument();
    }
    const letters = within(drawer).getByRole("region", { name: /Letters/ });
    expect(within(letters).getByText("Utility cost statement 2025")).toBeInTheDocument();
    expect(within(letters).getAllByText("From them").length).toBeGreaterThan(0);
    // actions
    expect(within(drawer).getByRole("link", { name: /Write to them/ })).toHaveAttribute("href", "/letters?kind=general_reply&to=pty_wohnbau");
    assertNoRawEnumsInElement(drawer);
    // closing removes the URL state
    await user.click(within(drawer).getByRole("button", { name: "Close" }));
    expect(router.state.location.search).toBe("");
  });

  it("shows a calm not-found state", async () => {
    useMockApi();
    renderWithProviders(<PartyDrawer />, { route: "/?party=pty_nope" });
    expect(await screen.findByText("We couldn't find this contact")).toBeInTheDocument();
  });
});
