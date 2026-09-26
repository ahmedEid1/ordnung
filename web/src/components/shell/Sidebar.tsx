import { NavLink } from "react-router";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { useIsDesktop, useLocalStorage } from "@/lib/hooks";
import { useDocuments, useProfile } from "@/api/hooks";
import { Tooltip } from "@/components/ui/Tooltip";
import { CountBadge } from "@/components/ui/Badge";
import { Avatar } from "@/components/ui/Avatar";
import { IconButton } from "@/components/ui/Button";
import { Logo } from "./Logo";
import { NAV_ITEMS, SETTINGS_ITEM, type NavItem } from "./nav";
import { DemoBadge } from "./DemoBadge";
import { ThemeToggle } from "./ThemeToggle";
import { TOUR_DOCK_ID } from "@/features/tour/steps";

/** Count of letters that need the user ("Please check"). */
export function usePleaseCheckCount(): number {
  const { data } = useDocuments({ status: "needs_review" });
  return data?.length ?? 0;
}

function NavEntry({ item, rail, badge }: { item: NavItem; rail: boolean; badge?: number }) {
  const Icon = item.icon;
  const link = (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cn(
          "group relative flex h-9 items-center gap-3 rounded-lg text-[14px] font-medium outline-none transition-colors",
          rail ? "w-10 justify-center" : "px-2.5",
          isActive
            ? "bg-surface text-ink shadow-[var(--shadow-card)] ring-1 ring-line"
            : "text-muted hover:bg-surface-3/60 hover:text-ink",
          "focus-visible:ring-2 focus-visible:ring-accent",
        )
      }
      aria-label={rail ? (badge ? `${item.label}, ${badge} to check` : item.label) : undefined}
    >
      {({ isActive }) => (
        <>
          <Icon className={cn("size-[18px] shrink-0 transition-colors", isActive ? "text-accent" : "text-muted group-hover:text-ink")} aria-hidden />
          {!rail ? <span className="flex-1 truncate">{item.label}</span> : null}
          {badge ? (
            rail ? (
              <span className="absolute right-1 top-1 size-2 rounded-full bg-warn ring-2 ring-surface-2" aria-hidden />
            ) : (
              // the count says what it is on hover too, not only to screen readers
              <span title={`${badge} ${badge === 1 ? "letter needs" : "letters need"} a check from you (“Please check”)`} className="inline-flex">
                <CountBadge count={badge} tone="warn" label={`${badge} ${badge === 1 ? "letter" : "letters"} to check`} />
              </span>
            )
          ) : null}
        </>
      )}
    </NavLink>
  );
  return rail ? (
    <Tooltip content={badge ? `${item.label} · ${badge} to check` : item.label} side="right">
      {link}
    </Tooltip>
  ) : (
    link
  );
}

/**
 * Left sidebar: wordmark, primary navigation (with the "Please check" count on Inbox), and the
 * footer (demo badge, Settings, profile, theme). Collapses to an icon rail on medium screens or
 * when the user collapses it (remembered in localStorage). Hidden on phones (tab bar instead).
 */
export function Sidebar() {
  const isDesktop = useIsDesktop();
  const [collapsed, setCollapsed] = useLocalStorage("ordnung.sidebar.collapsed", false);
  const rail = !isDesktop || collapsed;
  const pleaseCheck = usePleaseCheckCount();
  const { data: profile } = useProfile();

  return (
    <aside
      aria-label="Main"
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-line bg-surface-2/60 md:flex dark:bg-surface/40",
        "transition-[width] duration-200 ease-out motion-reduce:transition-none",
        rail ? "w-[68px] items-center px-3" : "w-[244px] px-3",
      )}
    >
      <div className={cn("flex h-14 shrink-0 items-center", rail ? "justify-center" : "justify-between pl-1.5")}>
        <NavLink to="/" aria-label="Ordnung — Today" className="rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <Logo compact={rail} />
        </NavLink>
        {isDesktop && !rail ? (
          <IconButton icon={PanelLeftClose} label="Collapse sidebar" size="sm" onClick={() => setCollapsed(true)} className="text-muted" />
        ) : null}
      </div>

      <nav aria-label="Primary" className="mt-3 flex flex-col gap-0.5">
        {NAV_ITEMS.map((item) => (
          <NavEntry key={item.to} item={item} rail={rail} badge={item.badge === "please-check" ? pleaseCheck : undefined} />
        ))}
      </nav>

      {/* the demo tour docks in this free space, clear of the page (see DemoTour) */}
      {rail ? <div className="flex-1" /> : <div id={TOUR_DOCK_ID} className="flex min-h-0 flex-1 flex-col justify-end overflow-y-auto py-4 scrollbar-thin" />}

      <div className={cn("flex flex-col gap-2 pb-4", rail && "items-center")}>
        {isDesktop && rail ? (
          <Tooltip content="Expand sidebar" side="right">
            <IconButton icon={PanelLeftOpen} label="Expand sidebar" title="" onClick={() => setCollapsed(false)} />
          </Tooltip>
        ) : null}
        <DemoBadge compact={rail} className={rail ? undefined : "self-start"} />
        <NavEntry item={SETTINGS_ITEM} rail={rail} />
        <div className={cn("mt-1 flex items-center gap-2 border-t border-line pt-3", rail ? "flex-col" : "pl-1.5")}>
          {!rail && profile?.name ? (
            <NavLink to="/settings" className="flex min-w-0 flex-1 items-center gap-2 rounded-lg py-1 outline-none focus-visible:ring-2 focus-visible:ring-accent">
              <Avatar name={profile.name} tone="accent" size="sm" className="rounded-full" />
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-medium leading-4 text-ink">{profile.name}</span>
                <span className="block truncate text-[11.5px] leading-4 text-muted">Your data stays local</span>
              </span>
            </NavLink>
          ) : null}
          <ThemeToggle compact />
        </div>
      </div>
    </aside>
  );
}
