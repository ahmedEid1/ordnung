import { Monitor, Moon, Sun } from "lucide-react";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { IconButton } from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { useTheme, type ThemePref } from "@/app/theme";

const OPTIONS = [
  { value: "light" as const, label: "Light", icon: Sun, iconOnly: true },
  { value: "dark" as const, label: "Dark", icon: Moon, iconOnly: true },
  { value: "system" as const, label: "Match system", icon: Monitor, iconOnly: true },
];

/** Light / dark / system switch (persisted in localStorage `ordnung.theme`). */
export function ThemeToggle({ compact, className }: { compact?: boolean; className?: string }) {
  const { pref, setTheme } = useTheme();
  if (compact) {
    const order: ThemePref[] = ["light", "dark", "system"];
    const next = order[(order.indexOf(pref) + 1) % order.length]!;
    const cur = OPTIONS.find((o) => o.value === pref)!;
    return (
      <Tooltip content={`Theme: ${cur.label} — switch to ${OPTIONS.find((o) => o.value === next)!.label.toLowerCase()}`} side="right">
        <IconButton icon={cur.icon} label={`Theme: ${cur.label}`} title="" onClick={() => setTheme(next)} className={className} />
      </Tooltip>
    );
  }
  return <SegmentedControl label="Theme" size="sm" options={OPTIONS} value={pref} onChange={setTheme} className={className} />;
}
