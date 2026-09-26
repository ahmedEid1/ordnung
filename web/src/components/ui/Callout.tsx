import type { ReactNode } from "react";
import { CircleCheck, Info, OctagonAlert, TriangleAlert, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type CalloutTone = "info" | "warn" | "danger" | "success";

const styles: Record<CalloutTone, { box: string; icon: string; title: string; Icon: LucideIcon }> = {
  info: { box: "bg-accent-soft/70 border-accent/20", icon: "text-accent", title: "text-ink", Icon: Info },
  warn: { box: "bg-warn-soft border-warn/25", icon: "text-warn", title: "text-warn-ink", Icon: TriangleAlert },
  danger: { box: "bg-danger-soft border-danger/25", icon: "text-danger", title: "text-danger-ink", Icon: OctagonAlert },
  success: { box: "bg-ok-soft border-ok/25", icon: "text-ok", title: "text-ok-ink", Icon: CircleCheck },
};

export interface CalloutProps {
  tone?: CalloutTone;
  title?: ReactNode;
  children?: ReactNode;
  /** Override the icon. */
  icon?: LucideIcon;
  /** Actions (buttons) under the text. */
  action?: ReactNode;
  /** Use role="alert" for urgent, newly-appearing messages (scam banner). */
  alert?: boolean;
  className?: string;
}

/**
 * Inline message box: info · warn · danger (e.g. scam warning) · success.
 *
 * @example <Callout tone="danger" title="This looks like a scam">The IBAN differs…</Callout>
 */
export function Callout({ tone = "info", title, children, icon, action, alert, className }: CalloutProps) {
  const s = styles[tone];
  const Icon = icon ?? s.Icon;
  return (
    <div role={alert ? "alert" : undefined} className={cn("flex gap-3 rounded-xl border px-4 py-3.5 text-base", s.box, className)}>
      <Icon className={cn("mt-0.5 size-[18px] shrink-0", s.icon)} aria-hidden />
      <div className="min-w-0 flex-1">
        {title ? <div className={cn("font-semibold leading-5", s.title)}>{title}</div> : null}
        {children ? <div className={cn("leading-relaxed text-ink/85", title && "mt-1")}>{children}</div> : null}
        {action ? <div className="mt-3 flex flex-wrap gap-2">{action}</div> : null}
      </div>
    </div>
  );
}
