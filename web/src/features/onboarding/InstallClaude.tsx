import { useId, useState } from "react";
import { Tabs } from "@/components/ui/Tabs";
import { COMPUTER_OS_LABELS, computerOs, type ComputerOs } from "@/features/settings/phoneAccess";
import { CopyCommand } from "./CopyCommand";
import { CLAUDE_INSTALL, CLAUDE_NPM_INSTALL, CLAUDE_NPM_NEEDS, CLAUDE_UPDATE_CMD, CLAUDE_UPDATE_OTHER } from "./options";

const OS_ORDER: ComputerOs[] = ["mac", "windows", "linux"];
const code = "rounded bg-surface-2 px-1 py-px font-mono text-[12px] text-ink [overflow-wrap:anywhere]";

/**
 * Installing Claude Code, for this computer's system (guessed from the browser, switchable): Anthropic's
 * installer first, then the package manager the setup page lists for that system, npm last.
 */
export function InstallClaude() {
  const id = useId();
  const [os, setOs] = useState<ComputerOs>(() => computerOs(typeof navigator === "undefined" ? "" : navigator.userAgent));
  const { shell, command, other } = CLAUDE_INSTALL[os];
  return (
    <div className="space-y-2.5">
      <Tabs id={id} label="This computer's system" variant="pill" value={os} onChange={setOs} items={OS_ORDER.map((o) => ({ value: o, label: COMPUTER_OS_LABELS[o] }))} />
      <div role="tabpanel" id={`${id}-panel-${os}`} aria-labelledby={`${id}-tab-${os}`} className="space-y-2">
        <p className="text-[13px] text-muted">In {shell}:</p>
        <CopyCommand command={command} label="install Claude Code" />
        <p className="text-[12.5px] leading-5 text-muted">
          {other ? (
            <>
              Or with {other.via}: <code className={code}>{other.command}</code>.{" "}
            </>
          ) : null}
          With {CLAUDE_NPM_NEEDS}, npm works too: <code className={code}>{CLAUDE_NPM_INSTALL}</code>. Then open a new terminal window.
        </p>
      </div>
    </div>
  );
}

/** Updating Claude Code: `claude update`, or the package manager it came from. */
export function UpdateClaude() {
  return (
    <div className="space-y-2">
      <CopyCommand command={CLAUDE_UPDATE_CMD} label="update Claude Code" />
      <p className="text-[12.5px] leading-5 text-muted">
        Installed it with {CLAUDE_UPDATE_OTHER.map((o) => o.via).join(" or ")}? Update it there:{" "}
        {CLAUDE_UPDATE_OTHER.map((o, i) => (
          <span key={o.via}>
            {i ? " or " : ""}
            <code className={code}>{o.command}</code>
          </span>
        ))}
        .
      </p>
    </div>
  );
}
