import { Link, NavLink } from "react-router";
import { ChevronRight, Plus, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import { useScrolled } from "@/lib/hooks";
import { Button, IconButton } from "@/components/ui/Button";
import { LogoMark } from "./Logo";
import { SearchBox } from "./SearchBox";
import { useAddLetters } from "./AddLetters";
import { usePageMeta } from "./page-meta";
import { DemoBadge } from "./DemoBadge";

/**
 * Sticky top bar: page title (with breadcrumb parent), letter search and the primary
 * "Add letters" action. On phones it also carries the logo, demo badge and Settings.
 */
export function TopBar() {
  const { title, parent } = usePageMeta();
  const { openPicker, uploading } = useAddLetters();
  const scrolled = useScrolled();

  return (
    <header
      className={cn(
        "sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b bg-canvas/85 px-4 backdrop-blur-md transition-[border-color,box-shadow] sm:px-6 lg:px-10 supports-[backdrop-filter]:bg-canvas/75",
        scrolled ? "border-line shadow-[0_1px_0_rgb(0_0_0/0.02)]" : "border-transparent",
      )}
    >
      <Link to="/" className="mr-1 rounded-lg md:hidden" aria-label="Ordnung — Today">
        <LogoMark className="size-7" />
      </Link>
      <div className="flex min-w-0 flex-1 items-center gap-1.5 text-[15px]">
        {parent ? (
          <>
            <Link to={parent.to} className="hidden shrink-0 rounded text-muted transition-colors hover:text-ink sm:inline">
              {parent.label}
            </Link>
            <ChevronRight className="hidden size-4 shrink-0 text-muted/70 sm:block" aria-hidden />
          </>
        ) : null}
        <span className="truncate font-semibold text-ink" aria-current="page">
          {title}
        </span>
      </div>
      <DemoBadge compact className="size-8 md:hidden" />
      <SearchBox />
      <Button variant="primary" icon={Plus} onClick={openPicker} loading={uploading} className="hidden sm:inline-flex">
        Add letters
      </Button>
      <IconButton icon={Plus} label="Add letters" variant="primary" onClick={openPicker} loading={uploading} className="sm:hidden" />
      <NavLink
        to="/settings"
        aria-label="Settings"
        className={({ isActive }) =>
          cn("grid size-9 place-items-center rounded-lg text-muted hover:bg-surface-3/70 hover:text-ink md:hidden", isActive && "text-accent")
        }
      >
        <Settings className="size-[18px]" aria-hidden />
      </NavLink>
    </header>
  );
}
