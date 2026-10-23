import { ImdbRatingResult, SearchMediaMetadata, TorrentSearchResult } from '../../api/client.ts';
import { mergeSearchMetadataItems } from './grouping.ts';

export type CachedFranchiseSearchMode = 'marvel' | 'marvel-hindi' | 'dc-live-action' | 'dc-live-action-hindi' | 'dc-animated' | 'classics';

export type FranchisePageCacheEntry = {
  results: TorrentSearchResult[];
  totalMovies: number;
  totalPages: number;
  savedAt: number;
};

export const FRANCHISE_PAGE_CACHE_STORAGE_KEY = 'home_franchise_catalogue_pages_v1';

export const FRANCHISE_PAGE_CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export const FRANCHISE_PAGE_CACHE_MAX_ENTRIES = 48;

// Per-title data (metadata, OTT, IMDb) hardly changes and the backend serves it from its own
// cache, so the browser keeps it for 30 days instead of asking again every week.
export const SEARCH_METADATA_CACHE_STORAGE_KEY = 'home_search_media_metadata_v1';

export const SEARCH_METADATA_CACHE_TTL_MS = 30 * 24 * 60 * 60 * 1000;

export const SEARCH_METADATA_CACHE_MAX_ENTRIES = 500;

export const SEARCH_AVAILABILITY_CACHE_STORAGE_KEY = 'home_search_ott_availability_v1';

export const SEARCH_AVAILABILITY_CACHE_TTL_MS = 30 * 24 * 60 * 60 * 1000;

export const IMDB_RATINGS_CACHE_STORAGE_KEY = 'home_imdb_ratings_v1';

export const IMDB_RATINGS_CACHE_TTL_MS = 30 * 24 * 60 * 60 * 1000;

export function readFranchisePageCache(mode: CachedFranchiseSearchMode, page: number): FranchisePageCacheEntry | null {
  try {
    const stored = JSON.parse(localStorage.getItem(FRANCHISE_PAGE_CACHE_STORAGE_KEY) || '{}');
    const entry = stored?.[mode + ':' + page] as FranchisePageCacheEntry | undefined;
    if (
      entry &&
      Array.isArray(entry.results) &&
      Date.now() - Number(entry.savedAt) < FRANCHISE_PAGE_CACHE_TTL_MS
    ) return entry;
  } catch {
    console.warn('Could not read the saved catalogue page from browser storage.');
  }
  return null;
}

export function writeFranchisePageCache(
  mode: CachedFranchiseSearchMode,
  page: number,
  results: TorrentSearchResult[],
  totalMovies: number,
  totalPages: number,
): void {
  try {
    const now = Date.now();
    const stored = JSON.parse(localStorage.getItem(FRANCHISE_PAGE_CACHE_STORAGE_KEY) || '{}');
    const entries = stored && typeof stored === 'object' && !Array.isArray(stored) ? stored : {};
    entries[mode + ':' + page] = { results, totalMovies, totalPages, savedAt: now };
    const retained = Object.entries(entries)
      .filter(([, entry]) => entry && now - Number((entry as FranchisePageCacheEntry).savedAt) < FRANCHISE_PAGE_CACHE_TTL_MS)
      .sort((a, b) => Number((b[1] as FranchisePageCacheEntry).savedAt) - Number((a[1] as FranchisePageCacheEntry).savedAt))
      .slice(0, FRANCHISE_PAGE_CACHE_MAX_ENTRIES);
    localStorage.setItem(FRANCHISE_PAGE_CACHE_STORAGE_KEY, JSON.stringify(Object.fromEntries(retained)));
  } catch {
    console.warn('Could not save the catalogue page in browser storage; it will be fetched again next time.');
  }
}

export function readPersistentSearchMetadata(): SearchMediaMetadata[] {
  try {
    const stored = JSON.parse(localStorage.getItem(SEARCH_METADATA_CACHE_STORAGE_KEY) || '{}');
    const now = Date.now();
    return (Array.isArray(stored?.entries) ? stored.entries : [])
      .filter((entry: any) =>
        entry?.item &&
        typeof entry.item.title === 'string' &&
        now - Number(entry.savedAt) < SEARCH_METADATA_CACHE_TTL_MS
      )
      .map((entry: any) => entry.item);
  } catch {
    console.warn('Could not read saved movie details from browser storage.');
    return [];
  }
}

