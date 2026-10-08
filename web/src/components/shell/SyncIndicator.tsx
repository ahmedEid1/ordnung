import { NavLink } from "react-router";
import { CloudAlert, CloudCheck, CloudUpload } from "lucide-react";
import { useSync } from "@/api/hooks";
import { usePhoneCompanion } from "@/features/phone/client";
import { indicatorLabel } from "@/features/settings/sync";
import { cn } from "@/lib/utils";

const ICONS = { saved: CloudCheck, saving: CloudUpload, problem: CloudAlert } as const;

/**
 * Hand-off sync in the top bar, only on the computer in use: whether its changes are saved to the sync folder and
 * reached the other computer ("Saved · desktop has it" — safe to close the lid), are being saved, or can't be. It
 * leads to Settings → Your computers. Never on a phone (sync is the computer's).
 */
export function SyncIndicator({ className }: { className?: string }) {
  const phone = usePhoneCompanion();
  const { data: status } = useSync(!phone);
  if (phone || !status?.connected || status.mode !== "in_use") return null;
  const { state, label } = indicatorLabel(status);
  const Icon = ICONS[state];
  return (
    <NavLink
      to="/settings?section=computers"
      aria-label={label}
      title={label}
      data-state={state}
      className={({ isActive }) =>
        cn(
          "grid size-9 shrink-0 place-items-center rounded-lg hover:bg-surface-3/70",
          state === "problem" ? "text-warn" : "text-muted hover:text-ink",
          isActive && state !== "problem" && "text-accent",
          className,
        )
      }
    >
      <Icon className={cn("size-[18px]", state === "saving" && "animate-pulse-soft motion-reduce:animate-none")} aria-hidden />
    </NavLink>
  );
}
