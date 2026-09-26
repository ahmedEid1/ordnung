import { ChartNoAxesGantt, Inbox, MessagesSquare, PenLine, Settings, Signature, Sun, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Short label for the mobile tab bar. */
  short?: string;
  /** Match only the exact path (for "/"). */
  end?: boolean;
  /** Badge source. */
  badge?: "please-check";
}

/** Primary navigation (SPEC §14): Today · Inbox · Timeline · Contracts · Letters · Ask. */
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Today", icon: Sun, end: true },
  { to: "/inbox", label: "Inbox", icon: Inbox, badge: "please-check" },
  { to: "/timeline", label: "Timeline", icon: ChartNoAxesGantt },
  { to: "/contracts", label: "Contracts", icon: Signature },
  { to: "/letters", label: "Letters", icon: PenLine },
  { to: "/ask", label: "Ask", icon: MessagesSquare },
];

export const SETTINGS_ITEM: NavItem = { to: "/settings", label: "Settings", icon: Settings };
