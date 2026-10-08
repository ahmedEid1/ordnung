/**
 * "Why this date?" on Today (Top 3): a date counted without the sender's Land says so, with the way to choose it —
 * as the letter's own receipt does (`features/document/sender-land.test.tsx`).
 */
import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Contract, Party } from "@/api/types";
import { qk } from "@/api/hooks";
import { makeItem, makeReceipt } from "@/features/document/fixtures";
import { makeTestQueryClient, renderWithProviders } from "@/test/render";
import { receiptForContract, receiptForItem } from "./receipt";
import { WhyThisDate } from "./WhyThisDate";

const CITY: Party = {
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
};

/** The engine without the sender's Land, for a Land authority's letter (`rules.delivery`). */
const THREE_DAYS = "Some Länder may still use the 3-day rule for their authorities and we couldn't confirm this sender's, so we counted 3 days (the earlier date).";

/** Counted backwards past a holiday of some Länder (`rules.deadlines.REGION_EARLIER`): the date may be a day late. */
const BACKWARDS =
  "Holiday region unknown — Wed 18 Nov 2026 is a public holiday in some Länder (e.g. Sachsen), where the deadline would be earlier — act a working day before it to be safe. We used nationwide holidays only.";

/** Today's receipt for a to-do of `party`'s, with Today's list of parties loaded. */
function renderReceipt(party: Party, warnings: string[] = [THREE_DAYS]) {
  const client = makeTestQueryClient();
  client.setQueryData(qk.parties.list(), [party]);
  const item = makeItem({ title: "Pay the fee", due_date: "2026-11-17", party_id: party.id, computation: makeReceipt({ warnings, confidence: "medium" }) });
  return { user: userEvent.setup(), ...renderWithProviders(<WhyThisDate receipt={receiptForItem(item)} context="Pay the fee" />, { client }) };
}

describe("Today's “Why this date?” for a date that waits for the sender's state", () => {
  it("knows whose date it is: the to-do's sender, or the contract's", () => {
    expect(receiptForItem(makeItem({ party_id: "pty_city" })).partyId).toBe("pty_city");
    expect(receiptForItem(makeItem({ party_id: null })).partyId).toBeNull();
    const contract = { party_id: "pty_gym", computed: { summary: "", steps: [], warnings: [], notes: [], confidence: "high", send_by: null, cancel_by: null }, evidence: [] };
    expect(receiptForContract(contract as unknown as Contract)!.partyId).toBe("pty_gym");
  });

  it("says Ordnung doesn't know their state, and “Choose their state” opens their details", async () => {
    const { user, router } = renderReceipt(CITY);
    await user.click(screen.getByRole("button", { name: "Why this date? (Pay the fee)" }));
    const sheet = await screen.findByRole("dialog", { name: "Why this date? Pay the fee" });
    expect(within(sheet).getByText(/Ordnung doesn't know which state Stadt Musterstadt is in, so this date may be a few days early\./)).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Choose their state" }));
    expect(router.state.location.search).toBe("?party=pty_city");
  });

  it("says a date counted backwards may be a day late, and to act a working day before it", async () => {
    const { user } = renderReceipt(CITY, [BACKWARDS]);
    await user.click(screen.getByRole("button", { name: "Why this date? (Pay the fee)" }));
    const sheet = await screen.findByRole("dialog", { name: "Why this date? Pay the fee" });
    expect(within(sheet).getByText(/Ordnung doesn't know which state Stadt Musterstadt is in, so this date may be a day late: act a working day before it\./)).toBeInTheDocument();
    expect(within(sheet).queryByText(/a few days early/)).toBeNull();
  });

  it("says nothing once their state is set, for a sender abroad, or for a date that doesn't wait for it", async () => {
    for (const [party, warnings] of [
      [{ ...CITY, region: "NW" }, [THREE_DAYS]],
      [{ ...CITY, address: "1 Example Road, Examplia" }, [THREE_DAYS]],
      [CITY, ["This was read by AI from a photo or scan — compare the date with the paper letter."]],
    ] as const) {
      const { user, unmount } = renderReceipt(party, [...warnings]);
      await user.click(screen.getByRole("button", { name: "Why this date? (Pay the fee)" }));
      const sheet = await screen.findByRole("dialog", { name: "Why this date? Pay the fee" });
      expect(within(sheet).queryByRole("button", { name: "Choose their state" })).toBeNull();
      unmount();
    }
  });
});
