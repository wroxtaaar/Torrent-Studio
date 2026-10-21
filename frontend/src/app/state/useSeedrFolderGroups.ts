import { useEffect, useCallback, useMemo } from 'react';
import { StorageFile } from '../../types/index.ts';
import { useSeedrState } from './useSeedrState.ts';

export function useSeedrFolderGroups({ setSeedrTorrentNames, seedrTorrentNamesKey, setSeedrDeletedFolderIds, setSeedrFolderContentsCache, setSeedrLibraryFolders, setSeedrFiles, setSelectedSeedrFolderId, seedrFolderContentsCache, seedrLibraryFolders, seedrTorrentNames, seedrNotice, selectedSeedrFolderId }: Pick<ReturnType<typeof useSeedrState>, 'setSeedrTorrentNames' | 'seedrTorrentNamesKey' | 'setSeedrDeletedFolderIds' | 'setSeedrFolderContentsCache' | 'setSeedrLibraryFolders' | 'setSeedrFiles' | 'setSelectedSeedrFolderId' | 'seedrFolderContentsCache' | 'seedrLibraryFolders' | 'seedrTorrentNames' | 'seedrNotice' | 'selectedSeedrFolderId'>) {
  const rememberSeedrTorrentName = useCallback((folderId: string, torrentName: string) => {
    const id = String(folderId || '').trim();
    const name = String(torrentName || '').trim();
    if (!id || !name || name === 'Waiting for Seedr metadata…') return;

    setSeedrTorrentNames(prev => {
      const next = { ...prev, [id]: name };
      try {
        window.localStorage.setItem(seedrTorrentNamesKey, JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);
  const forgetSeedrFolders = useCallback((folderIds: Array<string | number>) => {
    const removedIds = new Set(
      folderIds.map(id => String(id || '').trim()).filter(Boolean)
    );
    if (removedIds.size === 0) return;

    setSeedrDeletedFolderIds(prev => Array.from(new Set([...prev, ...removedIds])));
    setSeedrFolderContentsCache(prev =>
      Object.fromEntries(
        Object.entries(prev).filter(([folderId]) => !removedIds.has(String(folderId)))
      )
    );
    setSeedrLibraryFolders(prev =>
      prev.filter(folder => !removedIds.has(String(folder.folderId || folder.id || '')))
    );
    setSeedrFiles(prev =>
      prev.filter(file => !removedIds.has(String(file.folderId || '')))
    );
    setSeedrTorrentNames(prev => {
      const next = { ...prev };
      for (const id of removedIds) delete next[id];
      try {
        window.localStorage.setItem(seedrTorrentNamesKey, JSON.stringify(next));
      } catch {}
      return next;
    });
    setSelectedSeedrFolderId(prev => (
      prev && removedIds.has(String(prev)) ? null : prev
    ));
  }, []);
  const toSeedrStorageFile = useCallback((file: {
    id: string;
    streamId?: string;
    name: string;
    size: number;
    folderId: string;
    folderPath: string;
  }): StorageFile => {
    const lower = file.name.toLowerCase();
    const type: StorageFile['type'] =
      /\.(mkv|mp4|m4v|webm|mov|avi|m3u8|ts)$/i.test(lower) ? 'video' :
      /\.(mp3|wav|flac|aac|ogg|m4a)$/i.test(lower) ? 'audio' :
      /\.(zip|rar|7z|tar|gz|bz2)$/i.test(lower) ? 'archive' :
      /\.(pdf|txt|doc|docx|xls|xlsx|ppt|pptx|csv)$/i.test(lower) ? 'document' :
      'other';

    return {
      id: file.id,
      name: file.name,
      streamId: file.streamId || file.id,
      path: (file.folderPath || '/Torrent Studio').replace(/\/$/, '') + '/' + file.name,
      folder: file.folderPath || '/Torrent Studio',
      size: Number(file.size) || 0,
      type,
      mimeType: type === 'video' ? 'video/mp4' : type === 'audio' ? 'audio/mpeg' : 'application/octet-stream',
      createdAt: Date.now(),
      ownerId: 'seedr',
      ownerName: 'Seedr',
      isStreamable: type === 'video' || type === 'audio',
      downloadUrl: '/api/seedr/files/' + encodeURIComponent(file.id) + '/download',
      // The stream URL is resolved only when the user presses Stream.
      // Keep a placeholder here so library rendering never depends on a
      // runtime streamUrl variable.
      streamUrl: '',
    };
  }, []);
  const seedrAllPrefetchedFiles = useMemo(
    () => Object.values(seedrFolderContentsCache).flat(),
    [seedrFolderContentsCache]
  );
  // Active Seedr transfers are shown only in the transfer card above.
  // The initial response contains folder metadata only; file rows are loaded
  // lazily after a folder is opened.
  const seedrFolderGroups = useMemo(() => {
    type SeedrFolderGroup = {
      folderId: string;
      name: string;
      path: string;
      files: Array<{ id: string; name: string; size: number; folderId: string; folderPath: string }>;
      totalSize: number;
      filesCount: number;
      active?: boolean;
      progress?: number;
    };

    const groups: SeedrFolderGroup[] = seedrLibraryFolders.map(folder => {
      const folderId = folder.folderId || folder.id;
      const savedTorrentName = seedrTorrentNames[folderId];
      const torrentName = String((folder as { torrentName?: string }).torrentName || savedTorrentName || '').trim();
      return {
      folderId,
      name: torrentName || folder.name,
      path: folder.path,
      files: [],
      totalSize: Number(folder.totalSize) || 0,
      filesCount: Number(folder.filesCount) || 0,
      active: false,
      progress: undefined,
      };
    });

    if (seedrNotice?.taskId != null && seedrNotice.status !== 'completed') {
      const normalizeSeedrText = (value: string) =>
        value.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

      const actualFolderId =
        seedrNotice.folderId?.trim() ||
        seedrNotice.files.find(file => file.folderId && !file.folderId.startsWith('__'))?.folderId ||
        '';

      const activeName =
        seedrNotice.name?.trim() ||
        'Seedr download';

      const activeNameKey = normalizeSeedrText(activeName);
      let matchingEntry = actualFolderId
        ? groups.find(group => group.folderId === actualFolderId)
        : undefined;

      if (!matchingEntry) {
        matchingEntry = groups.find(group =>
          normalizeSeedrText(group.name) === activeNameKey ||
          normalizeSeedrText(group.path.split('/').filter(Boolean).pop() || '') === activeNameKey
        );
      }

      const activeFileSize = (seedrNotice.files || []).reduce((sum, file) => sum + Number(file.size || 0), 0);
      const activeFileCount = seedrNotice.files?.length || 0;

      if (matchingEntry) {
        matchingEntry.active = true;
        matchingEntry.progress = Math.max(0, Math.min(100, Number(seedrNotice.progress) || 0));
        matchingEntry.name = activeName || matchingEntry.name;
        if (actualFolderId) matchingEntry.folderId = actualFolderId;
        if (activeFileCount > 0 && matchingEntry.filesCount === 0) matchingEntry.filesCount = activeFileCount;
        if (activeFileSize > 0 && matchingEntry.totalSize === 0) matchingEntry.totalSize = activeFileSize;
      } else {
        groups.unshift({
          folderId: actualFolderId || '__active_seedr__',
          name: activeName,
          path: '/Torrent Studio/' + activeName,
          files: [],
          totalSize: activeFileSize,
          filesCount: activeFileCount,
          active: true,
          progress: Math.max(0, Math.min(100, Number(seedrNotice.progress) || 0)),
        });
      }
    }

    return groups.sort((a, b) => {
      if (a.active && !b.active) return -1;
      if (!a.active && b.active) return 1;
      return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
    });
  }, [seedrLibraryFolders, seedrNotice, seedrTorrentNames]);
  useEffect(() => {
    if (
      selectedSeedrFolderId !== null &&
      seedrLibraryFolders.length > 0 &&
      !seedrFolderGroups.some(folder => folder.folderId === selectedSeedrFolderId)
    ) {
      setSelectedSeedrFolderId(null);
      setSeedrFiles([]);
    }
  }, [selectedSeedrFolderId, seedrLibraryFolders.length, seedrFolderGroups]);

  return {
    rememberSeedrTorrentName,
    forgetSeedrFolders,
    toSeedrStorageFile,
    seedrAllPrefetchedFiles,
    seedrFolderGroups,
  };
}
