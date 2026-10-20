import { TorrentSearchResult } from '../../api/client.ts';

// v2: v1 also stored year-less keys, which let a poster for one year (e.g. The Crow 1994)
// be reused for a different year of the same title (The Crow 2024).
export const POSTER_TITLE_CACHE_STORAGE_KEY = 'home_poster_title_cache_v2';

export const POSTER_TITLE_CACHE_TTL_MS = 30 * 24 * 60 * 60 * 1000;

export type CachedTitlePoster = { url: string; expiresAt: number };

export const posterByTitleCache = new Map<string, CachedTitlePoster>();

export function normalizePosterTitle(value: unknown): string {
  return String(value || '')
    .toLowerCase()
    .replace(/\\.[a-z0-9]{2,5}$/i, '')
    .replace(/[._]+/g, ' ')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\\s+/g, ' ')
    .trim();
}

export function posterTitleCacheKeys(result: TorrentSearchResult): string[] {
  const title = normalizePosterTitle(result.mediaTitle || result.title);
  if (!title) return [];
  const rawYear = String(result.year || (String(result.title || '').match(/\\b((?:19|20)\\d{2})\\b/) || [])[1] || '').trim();
  const year = /^\\d{4}$/.test(rawYear) ? rawYear : '';
  // With a known year only the exact title+year key is valid; never fall back to another year.
  return year ? [title + '|' + year] : [title + '|'];
}

export function readPosterTitleCache(): void {
  try {
    const raw = localStorage.getItem(POSTER_TITLE_CACHE_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== 'object') return;
    const now = Date.now();
    for (const [key, value] of Object.entries(parsed as Record<string, CachedTitlePoster>)) {
      if (value && typeof value.url === 'string' && value.url && Number(value.expiresAt) > now) {
        posterByTitleCache.set(key, { url: value.url, expiresAt: Number(value.expiresAt) });
      }
    }
  } catch {}
}

export function savePosterTitleCache(key: string, url: string): void {
  if (!key || !url) return;
  posterByTitleCache.set(key, { url, expiresAt: Date.now() + POSTER_TITLE_CACHE_TTL_MS });
  try {
    const now = Date.now();
    const entries = Array.from(posterByTitleCache.entries())
      .filter(([, value]) => value.expiresAt > now)
      .slice(-500);
    localStorage.setItem(POSTER_TITLE_CACHE_STORAGE_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {}
}

export function cachedPosterForTitle(result: TorrentSearchResult): string {
  const now = Date.now();
  for (const key of posterTitleCacheKeys(result)) {
    const cached = posterByTitleCache.get(key);
    if (cached && cached.expiresAt > now) return cached.url;
    if (cached) posterByTitleCache.delete(key);
  }
  return '';
}
