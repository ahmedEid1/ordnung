/**
 * Phone mode: is this tab the computer Ordnung runs on, or a phone paired over the home network (Settings → Phone)?
 *
 * The server says so in every `/api/health` answer (`Health.client`): the phone's own listener answers "phone",
 * the computer's "computer". Health loads before the shell renders, so the answer is known at first paint. In phone
 * mode the app hides what only the computer may do (settings, backups, deleting, downloads, held letters), and the
 * server refuses it anyway (403 `computer_only`).
 */
import { useHealth } from "@/api/hooks";

export { clientKind, setClientKind } from "@/api/clientKind";

/** True on a paired phone (`/api/health` says `client: "phone"`); false on the computer and while health loads. */
export function usePhoneCompanion(): boolean {
  return useHealth().data?.client === "phone";
}
