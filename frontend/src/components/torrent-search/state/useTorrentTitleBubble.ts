import { useEffect } from 'react';
import { useSearchInputState } from './useSearchInputState.ts';
import { usePrepareState } from './usePrepareState.ts';

export function useTorrentTitleBubble({ query, fullTorrentTitleFadeTimerRef, fullTorrentTitleHideTimerRef, setFullTorrentTitleKey, setFullTorrentTitle, setFullTorrentTitleFading }: Pick<ReturnType<typeof useSearchInputState>, 'query'> & Pick<ReturnType<typeof usePrepareState>, 'fullTorrentTitleFadeTimerRef' | 'fullTorrentTitleHideTimerRef' | 'setFullTorrentTitleKey' | 'setFullTorrentTitle' | 'setFullTorrentTitleFading'>) {
  useEffect(() => {
    return () => {
      if (fullTorrentTitleFadeTimerRef.current !== null) {
        window.clearTimeout(fullTorrentTitleFadeTimerRef.current);
      }
      if (fullTorrentTitleHideTimerRef.current !== null) {
        window.clearTimeout(fullTorrentTitleHideTimerRef.current);
      }
    };
  }, []);

}
