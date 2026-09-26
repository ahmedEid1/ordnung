/**
 * Unsaved edits in Settings: every form's SaveBar reports whether it is dirty, so the Settings page
 * can warn before switching sections (or leaving) and throwing the edits away.
 */
import { createContext, useContext, useEffect, useId } from "react";

/** Receives "this form has unsaved edits" reports (the Settings page warns before switching away). */
type DirtyReporter = (key: string, dirty: boolean) => void;
const DirtyContext = createContext<DirtyReporter | null>(null);

/** Provided by the Settings page: every `SaveBar` below reports whether its form is dirty. */
export const SettingsDirtyProvider = DirtyContext.Provider;

/** Report unsaved edits of a settings form (cleared when it unmounts). No-op outside the Settings page. */
export function useReportDirty(dirty: boolean): void {
  const report = useContext(DirtyContext);
  const key = useId();
  useEffect(() => {
    if (!report) return;
    report(key, dirty);
    return () => report(key, false);
  }, [report, key, dirty]);
}
