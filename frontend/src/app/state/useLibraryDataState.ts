import { useState } from 'react';
import { TorrentItem, StorageFile, StorageFolder, UserProfile, StorageStats, ActivityLog, AppNotification, CleanupSettings } from '../../types/index.ts';

export function useLibraryDataState() {
  // Core Data
  const [torrents, setTorrents] = useState<TorrentItem[]>([]);
  const [files, setFiles] = useState<StorageFile[]>([]);
  const [folders, setFolders] = useState<StorageFolder[]>([]);
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [activeUser, setActiveUser] = useState<UserProfile | null>(null);
  const [storageStats, setStorageStats] = useState<StorageStats | null>(null);
  const activityStorageKey = 'seedflow_activity_logs';
  const [activityLogs, setActivityLogs] = useState<ActivityLog[]>(() => {
    try {
      const raw = window.localStorage.getItem(activityStorageKey);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [cleanupSettings, setCleanupSettings] = useState<CleanupSettings | null>(null);

  return {
    torrents,
    setTorrents,
    files,
    setFiles,
    folders,
    setFolders,
    users,
    setUsers,
    activeUser,
    setActiveUser,
    storageStats,
    setStorageStats,
    activityStorageKey,
    setActivityLogs,
    notifications,
    setNotifications,
    cleanupSettings,
    setCleanupSettings,
  };
}
