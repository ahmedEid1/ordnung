/**
 * `/join` (design §19.2): "I already use Ordnung on another computer" — the setup card in its joining form (a
 * folder that holds a sync, the passphrase once), then what is arriving; once Ordnung is in use here, the app opens
 * with a full page load. The wizard's first step links here.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { __clearToasts } from "@/components/ui/Toast";
import { pageLoad } from "@/features/phone/platform";
import { SYNC_EXISTING_FOLDER, WRONG_PASSPHRASE_MESSAGE } from "@/mocks/data/sync";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import JoinPage, { joinDone } from "./JoinPage";

let assign: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  vi.stubGlobal("scrollTo", () => {});
  assign = vi.spyOn(pageLoad, "assign").mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  act(() => __clearToasts());
});

const WAIT = { timeout: 5000 };

describe("/join", () => {
  it("brings Ordnung over from the other computer, then opens the app", async () => {
    const { srv } = useMockApi();
    srv.db.state.documents = []; // a computer that has nothing yet
    const user = userEvent.setup();
    renderWithProviders(<JoinPage />, { route: "/join" });
    expect(await screen.findByRole("heading", { level: 1, name: "I already use Ordnung on another computer" }, WAIT)).toBeInTheDocument();
    const card = await screen.findByRole("region", { name: "Bring Ordnung over from your other computer" }, WAIT);
    expect(within(card).queryByText("In use on one computer at a time — the others stand by")).toBeNull();
    await user.type(within(card).getByLabelText("Sync folder"), SYNC_EXISTING_FOLDER);
    await user.click(within(card).getByRole("button", { name: "Next" }));
    const passphrase = await within(card).findByLabelText("The sync passphrase", {}, WAIT);
    await waitFor(() => expect(passphrase).toHaveFocus());
    await user.type(passphrase, "wrong passphrase here");
    await user.click(within(card).getByRole("button", { name: "Bring it here" }));
    await waitFor(() => expect(passphrase).toHaveAccessibleDescription(WRONG_PASSPHRASE_MESSAGE));
    await user.clear(passphrase);
    await user.type(passphrase, "kirun bodaf sumel tavok perin");
    await user.click(within(card).getByRole("button", { name: "Bring it here" }));
    expect(await screen.findByText(/Ordnung is in use on this computer — opening it/, {}, WAIT)).toBeInTheDocument();
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
    expect(srv.sync.connected).toBe(true);
    expect(srv.sync.baseFrom).toBe("sam-desktop");
  });

  it("expects a folder that holds a sync", async () => {
    useMockApi();
    const user = userEvent.setup();
    renderWithProviders(<JoinPage />, { route: "/join" });
    const card = await screen.findByRole("region", { name: "Bring Ordnung over from your other computer" }, WAIT);
    const folder = within(card).getByLabelText("Sync folder");
    await user.type(folder, "/home/sam/Nextcloud/Elsewhere");
    await user.click(within(card).getByRole("button", { name: "Next" }));
    await waitFor(() => expect(folder).toHaveAccessibleDescription(/No sync from your other computer is in this folder yet/));
    expect(within(card).queryByLabelText("The sync passphrase")).toBeNull();
  });

  it("shows what is still arriving after joining, until it is in use here", async () => {
    const { srv } = useMockApi();
    srv.sync.setUp().otherTakesOver().arriving(40, 340);
    srv.sync.takeOverWaiting = true;
    renderWithProviders(<JoinPage />, { route: "/join" });
    expect(await screen.findByRole("heading", { name: "Bringing Ordnung over from sam-desktop" }, WAIT)).toBeInTheDocument();
    expect(screen.getByText(/^Waiting for 300 of 340 files from your sync tool/)).toBeInTheDocument();
    expect(screen.getByText(/stops waiting after 30 minutes/)).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it("is done once joined and in use here with nothing left to bring over", () => {
    const base = { connected: true, mode: "in_use", activity: "idle", take_over_waiting: false } as const;
    expect(joinDone(base as never)).toBe(true);
    expect(joinDone({ ...base, activity: "bringing_over" } as never)).toBe(false);
    expect(joinDone({ ...base, mode: "standing_by" } as never)).toBe(false);
    expect(joinDone({ ...base, take_over_waiting: true } as never)).toBe(false);
    expect(joinDone(undefined)).toBe(false);
  });
});
