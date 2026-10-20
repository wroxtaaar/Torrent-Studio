import { API_BASE, MovieCatalogueItem, TorrentSearchResult } from '../../api/client.ts';
import { normalizeGroupTitle, torrentQualityDetails } from './grouping.ts';

export const catalogueMovieIdentity = (movie: MovieCatalogueItem, catalogueKey?: string | null) =>
  [String(catalogueKey || 'catalogue'), String(movie.id), normalizeGroupTitle(movie.title), String(movie.year || '')].join('|');

export const writeLocalCache = <T,>(key: string, cacheKey: string, value: T) => {
  try {
    const entries = JSON.parse(localStorage.getItem(key) || '{}') as Record<string, { value: T; savedAt: number }>;
    entries[cacheKey] = { value, savedAt: Date.now() };
    const keys = Object.keys(entries);
    for (const oldKey of keys.slice(0, Math.max(0, keys.length - 300))) delete entries[oldKey];
    localStorage.setItem(key, JSON.stringify(entries));
  } catch { /* Storage can be unavailable or full. */ }
};

export const normalizeMatchText = (value: string) =>
  String(value || '')
    .toLowerCase()
    .replace(/\.[a-z0-9]{2,5}$/i, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

export const apiFetchRecent = (input: RequestInfo | URL, init?: RequestInit) => {
  const value = String(input);
  const url = value.startsWith('/') ? API_BASE + value : value;
  return fetch(url, { ...init, credentials: 'include' });
};

export const extractedQuality = (result: TorrentSearchResult) => {
  const details = torrentQualityDetails(result);
  return details.label === 'Other release' ? '' : details.label;
};
