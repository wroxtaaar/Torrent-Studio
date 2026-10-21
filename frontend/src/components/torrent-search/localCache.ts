import { MOVIE_TORRENT_CACHE_TTL_MS, NEXSTREAM_CACHE_TTL_MS } from './constants.ts';

export const readLocalCache = <T,>(
  key: string,
  cacheKey: string,
  ttlMs = NEXSTREAM_CACHE_TTL_MS,
): T | null => {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || '{}') as
      | Record<string, { value: T; savedAt: number }>
      | Array<[string, T & { savedAt?: number }]>;
    // Movie torrent details are persisted as [key, value] tuples, while
    // NexStream caches use an object keyed by cacheKey. Read both formats.
    if (Array.isArray(parsed)) {
      const tuple = parsed.find(entry => Array.isArray(entry) && entry[0] === cacheKey);
      if (tuple && tuple[1] && Date.now() - Number(tuple[1].savedAt || 0) < MOVIE_TORRENT_CACHE_TTL_MS) {
        return tuple[1] as T;
      }
      return null;
    }
    const entry = parsed[cacheKey];
    if (entry && Date.now() - entry.savedAt < ttlMs) return entry.value;
  } catch {}
  return null;
};
