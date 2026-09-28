import { Link, useLocation } from "react-router";
import { PanelLeftClose, PanelLeftOpen, UserRound } from "lucide-react";
import { cn } from "@/lib/utils";
import { useIsDesktop, useLocalStorage } from "@/lib/hooks";
import { useDocuments, useProfile } from "@/api/hooks";
import { Tooltip } from "@/components/ui/Tooltip";
import { CountBadge } from "@/components/ui/Badge";
import { Avatar } from "@/components/ui/Avatar";
import { IconButton } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Logo } from "./Logo";
import { NAV_ITEMS, SETTINGS_ITEM, isNavItemActive, type NavItem } from "./nav";
import { DemoBadge } from "./DemoBadge";
import { ThemeToggle } from "./ThemeToggle";
import { TOUR_DOCK_ID } from "@/features/tour/steps";

/** Count of letters that need the user ("Please check"). */
export function usePleaseCheckCount(): number {
  const { data } = useDocuments({ status: "needs_review" });
  return data?.length ?? 0;
}

/** What the Inbox asks of the person: letters to check, and letters waiting from the watched folder. */
export interface InboxCounts {
  check: number;
  waiting: number;
}

/** The Inbox's counts: "Please check" letters and letters from the watched folder that wait for "Read these". */
export function useInboxCounts(): InboxCounts {
  const check = usePleaseCheckCount();
  const { data } = useDocuments({ status: "held" });
  return { check, waiting: data?.length ?? 0 };
}

const toCheck = (n: number) => `${n} ${n === 1 ? "letter" : "letters"} to check`;

/** "1 letter to check, 3 waiting for you" (`short`: "1 to check, 3 waiting for you"). */
export function inboxCountText({ check, waiting }: InboxCounts, short = false): string {
  return [check ? (short ? `${check} to check` : toCheck(check)) : "", waiting ? `${waiting} waiting for you` : ""].filter(Boolean).join(", ");
}

/** Hover text of the Inbox's count: what each number is. */
export function inboxCountTitle({ check, waiting }: InboxCounts): string {
  return [
    check ? `${check} ${check === 1 ? "letter needs" : "letters need"} a check from you (“Please check”)` : "",
    waiting ? `${waiting} ${waiting === 1 ? "letter" : "letters"} from your folder ${waiting === 1 ? "waits" : "wait"} for your OK` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** One bubble on an icon's corner: the letters that need the person, warn-coloured while any is to check. */
export function InboxBubble({ counts, className }: { counts: InboxCounts; className?: string }) {
  return <CountBadge count={counts.check + counts.waiting} tone={counts.check ? "warn" : "accent"} variant="solid" size="compact" className={className} />;
}

function NavEntry({ item, rail, counts }: { item: NavItem; rail: boolean; counts?: InboxCounts }) {
  const { pathname } = useLocation();
  const active = isNavItemActive(item, pathname);
  const Icon = item.icon;
  const badge = counts ? counts.check + counts.waiting : 0;

  if (rail) {
    // icon over a short label (like the phone tab bar): the rail is readable without hovering
    return (
      <Link
        to={item.to}
        aria-current={active ? "page" : undefined}
        aria-label={counts && badge ? `${item.label}, ${inboxCountText(counts)}` : undefined}
        title={counts && badge ? inboxCountTitle(counts) : undefined}
        className={cn(
          "group flex w-full flex-col items-center gap-1 rounded-lg py-1.5 text-xs font-medium outline-none transition-colors",
          // inset: the rail's labels use its whole width, and the ring stays inside its scroll area
          "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent",
          active ? "text-ink" : "text-muted hover:text-ink",
        )}
      >
        <span
          className={cn(
            "relative grid h-7 w-12 place-items-center rounded-full transition-colors",
            active ? "bg-accent-soft text-accent" : "group-hover:bg-surface-3/70",
          )}
        >
          <Icon className="size-[18px]" aria-hidden />
          {counts && badge ? <InboxBubble counts={counts} className="absolute -right-1 -top-1 ring-2 ring-surface-2 dark:ring-surface" /> : null}
        </span>
        <span className="max-w-full truncate leading-4">{item.short ?? item.label}</span>
      </Link>
    );
  }

  return (
    <Link
      to={item.to}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex h-9 items-center gap-3 rounded-lg px-2.5 text-[14px] font-medium outline-none transition-colors",
        active ? "bg-surface text-ink shadow-[var(--shadow-card)] ring-1 ring-line" : "text-muted hover:bg-surface-3/60 hover:text-ink",
        "focus-visible:ring-2 focus-visible:ring-accent",
      )}
    >
      <Icon className={cn("size-[18px] shrink-0 transition-colors", active ? "text-accent" : "text-muted group-hover:text-ink")} aria-hidden />
      <span className="flex-1 truncate">{item.label}</span>
      {counts && badge ? (
        // the counts say what they are on hover too, not only to screen readers
        <span title={inboxCountTitle(counts)} className="inline-flex gap-1">
          <CountBadge count={counts.check} tone="warn" label={toCheck(counts.check)} />
          <CountBadge count={counts.waiting} tone="accent" label={`${counts.waiting} waiting for you`} />
        </span>
      ) : null}
    </Link>
  );
}

