import { ImdbRatingResult, MovieCatalogueItem } from '../../api/client.ts';

export const CROW_2024_POSTER_URL = 'https://m.media-amazon.com/images/M/MV5BNjYyZjJjMzQtNmNlMS00NmE4LTljZTEtZDI5ZjIxYjE1MzI2XkEyXkFqcGc%40._V1_.jpg';

export function isWonderWoman1984(movie: { title?: string; year?: number | string | null }): boolean {
  return /^wonder woman 1984$/i.test(String(movie.title || '').trim()) &&
    Number(movie.year || 0) === 2020;
}

export function isTheCrow2024(movie: { title?: string; year?: number | string | null }): boolean {
  return /^the crow$/i.test(String(movie.title || '').trim()) &&
    Number(movie.year || 0) === 2024;
}

export function imdbFallbackForCatalogueMovie(movie: { title?: string; year?: number | string | null }): ImdbRatingResult | undefined {
  if (isWonderWoman1984(movie)) {
    return {
      title: 'Wonder Woman 1984',
      year: 2020,
      mediaType: 'movie',
      status: 'found',
      imdbRating: 5.3,
      imdbId: 'tt7126948',
      imdbUrl: 'https://www.imdb.com/title/tt7126948/',
    };
  }
  if (isTheCrow2024(movie)) {
    return {
      title: 'The Crow',
      year: 2024,
      mediaType: 'movie',
      status: 'found',
      imdbRating: 4.7,
      imdbId: 'tt1340094',
      imdbUrl: 'https://www.imdb.com/title/tt1340094/',
    };
  }
  return undefined;
}

export function imdbRatingForCatalogueMovie(movie: MovieCatalogueItem): ImdbRatingResult | undefined {
  // Regional catalogue rows can include a usable stored IMDb score even when
  // their status field is absent or uses a newer cache status. The score itself
  // is authoritative for display; don't hide it because the status is stale.
  const rating = Number(movie.imdbRating);
  const hasRating = Number.isFinite(rating) && rating > 0;
  if (!hasRating && movie.imdbRatingStatus !== 'found' && movie.imdbRatingStatus !== 'not_found') {
    return undefined;
  }
  return {
    title: movie.title,
    year: movie.year,
    mediaType: 'movie',
    status: hasRating || movie.imdbRatingStatus !== 'not_found' ? 'found' : 'not_found',
    imdbRating: hasRating ? rating : movie.imdbRating,
    imdbVotes: movie.imdbVotes,
    imdbId: movie.imdbId,
    imdbUrl: movie.imdbUrl,
  };
}

export function cataloguePosterOverride(movie: { title?: string; year?: number | string | null; posterUrl?: string | null }): string {
  return isTheCrow2024(movie) ? CROW_2024_POSTER_URL : String(movie.posterUrl || '').trim();
}

export function cataloguePosterSource(movie: { title?: string; year?: number | string | null; posterUrl?: string | null }): string {
  const known = cataloguePosterOverride(movie);
  if (known) return known;
  const directPosterUrl = String(movie.posterUrl || '').trim();
  if (/^https?:\/\//i.test(directPosterUrl)) return directPosterUrl;
  const params = new URLSearchParams({ title: String(movie.title || '').trim() });
  if (movie.year) params.set('year', String(movie.year));
  params.set('size', 'w185');
  return '/api/poster?' + params.toString();
}
