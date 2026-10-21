import { useEffect, useCallback, useMemo } from 'react';
import { TorrentItem, ActivityLog } from '../../types/index.ts';
import { api } from '../../api/client.ts';
import { dispatchBrowserNotification, playNotificationSound } from '../../utils/notifications.ts';
import { useFileExplorerState } from './useFileExplorerState.ts';
import { useLibraryDataState } from './useLibraryDataState.ts';
import { useTransferRefs } from './useTransferRefs.ts';

export function useTransferPolling({ torrents, setFiles, setStorageStats, setNotifications, setTorrents, setActivityLogs, activityStorageKey, prevTorrentStates, pendingTransferStates, currentFolder }: Pick<ReturnType<typeof useLibraryDataState>, 'torrents' | 'setFiles' | 'setStorageStats' | 'setNotifications' | 'setTorrents' | 'setActivityLogs' | 'activityStorageKey'> & Pick<ReturnType<typeof useTransferRefs>, 'prevTorrentStates' | 'pendingTransferStates'> & Pick<ReturnType<typeof useFileExplorerState>, 'currentFolder'>) {
  const hasActiveQbtTransfers = useMemo(
    () => torrents.some(t =>
      t.state === 'downloading' ||
      t.state === 'pausedDL' ||
      (t.state as string) === 'queuedDL' ||
      t.progress < 1
    ),
    [torrents]
  );
  // Poll qBittorrent compatibility data slowly when idle and faster only while
  // there is an active transfer. Seedr has its own lighter task polling loop.
  useEffect(() => {
    let isMounted = true;

    const pollTorrents = async () => {
      try {
        const torrentList = await api.getTorrents();        if (!isMounted) return;

        // Check for completions to fire push notifications
        torrentList.forEach(t => {          const prevState = prevTorrentStates.current[t.hash];
          if (prevState === 'downloading' && (t.state === 'completed' || t.progress >= 1)) {
            // Transfer finished! Trigger sound and push alert
            playNotificationSound();
            dispatchBrowserNotification(
              `Download Finished: ${t.name}`,
              `Direct streaming and direct download links are now ready in your cloud storage.`
            );
            // Refresh storage & files list
            api.getFiles(currentFolder).then(setFiles).catch(console.error);
            api.getStorageStats().then(setStorageStats).catch(console.error);
            api.getNotifications().then(setNotifications).catch(console.error);
          }
          prevTorrentStates.current[t.hash] = t.state;
        });

        const now = Date.now();
        const reconciledTorrentList = torrentList.map((t): TorrentItem => {
          const pending = pendingTransferStates.current[t.hash];
          if (!pending) return t;

          if (pending.expiresAt <= now) {
            delete pendingTransferStates.current[t.hash];
            return t;
          }

          if (pending.state === 'pausedDL') {
            return { ...t, state: 'pausedDL', dlspeed: 0, eta: -1 };
          }

          return {
            ...t,
            state: 'downloading',
            eta: t.eta < 0 ? 0 : t.eta
          };
        });

        setTorrents(reconciledTorrentList);
      } catch (e) {
        console.error('Polling error:', e);
      }
    };

    pollTorrents();
    if (!hasActiveQbtTransfers) {
      return () => {
        isMounted = false;
      };
    }

    const interval = setInterval(pollTorrents, 5000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [currentFolder, hasActiveQbtTransfers]);
  // Actions
  const appendActivityLog = useCallback((log: ActivityLog) => {
    setActivityLogs(prev => {
      const next = [log, ...prev].slice(0, 100);
      try {
        window.localStorage.setItem(activityStorageKey, JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);

  return {
    appendActivityLog,
  };
}
