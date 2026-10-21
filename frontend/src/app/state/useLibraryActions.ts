import { useAppDialogState } from './useAppDialogState.ts';
import { useFileExplorerState } from './useFileExplorerState.ts';
import { useLibraryDataState } from './useLibraryDataState.ts';
import { useFeedback } from './useFeedback.ts';
import { useFileOperations } from './useFileOperations.ts';

export function useLibraryActions({ files, setFiles, setStorageStats, setTorrents, setFolders, activeUser, setActiveUser, activityStorageKey, setActivityLogs, torrents, notifications, setDeleteTarget, deleteTarget, feedbackMessage, setFeedbackError, setFeedbackSubmitting, setFeedbackSuccess, feedbackType, feedbackRating, feedbackName, setFeedbackMessage, setFeedbackName, setFeedbackRating, currentFolder }: Pick<ReturnType<typeof useLibraryDataState>, 'files' | 'setFiles' | 'setStorageStats' | 'setTorrents' | 'setFolders' | 'activeUser' | 'setActiveUser' | 'activityStorageKey' | 'setActivityLogs' | 'torrents' | 'notifications'> & Pick<ReturnType<typeof useAppDialogState>, 'setDeleteTarget' | 'deleteTarget' | 'feedbackMessage' | 'setFeedbackError' | 'setFeedbackSubmitting' | 'setFeedbackSuccess' | 'feedbackType' | 'feedbackRating' | 'feedbackName' | 'setFeedbackMessage' | 'setFeedbackName' | 'setFeedbackRating'> & Pick<ReturnType<typeof useFileExplorerState>, 'currentFolder'>) {
  const { handleConfirmDelete, handleCreateFolder, handleMoveFile, handleRename, handleFolderShareSave, handleRunCleanup } = useFileOperations({ files, setFiles, setStorageStats, setTorrents, setFolders, activeUser, setActiveUser, activityStorageKey, setActivityLogs, setDeleteTarget, deleteTarget, currentFolder });
  const { submitFeedback } = useFeedback({ feedbackMessage, setFeedbackError, setFeedbackSubmitting, setFeedbackSuccess, feedbackType, feedbackRating, feedbackName, setFeedbackMessage, setFeedbackName, setFeedbackRating });
  // Download batch zip
  const activeDownloadsCount = torrents.filter(t => t.state === 'downloading').length;
  const unreadNotifsCount = notifications.filter(n => !n.read).length;
  const currentFolderPrefix = currentFolder === '/' ? '/' : currentFolder + '/';

  return {
    handleConfirmDelete,
    handleCreateFolder,
    handleMoveFile,
    handleRename,
    handleFolderShareSave,
    handleRunCleanup,
    submitFeedback,
    unreadNotifsCount,
    currentFolderPrefix,
  };
}
