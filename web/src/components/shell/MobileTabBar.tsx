import { Link, useLocation } from "react-router";
import { cn } from "@/lib/utils";
import { TAB_BAR_ITEMS, isNavItemActive } from "./nav";
import { InboxBubble, inboxCountText, useInboxCounts } from "./Sidebar";

/**
 * Bottom tab bar on phones (< 768 px), safe-area aware. Labels are 12 px (11 px below 360 px,
 * where six columns get narrow); the focus ring goes round the icon pill, inside the bar.
 */
export function MobileTabBar() {
  const inbox = useInboxCounts();
  const { pathname } = useLocation();
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md backdrop-saturate-150 md:hidden"
    >
      <ul className="mx-auto grid h-16 max-w-lg grid-cols-6">
        {TAB_BAR_ITEMS.map((item) => {
          const Icon = item.icon;
          const counts = item.badge === "please-check" ? inbox : null;
          const badge = counts ? counts.check + counts.waiting : 0;
          const active = isNavItemActive(item, pathname);
          return (
            <li key={item.to} className="min-w-0">
              <Link
                to={item.to}
                aria-current={active ? "page" : undefined}
                aria-label={counts && badge ? `${item.label}, ${inboxCountText(counts, true)}` : item.label}
                className={cn(
                  "group relative flex h-full flex-col items-center justify-center gap-1 text-xs font-medium outline-none transition-colors max-[360px]:text-2xs",
                  active ? "text-accent" : "text-muted hover:text-ink",
                )}
              >
                <span
                  className={cn(
                    "relative grid h-7 w-12 place-items-center rounded-full transition-colors group-focus-visible:ring-2 group-focus-visible:ring-accent",
                    active && "bg-accent-soft",
                  )}
                >
                  <Icon className="size-[19px]" aria-hidden />
                  {counts && badge ? (
                    <span aria-hidden className="absolute -right-1 -top-1 inline-flex">
                      <InboxBubble counts={counts} className="ring-2 ring-surface" />
                    </span>
                  ) : null}
                </span>
                <span aria-hidden className="max-w-full truncate leading-4">
                  {item.short ?? item.label}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