export function persistSearchMetadata(items: SearchMediaMetadata[]): void {
  try {
    const now = Date.now();
    const existing = readPersistentSearchMetadata();
    const merged = mergeSearchMetadataItems(existing, items);
    const entries = merged.slice(-SEARCH_METADATA_CACHE_MAX_ENTRIES)
      .map(item => ({ item, savedAt: now }));
    localStorage.setItem(SEARCH_METADATA_CACHE_STORAGE_KEY, JSON.stringify({ entries }));
  } catch {
    console.warn('Could not save movie details in browser storage; they may be fetched again.');
  }
}

export function readPersistentSearchAvailability(): Record<string, {
  status: 'ready' | 'not_found' | 'not_confirmed' | 'unavailable' | 'loading';
  query: string;
  title?: string;
  year?: number | string;
  matches?: Array<{
    id: string;
    title: string;
    year?: number | string;
    type?: string;
    tmdbId?: number | string;
    status: 'ready' | 'not_found' | 'not_confirmed' | 'unavailable';
    providers: Array<{ name: string; region: string; type: string; webUrl?: string }>;
  }>;
  providers: Array<{ name: string; region: string; type: string; webUrl?: string }>;
  message?: string;
}> {
  try {
    const stored = JSON.parse(localStorage.getItem(SEARCH_AVAILABILITY_CACHE_STORAGE_KEY) || '{}');
    const now = Date.now();
    const result: Record<string, any> = {};
    for (const [key, entry] of Object.entries(stored || {})) {
      const value = entry as { savedAt?: number; value?: any };
      if (
        value?.value &&
        ['ready', 'not_confirmed', 'not_found'].includes(value.value.status) &&
        now - Number(value.savedAt) < SEARCH_AVAILABILITY_CACHE_TTL_MS
      ) result[key] = value.value;
    }
    return result;
  } catch {
    console.warn('Could not read saved streaming details from browser storage.');
    return {};
  }
}

export function persistSearchAvailability(value: ReturnType<typeof readPersistentSearchAvailability>): void {
  try {
    const now = Date.now();
    const entries = Object.fromEntries(
      Object.entries(value)
        .filter(([, item]) => ['ready', 'not_confirmed', 'not_found'].includes(item.status))
        .map(([key, item]) => [key, { value: item, savedAt: now }]),
    );
    localStorage.setItem(SEARCH_AVAILABILITY_CACHE_STORAGE_KEY, JSON.stringify(entries));
  } catch {
    console.warn('Could not save streaming details in browser storage; they may be checked again.');
  }
}

export function readPersistentImdbRatings(): Record<string, ImdbRatingResult> {
  try {
    const stored = JSON.parse(localStorage.getItem(IMDB_RATINGS_CACHE_STORAGE_KEY) || '{}');
    const now = Date.now();
    const result: Record<string, ImdbRatingResult> = {};
    for (const [key, entry] of Object.entries(stored || {})) {
      const cached = entry as { savedAt?: number; value?: ImdbRatingResult };
      if (
        cached?.value &&
        ['found', 'not_found'].includes(cached.value.status) &&
        now - Number(cached.savedAt) < IMDB_RATINGS_CACHE_TTL_MS
      ) result[key] = cached.value;
    }
    return result;
  } catch {
    console.warn('Could not read saved IMDb ratings from browser storage.');
  }
  return {};
}

export function persistImdbRatings(value: Record<string, ImdbRatingResult>): void {
  try {
    const now = Date.now();
    const entries = Object.fromEntries(
      Object.entries(value)
        .filter(([, rating]) => ['found', 'not_found'].includes(rating.status))
        .map(([key, rating]) => [key, { value: rating, savedAt: now }]),
    );
    localStorage.setItem(IMDB_RATINGS_CACHE_STORAGE_KEY, JSON.stringify(entries));
  } catch {
    console.warn('Could not save IMDb ratings in browser storage; they may be fetched again.');
  }
}
