import type { ReactNode } from "react";
import type { Lane, LaneBar, RefLink, TimelineMarker } from "@/api/types";

/** What was clicked on the chart. */
export interface LaneSelection {
  lane: Lane;
  /** the bar that was clicked, or the bar a clicked marker belongs to */
  bar: LaneBar | null;
  /** the clicked marker (the most important one of a merged cluster) */
  marker: TimelineMarker | null;
  ref: RefLink | null;
  /** the date the selection is about (marker date, or bar end) */
  date: string;
}

/** Where a selection leads: an in-app link and/or a short hint for tooltips ("Opens the letter"). */
export interface LaneTarget {
  href?: string;
  hint: string;
}

/** Optional per-lane presentation (icon, label override, second line). */
export interface LaneDescription {
  icon?: ReactNode;
  label?: string;
  /** replaces the default "Send by 8 Oct · in 10 days" line */
  sublabel?: ReactNode;
}
