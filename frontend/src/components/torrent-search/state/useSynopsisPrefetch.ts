import { useEffect } from 'react';
import { api } from '../../../api/client.ts';
import { episodeSeriesTitle, mergeSearchMetadataItems, normalizeSavedOttTitle, searchMetadataForGroup } from '../grouping.ts';
import { useSearchMetadataState } from './useSearchMetadataState.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useGroupedResults } from './useGroupedResults.ts';
import { franchiseCatalogueSection } from '../../../api/sectionCache.ts';

export function useSynopsisPrefetch({ franchiseGridPage, franchiseGridPageSize, groupedResults, searchMetadata, setSearchMetadata, tvMetadataRequestedRef, activeFranchiseSearchMode }: Pick<ReturnType<typeof useCatalogueNavigationState>, 'franchiseGridPage' | 'franchiseGridPageSize' | 'activeFranchiseSearchMode'> & Pick<ReturnType<typeof useGroupedResults>, 'groupedResults'> & Pick<ReturnType<typeof useSearchMetadataState>, 'searchMetadata' | 'setSearchMetadata' | 'tvMetadataRequestedRef'>) {
  // Search cards can come from the prebuilt Marvel/DC/Bollywood/Hollywood
  // catalogues and therefore aren't necessarily related to the text the user
  // typed. Merge their per-title metadata from the persistent VPS JSON rather
  // than relying only on a single broad TMDB search for the original query.
  useEffect(() => {
    if (activeFranchiseSearchMode && franchiseCatalogueSection(activeFranchiseSearchMode)) return;
    // Synopsis/IMDb are cheap cached reads: load them with the initial cards, not after posters.
    const pageStart = (franchiseGridPage - 1) * franchiseGridPageSize;
    const visibleGroups = groupedResults.slice(pageStart, pageStart + franchiseGridPageSize);
    const titles = Array.from(new Set(visibleGroups
      .map(group => {
        if (searchMetadataForGroup(group, searchMetadata)) return '';
        const title = String(group.title || '').trim();
        const year = String(group.year || '').trim();
        // group.title can already include its release year (parsed from the
        // torrent title), so never append the same year twice.
        const alreadyHasYear = /\(?((?:19|20)\d{2})\)?\s*$/.test(title);
        return title ? title + (year && !alreadyHasYear ? ' (' + year + ')' : '') : '';
      })
      .filter(Boolean)));
    if (!titles.length) return;

    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void api.searchMediaMetadataBatch(titles, controller.signal).then(response => {
        if (controller.signal.aborted) return;
        const additions = Array.isArray(response.results) ? response.results : [];
        if (additions.length) {
          setSearchMetadata(previous => mergeSearchMetadataItems(previous, additions));
        }
      }).catch(() => {
        // This is a supplementary local-cache lookup; keep the live TMDB metadata
        // response and torrent results working if a VPS cache file is unavailable.
      });
    }, 250);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [groupedResults, franchiseGridPage, searchMetadata, activeFranchiseSearchMode]);
  // Search TMDB by show name for episode-shaped torrent titles. A broad search for
  // the episode name (e.g. "Escape Plan") cannot resolve "The Rookie" or "NCIS: New Orleans".
  useEffect(() => {
    if (activeFranchiseSearchMode && franchiseCatalogueSection(activeFranchiseSearchMode)) return;
    // Synopsis/IMDb are cheap cached reads: load them with the initial cards, not after posters.
    const pageStart = (franchiseGridPage - 1) * franchiseGridPageSize;
    const visibleGroups = groupedResults.slice(pageStart, pageStart + franchiseGridPageSize);
    const discoveredSeriesTitles = Array.from(new Set(visibleGroups
      .map(group => episodeSeriesTitle(group.title))
      .filter((title): title is string => Boolean(title))))
      .slice(0, 12);
    const seriesTitles = discoveredSeriesTitles.filter(title => {
      const key = normalizeSavedOttTitle(title);
      const hasCachedMetadata = searchMetadata.some(item =>
        item.mediaType === 'tv' && normalizeSavedOttTitle(item.title) === key
      );
      if (!key || hasCachedMetadata || tvMetadataRequestedRef.current.has(key)) return false;
      tvMetadataRequestedRef.current.add(key);
      return true;
    });
    if (!seriesTitles.length) return;

    const controller = new AbortController();
    void Promise.all(seriesTitles.map(async title => {
      try {
        const response = await api.searchMediaMetadata(title, controller.signal);
        const normalized = normalizeSavedOttTitle(title);
        return (response.results || []).filter(item =>
          item.mediaType === 'tv' && normalizeSavedOttTitle(item.title) === normalized
        ).slice(0, 1);
      } catch {
        // Optional TV metadata must never block or fail torrent search.
        return [];
      }
    })).then(groups => {
      if (controller.signal.aborted) return;
      const additions = groups.flat();
      if (additions.length) {
        setSearchMetadata(previous => mergeSearchMetadataItems(previous, additions));
      }
    });

    return () => controller.abort();
  }, [groupedResults, franchiseGridPage, searchMetadata, activeFranchiseSearchMode]);

}
