import { useEffect } from 'react';
import { setHighQualityPostersReady } from '../../MovieCards.tsx';
import { useSearchMetadataState } from './useSearchMetadataState.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';

export function usePosterReadyGate({ posterFirstPageReady, activeFranchiseSearchMode, imdbInFlightRef }: Pick<ReturnType<typeof useCatalogueNavigationState>, 'posterFirstPageReady' | 'activeFranchiseSearchMode'> & Pick<ReturnType<typeof useSearchMetadataState>, 'imdbInFlightRef'>) {
  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;
    const startedAt = Date.now();
    let settledSince: number | null = null;

    // Keep every card on the low-resolution poster until the visible page has
    // loaded its thumbnails; only then let the idle queue consider upgrades.
    if (!posterFirstPageReady) return;

    const checkPageDetails = () => {
      if (cancelled) return;
      // OTT availability is useful card content, but it must not hold back idle
      // poster upgrades while the provider service is slow.
      const metadataSettled = activeFranchiseSearchMode || imdbInFlightRef.current === 0;
      const now = Date.now();

      if (metadataSettled) {
        if (settledSince == null) settledSince = now;
        // Allow state updates from the last metadata response to paint before
        // opening the shared high-resolution poster queue.
        if (now - settledSince >= 650) {
          setHighQualityPostersReady(true);
          return;
        }
      } else {
        settledSince = null;
      }

      // IMDb can be unavailable upstream. Do not leave thumbnails permanently
      // low-res: after 25 seconds, release the page as a whole.
      if (now - startedAt >= 25000) {
        setHighQualityPostersReady(true);
        return;
      }
      timer = window.setTimeout(checkPageDetails, 200);
    };

    timer = window.setTimeout(checkPageDetails, 200);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [posterFirstPageReady, activeFranchiseSearchMode]);

}
