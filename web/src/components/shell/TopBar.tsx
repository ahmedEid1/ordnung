import { useState } from "react";
import { Link, NavLink } from "react-router";
import { ArrowLeft, ChevronRight, Plus, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import { useScrolled } from "@/lib/hooks";
import { Button, IconButton, buttonVariants } from "@/components/ui/Button";
import { LogoMark } from "./Logo";
import { SearchBox } from "./SearchBox";
import { useAddLetters } from "./AddLetters";
import { usePageMeta } from "./page-meta";
import { DemoBadge } from "./DemoBadge";
import { SHELL_GUTTERS, shellWidth } from "./layout";
import { useHeadingUnderBar } from "./useHeadingUnderBar";

/** A back arrow in the logo's place (phones), as big as the bar's other icon buttons. */
const backButton = buttonVariants({ variant: "ghost", className: "-ml-1.5 size-9 px-0 text-ink [&_svg]:size-5" });

/**
 * Sticky top bar, lined up with the page column: page title (a breadcrumb on detail pages — a back
 * button on phones), letter search and the primary "Add letters" action. On phones it also
 * carries the logo, demo badge and Settings.
 *
 * On section pages the title fades in only once the page's own heading has scrolled under the bar.
 */
export function TopBar() {
  const { title, parent, width } = usePageMeta();
  const { openPicker, uploading } = useAddLetters();
  const scrolled = useScrolled();
  const [bar, setBar] = useState<HTMLElement | null>(null);
  const showTitle = useHeadingUnderBar(bar, !parent);

  return (
    <header
      ref={setBar}
      className={cn(
        "sticky top-0 z-30 h-14 shrink-0 border-b bg-canvas/95 backdrop-blur-md backdrop-saturate-150 transition-[border-color,box-shadow]",
        scrolled ? "border-line shadow-[0_1px_0_rgb(0_0_0/0.02)]" : "border-transparent",
      )}
    >
      <div className={cn("mx-auto flex h-full w-full items-center gap-2", SHELL_GUTTERS, shellWidth(width))}>
        <Link to="/" className={cn("mr-1 shrink-0 rounded-lg md:hidden", parent && "max-sm:hidden")} aria-label="Ordnung — Today">
          <LogoMark className="size-7" />
        </Link>
        <div className="flex min-w-0 flex-1 items-center text-[15px]">
          {parent ? (
            <nav aria-label="Breadcrumb" className="min-w-0">
              <ol className="flex min-w-0 items-center gap-1.5">
                <li className="flex shrink-0 sm:hidden">
                  <Link to={parent.to} aria-label={`Back to ${parent.label}`} title={`Back to ${parent.label}`} className={backButton}>
                    <ArrowLeft aria-hidden />
                  </Link>
                </li>
                <li className="hidden shrink-0 items-center gap-1.5 sm:flex">
                  <Link to={parent.to} className="rounded py-1 text-muted transition-colors hover:text-ink">
                    {parent.label}
                  </Link>
                  <ChevronRight className="size-4 shrink-0 text-muted/70" aria-hidden />
                </li>
                <li className="min-w-0">
                  <span aria-current="page" title={title} className="block truncate py-1 font-semibold text-ink">
                    {title}
                  </span>
                </li>
              </ol>
            </nav>
          ) : (
            <span
              title={title}
              aria-hidden={showTitle ? undefined : true}
              data-state={showTitle ? "shown" : "hidden"}
              className={cn(
                "truncate font-semibold text-ink transition-opacity duration-200 motion-reduce:transition-none",
                !showTitle && "opacity-0",
              )}
            >
              {title}
            </span>
          )}
        </div>
        <DemoBadge compact className="md:hidden max-[360px]:hidden" />
        <SearchBox />
        <Button variant="primary" icon={Plus} onClick={openPicker} loading={uploading} className="hidden sm:inline-flex">
          Add letters
        </Button>
        <IconButton icon={Plus} label="Add letters" variant="primary" onClick={openPicker} loading={uploading} className="sm:hidden" />
        <NavLink
          to="/settings"
          aria-label="Settings"
          title="Settings"
          className={({ isActive }) =>
            cn("grid size-9 shrink-0 place-items-center rounded-lg text-muted hover:bg-surface-3/70 hover:text-ink md:hidden", isActive && "text-accent")
          }
        >
          <Settings className="size-[18px]" aria-hidden />
        </NavLink>
      </div>
    </header>
  );
}
