import { ChartNoAxesGantt, Inbox, MessagesSquare, PenLine, Settings, Signature, Sun, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Short label for the mobile tab bar. */
  short?: string;
  /** Match only the exact path (for "/"). */
  end?: boolean;
  /** More path prefixes this item is the home of (a letter at `/documents/…` belongs to Inbox). */
  match?: string[];
  /** Badge source. */
  badge?: "please-check";
}

/** Primary navigation (SPEC §14): Today · Inbox · Timeline · Contracts · Letters · Ask. */
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Today", icon: Sun, end: true },
  { to: "/inbox", label: "Inbox", icon: Inbox, badge: "please-check", match: ["/documents"] },
  { to: "/timeline", label: "Timeline", icon: ChartNoAxesGantt },
  { to: "/contracts", label: "Contracts", icon: Signature },
  { to: "/letters", label: "Letters", icon: PenLine },
  { to: "/ask", label: "Ask", icon: MessagesSquare },
];

export const SETTINGS_ITEM: NavItem = { to: "/settings", label: "Settings", icon: Settings };

const within = (pathname: string, prefix: string) => pathname === prefix || pathname.startsWith(`${prefix}/`);

/** Whether `item` is the current section: its own path (and below, unless `end`) or one of its `match` prefixes. */
export function isNavItemActive(item: NavItem, pathname: string): boolean {
  if (item.end ? pathname === item.to : within(pathname, item.to)) return true;
  return (item.match ?? []).some((prefix) => within(pathname, prefix));
}

/** The section page at exactly this path (Today, Inbox … Settings), if it is one. */
export function sectionAt(pathname: string): NavItem | undefined {
  return [...NAV_ITEMS, SETTINGS_ITEM].find((item) => item.to === pathname);
}
