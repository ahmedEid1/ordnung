/**
 * Background problems (the watched folder, calendar sync, the morning notification) reach the person
 * outside Settings: a "Needs your attention" card on Today and a dot on Settings, each linking to its
 * section — and nothing while all is well.
 */
import { describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import { api } from "@/api/endpoints";
import type { CalendarSyncStatus, DesktopReminders, FolderStatus } from "@/api/types";
import { AttentionCard } from "@/features/today/AttentionCard";
import { SettingsNav } from "./SettingsNav";
import { Sidebar } from "@/components/shell/Sidebar";
import { renderWithProviders } from "@/test/render";
import { useMockApi } from "@/test/mockFetch";
import { backgroundProblems } from "./attention";

const MISSING = "Ordnung can't find this folder. Check the path, or create the folder — Ordnung looks again every 30 seconds.";

describe("backgroundProblems", () => {
  it("names what stopped and where to fix it", () => {
    expect(backgroundProblems({})).toEqual([]);
    const problems = backgroundProblems({
      folder: { folder: "/home/sam/Scans", state: "problem", problem: MISSING },
      calendar: { connected: true, paused: true, password_saved: true, last_sync: null },
      desktop: { last_failure: "notify-send failed (exit code 1).", last_failure_on: "2026-09-28", last_shown_on: null },
      settings: { desktop_notifications: "discreet" },
    });
    expect(problems.map((p) => [p.section, p.title])).toEqual([
      ["folder", "Not watching your folder"],
      ["calendar", "Calendar sync is paused"],
      ["reminders", "The morning notification didn't show"],
    ]);
    // switched off, a failure of long ago is no news; a folder not chosen, no calendar: nothing
    expect(
      backgroundProblems({
        folder: { folder: null, state: "off", problem: null },
        calendar: { connected: false, paused: false, password_saved: false, last_sync: null },
        desktop: { last_failure: "failed", last_failure_on: "2026-09-20", last_shown_on: null },
        settings: { desktop_notifications: "off" },
      }),
    ).toEqual([]);
  });
});

describe("Needs your attention", () => {
  it("shows on Today and as a dot on Settings, linking to the section", async () => {
    useMockApi();
    const folder = await api.folder();
    vi.spyOn(api, "folder").mockResolvedValue({ ...folder, folder: "/home/sam/Scans", state: "problem", problem: MISSING } as FolderStatus);
    const calendar = await api.calendarSync();
    vi.spyOn(api, "calendarSync").mockResolvedValue({ ...calendar, connected: true, paused: true, password_saved: true } as CalendarSyncStatus);
    renderWithProviders(
      <>
        <AttentionCard />
        <Sidebar />
      </>,
    );
    const card = await screen.findByRole("region", { name: "Needs your attention" });
    expect(within(card).getByText(/New scans don't arrive: Ordnung can't find this folder/)).toBeInTheDocument();
    const links = within(card).getAllByRole("link", { name: "Open Settings" });
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/settings?section=folder", "/settings?section=calendar"]);
    // the dot leads to the section with the problem, not to Profile
    expect(await screen.findByRole("link", { name: "Settings, needs your attention" })).toHaveAttribute("href", "/settings?section=folder");
  });

  it("marks the sections with a problem in Settings' own list", async () => {
    useMockApi();
    const folder = await api.folder();
    vi.spyOn(api, "folder").mockResolvedValue({ ...folder, folder: "/home/sam/Scans", state: "problem", problem: MISSING } as FolderStatus);
    renderWithProviders(<SettingsNav current="profile" hrefFor={(id) => `/settings?section=${id}`} onNavigate={() => {}} />);
    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    const marked = await within(nav).findByRole("link", { name: "Watched folder, needs your attention" });
    expect(within(marked).getByTestId("attention-dot")).toBeInTheDocument();
    const profile = within(nav).getByRole("link", { name: "Profile & address" });
    expect(profile).toHaveAttribute("aria-current", "page");
    expect(within(profile).queryByTestId("attention-dot")).toBeNull();
  });

  it("stays away while all is well", async () => {
    useMockApi();
    const desktop = await api.desktopReminders();
    vi.spyOn(api, "desktopReminders").mockResolvedValue({ ...desktop, last_failure: null } as DesktopReminders);
    renderWithProviders(
      <>
        <AttentionCard />
        <Sidebar />
      </>,
    );
    expect(await screen.findByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
    expect(screen.queryByRole("region", { name: "Needs your attention" })).toBeNull();
    expect(screen.queryByTestId("attention-dot")).toBeNull();
  });
});
