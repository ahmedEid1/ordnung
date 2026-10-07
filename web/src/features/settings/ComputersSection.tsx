/**
 * Settings → Your computers (design §19.1): hand-off sync between the person's computers. Not connected: the setup
 * card (or why it can't be used here: no password store, the demo). Connected: the notices, this computer, the
 * others, and the kept copies. The status comes from the server's memory — asking never reads the folder or the
 * password store.
 */
import { useSync } from "@/api/hooks";
import { LoadError } from "@/components/ui/LoadError";
import { LoadingLabel, SkeletonText } from "@/components/ui/Skeleton";
import { SyncNotices } from "@/features/sync/parts";
import { ComputersListCard } from "./ComputersListCard";
import { KeptCopiesCard } from "./KeptCopiesCard";
import { SectionHeading } from "./SettingsCard";
import { SyncSetupCard } from "./SyncSetupCard";
import { ThisComputerCard } from "./ThisComputerCard";

export function ComputersSection() {
  const sync = useSync();
  const status = sync.data;
  return (
    <section aria-labelledby="set-computers">
      <SectionHeading
        id="set-computers"
        title="Your computers"
        description="Use Ordnung on your laptop and your desktop — one at a time, through a folder your own sync tool keeps in step. Only encrypted files go there."
      />
      {sync.isPending ? (
        <div aria-busy="true" className="card p-6">
          <LoadingLabel>Loading your computers…</LoadingLabel>
          <SkeletonText lines={5} />
        </div>
      ) : sync.isError || !status ? (
        <LoadError
          what="hand-off sync"
          description="Nothing was changed — Ordnung didn't answer. Is it still running?"
          error={sync.error}
          onRetry={() => void sync.refetch()}
          retrying={sync.isFetching}
          headingLevel={3}
        />
      ) : (
        <div className="space-y-5">
          {status.connected ? (
            <>
              <SyncNotices notices={status.notices} />
              <ThisComputerCard status={status} />
              <ComputersListCard status={status} />
            </>
          ) : (
            // a fresh editor after disconnecting (its fields belong to one state)
            <SyncSetupCard key="setup" status={status} />
          )}
          <KeptCopiesCard status={status} />
        </div>
      )}
    </section>
  );
}
