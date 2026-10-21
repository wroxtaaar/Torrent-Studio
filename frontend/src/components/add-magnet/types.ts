export interface AddMagnetModalProps {
  isOpen: boolean;
  onClose: () => void;
  onOpen: () => void;
  onAdd: (
    magnet: string,
    category: string,
    selectedFiles?: number[],
    manifest?: { index?: number; name: string; size: number; priority: number }[],
    existingHash?: string,
    forceBackend?: 'seedr' | 'qbittorrent',
    selectedNames?: string[],
     seedrTaskId?: number | string,
    torrentName?: string
  ) => Promise<void>;
  defaultFolder?: string;
  initialMagnet?: string;
  initialSourceUrl?: string;
  initialDescriptorUrl?: string;
  onBackgroundChange?: (state: { active: boolean; title: string; message: string; ready?: boolean; error?: string; jobId?: string }) => void;
}

export interface InspectFileItem {
  index: number;
  name: string;
  size: number;
  type: 'video' | 'audio' | 'archive' | 'document' | 'other';
  selected: boolean;
}
