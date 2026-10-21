import { useRef } from 'react';

export function useTransferRefs() {
  // Previous torrent hashes for completion tracking
  const prevTorrentStates = useRef<Record<string, string>>({});
  // qBittorrent applies stop/start asynchronously. Keep an optimistic transfer
  // state visible for a short reconciliation window so the 1.8s polling loop
  // cannot immediately overwrite a user's pause/resume click with stale state.
  const pendingTransferStates = useRef<Record<string, { state: 'pausedDL' | 'downloading'; expiresAt: number }>>({});

  return {
    prevTorrentStates,
    pendingTransferStates,
  };
}
