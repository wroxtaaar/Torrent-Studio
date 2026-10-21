import { useEffect } from 'react';
import { TorrentSearchResult } from '../../../api/client.ts';
import { posterKeyFor } from '../posterUrls.ts';
import { useSearchInputState } from './useSearchInputState.ts';
import { usePrepareState } from './usePrepareState.ts';

export function useTorrentTitleBubble({ query, fullTorrentTitleFadeTimerRef, fullTorrentTitleHideTimerRef, setFullTorrentTitleKey, setFullTorrentTitle, setFullTorrentTitleFading }: Pick<ReturnType<typeof useSearchInputState>, 'query'> & Pick<ReturnType<typeof usePrepareState>, 'fullTorrentTitleFadeTimerRef' | 'fullTorrentTitleHideTimerRef' | 'setFullTorrentTitleKey' | 'setFullTorrentTitle' | 'setFullTorrentTitleFading'>) {
  const fullTorrentTitleFor = (result: TorrentSearchResult) => {
    // Indexer search pages can truncate the displayed title, while the magnet's
    // dn parameter normally carries the actual full torrent name.
    const magnet = String(result.magnetUrl || result.downloadUrl || '').trim();
    if (magnet) {
      try {
        const query = magnet.includes('?') ? magnet.slice(magnet.indexOf('?') + 1) : '';
        const params = new URLSearchParams(query);
        const displayName = params.get('dn')?.trim();
        if (displayName) return displayName;
      } catch {
        // Fall back to the API title below.
      }
    }

    return String(result.title || result.mediaTitle || '').trim();
  };
  const showFullTorrentTitleBubble = (result: TorrentSearchResult) => {
    if (fullTorrentTitleFadeTimerRef.current !== null) {
      window.clearTimeout(fullTorrentTitleFadeTimerRef.current);
    }
    if (fullTorrentTitleHideTimerRef.current !== null) {
      window.clearTimeout(fullTorrentTitleHideTimerRef.current);
    }

    const key = posterKeyFor(result);
    setFullTorrentTitleKey(key);
    setFullTorrentTitle(String(result.title || result.mediaTitle || '').trim());
    setFullTorrentTitleFading(false);

    fullTorrentTitleFadeTimerRef.current = window.setTimeout(() => {
      setFullTorrentTitleFading(true);
    }, 5550);

    fullTorrentTitleHideTimerRef.current = window.setTimeout(() => {
      setFullTorrentTitle(null);
      setFullTorrentTitleKey(null);
      setFullTorrentTitleFading(false);
    }, 6000);
  };
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
