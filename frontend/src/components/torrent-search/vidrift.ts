export const VIDRIFT_EMBED_ORIGIN = 'https://embed.vidrift.net';

export function validTmdbId(value: unknown): value is number {
  if (typeof value === 'number') return Number.isInteger(value) && value > 0;
  if (typeof value !== 'string' || !/^\d+$/.test(value.trim())) return false;
  const parsed = Number(value.trim());
  return Number.isInteger(parsed) && parsed > 0;
}

export function buildVidRiftMovieUrl(tmdbId: unknown): string | null {
  if (!validTmdbId(tmdbId)) return null;
  return `${VIDRIFT_EMBED_ORIGIN}/embed/movie/${Number(tmdbId)}`;
}

export function buildVidRiftTvUrl(tmdbId: unknown, season: unknown, episode: unknown): string | null {
  if (!validTmdbId(tmdbId)) return null;
  const seasonNumber = Number(season);
  const episodeNumber = Number(episode);
  if (!Number.isInteger(seasonNumber) || seasonNumber < 1 || !Number.isInteger(episodeNumber) || episodeNumber < 1) return null;
  return `${VIDRIFT_EMBED_ORIGIN}/embed/tv/${Number(tmdbId)}/${seasonNumber}/${episodeNumber}`;
}
