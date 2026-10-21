import { UserPermission } from '../../types/index.ts';
import { api } from '../../api/client.ts';
import { useAppDialogState } from './useAppDialogState.ts';
import { useFileExplorerState } from './useFileExplorerState.ts';
import { useLibraryDataState } from './useLibraryDataState.ts';

export function useFileOperations({ files, setFiles, setStorageStats, setTorrents, setFolders, activeUser, setActiveUser, activityStorageKey, setActivityLogs, setDeleteTarget, deleteTarget, currentFolder }: Pick<ReturnType<typeof useLibraryDataState>, 'files' | 'setFiles' | 'setStorageStats' | 'setTorrents' | 'setFolders' | 'activeUser' | 'setActiveUser' | 'activityStorageKey' | 'setActivityLogs'> & Pick<ReturnType<typeof useAppDialogState>, 'setDeleteTarget' | 'deleteTarget'> & Pick<ReturnType<typeof useFileExplorerState>, 'currentFolder'>) {
  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      if (deleteTarget.type === 'file') {
        await api.deleteFile(deleteTarget.id);
        setFiles(prev => prev.filter(f => f.id !== deleteTarget.id));
        const stats = await api.getStorageStats();
        setStorageStats(stats);
      } else if (deleteTarget.type === 'torrent') {
        await api.deleteTorrent(deleteTarget.id, true);
        setTorrents(prev => prev.filter(t => t.hash !== deleteTarget.id));
        const stats = await api.getStorageStats();
        setStorageStats(stats);
        const f = await api.getFiles(currentFolder);
        setFiles(f);
      }
    } catch (err) {
      console.error('Failed to execute delete:', err);
    }
  };
  const handleCreateFolder = async (name: string, isShared: boolean) => {
    const newFolder = await api.createFolder(name, currentFolder, isShared);
    setFolders(prev => [...prev, newFolder]);
  };
  const handleMoveFile = async (fileId: string, targetFolder: string) => {
    await api.moveFile(fileId, targetFolder);
    const updated = await api.getFiles(currentFolder);
    setFiles(updated);
  };
  const handleRename = async (id: string, newName: string, isFolder: boolean) => {
    await api.renameItem(id, newName, isFolder);
    if (isFolder) {
      const f = await api.getFolders();
      setFolders(f);
    }
    const updated = await api.getFiles(currentFolder);
    setFiles(updated);
  };
  const handleFolderShareSave = async (folderId: string, isShared: boolean, permissions: Record<string, UserPermission>) => {
    await api.updateFolderShare(folderId, isShared, permissions);
    const f = await api.getFolders();
    setFolders(f);
  };
  const handleSwitchUser = async (userId: string) => {
    const { activeUser: newUser } = await api.switchUser(userId);
    setActiveUser(newUser);
  };
  const handleRunCleanup = async () => {
    const res = await api.runCleanup();
    const stats = await api.getStorageStats();
    setStorageStats(stats);
    const f = await api.getFiles(currentFolder);
    setFiles(f);
    const logs = await api.getLogs();
    try {
      const rawLocalLogs = window.localStorage.getItem(activityStorageKey);
      const localLogs = rawLocalLogs ? JSON.parse(rawLocalLogs) : [];
      setActivityLogs(Array.isArray(localLogs) && localLogs.length ? localLogs : logs);
    } catch {
      setActivityLogs(logs);
    }
    return res;
  };

  return {
    handleConfirmDelete,
    handleCreateFolder,
    handleMoveFile,
    handleRename,
    handleFolderShareSave,
    handleRunCleanup,
  };
}
