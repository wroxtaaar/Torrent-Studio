import { useEffect, useLayoutEffect } from 'react';
import { setHighQualityPostersReady } from '../../MovieCards.tsx';
import { posterKeyFor } from '../posterUrls.ts';
import { useMoviePreviewState } from './useMoviePreviewState.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { usePosterState } from './usePosterState.ts';
import { usePosterWorkers } from './usePosterWorkers.ts';
import { useMovieTorrentSearch } from './useMovieTorrentSearch.ts';
import { useGroupedResults } from './useGroupedResults.ts';
import { franchiseCatalogueSection } from '../../../api/sectionCache.ts';

export function usePosterEffects({ groupedResults, franchiseGridPage, franchiseGridPageSize, posterFirstPageReadyRef, setPosterFirstPageReady, previousPosterPageRef, movieCatalogue, posterFirstPageReady, queueOttLookups, activeFranchiseSearchMode, posterBackgroundGenerationRef, posterBackgroundQueueRef, posterBackgroundQueuedRef, posterBackgroundAttemptsRef, posterBackgroundActiveKeysRef, enqueuePosterBackgroundJobs, pendingPosterAction, setPendingPosterAction, prepareClickIntentRef, prepareTraceIdRef, setExpandedSearchGroupKey, searchMovieTorrents }: Pick<ReturnType<typeof useGroupedResults>, 'groupedResults'> & Pick<ReturnType<typeof useCatalogueNavigationState>, 'franchiseGridPage' | 'franchiseGridPageSize' | 'posterFirstPageReadyRef' | 'setPosterFirstPageReady' | 'previousPosterPageRef' | 'movieCatalogue' | 'posterFirstPageReady' | 'queueOttLookups' | 'activeFranchiseSearchMode'> & Pick<ReturnType<typeof usePosterState>, 'posterBackgroundGenerationRef' | 'posterBackgroundQueueRef' | 'posterBackgroundQueuedRef' | 'posterBackgroundAttemptsRef' | 'posterBackgroundActiveKeysRef'> & Pick<ReturnType<typeof usePosterWorkers>, 'enqueuePosterBackgroundJobs'> & Pick<ReturnType<typeof useMoviePreviewState>, 'pendingPosterAction' | 'setPendingPosterAction' | 'prepareClickIntentRef' | 'prepareTraceIdRef' | 'setExpandedSearchGroupKey'> & Pick<ReturnType<typeof useMovieTorrentSearch>, 'searchMovieTorrents'>) {
  // Staged loading: every new result set starts with low-bandwidth thumbnails.
  // High-quality upgrades remain paused until the visible page's initial details settle.
  // Page-by-page staging restarts low-resolution posters before background upgrades.
  const currentPagePosterKeys = () => new Set(
    groupedResults
      .slice((franchiseGridPage - 1) * franchiseGridPageSize, franchiseGridPage * franchiseGridPageSize)
      .map(group => posterKeyFor(group.posterResult))
  );
  useLayoutEffect(() => {
    // Close high-resolution upgrades before the next page paints. Cancel queued
    // artwork work for the old page so only the newly visible page keeps loading.
    posterFirstPageReadyRef.current = false;
    setPosterFirstPageReady(false);
    setHighQualityPostersReady(false);
    if (previousPosterPageRef.current !== franchiseGridPage) {
      previousPosterPageRef.current = franchiseGridPage;
      posterBackgroundGenerationRef.current += 1;
      posterBackgroundQueueRef.current = [];
      posterBackgroundQueuedRef.current.clear();
      posterBackgroundAttemptsRef.current.clear();
      posterBackgroundActiveKeysRef.current.clear();
    }
    const visibleKeys = currentPagePosterKeys();
    posterBackgroundQueueRef.current = posterBackgroundQueueRef.current.filter(job => visibleKeys.has(job.key));
  }, [movieCatalogue, groupedResults, franchiseGridPage]);
  useEffect(() => {
    if (activeFranchiseSearchMode && franchiseCatalogueSection(activeFranchiseSearchMode)) return;
    // Resolve poster sources only for cards on the page currently being viewed.
    // Page 2+ artwork waits until the user navigates to that page.
    const start = (franchiseGridPage - 1) * franchiseGridPageSize;
    const visibleItems = groupedResults
      .slice(start, start + franchiseGridPageSize)
      .flatMap(group => group.variants);
    if (visibleItems.length > 0) enqueuePosterBackgroundJobs(visibleItems);
  }, [groupedResults, franchiseGridPage, activeFranchiseSearchMode]);
  useEffect(() => {
    let posterCheckTimer: number | undefined;
    let cancelled = false;
    const startedAt = Date.now();
    const checkVisiblePosterLoads = () => {
      if (cancelled) return;
      const slots = Array.from(document.querySelectorAll<HTMLElement>('[data-movie-poster-slot="true"]'))
        .filter(slot => slot.isConnected && slot.getClientRects().length > 0);
      const settled = slots.length === 0 || slots.every(slot => {
        const image = slot.querySelector<HTMLImageElement>('img[data-movie-poster-stage="true"]');
        if (!image) return slot.dataset.posterWaiting !== 'true';
        return ['low-loaded', 'high-loaded', 'low-failed'].includes(String(image.dataset.posterQuality || ''));
      });
      // A broken/unreachable poster must not block metadata forever; give the
      // visible thumbnails up to eight seconds before continuing with fallbacks.
      if (settled || Date.now() - startedAt >= 8000) {
        posterFirstPageReadyRef.current = true;
        setPosterFirstPageReady(true);
        return;
      }
      posterCheckTimer = window.setTimeout(checkVisiblePosterLoads, 80);
    };
    posterCheckTimer = window.setTimeout(checkVisiblePosterLoads, 0);
    return () => {
      cancelled = true;
      if (posterCheckTimer !== undefined) window.clearTimeout(posterCheckTimer);
    };
  }, [movieCatalogue, groupedResults, franchiseGridPage]);
  useEffect(() => {
    if (!pendingPosterAction) return;
    if (pendingPosterAction.kind === 'catalogue') {
      if (
        !movieCatalogue ||
        movieCatalogue.catalogue !== pendingPosterAction.catalogue ||
        movieCatalogue.page !== pendingPosterAction.page
      ) {
        setPendingPosterAction(null);
        prepareClickIntentRef.current = false;
        prepareTraceIdRef.current = null;
        return;
      }
    } else if (
      franchiseGridPage !== pendingPosterAction.page ||
      !groupedResults.some(group => group.key === pendingPosterAction.groupKey)
    ) {
      setPendingPosterAction(null);
      return;
    }
    if (!posterFirstPageReady) return;

    const action = pendingPosterAction;
    setPendingPosterAction(null);
    if (action.kind === 'catalogue') {
      void searchMovieTorrents(action.movie);
    } else {
      setExpandedSearchGroupKey(action.groupKey);
    }
  }, [pendingPosterAction, posterFirstPageReady, movieCatalogue, groupedResults, franchiseGridPage]);
  useEffect(() => {
    if (!movieCatalogue?.results?.length || movieCatalogue.curatedOrder) return;
    queueOttLookups(movieCatalogue.results.slice(0, franchiseGridPageSize));
  }, [movieCatalogue?.results, movieCatalogue?.curatedOrder]);

}
