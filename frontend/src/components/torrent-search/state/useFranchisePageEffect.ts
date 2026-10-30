import { useEffect } from 'react';
import { api, TorrentSearchResult } from '../../../api/client.ts';
import { episodeSeriesTitle, normalizeSavedOttTitle } from '../grouping.ts';
import { normalizeSavedOttProviders, uniqueOttProviders } from '../ottProviders.ts';
import { franchiseCatalogueSection } from '../../../api/sectionCache.ts';
import { useSearchMetadataState } from './useSearchMetadataState.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useGroupedResults } from './useGroupedResults.ts';

export function useFranchisePageEffect({ activeFranchiseSearchMode, franchiseGridPage, franchiseGridPageSize, error, groupedResults, searchAvailabilityByGroup, setSearchAvailabilityByGroup }: Pick<ReturnType<typeof useCatalogueNavigationState>, 'activeFranchiseSearchMode' | 'franchiseGridPage' | 'franchiseGridPageSize' | 'error'> & Pick<ReturnType<typeof useGroupedResults>, 'groupedResults'> & Pick<ReturnType<typeof useSearchMetadataState>, 'searchAvailabilityByGroup' | 'setSearchAvailabilityByGroup'>) {
  // Every cached catalogue page needs its own saved streaming-provider hydration.
  // The initial search only enriches page 1; without this page-scoped pass, later
  // pages render cards before their persisted OTT data is ever attached.
  useEffect(() => {
    if (!activeFranchiseSearchMode) return;
    const start = (franchiseGridPage - 1) * franchiseGridPageSize;
    const pageGroups = groupedResults
      .slice(start, start + franchiseGridPageSize)
      .filter(group => !searchAvailabilityByGroup[group.key]);
    if (!pageGroups.length) return;
    const titles = Array.from(new Set(pageGroups.map(group => String(group.title || '').trim()).filter(Boolean)));
    if (!titles.length) return;

    if (franchiseCatalogueSection(activeFranchiseSearchMode)) {
      setSearchAvailabilityByGroup(previous => {
        const next = { ...previous };
        for (const group of pageGroups) {
          const row = group.variants.find(variant =>
            Boolean(variant.ottAvailability || variant.streamingProviders?.length)
          );
          const saved = row?.ottAvailability;
          const region = String(saved?.region || 'IN');
          const providers = uniqueOttProviders([
            ...normalizeSavedOttProviders(saved?.streamingProviders || [], 'streaming', region),
            ...normalizeSavedOttProviders(saved?.rentProviders || [], 'rent', region),
            ...normalizeSavedOttProviders(saved?.buyProviders || [], 'buy', region),
            ...normalizeSavedOttProviders(row?.streamingProviders || [], 'streaming', region),
          ]);
          next[group.key] = {
            status: providers.length ? 'ready' : 'not_confirmed',
            query: group.title,
            title: row?.title || group.title,
            year: group.year,
            providers,
            matches: providers.length ? [{
              id: String(row?.tmdbId || ''),
              tmdbId: row?.tmdbId ?? undefined,
              title: row?.title || group.title,
              year: group.year,
              type: 'movie',
              status: 'ready',
              providers,
            }] : [],
          };
        }
        return next;
      });
      return;
    }

    const controller = new AbortController();
    void api.searchSavedOtt(titles, controller.signal).then(response => {
      if (controller.signal.aborted) return;
      const savedByTitle = new Map<string, any>();
      for (const result of response.results || []) {
        for (const entry of result.entries || []) {
          const keys = [entry.title, result.query]
            .map(value => normalizeSavedOttTitle(String(value || '')))
            .filter(Boolean);
          for (const key of keys) {
            const current = savedByTitle.get(key);
            const count = (value: any) => ['streamingProviders', 'rentProviders', 'buyProviders']
              .reduce((total, field) => total + (Array.isArray(value?.ottAvailability?.[field])
                ? value.ottAvailability[field].length
                : Array.isArray(value?.[field]) ? value[field].length : 0), 0);
            if (!current || count(entry) > count(current)) savedByTitle.set(key, entry);
          }
        }
      }
      setSearchAvailabilityByGroup(previous => {
        const next = { ...previous };
        for (const group of pageGroups) {
          const titleKey = normalizeSavedOttTitle(episodeSeriesTitle(group.title) || group.title);
          const entry = savedByTitle.get(titleKey) || savedByTitle.get(normalizeSavedOttTitle(group.title));
          if (!entry) {
            const hasTmdbId = group.variants.some(variant => {
              const id = Number((variant as TorrentSearchResult & { tmdbId?: number | string }).tmdbId);
              return Number.isInteger(id) && id > 0;
            });
            if (!hasTmdbId) {
              next[group.key] = {
                status: 'not_found',
                query: group.title,
                providers: [],
                message: 'No saved streaming details or TMDB ID for this title.',
              };
            }
            continue;
          }
          const saved = entry.ottAvailability && typeof entry.ottAvailability === 'object' ? entry.ottAvailability : entry;
          const region = String(saved.region || 'IN');
          const providers = uniqueOttProviders([
            ...normalizeSavedOttProviders(saved.streamingProviders, 'streaming', region),
            ...normalizeSavedOttProviders(saved.rentProviders, 'rent', region),
            ...normalizeSavedOttProviders(saved.buyProviders, 'buy', region),
          ]);
          // Preserve richer provider data already visible for this group.
          const existing = next[group.key];
          if ((existing?.providers?.length || 0) > providers.length) continue;
          next[group.key] = {
            status: providers.length ? 'ready' : 'not_confirmed',
            query: group.title,
            title: String(entry.catalogueTitle || entry.marvelCatalogueTitle || entry.title || group.title),
            year: group.year,
            providers,
            matches: providers.length ? [{
              id: String(entry.tmdbId || ''),
              tmdbId: entry.tmdbId,
              title: String(entry.catalogueTitle || entry.marvelCatalogueTitle || entry.title || group.title),
              year: group.year,
              type: 'movie',
              status: 'ready',
              providers,
            }] : [],
            message: providers.length ? undefined : 'No saved streaming providers for this title.',
          };
        }
        return next;
      });
      const groupsNeedingLookup = pageGroups.filter(group => {
        const titleKey = normalizeSavedOttTitle(episodeSeriesTitle(group.title) || group.title);
        const entry = savedByTitle.get(titleKey) || savedByTitle.get(normalizeSavedOttTitle(group.title));
        const hasSavedProviders = entry && [
          'streamingProviders',
          'rentProviders',
          'buyProviders',
        ].some(field => {
          const availability = entry.ottAvailability && typeof entry.ottAvailability === 'object'
            ? entry.ottAvailability
            : entry;
          return Array.isArray(availability[field]) && availability[field].length > 0;
        });
        const hasTmdbId = group.variants.some(variant => {
          const id = Number((variant as TorrentSearchResult & { tmdbId?: number | string }).tmdbId);
          return Number.isInteger(id) && id > 0;
        });
        return !hasSavedProviders && hasTmdbId;
      });

      setSearchAvailabilityByGroup(previous => {
        const next = { ...previous };
        for (const group of groupsNeedingLookup) {
          if ((next[group.key]?.providers.length || 0) === 0) {
            next[group.key] = { status: 'loading', query: group.title, providers: [] };
          }
        }
        return next;
      });

      let nextGroupIndex = 0;
      const lookupWorker = async () => {
        while (!controller.signal.aborted) {
          const group = groupsNeedingLookup[nextGroupIndex++];
          if (!group) return;
          const variantWithId = group.variants.find(variant => {
            const id = Number((variant as TorrentSearchResult & { tmdbId?: number | string }).tmdbId);
            return Number.isInteger(id) && id > 0;
          });
          if (!variantWithId) continue;
          const tmdbId = Number((variantWithId as TorrentSearchResult & { tmdbId?: number | string }).tmdbId);
          try {
            const availability = await api.getMovieOttAvailability(tmdbId, 'IN', controller.signal);
            if (controller.signal.aborted) return;
            const region = String(availability.region || 'IN');
            const providers = uniqueOttProviders([
              ...normalizeSavedOttProviders(availability.streamingProviders, 'streaming', region),
              ...normalizeSavedOttProviders(availability.rentProviders, 'rent', region),
              ...normalizeSavedOttProviders(availability.buyProviders, 'buy', region),
            ].map(provider => ({
              name: provider.name,
              region: provider.region,
              type: provider.type,
              webUrl: provider.webUrl,
            })));
            const title = group.title.replace(/\s*\(?(?:19|20)\d{2}\)?\s*$/, '').trim();
            setSearchAvailabilityByGroup(previous => {
              const existing = previous[group.key];
              if ((existing?.providers.length || 0) > providers.length) return previous;
              return {
                ...previous,
                [group.key]: {
                  status: providers.length ? 'ready' : 'not_confirmed',
                  query: title,
                  title,
                  year: group.year,
                  providers,
                  matches: providers.length ? [{
                    id: String(tmdbId),
                    tmdbId,
                    title,
                    year: group.year,
                    type: 'movie',
                    status: 'ready',
                    providers,
                  }] : [],
                  message: providers.length ? undefined : 'No streaming providers reported.',
                },
              };
            });
          } catch (error) {
            if (controller.signal.aborted) return;
            setSearchAvailabilityByGroup(previous => {
              const existing = previous[group.key];
              if ((existing?.providers.length || 0) > 0) return previous;
              return {
                ...previous,
                [group.key]: {
                  status: 'unavailable',
                  query: group.title,
                  providers: [],
                  message: error instanceof Error ? error.message : 'Streaming availability could not be checked.',
                },
              };
            });
          }
        }
      };
      void Promise.all(
        Array.from({ length: Math.min(3, groupsNeedingLookup.length) }, () => lookupWorker()),
      );
    }).catch(error => {
      if (controller.signal.aborted) return;
      setSearchAvailabilityByGroup(previous => {
        const next = { ...previous };
        for (const group of pageGroups) {
          if ((next[group.key]?.providers.length || 0) > 0) continue;
          next[group.key] = {
            status: 'unavailable',
            query: group.title,
            providers: [],
            message: error instanceof Error ? error.message : 'Saved streaming information could not be loaded.',
          };
        }
        return next;
      });
    });
    return () => controller.abort();
  }, [activeFranchiseSearchMode, franchiseGridPage, groupedResults]);

}
