import { api } from '../../api/client.ts';
import { useAppDialogState } from './useAppDialogState.ts';
import { useLibraryDataState } from './useLibraryDataState.ts';
import { useTransferRefs } from './useTransferRefs.ts';

export function useTorrentActions({ activeUser, torrents, setTorrents, setActiveMediaFile, setIsPlayerMinimized, setDeleteTarget, pendingTransferStates }: Pick<ReturnType<typeof useLibraryDataState>, 'activeUser' | 'torrents' | 'setTorrents'> & Pick<ReturnType<typeof useAppDialogState>, 'setActiveMediaFile' | 'setIsPlayerMinimized' | 'setDeleteTarget'> & Pick<ReturnType<typeof useTransferRefs>, 'pendingTransferStates'>) {
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
