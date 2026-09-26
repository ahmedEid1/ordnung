import { NavLink } from "react-router";
import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "./nav";
import { usePleaseCheckCount } from "./Sidebar";

/** Bottom tab bar on phones (< 768 px), safe-area aware. */
export function MobileTabBar() {
  const pleaseCheck = usePleaseCheckCount();
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
    >
      <ul className="mx-auto grid h-16 max-w-lg grid-cols-6">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const badge = item.badge === "please-check" ? pleaseCheck : 0;
          return (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.end}
                aria-label={badge ? `${item.label}, ${badge} to check` : item.label}
                className={({ isActive }) =>
                  cn(
                    "relative flex h-full flex-col items-center justify-center gap-1 text-[10.5px] font-medium transition-colors",
                    isActive ? "text-accent" : "text-muted hover:text-ink",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span className={cn("relative grid h-7 w-12 place-items-center rounded-full transition-colors", isActive && "bg-accent-soft")}>
                      <Icon className="size-[19px]" aria-hidden />
                      {badge ? (
                        <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-warn px-1 text-[9.5px] font-bold text-white dark:text-canvas" aria-hidden>
                          {badge}
                        </span>
                      ) : null}
                    </span>
                    <span aria-hidden>{item.short ?? item.label}</span>
                  </>
                )}
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
