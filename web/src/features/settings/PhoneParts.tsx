/**
 * Small parts Settings → Phone's cards share: a disclosure in the cards' style, and how to remove Ordnung's
 * certificate from a phone (said after Start over, Delete everything and a new address, which all make the old
 * certificate useless — a phone that trusted it should not keep trusting it).
 */
import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { Tabs } from "@/components/ui/Tabs";
import { cn } from "@/lib/utils";
import { REMOVE_STEPS, TRUST_PLATFORM_LABELS, type TrustPlatform } from "./phoneAccess";

/** A disclosure ("Why does my phone warn me?"): a question to open, its answer under it. `open` controls it. */
export function Disclosure({
  summary,
  children,
  open,
  onToggle,
  className,
  id,
}: {
  summary: ReactNode;
  children: ReactNode;
  open?: boolean;
  onToggle?: (open: boolean) => void;
  className?: string;
  id?: string;
}) {
  return (
    <details
      id={id}
      open={open}
      onToggle={onToggle ? (e) => onToggle(e.currentTarget.open) : undefined}
      className={cn("group rounded-xl border border-line bg-surface-2/50 px-3.5 py-2.5 text-[13.5px] leading-5 text-ink/85", className)}
    >
      <summary className="flex min-h-6 cursor-pointer list-none items-center gap-1.5 rounded-sm font-medium text-ink marker:hidden [&::-webkit-details-marker]:hidden">
        <ChevronDown className="size-4 shrink-0 transition-transform group-open:rotate-180 motion-reduce:transition-none" aria-hidden />
        {summary}
      </summary>
      <div className="mt-2 space-y-2">{children}</div>
    </details>
  );
}

const PLATFORMS: TrustPlatform[] = ["ios", "android"];

/**
 * Steps for each phone system, as tabs (iPhone · Android), with the one this person is likely to use first.
 * `render` draws a system's steps.
 */
export function PlatformTabs({ label, render, initial = "ios", id }: { label: string; render: (p: TrustPlatform) => ReactNode; initial?: TrustPlatform; id: string }) {
  const [platform, setPlatform] = useState<TrustPlatform>(initial);
  return (
    <div>
      <Tabs id={id} label={label} variant="pill" value={platform} onChange={setPlatform} items={PLATFORMS.map((p) => ({ value: p, label: TRUST_PLATFORM_LABELS[p] }))} />
      <div role="tabpanel" id={`${id}-panel-${platform}`} aria-labelledby={`${id}-tab-${platform}`} className="mt-2">
        {render(platform)}
      </div>
    </div>
  );
}

/** How to remove Ordnung's certificate from a phone that trusted it. */
export function RemoveCertificateSteps({ id }: { id: string }) {
  return (
    <PlatformTabs
      id={id}
      label="Which phone"
      render={(p) => <p className="text-[13.5px] leading-5 text-ink/85">{REMOVE_STEPS[p]}</p>}
    />
  );
}
