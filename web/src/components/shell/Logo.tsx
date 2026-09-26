import { cn } from "@/lib/utils";

/** The Ordnung mark (document + check seal), same drawing as `public/favicon.svg`. */
export function LogoMark({ className, title }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={cn("size-7 shrink-0", className)} role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <rect width="64" height="64" rx="14" fill="#0F6E66" />
      <rect x="16" y="14" width="32" height="38" rx="4" fill="#F7F5F0" />
      <rect x="22" y="22" width="20" height="3" rx="1.5" fill="#0F6E66" />
      <rect x="22" y="29" width="14" height="3" rx="1.5" fill="#0F6E66" opacity=".55" />
      <rect x="22" y="36" width="17" height="3" rx="1.5" fill="#0F6E66" opacity=".55" />
      <circle cx="44" cy="46" r="9" fill="#FCD34D" />
      <path d="M40 46l3 3 5-6" stroke="#0B4F49" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Mark + "Ordnung" wordmark in Fraunces. */
export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      {!compact ? (
        <span className="display text-[21px] font-semibold leading-none tracking-[-0.01em] text-ink" style={{ fontVariationSettings: '"opsz" 48, "SOFT" 60' }}>
          Ordnung
        </span>
      ) : (
        <span className="sr-only">Ordnung</span>
      )}
    </span>
  );
}
