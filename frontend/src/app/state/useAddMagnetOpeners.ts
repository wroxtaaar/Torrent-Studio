import { useCallback } from 'react';
import { useAppDialogState } from './useAppDialogState.ts';
import { useSeedrState } from './useSeedrState.ts';
import { useAppShellState } from './useAppShellState.ts';

export function useAddMagnetOpeners({ seedrNotice, setSeedrAddBlockedNotice, setInitialMagnet, setIsAddMagnetOpen, setInitialSourceUrl, setInitialDescriptorUrl, setBackgroundMetadataJob, setActiveTab }: Pick<ReturnType<typeof useSeedrState>, 'seedrNotice' | 'setSeedrAddBlockedNotice'> & Pick<ReturnType<typeof useAppDialogState>, 'setInitialMagnet' | 'setIsAddMagnetOpen'> & Pick<ReturnType<typeof useAppShellState>, 'setInitialSourceUrl' | 'setInitialDescriptorUrl' | 'setBackgroundMetadataJob' | 'setActiveTab'>) {
  const seedrDownloadActive = Boolean(
    seedrNotice?.taskId != null && seedrNotice.status !== 'completed'
  );
  const openMetadataSelector = useCallback((source: string) => {
    const value = String(source || '').trim();
    if (!value) return;
    setInitialMagnet(value);
    setInitialSourceUrl('');
    setInitialDescriptorUrl('');
    setBackgroundMetadataJob(null);
    setIsAddMagnetOpen(true);
  }, []);
  const openAddMagnet = useCallback((source = '', sourceUrl = '', descriptorUrl = '') => {
    if (seedrDownloadActive) {
      setSeedrAddBlockedNotice(
        'A Seedr download is already in progress. Free Seedr accounts allow one parallel download. Wait for it to finish before adding another magnet link.'
      );
      setActiveTab('files');
      window.setTimeout(() => setSeedrAddBlockedNotice(null), 5000);
      return;
    }

    setInitialMagnet(source);
    setInitialSourceUrl(sourceUrl);
    setInitialDescriptorUrl(descriptorUrl);
    setIsAddMagnetOpen(true);
  }, [seedrDownloadActive]);

  return {
    seedrDownloadActive,
    openMetadataSelector,
    openAddMagnet,
  };
}
