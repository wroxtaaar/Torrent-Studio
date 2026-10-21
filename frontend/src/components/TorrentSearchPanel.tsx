import React from 'react';
import { TorrentSearchPanelProps } from './torrent-search/props.ts';
import { useTorrentSearchPanel } from './torrent-search/useTorrentSearchPanel.tsx';
import { EmptyResultsNotice } from './torrent-search/sections/EmptyResultsNotice.tsx';
import { SearchResultsSection } from './torrent-search/sections/SearchResultsSection.tsx';
import { MovieTorrentPickerSection } from './torrent-search/sections/MovieTorrentPickerSection.tsx';
import { MovieCatalogueSection } from './torrent-search/sections/MovieCatalogueSection.tsx';
import { NexStreamLoadingNotice } from './torrent-search/sections/NexStreamLoadingNotice.tsx';
import { NexStreamSection } from './torrent-search/sections/NexStreamSection.tsx';
import { ErrorBanner } from './torrent-search/sections/ErrorBanner.tsx';
import { PrepareWaitModal } from './torrent-search/sections/PrepareWaitModal.tsx';
import { PrepareErrorBanner } from './torrent-search/sections/PrepareErrorBanner.tsx';
import { SearchingBanner } from './torrent-search/sections/SearchingBanner.tsx';
import { SearchBarSection } from './torrent-search/sections/SearchBarSection.tsx';

export const TorrentSearchPanel: React.FC<TorrentSearchPanelProps> = (props) => {
  const vm = useTorrentSearchPanel({ ...props, seedrFiles: props.seedrFiles ?? [], seedrDeletedFolderIds: props.seedrDeletedFolderIds ?? [] });

  // Load lightweight w185 thumbnails first; MovieCards upgrades them to w780 only
  // after card metadata, ratings and OTT availability have settled.

  // Recent searches belong to this Home deployment. Use the same-origin API
  // base as every other Home request; a hard-coded Render URL causes browser CORS
  // failures when Home is opened from the Oracle VPS.

  return (
    <div className="space-y-2.5 sm:space-y-4">
      <SearchBarSection vm={vm} />

      <SearchingBanner vm={vm} />
      <PrepareErrorBanner vm={vm} />
      <PrepareWaitModal vm={vm} />
      <ErrorBanner vm={vm} />
      <NexStreamSection vm={vm} />
      <NexStreamLoadingNotice vm={vm} />
      <MovieCatalogueSection vm={vm} />
      <MovieTorrentPickerSection vm={vm} />
      <SearchResultsSection vm={vm} />
      <EmptyResultsNotice vm={vm} />
    </div>
  );
};
