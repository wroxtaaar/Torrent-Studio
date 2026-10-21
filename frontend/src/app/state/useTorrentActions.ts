import { TorrentItem, StorageFile } from '../../types/index.ts';
import { api } from '../../api/client.ts';
import { formatBytes } from '../../utils/formatters.ts';
import { useAppDialogState } from './useAppDialogState.ts';
import { useLibraryDataState } from './useLibraryDataState.ts';
import { useTransferRefs } from './useTransferRefs.ts';

export function useTorrentActions({ activeUser, torrents, setTorrents, setActiveMediaFile, setIsPlayerMinimized, setDeleteTarget, pendingTransferStates }: Pick<ReturnType<typeof useLibraryDataState>, 'activeUser' | 'torrents' | 'setTorrents'> & Pick<ReturnType<typeof useAppDialogState>, 'setActiveMediaFile' | 'setIsPlayerMinimized' | 'setDeleteTarget'> & Pick<ReturnType<typeof useTransferRefs>, 'pendingTransferStates'>) {
  const handleStreamTorrent = (torrent: TorrentItem) => {
    const streamableFile = torrent.files?.find(file => {
      if (file.priority <= 0 || file.progress < 0.999) return false;
      return /\.(mkv|mp4|m4v|webm|mov|avi|mp3|wav|flac|aac|ogg|m4a)$/i.test(file.name);
    });

    if (!streamableFile) return;

    const lower = streamableFile.name.toLowerCase();
    const type: StorageFile['type'] =
      /\.(mkv|mp4|m4v|webm|mov|avi)$/i.test(lower) ? 'video' : 'audio';

    const syntheticFile: StorageFile = {
      id: `torrent-${torrent.hash}-${streamableFile.index}`,
      name: streamableFile.name.split('/').pop() || streamableFile.name,
      path: streamableFile.path || streamableFile.name,
      folder: torrent.category || '/',
      size: streamableFile.size,
      type,
      mimeType: type === 'video' ? 'video/mp4' : 'audio/mpeg',
      createdAt: torrent.completion_on ? torrent.completion_on * 1000 : Date.now(),
      torrentHash: torrent.hash,
      isStreamable: true,
      ownerId: activeUser?.id || 'user_admin',
      ownerName: activeUser?.name || 'Admin',
      downloadUrl: `/api/torrents/download/${encodeURIComponent(torrent.hash)}/${streamableFile.index}`,
      streamUrl: `/api/torrents/stream/${encodeURIComponent(torrent.hash)}/${streamableFile.index}`
    };

    setActiveMediaFile(syntheticFile);
    setIsPlayerMinimized(false);
  };
  const handlePauseTorrent = async (hash: string) => {
    // Update immediately and hold that state through the next few polling
    // cycles while qBittorrent finishes applying stop().
    const previous = torrents;
    pendingTransferStates.current[hash] = {
      state: 'pausedDL',
      expiresAt: Date.now() + 5000
    };

    setTorrents(prev =>
      prev.map(t =>        t.hash === hash
          ? { ...t, state: 'pausedDL', dlspeed: 0, eta: -1 }
          : t
      )
    );

    try {      await api.pauseTorrent(hash);
    } catch (error) {
      delete pendingTransferStates.current[hash];
      console.error('Failed to pause torrent:', error);
      setTorrents(previous);
      throw error;
    }
  };
  const handleResumeTorrent = async (hash: string) => {
    const previous = torrents;
    pendingTransferStates.current[hash] = {
      state: 'downloading',
      expiresAt: Date.now() + 5000
    };

    setTorrents(prev =>
      prev.map(t =>
        t.hash === hash
          ? { ...t, state: 'downloading', eta: t.eta < 0 ? 0 : t.eta }
          : t
      )
    );

    try {
      await api.resumeTorrent(hash);
    } catch (error) {
      delete pendingTransferStates.current[hash];
      console.error('Failed to resume torrent:', error);
      setTorrents(previous);
      throw error;
    }
  };
  const handleDeleteTorrent = (hash: string) => {
    const torrent = torrents.find(t => t.hash === hash);
    if (!torrent) return;
    setDeleteTarget({
      type: 'torrent',
      id: torrent.hash,
      name: torrent.name,
      details: `${formatBytes(torrent.total_size)} • Progress: ${Math.round(torrent.progress * 100)}%`
    });
  };
  const handleUpdateFilePriority = async (hash: string, fileId: string, priority: number) => {
    const ids = fileId.split('|').map(Number).filter(Number.isFinite);
    const previous = torrents;

    // Reflect checkbox/priority changes immediately in the main torrent card.
    setTorrents(prev =>
      prev.map(t => {
        if (t.hash !== hash) return t;

        const nextFiles = (t.files || []).map(file =>
          ids.includes(file.index)
            ? {
                ...file,
                priority,
                progress: priority === 0 ? 0 : file.progress
              }
            : file
        );

        const selectedSize = nextFiles
          .filter(file => file.priority > 0)
          .reduce((sum, file) => sum + file.size, 0);

        return {
          ...t,
          files: nextFiles,
          selected_size: selectedSize
        };
      })
    );

    try {
      await api.setFilePriority(hash, fileId, priority);
    } catch (error) {
      console.error('Failed to update file priority:', error);
      setTorrents(previous);
      throw error;
    }

    api.getTorrents()
      .then(setTorrents)
      .catch(error => console.error('Failed to refresh torrents after priority update:', error));
  };

  return {
    handleUpdateFilePriority,
  };
}
