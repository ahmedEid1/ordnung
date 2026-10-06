import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Party } from "@/api/types";
import { qk } from "@/api/hooks";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { makeDetail, makeDoc, makeItem, makeReceipt } from "./fixtures";
import { ReceiptView, senderLandUnknown, WhyThisDate } from "./WhyThisDate";

const party = (p: Partial<Party> = {}): Party => ({
  id: "pty_city",
  name: "Stadt Musterstadt",
  kind: "authority",
  aliases: [],
  identifiers: [],
  address: "Rathausplatz 1, 12345 Musterstadt",
  email: null,
  phone: null,
  website: null,
  notes: null,
  region: null,
  ibans: [],
  created_at: "2026-09-01T07:00:00Z",
  updated_at: "2026-09-01T07:00:00Z",
  ...p,
});

const NATIONWIDE = "Germany (nationwide holidays only)";

/** The engine without the sender's Land, for a Land authority's letter: the 3-day rule, at lower confidence. */
const threeDays = makeReceipt({
  due_date: "2026-11-17",
  holiday_calendar: NATIONWIDE,
  confidence: "medium",
  warnings: ["Some Länder may still use the 3-day rule for their authorities and we couldn't confirm this sender's, so we counted 3 days (the earlier date)."],
});

/** … or where a Land's holiday may make the date later. */
const holiday = makeReceipt({
  due_date: "2027-11-01",
  holiday_calendar: NATIONWIDE,
  confidence: "low",
  warnings: [
    "Holiday region unknown — Mon 1 Nov 2027 is a public holiday in some Länder (e.g. Baden-Württemberg, Bayern, Nordrhein-Westfalen), where the deadline would be later. We used nationwide holidays only.",
  ],
});

describe("a date that waits for the sender's state", () => {
  it("is one the engine says its Land would change, for a sender in Germany whose state isn't set", () => {
    expect(senderLandUnknown(threeDays, party())?.id).toBe("pty_city");
    expect(senderLandUnknown(holiday, party())?.id).toBe("pty_city");
    expect(senderLandUnknown(threeDays, party({ region: "SN" }))).toBeNull(); // the person said
    expect(senderLandUnknown(threeDays, party({ address: "1 Example Road, Examplia" }))).toBeNull(); // abroad
    expect(senderLandUnknown(threeDays, null)).toBeNull();
    // nationwide holidays and lower confidence for another reason (the demo's appointment read from a photo)
    const photo = makeReceipt({ holiday_calendar: NATIONWIDE, confidence: "medium", warnings: ["This was read by AI from a photo or scan — compare the date with the paper letter."] });
    expect(senderLandUnknown(photo, party())).toBeNull();
  });

  it("says so on “Why this date?” and opens the sender's drawer to choose it", async () => {
    const user = userEvent.setup();
    const client = makeTestQueryClient();
    client.setQueryData(qk.documents.detail("doc_1"), makeDetail({ document: makeDoc({ party_id: "pty_city" }), party: party() }));
    const item = makeItem({ due_date: "2026-11-17", computation: threeDays });
    const { router } = renderWithProviders(<ReceiptView receipt={threeDays} item={item} />, { client });
    expect(screen.getByText(/Ordnung doesn't know which state Stadt Musterstadt is in, so this date may be a few days early\./)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Choose their state" }));
    expect(router.state.location.search).toBe("?party=pty_city");
  });

  it("closes “Why this date?” before the drawer opens: on a phone its sheet kept the keyboard from the State picker", async () => {
    const user = userEvent.setup();
    const client = makeTestQueryClient();
    client.setQueryData(qk.documents.detail("doc_1"), makeDetail({ document: makeDoc({ party_id: "pty_city" }), party: party() }));
    const item = makeItem({ due_date: "2026-11-17", computation: threeDays });
    // jsdom has no media queries: the phone's bottom sheet, modal
    const { router } = renderWithProviders(<WhyThisDate receipt={threeDays} item={item} context="Pay the fee" />, { client });
    const trigger = screen.getByRole("button", { name: "Why this date? (Pay the fee)" });
    await user.click(trigger);
    const sheet = await screen.findByRole("dialog", { name: "Why this date? Pay the fee" });
    expect(sheet).toHaveAttribute("aria-modal", "true");
    await user.click(within(sheet).getByRole("button", { name: "Choose their state" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Why this date? Pay the fee" })).toBeNull());
    expect(router.state.location.search).toBe("?party=pty_city");
    // where the drawer gives the keyboard back when it closes
    expect(trigger).toHaveFocus();
  });

  it("is not mentioned once the sender's state is set", () => {
    const client = makeTestQueryClient();
    client.setQueryData(qk.documents.detail("doc_1"), makeDetail({ party: party({ region: "SN" }) }));
    renderWithProviders(<ReceiptView receipt={threeDays} item={makeItem({ computation: threeDays })} />, { client });
    expect(screen.queryByRole("button", { name: "Choose their state" })).toBeNull();
  });
});
