import { StorageFile } from '../../types/index.ts';

export interface MediaPlayerModalProps {
  file: StorageFile | null;
  onClose: () => void;
  onPlaybackStarted?: () => void;
  isMinimized: boolean;
  onToggleMinimize: () => void;
}
