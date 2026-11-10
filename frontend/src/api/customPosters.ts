// Own posters: paste an https image link in src/assets/posters/links.json ("tv-61889": "https://…"), or
// drop a file.
// (older note) Own posters for chosen titles: drop an image named <tv|movie>-<TMDB id>.<jpg|png|webp> into src/assets/posters/
// (Daredevil 2015 = tv-61889, 13 Reasons Why = tv-66788). It then replaces that title's poster in every card.
import LINKS from '../assets/posters/links.json';

const FILES = import.meta.glob('../assets/posters/*.{jpg,jpeg,png,webp}', { eager: true, query: '?url', import: 'default' }) as Record<string, string>;

const BY_KEY: Record<string, string> = {};
for (const [path, url] of Object.entries(FILES)) {
  const name = path.split('/').pop()?.replace(/\.[^.]+$/, '').toLowerCase();
  if (name) BY_KEY[name] = url;
}

export function customPoster(kind: 'tv' | 'movie', tmdbId: number | string | undefined | null): string | undefined {
  if (tmdbId == null) return undefined;
  const key = `${kind}-${tmdbId}`;
  const link = (LINKS as Record<string, string>)[key];
  return (typeof link === 'string' && /^https:\/\//.test(link.trim()) ? link.trim() : undefined) || BY_KEY[key];
}
