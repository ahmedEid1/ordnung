import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Bell, CalendarDays, Cpu, Database, FolderInput, MapPin, Plug, Scale, ShieldCheck, Smartphone, UserRound, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { AttentionDot } from "@/components/shell/Sidebar";
import { SECTION_IDS, SECTION_LABELS, type SectionId } from "./logic";
import { useBackgroundProblems } from "./attention";

const ICONS: Record<SectionId, LucideIcon> = {
  profile: UserRound,
  region: MapPin,
  reminders: Bell,
  calendar: CalendarDays,
  folder: FolderInput,
  phone: Smartphone,
  ai: Cpu,
  claude: Plug,
  privacy: ShieldCheck,
  rules: Scale,
  data: Database,
};
const SECTIONS = SECTION_IDS.map((id) => ({ id, label: SECTION_LABELS[id], icon: ICONS[id] }));

/** How far the row fades out at an edge with more pills behind it. */
const FADE = "1.5rem";

/** A soft edge where the scrolling row has more pills to show (none when everything fits). */
export function edgeFade(start: boolean, end: boolean): CSSProperties | undefined {
  if (!start && !end) return undefined;
  const mask = `linear-gradient(to right, ${start ? "transparent" : "#000"}, #000 ${FADE}, #000 calc(100% - ${FADE}), ${end ? "transparent" : "#000"})`;
  return { maskImage: mask, WebkitMaskImage: mask };
}

/**
 * Settings sub-navigation, sized by the page column it sits in (a container query — the app's own
 * sidebar leaves less room than the window width suggests):
 *
 * - narrow (phones): one row of pills that scrolls sideways, fading out at an edge with more behind
 *   it; a pill that gets keyboard focus scrolls fully into view.
 * - from 36rem: the pills wrap onto a second row — nothing hidden.
 * - from 56rem: a vertical list next to the section.
 *
 * Each entry is a link (`?section=…`), so sections are linkable and work with Back. A section whose
 * background feature stopped working (the watched folder, calendar sync, the morning notification, phone
 * access) carries the same dot as Settings in the app's navigation.
 */
export function SettingsNav({ current, hrefFor, onNavigate }: { current: SectionId; hrefFor: (id: SectionId) => string; onNavigate: (id: SectionId) => void }) {
  const listRef = useRef<HTMLUListElement>(null);
  const [edges, setEdges] = useState({ start: false, end: false });
  const problems = useBackgroundProblems();
  const needsAttention = new Set(problems.map((p) => p.section));

  // phones: keep the current section's pill in view in the scrolling row
  useEffect(() => {
    const list = listRef.current;
    const active = list?.querySelector<HTMLElement>("[aria-current=page]");
    if (!list || !active || list.scrollWidth <= list.clientWidth) return;
    list.scrollLeft = active.offsetLeft - (list.clientWidth - active.offsetWidth) / 2;
  }, [current]);

  // which edges have more pills behind them (measured when the row scrolls or changes size)
  useEffect(() => {
    const list = listRef.current;
    if (!list || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const max = list.scrollWidth - list.clientWidth;
      const start = max > 1 && list.scrollLeft > 1;
      const end = max > 1 && list.scrollLeft < max - 1;
      setEdges((e) => (e.start === start && e.end === end ? e : { start, end }));
    };
    const ro = new ResizeObserver(measure);
    ro.observe(list);
    list.addEventListener("scroll", measure, { passive: true });
    return () => {
      ro.disconnect();
      list.removeEventListener("scroll", measure);
    };
  }, []);

  return (
    <nav aria-label="Settings sections">
      <ul
        ref={listRef}
        style={edgeFade(edges.start, edges.end)}
        className={cn(
          // phones: a row that scrolls sideways out to the screen's edges; room above and below for focus rings
          "-mx-4 -my-1 flex scroll-px-8 gap-1.5 overflow-x-auto px-4 py-1 scrollbar-thin",
          "@xl:m-0 @xl:flex-wrap @xl:overflow-visible @xl:p-0",
          "@4xl:flex-col @4xl:gap-0.5",
        )}
      >
        {SECTIONS.map((s) => {
          const active = s.id === current;
          const attention = needsAttention.has(s.id);
          return (
            <li key={s.id} className="shrink-0">
              <a
                href={hrefFor(s.id)}
                onClick={(e) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                  e.preventDefault();
                  onNavigate(s.id);
                }}
                onFocus={(e) => e.currentTarget.scrollIntoView?.({ block: "nearest", inline: "nearest" })}
                aria-current={active ? "page" : undefined}
                // named as the app's Settings link is (an sr-only span would sit outside the scrolling
                // row — its containing block is the page — and widen a phone's page)
                aria-label={attention ? `${s.label}, needs your attention` : undefined}
                className={cn(
                  "flex items-center gap-2.5 whitespace-nowrap rounded-full border px-3 py-1.5 text-[13.5px] font-medium transition-colors @4xl:rounded-lg @4xl:border-transparent @4xl:px-2.5 @4xl:py-2",
                  active
                    ? "border-line-strong bg-surface text-ink shadow-[var(--shadow-card)] @4xl:border-line"
                    : "border-line text-muted hover:bg-surface-2 hover:text-ink @4xl:hover:bg-surface-3/60",
                )}
              >
                <s.icon className={cn("size-4 shrink-0", active ? "text-accent" : "text-faint")} aria-hidden />
                {s.label}
                {attention ? <AttentionDot className="shrink-0 ring-0 @4xl:ml-auto" /> : null}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
