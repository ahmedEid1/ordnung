import type { Variants } from "motion/react";

const EASE = [0.2, 0.8, 0.2, 1] as const;

/** Parent of a staggered fade-in (children use {@link fadeUp}). */
export const stagger: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.02 } },
};

/**
 * Subtle fade + 8 px rise. With "reduce motion" the global MotionConfig drops the transform and
 * keeps only the opacity change.
 */
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: EASE } },
};

/** Exit used when an Idea or action card is dismissed. */
export const collapseOut = { opacity: 0, scale: 0.98, transition: { duration: 0.18 } };
