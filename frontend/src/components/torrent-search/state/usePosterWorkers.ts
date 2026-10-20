import { TorrentSearchResult } from '../../../api/client.ts';
import { cachedPosterForTitle, posterTitleCacheKeys, savePosterTitleCache } from '../posterCache.ts';
import { lowQualityPosterUrl, posterKeyFor, posterResolveCandidateUrlsFor } from '../posterUrls.ts';
import { usePosterState } from './usePosterState.ts';

export function usePosterWorkers({ posterBackgroundGenerationRef, posterResolveCacheRef, posterBackgroundActiveRef, posterBackgroundQueueRef, posterBackgroundQueuedRef, posterBackgroundActiveKeysRef, posterLoadedRef, setPosterOverrides, posterBackgroundAttemptsRef, posterOverrides }: Pick<ReturnType<typeof usePosterState>, 'posterBackgroundGenerationRef' | 'posterResolveCacheRef' | 'posterBackgroundActiveRef' | 'posterBackgroundQueueRef' | 'posterBackgroundQueuedRef' | 'posterBackgroundActiveKeysRef' | 'posterLoadedRef' | 'setPosterOverrides' | 'posterBackgroundAttemptsRef' | 'posterOverrides'>) {
  const resolvePosterInBackground = async (url: string, generation: number) => {
    if (generation !== posterBackgroundGenerationRef.current) return '';

    const now = Date.now();
    const cached = posterResolveCacheRef.current.get(url);
    if (cached && cached.expiresAt > now) return cached.url;
    if (cached) posterResolveCacheRef.current.delete(url);

    try {
      const response = await fetch(url, {
        method: 'GET',
        credentials: 'include',
        cache: 'force-cache'
      });

      if (!response.ok) {
        if (response.status === 404) {
          posterResolveCacheRef.current.set(url, { url: '', expiresAt: Date.now() + 10 * 60 * 1000 });
        }
        return '';
      }

      const data = await response.json().catch(() => null);
      const resolved = String(data?.url || '').trim();
      if (resolved) {
        posterResolveCacheRef.current.set(url, { url: resolved, expiresAt: Date.now() + 6 * 60 * 60 * 1000 });
      } else {
        posterResolveCacheRef.current.set(url, { url: '', expiresAt: Date.now() + 10 * 60 * 1000 });
      }
      return resolved;
    } catch {
      // Network/server failures are not cached; allow transient failures to retry.
      return '';
    }
  };
  const startPosterBackgroundWorkers = () => {
    const generation = posterBackgroundGenerationRef.current;

    while (
      posterBackgroundActiveRef.current < 2 &&
      posterBackgroundQueueRef.current.length > 0
    ) {
      const job = posterBackgroundQueueRef.current.shift();
      if (!job) break;

      posterBackgroundQueuedRef.current.delete(job.key);
      posterBackgroundActiveRef.current += 1;
      posterBackgroundActiveKeysRef.current.add(job.key);

      void (async () => {
        try {
          if (generation !== posterBackgroundGenerationRef.current) return;

          const key = job.key;

          // A visible/loaded poster wins immediately; don't spend background
          // work resolving something the browser already has.
          if (posterLoadedRef.current.has(key)) return;

          const candidates = posterResolveCandidateUrlsFor(job.result);
          for (const candidate of candidates) {
            if (generation !== posterBackgroundGenerationRef.current) return;

            const resolved = await resolvePosterInBackground(candidate, generation);
            if (resolved) {
              for (const titleCacheKey of posterTitleCacheKeys(job.result)) {
                savePosterTitleCache(titleCacheKey, resolved);
              }
              setPosterOverrides(prev => (
                prev[key] === resolved ? prev : { ...prev, [key]: resolved }
              ));
              return;
            }

            await new Promise(resolve => window.setTimeout(resolve, 250));
          }

          // One delayed retry gives transient provider failures another chance.
          const attempts = posterBackgroundAttemptsRef.current.get(key) || 0;
          if (attempts < 1 && generation === posterBackgroundGenerationRef.current) {
            posterBackgroundAttemptsRef.current.set(key, attempts + 1);
            window.setTimeout(() => {
              if (generation !== posterBackgroundGenerationRef.current) return;
              if (posterLoadedRef.current.has(key)) return;
              if (posterBackgroundQueuedRef.current.has(key)) return;

              posterBackgroundQueuedRef.current.add(key);
              posterBackgroundQueueRef.current.push(job);
              startPosterBackgroundWorkers();
            }, 45000);
          }
        } finally {
          posterBackgroundActiveKeysRef.current.delete(job.key);
          posterBackgroundActiveRef.current = Math.max(
            0,
            posterBackgroundActiveRef.current - 1
          );

          if (generation === posterBackgroundGenerationRef.current) {
            startPosterBackgroundWorkers();
          }
        }
      })();
    }
  };
  const startPosterBackgroundSearch = (items: TorrentSearchResult[]) => {
    posterBackgroundGenerationRef.current += 1;
    posterBackgroundQueueRef.current = [];
    posterBackgroundQueuedRef.current.clear();
    posterBackgroundActiveKeysRef.current.clear();
    posterBackgroundAttemptsRef.current.clear();
    posterLoadedRef.current.clear();

    const generation = posterBackgroundGenerationRef.current;

    for (const result of items) {
      const key = posterKeyFor(result);
      if (!key || posterBackgroundQueuedRef.current.has(key) || posterBackgroundActiveKeysRef.current.has(key)) continue;

      // Reuse title/year artwork across different torrent releases and searches.
      const cachedPoster = cachedPosterForTitle(result);
      if (cachedPoster) {
        setPosterOverrides(prev => (
          prev[key] === cachedPoster ? prev : { ...prev, [key]: cachedPoster }
        ));
        continue;
      }

      posterBackgroundQueuedRef.current.add(key);
      posterBackgroundQueueRef.current.push({ key, result });
    }

    // Start immediately after results arrive, but never await this work.
    if (generation === posterBackgroundGenerationRef.current) {
      startPosterBackgroundWorkers();
    }
  };
  // Append poster jobs without resetting the queue (used when more catalogue pages stream in).
  const enqueuePosterBackgroundJobs = (items: TorrentSearchResult[]) => {
    for (const result of items) {
      const key = posterKeyFor(result);
      if (!key || posterBackgroundQueuedRef.current.has(key)) continue;
      const cachedPoster = cachedPosterForTitle(result);
      if (cachedPoster) {
        setPosterOverrides(prev => (prev[key] === cachedPoster ? prev : { ...prev, [key]: cachedPoster }));
        continue;
      }
      posterBackgroundQueuedRef.current.add(key);
      posterBackgroundQueueRef.current.push({ key, result });
    }
    startPosterBackgroundWorkers();
  };
  const posterUrlFor = (result: TorrentSearchResult) =>
    lowQualityPosterUrl(posterOverrides[posterKeyFor(result)] || '');

  return {
    startPosterBackgroundWorkers,
    startPosterBackgroundSearch,
    enqueuePosterBackgroundJobs,
    posterUrlFor,
  };
}