/** "Sam Rivera · Your data stays local" → Settings › Profile; a placeholder row while it loads. */
function ProfileLink() {
  const { data: profile, isPending } = useProfile();
  if (isPending) {
    return (
      <div className="flex min-w-0 flex-1 items-center gap-2 py-1" aria-hidden data-testid="profile-loading">
        <Skeleton className="size-6 rounded-full" />
        <span className="flex-1 space-y-1.5">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-3 w-28" />
        </span>
      </div>
    );
  }
  const name = profile?.name?.trim();
  return (
    <Link
      to="/settings?section=profile"
      // starts with the visible name (WCAG 2.5.3: "click Sam Rivera" works for voice control)
      aria-label={name ? `${name} — your profile` : "Your profile"}
      className="flex min-w-0 flex-1 items-center gap-2 rounded-lg py-1 outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      {name ? (
        <Avatar name={name} tone="accent" size="sm" className="rounded-full" />
      ) : (
        <span className="grid size-6 shrink-0 place-items-center rounded-full bg-surface-3 text-muted" aria-hidden>
          <UserRound className="size-3.5" />
        </span>
      )}
      <span className="min-w-0">
        <span className="block truncate text-[13px] font-medium leading-4 text-ink">{name || "Your profile"}</span>
        <span className="block truncate text-xs leading-4 text-muted">Your data stays local</span>
      </span>
    </Link>
  );
}

/**
 * Left sidebar: wordmark, primary navigation (with the letters to check and those waiting from the
 * watched folder counted on Inbox), and the
 * footer (demo badge, Settings, profile, theme). An icon rail with short labels on tablets, or on
 * laptops when the person collapses it (remembered in localStorage). Hidden on phones (tab bar
 * instead).
 */
export function Sidebar() {
  const isDesktop = useIsDesktop();
  const [collapsed, setCollapsed] = useLocalStorage("ordnung.sidebar.collapsed", false);
  const rail = !isDesktop || collapsed;
  const inbox = useInboxCounts();
  const toggleLabel = collapsed ? "Expand sidebar" : "Collapse sidebar";

  return (
    <aside
      aria-label="Sidebar"
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-line bg-surface-2/60 md:flex dark:bg-surface/40",
        "transition-[width] duration-200 ease-out motion-reduce:transition-none",
        rail ? "w-20 items-center px-2" : "w-[244px] px-3",
      )}
    >
      {/* the collapse / expand toggle is one button in one place (under the logo on the rail): it keeps focus */}
      <div className={cn("flex shrink-0", rail ? "flex-col items-center gap-1" : "h-14 items-center justify-between pl-1.5")}>
        <span className={cn("flex items-center", rail && "h-14")}>
          <Link to="/" aria-label="Ordnung — Today" className="rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-accent">
            <Logo compact={rail} />
          </Link>
        </span>
        {isDesktop ? (
          <Tooltip content={toggleLabel} side={rail ? "right" : "bottom"}>
            <IconButton
              icon={collapsed ? PanelLeftOpen : PanelLeftClose}
              label={toggleLabel}
              title=""
              size="sm"
              onClick={() => setCollapsed(!collapsed)}
              className="text-muted"
            />
          </Tooltip>
        ) : null}
      </div>

      {/* on a short window the sections scroll inside the sidebar (the footer — Settings, the theme — stays
          on screen); py-1 (and px-1 when expanded): room for the focus ring inside the scroll area */}
      <nav
        aria-label="Primary"
        className={cn("mt-2 flex min-h-0 shrink flex-col overflow-y-auto overscroll-contain py-1 scrollbar-thin", rail ? "w-full gap-1" : "-mx-1 gap-0.5 px-1")}
      >
        {NAV_ITEMS.map((item) => (
          <NavEntry key={item.to} item={item} rail={rail} counts={item.badge === "please-check" ? inbox : undefined} />
        ))}
      </nav>

      {/* the demo tour docks in this free space, clear of the page, when the whole card fits (see
          DemoTour); `safe` end: if it ever overflows, its top stays reachable. -mx-1/px-1: room for
          the pill's focus ring inside the scroll area. */}
      {rail ? (
        <div className="flex-1" />
      ) : (
        <div id={TOUR_DOCK_ID} className="-mx-1 flex min-h-0 flex-1 flex-col justify-end-safe overflow-y-auto px-1 py-3 scrollbar-thin" />
      )}

      <div className={cn("flex shrink-0 flex-col gap-2 pb-4 pt-2", rail && "w-full items-center")}>
        <DemoBadge compact={rail} className={rail ? undefined : "self-start"} />
        <NavEntry item={SETTINGS_ITEM} rail={rail} />
        <div className={cn("mt-1 flex items-center gap-2 border-t border-line pt-3", rail ? "w-full flex-col" : "pl-1.5")}>
          {!rail ? <ProfileLink /> : null}
          <ThemeToggle compact className={rail ? undefined : "ml-auto"} />
        </div>
      </div>
    </aside>
  );
}
