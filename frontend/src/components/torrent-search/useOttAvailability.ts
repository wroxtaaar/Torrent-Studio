import { useRef, useState } from 'react';
import { api, MovieCatalogueItem } from '../../api/client.ts';
import { savedOttAvailabilityForMovie } from './ottProviders.ts';
import { MovieOttCardState } from './nexstream.ts';

export function useOttAvailability() {
  const [ottAvailability, setOttAvailability] = useState<Record<string, MovieOttCardState>>({});

  const ottAvailabilityRef = useRef<Record<string, MovieOttCardState>>({});

  const ottQueueRef = useRef<string[]>([]);

  const ottQueuedIdsRef = useRef(new Set<string>());

  const ottActiveWorkersRef = useRef(0);

  const ottLookupGenerationRef = useRef(0);

  const ottQueuePumpRef = useRef<() => void>(() => {});

  // Movies seen by the card grid, live lookups already made this session, and
  // failed-lookup retry counts. Missing streaming info is re-checked automatically.
  const ottKnownMoviesRef = useRef(new Map<string, MovieCatalogueItem>());

  const ottLiveCheckedRef = useRef(new Set<string>());

  const ottRetryAttemptsRef = useRef(new Map<string, number>());

  const ottRetryTimerRef = useRef<number | null>(null);

  const setOttState = (movieId: string, state: MovieOttCardState) => {
    const next = { ...ottAvailabilityRef.current, [movieId]: state };
    ottAvailabilityRef.current = next;
    setOttAvailability(next);
  };

  // Failed lookups are retried automatically (bounded) instead of staying on an error forever.
  const scheduleOttRetry = () => {
    if (ottRetryTimerRef.current !== null) return;
    const generation = ottLookupGenerationRef.current;
    ottRetryTimerRef.current = window.setTimeout(() => {
      ottRetryTimerRef.current = null;
      if (generation !== ottLookupGenerationRef.current) return;
      const retry = [...ottKnownMoviesRef.current.values()].filter(movie => {
        const id = String(movie.id);
        const state = ottAvailabilityRef.current[id];
        const hasData = !!state && state.status !== 'error' && state.status !== 'loading';
        return !movie.sectionCacheRecord && !hasData && (ottRetryAttemptsRef.current.get(id) || 0) < 5;
      });
      if (retry.length) queueOttLookups(retry, true);
    }, 30000);
  };

  // Limit upstream load. The backend caches provider hits for 24 hours and misses for 6 hours,
  // and coalesces simultaneous requests, so repeated visitors reuse the same result.
  const pumpOttQueue = () => {
    while (ottActiveWorkersRef.current < 3 && ottQueueRef.current.length > 0) {
      const movieId = ottQueueRef.current.shift();
      if (!movieId) continue;
      ottActiveWorkersRef.current += 1;
      const lookupGeneration = ottLookupGenerationRef.current;
      void (async () => {
        try {
          const availability = await api.getMovieOttAvailability(Number(movieId), 'IN');
          if (lookupGeneration === ottLookupGenerationRef.current) {
            const current = ottAvailabilityRef.current[movieId];
            const providerCount = (value: any) =>
              (Array.isArray(value?.streamingProviders) ? value.streamingProviders.length : 0) +
              (Array.isArray(value?.rentProviders) ? value.rentProviders.length : 0) +
              (Array.isArray(value?.buyProviders) ? value.buyProviders.length : 0);
            // A page-specific refresh can return an empty/incomplete response.
            // Never let it erase provider names already hydrated from the saved catalogue.
            if (providerCount(availability) === 0 && providerCount(current) > 0) {
              setOttState(movieId, current);
            } else {
              setOttState(movieId, availability);
            }
          }
        } catch (error: any) {
          if (lookupGeneration === ottLookupGenerationRef.current) {
            const current = ottAvailabilityRef.current[movieId];
            // Keep saved/cached provider info on screen if the live re-check fails.
            if (!current || current.status === 'loading' || current.status === 'error') {
              setOttState(movieId, {
                status: 'error',
                message: String(error?.message || 'OTT availability could not be checked.'),
              });
            }
            scheduleOttRetry();
          }
        } finally {
          if (lookupGeneration === ottLookupGenerationRef.current) {
            ottQueuedIdsRef.current.delete(movieId);
          }
          ottActiveWorkersRef.current -= 1;
          ottQueuePumpRef.current();
        }
      })();
    }
  };

  ottQueuePumpRef.current = pumpOttQueue;

  const queueOttLookups = (movies: MovieCatalogueItem[], retryErrors = false) => {
    const next = { ...ottAvailabilityRef.current };
    let changed = false;
    const hasProviders = (state?: MovieOttCardState) => {
      const value = state as any;
      return !!value && (
        (value.streamingProviders?.length || 0) + (value.rentProviders?.length || 0) + (value.buyProviders?.length || 0) > 0
      );
    };
    const recheckAfterMs = 6 * 60 * 60 * 1000;
    for (const movie of movies) {
      const movieId = String(movie.id);
      if (!/^\d+$/.test(movieId)) continue;
      ottKnownMoviesRef.current.set(movieId, movie);
      const existing = next[movieId];
      const isRetry = retryErrors && (!existing || existing.status === 'error' || existing.status === 'loading');

      // Hydrate saved provider data before checking whether a live lookup is
      // already queued. This matters when revisiting a page while a request for
      // the same title is still in flight.
      let state = existing && !isRetry ? existing : undefined;
      const saved = movie.ottAvailability;
      if (!state) {
        state = savedOttAvailabilityForMovie(movie);
      }
      if (state) {
        next[movieId] = state;
        changed = true;
      }

      if (movie.sectionCacheRecord) {
        ottLiveCheckedRef.current.add(movieId);
        continue;
      }

      if (ottQueuedIdsRef.current.has(movieId)) continue;
      if (existing && !isRetry && ottLiveCheckedRef.current.has(movieId)) continue;

      const checkedMs = Date.parse(String((state as any)?.checkedAt || ''));
      const savedIsFreshMiss = !!state && state.status !== 'loading' && state.status !== 'error' &&
        !hasProviders(state) && !(state as any).incomplete && !(saved as any)?.incomplete && Number.isFinite(checkedMs) && Date.now() - checkedMs < recheckAfterMs;
      const needsLive = isRetry || !state || state.status === 'loading' || state.status === 'error' ||
        (!hasProviders(state) && !savedIsFreshMiss);
      if (!needsLive) {
        ottLiveCheckedRef.current.add(movieId);
        continue;
      }
      const attempts = ottRetryAttemptsRef.current.get(movieId) || 0;
      if (isRetry && attempts >= 5) continue;
      ottRetryAttemptsRef.current.set(movieId, attempts + 1);
      ottLiveCheckedRef.current.add(movieId);
      ottQueuedIdsRef.current.add(movieId);
      ottQueueRef.current.push(movieId);
      if (!state) {
        next[movieId] = { status: 'loading' };
        changed = true;
      }
    }
    if (changed) {
      ottAvailabilityRef.current = next;
      setOttAvailability(next);
    }
    ottQueuePumpRef.current();
  };

  const ottAvailabilityForMovie = (movie: MovieCatalogueItem): MovieOttCardState | undefined => {
    const current = ottAvailability[String(movie.id)];
    if (!current || current.status === 'loading' || current.status === 'error') {
      return savedOttAvailabilityForMovie(movie) || current;
    }
    return current;
  };

  return { ottAvailability, setOttAvailability, ottAvailabilityRef, ottQueueRef, ottQueuedIdsRef, ottLookupGenerationRef, ottLiveCheckedRef, ottRetryAttemptsRef, queueOttLookups, ottAvailabilityForMovie };
}
