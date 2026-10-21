import type { PanelModel } from '../useAppModel.tsx';
import { CloudFilesTab } from './CloudFilesTab.tsx';
import { TorrentSearchTab } from './TorrentSearchTab.tsx';
import { SeedrAddBlockedNotice } from './SeedrAddBlockedNotice.tsx';
import { SharedStorageTab } from './SharedStorageTab.tsx';

export function MainContent({ vm }: { vm: PanelModel }) {
  return (
    <>
      <main className="flex-1 max-w-7xl w-full mx-auto p-2.5 sm:p-6 pb-20 md:pb-12">
        <SeedrAddBlockedNotice vm={vm} />

        {/* TAB 0: TORRENT SEARCH
            Keep this component mounted when switching tabs so an in-flight
            search continues in the background and its results remain available
            when the user returns to Search. */}
        <TorrentSearchTab vm={vm} />

        {/* TAB 2: MY CLOUD FILES */}
        <CloudFilesTab vm={vm} />

        {/* TAB 3: SHARED STORAGE & MULTI-USER */}
        <SharedStorageTab vm={vm} />
        {/* Activity Log and Auto-Cleanup/Disk tabs are intentionally hidden. */}

      </main>
    </>
  );
}
