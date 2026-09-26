import type { ReactNode } from "react";
import { motion } from "motion/react";
import { cn } from "@/lib/utils";
import { TONES, type Tone } from "@/lib/copy";

export interface ProgressRingProps {
  /** 0..1 */
  value: number;
  size?: number;
  stroke?: number;
  tone?: Tone;
  /** Accessible label ("Verified facts"). */
  label: string;
  /** Centre content (defaults to the percentage). */
  children?: ReactNode;
  className?: string;
}

/**
 * Circular progress / ratio indicator (e.g. share of facts found in the letter, job progress).
 * Exposes `role="progressbar"` with aria values.
 */
export function ProgressRing({ value, size = 44, stroke = 4, tone = "accent", label, children, className }: ProgressRingProps) {
  const v = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const t = TONES[tone];
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(v * 100)}
      className={cn("relative inline-grid shrink-0 place-items-center", className)}
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-line)" strokeWidth={stroke} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="currentColor"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          initial={false}
          animate={{ strokeDashoffset: c * (1 - v) }}
          transition={{ duration: 0.6, ease: [0.2, 0.8, 0.2, 1] }}
          className={t.icon}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-[11px] font-semibold tabular-nums text-ink">
        {children ?? `${Math.round(v * 100)}%`}
      </span>
    </div>
  );
}
