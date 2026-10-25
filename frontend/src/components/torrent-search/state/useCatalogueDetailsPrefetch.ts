import { useEffect } from 'react';
import { api } from '../../../api/client.ts';
import { episodeSeriesTitle, imdbRatingKey, imdbRatingQueryTitle, normalizeSavedOttTitle } from '../grouping.ts';
import { useSearchMetadataState } from './useSearchMetadataState.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useGroupedResults } from './useGroupedResults.ts';
import { useVisibleMovieCatalogue } from './useVisibleMovieCatalogue.ts';

export function useCatalogueDetailsPrefetch({ franchiseGridPage, franchiseGridPageSize, movieCatalogue, groupedResults, searchMetadata, imdbRatingsByKey, imdbRatingRequestedRef, imdbRetryCountRef, setImdbRetryTick, imdbInFlightRef, setImdbRatingsByKey, imdbRetryTick, visibleMovieCatalogueItems, tvItems, rateAllGroups }: { rateAllGroups: boolean; tvItems: Array<{ title: string; year?: number | string | null; tmdbId?: number }> } & Pick<ReturnType<typeof useCatalogueNavigationState>, 'franchiseGridPage' | 'franchiseGridPageSize' | 'movieCatalogue'> & Pick<ReturnType<typeof useGroupedResults>, 'groupedResults'> & Pick<ReturnType<typeof useSearchMetadataState>, 'searchMetadata' | 'imdbRatingsByKey' | 'imdbRatingRequestedRef' | 'imdbRetryCountRef' | 'setImdbRetryTick' | 'imdbInFlightRef' | 'setImdbRatingsByKey' | 'imdbRetryTick'> & Pick<ReturnType<typeof useVisibleMovieCatalogue>, 'visibleMovieCatalogueItems'>) {
  // IMDb ratings are fetched independently after cards have rendered.
  // Movies use OMDb's movie type; show metadata uses OMDb's series type.
  useEffect(() => {
    // Synopsis/IMDb are cheap cached reads: load them with the initial cards, not after posters.
    const visibleStart = (franchiseGridPage - 1) * franchiseGridPageSize;
    const visibleGroupTitles = new Set(groupedResults
      .slice(visibleStart, visibleStart + franchiseGridPageSize)
      .map(group => normalizeSavedOttTitle(episodeSeriesTitle(group.title) || group.title)));
    const visibleSearchMetadata = searchMetadata.filter(item =>
      visibleGroupTitles.has(normalizeSavedOttTitle(item.title))
    );
    const visibleCatalogueItems = visibleMovieCatalogueItems.slice(
      (franchiseGridPage - 1) * franchiseGridPageSize,
      franchiseGridPage * franchiseGridPageSize,
    );
    const cachedCatalogueRatingKeys = new Set(
      visibleCatalogueItems
        .filter(item => item.imdbRatingStatus === 'found' || item.imdbRatingStatus === 'not_found')
        .map(item => imdbRatingKey(item.title, item.year)),
    );
    const candidates = [
      ...visibleCatalogueItems.flatMap(item => {
        const candidate = {
          title: String(item.title || '').trim(),
          year: item.year,
          tmdbId: Number(item.tmdbId || item.id) || undefined,
          mediaType: 'movie' as const,
        };
        // IMDb classifies One Last Kill as a TV special, while TMDB serves it
        // in the movie catalogue. Query both OMDb types so its IMDb rating is found.
        return /punisher.*one last kill|one last kill.*punisher/i.test(candidate.title)
          ? [candidate, { ...candidate, mediaType: 'tv' as const }]
          : [candidate];
      }),
      ...visibleSearchMetadata.map(item => ({
        title: String(item.title || '').trim(),
        year: item.year,
        tmdbId: Number(item.tmdbId || item.id) || undefined,
        mediaType: item.mediaType === 'tv' ? 'tv' as const : 'movie' as const,
      })),
      // Cards whose title has no saved metadata match still get a rating: look them up by
      // their own title/year, plus the TMDB id the catalogue row already carries.
      // (rateAllGroups: a rating sort needs every loaded title rated, not only the visible page.)
      ...(rateAllGroups ? groupedResults : groupedResults
        .slice((franchiseGridPage - 1) * franchiseGridPageSize, franchiseGridPage * franchiseGridPageSize))
        .filter(group => !episodeSeriesTitle(group.title))
        .map(group => {
          const withId = group.variants.find(variant => Number((variant as any).tmdbId) > 0) as any;
          return {
            title: group.title.replace(/\s*\(?(?:19|20)\d{2}\)?\s*$/, '').trim(),
            year: group.year,
            tmdbId: Number(withId?.tmdbId) || undefined,
            mediaType: 'movie' as const,
          };
        }),
      // Web series / anime cards (all sections): look up their IMDb rating by TMDB TV id.
      ...tvItems.map(item => ({
        title: String(item.title || '').trim(),
        year: item.year,
        tmdbId: item.tmdbId,
        mediaType: 'tv' as const,
      })),
    ].filter(item => item.title);

    const pending = new Map<string, { title: string; mediaType: 'movie' | 'tv'; tmdbId?: number }>();
    for (const item of candidates) {
      const key = imdbRatingKey(item.title, item.year, item.mediaType);
      const cachedRating = imdbRatingsByKey[key];
      if (cachedCatalogueRatingKeys.has(key)) {
        imdbRatingRequestedRef.current.add(key);
        continue;
      }
      if (cachedRating && ['found', 'not_found'].includes(cachedRating.status)) {
        imdbRatingRequestedRef.current.add(key);
        continue;
      }
      if (!key.startsWith('movie||') && !key.startsWith('tv||') && !imdbRatingRequestedRef.current.has(key)) {
        pending.set(key, {
          title: imdbRatingQueryTitle(item.title, item.year),
          mediaType: item.mediaType,
          tmdbId: item.tmdbId,
        });
      }
    }
    const requests = [...pending.entries()].slice(0, 80);
    if (!requests.length) return;
    const hasMorePending = pending.size > requests.length;
    requests.forEach(([key]) => imdbRatingRequestedRef.current.add(key));

    const requestItems = requests.map(([, item]) => item);
    const scheduleImdbRetry = () => {
      // Bounded so a missing OMDb key doesn't poll forever.
      if (imdbRetryCountRef.current >= 5) return;
      imdbRetryCountRef.current += 1;
      window.setTimeout(() => setImdbRetryTick(tick => tick + 1), 20000);
    };
    imdbInFlightRef.current += 1;
    void api.getImdbRatings(
      requestItems.map(item => item.title),
      requestItems.map(item => item.mediaType),
      requestItems.map(item => item.tmdbId),
    ).then(response => {
      const ratings = Array.isArray(response.results) ? response.results : [];
      let needsRetry = false;
      // More than one batch of titles is waiting: continue with the next batch right away.
      if (hasMorePending) setImdbRetryTick(tick => tick + 1);
      setImdbRatingsByKey(previous => {
        const next = { ...previous };
        for (const rating of ratings) {
          // Transient failures (rate limit / upstream error) are not answers:
          // don't store them and let the lookup be retried below.
          if (rating.status === 'rate_limited' || rating.status === 'unavailable') {
            needsRetry = true;
            continue;
          }
          const mediaType = rating.mediaType === 'tv' ? 'tv' : 'movie';
          const queryKey = imdbRatingKey(rating.query || rating.title, undefined, mediaType);
          const canonicalKey = imdbRatingKey(rating.title, rating.year, mediaType);
          next[queryKey] = rating;
          next[canonicalKey] = rating;
        }
        return next;
      });
      if (needsRetry) {
        // Forget keys that never got a real answer, then re-run this effect later.
        requests.forEach(([key]) => {
          const done = ratings.some(rating => {
            if (rating.status === 'rate_limited' || rating.status === 'unavailable') return false;
            const mediaType = rating.mediaType === 'tv' ? 'tv' : 'movie';
            return imdbRatingKey(rating.query || rating.title, undefined, mediaType) === key;
          });
          if (!done) imdbRatingRequestedRef.current.delete(key);
        });
        scheduleImdbRetry();
      }
    }).catch(() => {
      // Ratings are optional metadata; don't interrupt torrent/catalogue rendering.
      requests.forEach(([key]) => imdbRatingRequestedRef.current.delete(key));
      scheduleImdbRetry();
    }).finally(() => {
      imdbInFlightRef.current = Math.max(0, imdbInFlightRef.current - 1);
    });
  }, [movieCatalogue?.results, searchMetadata, groupedResults, imdbRatingsByKey, imdbRetryTick, franchiseGridPage, tvItems, rateAllGroups]);

}
