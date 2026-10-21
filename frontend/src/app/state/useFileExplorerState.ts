import { useState } from 'react';

export function useFileExplorerState() {
  // File Explorer State
  const [currentFolder, setCurrentFolder] = useState<string>('/');
  const [fileSearch, setFileSearch] = useState<string>('');
  const [fileTypeFilter, setFileTypeFilter] = useState<string>('all');
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);

  return {
    currentFolder,
    setCurrentFolder,
    fileSearch,
    setFileSearch,
    fileTypeFilter,
    setFileTypeFilter,
  };
}
