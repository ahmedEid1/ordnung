import { useEffect, useRef } from "react";
import { Bell, CalendarDays, Cpu, Database, MapPin, Plug, Scale, ShieldCheck, UserRound, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { SECTION_IDS, SECTION_LABELS, type SectionId } from "./logic";

const ICONS: Record<SectionId, LucideIcon> = {
  profile: UserRound,
  region: MapPin,
  reminders: Bell,
  calendar: CalendarDays,
  ai: Cpu,
  claude: Plug,
  privacy: ShieldCheck,
  rules: Scale,
  data: Database,
};
const SECTIONS = SECTION_IDS.map((id) => ({ id, label: SECTION_LABELS[id], icon: ICONS[id] }));

/**
 * Settings sub-navigation: a vertical list on large screens, a horizontally scrolling row of pills
 * on phones. Each entry is a link (`?section=…`), so sections are linkable and work with Back.
 */
export function SettingsNav({ current, hrefFor, onNavigate }: { current: SectionId; hrefFor: (id: SectionId) => string; onNavigate: (id: SectionId) => void }) {
  const listRef = useRef<HTMLUListElement>(null);
  // phones: keep the current section's pill in view in the scrolling row
  useEffect(() => {
    const list = listRef.current;
    const active = list?.querySelector<HTMLElement>("[aria-current=page]");
    if (!list || !active || list.scrollWidth <= list.clientWidth) return;
    list.scrollLeft = active.offsetLeft - (list.clientWidth - active.offsetWidth) / 2;
  }, [current]);
  return (
    <nav aria-label="Settings sections">
      <ul ref={listRef} className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 scrollbar-thin sm:-mx-6 sm:px-6 lg:mx-0 lg:flex-col lg:gap-0.5 lg:overflow-visible lg:px-0 lg:pb-0">
        {SECTIONS.map((s) => {
          const active = s.id === current;
          return (
            <li key={s.id} className="shrink-0">
              <a
                href={hrefFor(s.id)}
                onClick={(e) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                  e.preventDefault();
                  onNavigate(s.id);
                }}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-[13.5px] font-medium transition-colors lg:rounded-lg lg:border-transparent lg:px-2.5 lg:py-2",
                  active
                    ? "border-line-strong bg-surface text-ink shadow-[var(--shadow-card)] lg:border-line"
                    : "border-line text-muted hover:bg-surface-2 hover:text-ink lg:hover:bg-surface-3/60",
                )}
              >
                <s.icon className={cn("size-4 shrink-0", active ? "text-accent" : "text-faint")} aria-hidden />
                {s.label}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
