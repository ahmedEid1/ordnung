/**
 * One look for "pick one of these": the pill `Tabs` (filters with panels) and `SegmentedControl`
 * (a setting or a view) share the track, the sliding thumb and the item shape, so the two never
 * read as near-misses of each other. Both are 36 px tall at the default size (32 px for a small
 * segmented control), with the focus ring inside the item.
 */
export const SEGMENT_TRACK = "rounded-xl bg-surface-2 p-1";
/** Space between two items on the track. */
export const SEGMENT_GAP = "gap-1";
/** The item's shape (the thumb takes the same one). */
export const SEGMENT_ITEM = "rounded-lg focus-visible:-outline-offset-2";
/** The selected item's raised thumb. */
export const SEGMENT_THUMB = "rounded-lg bg-surface shadow-[var(--shadow-card)] ring-1 ring-line";
