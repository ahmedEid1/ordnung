/**
 * The standing-by screen (design §19.3): another computer is in use, so the app shows this instead of its pages —
 * up to date, still arriving (wait for it, or use the copy this computer has), waiting (with when it stops), a
 * problem (the passphrase field), a choice. "Use Ordnung here" takes over and every cached page loads again. The
 * screen never covers Settings → Your computers or the privacy log, and there is no `checking` mode any more: a
 * computer starting up shows its pages.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { qk } from "@/api/hooks";
import { __clearToasts } from "@/components/ui/Toast";
import { useMockApi } from "@/test/mockFetch";
import { renderAppAt, stubShellGlobals } from "@/test/app";
import { TAKE_OVER_WAIT_MINUTES } from "@/features/settings/sync";
import { standbyKeepsPage } from "./StandbyScreen";

beforeEach(() => stubShellGlobals());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  act(() => __clearToasts());
});

const WAIT = { timeout: 8000 };
const HEADING = "Ordnung is in use on sam-desktop";

describe("the standing-by screen", () => {
  it("shows instead of the app's pages: whose Ordnung is in use, that everything arrived, and one button", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver();
    await renderAppAt("/", HEADING);
    expect(screen.getByText(/^Everything from sam-desktop has arrived here \(the last change arrived 4 min ago\)\.$/)).toBeInTheDocument();
    expect(screen.getByText("sam-desktop's Ordnung is still open. If you use it here, sam-desktop switches to standing by — nothing is lost.")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Use Ordnung here" });
    await waitFor(() => expect(button).toHaveFocus());
    // no "Are you sure?", no pages behind it
    expect(screen.queryByRole("navigation", { name: /main/i })).toBeNull();
    expect(screen.queryByRole("link", { name: "Inbox" })).toBeNull();
    const links = within(screen.getByRole("navigation", { name: "While standing by" })).getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/settings?section=computers", "/settings?section=privacy"]);
  });

  it("says no computer is using Ordnung when the one in use left sync — never that this one is", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherLeft();
    await renderAppAt("/", "No computer is using Ordnung now");
    expect(screen.getByText("sam-desktop stopped syncing; everything it saved last has arrived here.")).toBeInTheDocument();
    expect(screen.getByText("Use Ordnung here to go on with it on this computer — nothing is lost.")).toBeInTheDocument();
    expect(screen.queryByText(/is in use on/)).toBeNull();
    expect(screen.getByRole("button", { name: "Use Ordnung here" })).toBeInTheDocument();
  });

  it("says when the other computer was closed", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver("sam-desktop", { closed: true });
    await renderAppAt("/", HEADING);
    expect(screen.getByText("sam-desktop was closed. Use Ordnung here: nothing is lost.")).toBeInTheDocument();
  });

  it("takes over: in use here, and every page loads again (the data came from the other computer)", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver();
    const user = userEvent.setup();
    const { client } = await renderAppAt("/", HEADING);
    client.setQueryData(["documents", "from-before"], [{ id: "doc_old" }]);
    await user.click(screen.getByRole("button", { name: "Use Ordnung here" }));
    expect(await screen.findByText("Ordnung is in use here now", {}, WAIT)).toBeInTheDocument();
    expect(client.getQueryData(["documents", "from-before"])).toBeUndefined();
    expect(client.getQueryData(qk.health)).toBeDefined();
    await waitFor(() => expect(screen.queryByRole("heading", { level: 1, name: HEADING })).toBeNull(), WAIT);
    expect(srv.sync.mode).toBe("in_use");
    expect(srv.db.state.activity[0]?.kind).toBe("sync.taken_over");
  });

  it("while the latest changes are still arriving: waits for them, says when it stops waiting, and can stop", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver().arriving(5, 9);
    const user = userEvent.setup();
    await renderAppAt("/", HEADING);
    expect(screen.getByText("sam-desktop's latest changes are still on their way: 5 of 9 files are here.")).toBeInTheDocument();
    expect(screen.getAllByText(/^Waiting for 4 of 9 files from your sync tool \(\d+ KB\)\.$/).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Use it here as soon as they've arrived" }));
    expect(await screen.findByText("Waiting for sam-desktop's latest changes", {}, WAIT)).toBeInTheDocument();
    // a waiting take-over ends by itself (finding 23)
    expect(screen.getByText(new RegExp(`It stops waiting after ${TAKE_OVER_WAIT_MINUTES} minutes, or if sam-desktop saves a new change meanwhile`))).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("button", { name: "Use it here as soon as they've arrived" }, WAIT)).toBeInTheDocument();
    expect(srv.sync.takeOverWaiting).toBe(false);
  });

  it("a waiting take-over finishes by itself once everything has arrived", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver().arriving(5, 9);
    const user = userEvent.setup();
    const { client } = await renderAppAt("/", HEADING);
    await user.click(screen.getByRole("button", { name: "Use it here as soon as they've arrived" }));
    await screen.findByText("Waiting for sam-desktop's latest changes", {}, WAIT);
    srv.sync.arrived();
    await act(() => client.invalidateQueries({ queryKey: qk.sync })); // what `sync.updated` (or the poll) does
    await waitFor(() => expect(screen.queryByRole("heading", { level: 1, name: HEADING })).toBeNull(), WAIT);
    expect(srv.sync.mode).toBe("in_use");
  });

  it("can use the copy this computer has now, saying what happens to the changes still on their way", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver().arriving(5, 9);
    const user = userEvent.setup();
    await renderAppAt("/", HEADING);
    expect(screen.getByText(/If you change something here before sam-desktop's changes arrive, Ordnung will ask which computer's to keep/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Use the copy this computer has now \(from .+\)$/ }));
    await waitFor(() => expect(screen.queryByRole("heading", { level: 1, name: HEADING })).toBeNull(), WAIT);
    expect(srv.sync.mode).toBe("in_use");
  });

  it("says when files are online only on this computer, or nothing arrives any more (finding 6)", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver().arriving(5, 9, { onlyOnline: 3 });
    await renderAppAt("/", HEADING);
    expect(screen.getByText("Some files are online only here")).toBeInTheDocument();
    expect(screen.getByText(/3 files are online only on this computer, so they don't arrive: make the sync folder available offline/)).toBeInTheDocument();
  });

  it("a problem shows with what to do — the passphrase typed again", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver().setProblem("passphrase_needed");
    const user = userEvent.setup();
    await renderAppAt("/", HEADING);
    expect(screen.getByText("Type the sync passphrase again")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Sync passphrase"), "kirun bodaf sumel tavok perin");
    await user.click(screen.getByRole("button", { name: "Save passphrase" }));
    expect(await screen.findByText("Saved in this computer's password store", {}, WAIT)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Type the sync passphrase again")).toBeNull());
  });

  it("a choice to make shows here too", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver().bothChanged();
    const user = userEvent.setup();
    await renderAppAt("/", HEADING);
    expect(screen.getByText("Your two computers both have changes.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use Ordnung here" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Choose…" }));
    expect(await screen.findByRole("dialog", { name: "Which Ordnung do you want to keep?" }, WAIT)).toBeInTheDocument();
  });

  it("refuses a take-over in place, focused (the server's words)", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver().setProblem("pull_unfinished");
    const user = userEvent.setup();
    await renderAppAt("/", HEADING);
    await user.click(screen.getByRole("button", { name: "Use Ordnung here" }));
    const refusal = await screen.findByText("A take-over must finish first.", {}, WAIT);
    await waitFor(() => expect(refusal.closest("[tabindex]")).toHaveFocus());
    expect(screen.getByText("Ordnung isn't in use here yet")).toBeInTheDocument();
  });

  it("never covers Settings → Your computers or the privacy log: they show under the banner", async () => {
    expect(standbyKeepsPage("/settings", "?section=computers")).toBe(true);
    expect(standbyKeepsPage("/settings", "?section=privacy&device=x")).toBe(true);
    expect(standbyKeepsPage("/settings", "?section=data")).toBe(false);
    expect(standbyKeepsPage("/", "")).toBe(false);
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver();
    await renderAppAt("/settings?section=computers", "Settings");
    expect(screen.queryByRole("heading", { level: 1, name: HEADING })).toBeNull();
    expect(screen.getByText("Ordnung is in use on sam-desktop.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Use Ordnung here" }).length).toBeGreaterThan(0);
  });

  it("there is no `checking` mode: a computer starting up shows its pages, and writes aren't refused", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp();
    srv.sync.mode = "starting";
    await renderAppAt("/inbox", "Inbox");
    expect(screen.queryByRole("heading", { level: 1, name: /Ordnung is in use on/ })).toBeNull();
  });
});
