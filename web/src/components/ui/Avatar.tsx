import { cn, initials } from "@/lib/utils";
import { PARTY_KIND_COPY, TONES, copyFor, type Tone } from "@/lib/copy";
import type { PartyKind } from "@/api/types";

export interface AvatarProps {
  name: string;
  /** Colour by party kind (landlord, telecom…); otherwise `tone`. */
  kind?: PartyKind | null;
  tone?: Tone;
  size?: "xs" | "sm" | "md" | "lg";
  className?: string;
}

// initials are decorative (the name is always next to them), but still no smaller than 10–11 px
const sizes = {
  xs: "size-5 text-[10px] rounded-[5px]",
  sm: "size-6 text-2xs rounded-md",
  md: "size-8 text-xs rounded-lg",
  lg: "size-12 text-lg rounded-xl",
};

/** Initials monogram for people & organisations. Decorative (the name is always shown next to it). */
export function Avatar({ name, kind, tone, size = "sm", className }: AvatarProps) {
  const t = TONES[tone ?? (kind ? copyFor(PARTY_KIND_COPY, kind).tone : "neutral")];
  return (
    <span
      aria-hidden
      className={cn("inline-grid shrink-0 place-items-center font-semibold tracking-tight", sizes[size], t.soft, t.text, className)}
    >
      {initials(name)}
    </span>
  );
}
