/**
 * The calendar file stays on the computer (UX review: a paired phone downloaded `ordnung.ics` — to-do titles, amounts,
 * what to do — although a phone keeps no copy, and the export dialog then sent it to a computer's Downloads and to a
 * Settings page the phone doesn't have). A phone offers no calendar download anywhere — Timeline, Today's calendar
 * card, a letter's "Add to calendar" — and asks the API for none; the computer keeps all of them.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ClientKind } from "@/api/types";
import { renderAppAt, stubShellGlobals } from "@/test/app";
import { useMockApi } from "@/test/mockFetch";

beforeEach(stubShellGlobals);
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const EXPORT = "Add your dates to your calendar";
const ADD = "Add to calendar";

/** A letter with an open, dated to-do (its verdict offers "Add to calendar" on the computer). */
function datedLetter(srv: ReturnType<typeof useMockApi>["srv"]): string {
  const st = srv.db.state;
  const item = st.items.find(
    (i) => i.status === "open" && i.due_date && i.doc_id && st.documents.some((d) => d.id === i.doc_id && d.status === "processed" && !d.ai_private),
  )!;
  return item.doc_id!;
}

describe.each<[ClientKind, boolean]>([
  ["computer", true],
  ["phone", false],
])("on the %s", (client, offered) => {
  it(offered ? "Timeline offers the calendar file" : "Timeline offers no calendar file", async () => {
    const { srv } = useMockApi({ client });
    await renderAppAt("/timeline", "Timeline");
    expect(screen.queryAllByRole("button", { name: EXPORT })).toHaveLength(offered ? 1 : 0);
    expect(srv.refused).toEqual([]);
  });

  it(offered ? "Today shows the calendar card" : "Today shows no calendar card", async () => {
    const { srv } = useMockApi({ client });
    expect(srv.db.state.suggestions.some((s) => s.rule_id === "calendar_outdated" && s.status === "new")).toBe(true);
    await renderAppAt("/");
    expect(screen.queryAllByRole("region", { name: /calendar/i })).toHaveLength(offered ? 1 : 0);
    expect(srv.refused).toEqual([]);
  });

  it(offered ? "a letter's dated to-do can be added to a calendar" : "a letter's dated to-do offers no calendar file", async () => {
    const { srv } = useMockApi({ client });
    await renderAppAt(`/documents/${datedLetter(srv)}`);
    expect(screen.queryAllByRole("link", { name: ADD }).length > 0).toBe(offered);
    // the to-do's own menu
    const user = userEvent.setup();
    const menus = screen.queryAllByRole("button", { name: /^More actions for / });
    expect(menus.length).toBeGreaterThan(0);
    await user.click(menus[0]!);
    const menu = await screen.findByRole("menu");
    expect(within(menu).queryAllByRole("menuitem", { name: ADD }).length > 0).toBe(offered);
    expect(srv.refused).toEqual([]);
    cleanup();
  });
});
