import { reportNexStreamFailure } from '../nexstreamReports.ts';
import { fetchNexStreamEpisodeMetadata, nexStreamEpisodeCache, nexStreamEpisodeCacheKey, prefetchNexStreamEpisodeMetadata } from '../nexstream.ts';
import { writeLocalCache } from '../helpers.ts';
import { NexStreamTitle } from '../types.ts';
import { useNexStreamState } from './useNexStreamState.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { NEXSTREAM_RESOLVE_CACHE_KEY, NEXSTREAM_RESOLVE_CACHE_TTL_MS, NEXSTREAM_SEARCH_CACHE_KEY } from '../constants.ts';
import { readLocalCache } from '../localCache.ts';

export function useNexStreamFlow({ nexStreamSearchControllerRef, nexStreamSearchGenerationRef, setNexStreamSearchMode, setNexStreamLoadingTitle, setNexStreamLoading, setNexStreamError, setNexStreamResults, setNexStreamPlayer, setNexStreamEpisodePrefetchStatus, setNexStreamSeasons, setNexStreamEpisodes, setNexStreamSelectedSeason, setNexStreamEpisodesError, setNexStreamEpisodesLoading, setNexStreamEpisodePicker, setNexStreamResolvingId, error }: Pick<ReturnType<typeof useNexStreamState>, 'nexStreamSearchControllerRef' | 'nexStreamSearchGenerationRef' | 'setNexStreamSearchMode' | 'setNexStreamLoadingTitle' | 'setNexStreamLoading' | 'setNexStreamError' | 'setNexStreamResults' | 'setNexStreamPlayer' | 'setNexStreamEpisodePrefetchStatus' | 'setNexStreamSeasons' | 'setNexStreamEpisodes' | 'setNexStreamSelectedSeason' | 'setNexStreamEpisodesError' | 'setNexStreamEpisodesLoading' | 'setNexStreamEpisodePicker' | 'setNexStreamResolvingId'> & Pick<ReturnType<typeof useCatalogueNavigationState>, 'error'>) {
  const searchNexStreamTitles = async (titleQuery: string, mediaType: 'movie' | 'tv' = 'movie') => {
    nexStreamSearchControllerRef.current?.abort();
    const controller = new AbortController();
    nexStreamSearchControllerRef.current = controller;
    const generation = ++nexStreamSearchGenerationRef.current;
    setNexStreamSearchMode(mediaType);
    setNexStreamLoadingTitle(String(titleQuery || '').trim());
    setNexStreamLoading(true);
    setNexStreamError('');
    setNexStreamResults([]);
    setNexStreamPlayer(null);
    try {
      const types: Array<'movie' | 'tv'> = [mediaType];
      const cachedNexResults = readLocalCache<NexStreamTitle[]>(NEXSTREAM_SEARCH_CACHE_KEY, mediaType + ':' + String(titleQuery || '').trim().toLowerCase());
      if (cachedNexResults) {
        setNexStreamResults(cachedNexResults);
        if (mediaType === 'tv') {
          setNexStreamEpisodePrefetchStatus({});
          prefetchNexStreamEpisodeMetadata(cachedNexResults, (id, status) => {
            setNexStreamEpisodePrefetchStatus(previous => ({ ...previous, [String(id)]: status }));
          });
        }
        setNexStreamLoading(false);
        setNexStreamLoadingTitle('');
        return;
      }
      const responses = await Promise.allSettled(types.map(async type => {
        const params = new URLSearchParams({ query: titleQuery, type });
        const response = await fetch('/api/nexstream/search?' + params.toString(), {
          headers: { Accept: 'application/json' },
          credentials: 'same-origin',
          signal: controller.signal,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
          throw new Error(data.detail || 'NexStream title search failed.');
        }
        return (Array.isArray(data.results) ? data.results : []) as NexStreamTitle[];
      }));
      if (generation !== nexStreamSearchGenerationRef.current) return;
      const successfulResults = responses
        .filter((response): response is PromiseFulfilledResult<NexStreamTitle[]> => response.status === 'fulfilled')
        .flatMap(response => response.value);
      const failedSearches = responses.filter(response => response.status === 'rejected');
      const unique = new Map<string, NexStreamTitle>();
      for (const item of successfulResults) {
        unique.set(item.type + ':' + item.id, item);
      }
      const resolvedTitles = Array.from(unique.values());
      writeLocalCache(NEXSTREAM_SEARCH_CACHE_KEY, mediaType + ':' + String(titleQuery || '').trim().toLowerCase(), resolvedTitles);
      setNexStreamResults(resolvedTitles);
      // Fetch episode lists and thumbnails in the background, without delaying
      // the result cards. The first few TV cards are ready by the time a user
      // opens the episode picker; remaining cards are prefetched with 3 workers.
      if (mediaType === 'tv') {
        setNexStreamEpisodePrefetchStatus({});
        prefetchNexStreamEpisodeMetadata(resolvedTitles, (id, status) => {
          setNexStreamEpisodePrefetchStatus(previous => ({ ...previous, [String(id)]: status }));
        });
      }
      if (failedSearches.length === types.length) {
        const firstFailure = failedSearches[0] as PromiseRejectedResult;
        throw firstFailure.reason instanceof Error ? firstFailure.reason : new Error('TMDB title search failed.');
      }
      if (failedSearches.length > 0) {
        setNexStreamError('Some NexStream results could not be loaded. Try searching again to refresh them.');
      }
    } catch (error: any) {
      if (generation !== nexStreamSearchGenerationRef.current || error?.name === 'AbortError') return;
      setNexStreamError(String(error?.message || 'NexStream search is temporarily unavailable.'));
    } finally {
      if (generation === nexStreamSearchGenerationRef.current) {
        setNexStreamLoading(false);
        setNexStreamLoadingTitle('');
        if (nexStreamSearchControllerRef.current === controller) nexStreamSearchControllerRef.current = null;
      }
    }
  };
  const loadNexStreamEpisodes = async (item: NexStreamTitle, season: number) => {
    const cached = nexStreamEpisodeCache.get(nexStreamEpisodeCacheKey(item.id, season));
    if (cached) {
      setNexStreamSeasons(cached.seasons);
      setNexStreamEpisodes(cached.episodes);
      setNexStreamSelectedSeason(cached.selectedSeason);
      setNexStreamEpisodesError('');
      setNexStreamEpisodesLoading(false);
      return;
    }

    setNexStreamEpisodesLoading(true);
    setNexStreamEpisodesError('');
    try {
      const data = await fetchNexStreamEpisodeMetadata(item.id, season);
      setNexStreamSeasons(data.seasons);
      setNexStreamEpisodes(data.episodes);
      setNexStreamSelectedSeason(data.selectedSeason);
    } catch (error: any) {
      setNexStreamEpisodesError(String(error?.message || 'Could not load episode list.'));
      setNexStreamEpisodes([]);
    } finally {
      setNexStreamEpisodesLoading(false);
    }
  };
  const playWithNexStream = async (item: NexStreamTitle, chosenSeason?: number, chosenEpisode?: number, openInNewWindow = false) => {
    const popup = openInNewWindow ? window.open('about:blank', '_blank') : null;
    if (item.type === 'tv' && (chosenSeason === undefined || chosenEpisode === undefined)) {
      setNexStreamEpisodePicker(item);
      setNexStreamEpisodes([]);
      setNexStreamSeasons([]);
      setNexStreamEpisodesError('');
      await loadNexStreamEpisodes(item, 1);
      return;
    }
    const season = chosenSeason;
    const episode = chosenEpisode;

    const resolvingId = item.type + ':' + item.id;
    setNexStreamResolvingId(resolvingId);
    setNexStreamError('');
    try {
      // VidRift is an embed-only provider: its documented API is a TMDB-ID
      // iframe URL, not a server-side source-resolution endpoint.
      const tmdbId = Number(item.id);
      if (!Number.isInteger(tmdbId) || tmdbId <= 0) {
        throw new Error('This title has no valid TMDB ID for VidRift playback.');
      }
      const sourceUrl = item.type === 'tv'
        ? 'https://embed.vidrift.net/embed/tv/' + tmdbId + '/' + String(season) + '/' + String(episode)
        : 'https://embed.vidrift.net/embed/movie/' + tmdbId;
      if (popup) {
        popup.location.href = sourceUrl;
      } else if (openInNewWindow) {
        setNexStreamError('Your browser blocked the new window. Allow pop-ups and try again.');
      } else {
        setNexStreamPlayer({
          title: item.title,
          year: String(item.date || '').slice(0, 4),
          sourceName: 'VidRift',
          url: sourceUrl,
          type: item.type,
          tmdbId,
          season,
          episode,
        });
      }
      setNexStreamError('');
    } catch (error: any) {
      setNexStreamError(String(error?.message || 'Could not start VidRift playback.'));
    } finally {
      setNexStreamResolvingId(null);
    }
  };
  const playCatalogueTvWithNexStream = (show: {
    id: number | string;
    title: string;
    year?: number | null;
    releaseDate?: string;
    overview?: string;
    posterUrl?: string;
  }) => {
    // Catalogue IDs come directly from the cached TMDB TV catalogue. Do not
    // title-search these shows: pass the exact series ID into the episode flow.
    const tmdbId = Number(show.id);
    if (!Number.isInteger(tmdbId) || tmdbId <= 0) {
      setNexStreamSearchMode('tv');
      setNexStreamError('This TV catalogue entry has no valid TMDB series ID.');
      return;
    }

    // The episode picker is rendered inside the NexStream panel, which is
    // hidden unless a NexStream search mode is active. Activate the TV panel
    // before opening the picker so catalogue buttons work without title search.
    setNexStreamSearchMode('tv');
    setNexStreamResults([]);
    setNexStreamLoading(false);
    setNexStreamLoadingTitle('');
    setNexStreamError('');
    void playWithNexStream({
      id: tmdbId,
      title: show.title,
      date: show.releaseDate || (show.year ? String(show.year) : ''),
      overview: show.overview || '',
      poster: show.posterUrl || null,
      type: 'tv',
    });
  };

  return {
    searchNexStreamTitles,
    loadNexStreamEpisodes,
    playWithNexStream,
    playCatalogueTvWithNexStream,
  };
}
