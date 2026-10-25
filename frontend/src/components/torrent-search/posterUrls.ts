import { API_BASE, TorrentSearchResult } from '../../api/client.ts';
import { resizeKnownPosterHost } from '../movie-cards/posterUpgrade.ts';

export const posterKeyFor = (result: TorrentSearchResult) =>
  String(
    result.guid ||
    result.infoHash ||
    result.magnetUrl ||
    result.downloadUrl ||
    result.title
  );

export const rawPosterUrlFor = (result: TorrentSearchResult) => {
  const raw = String(result.posterUrl || '').trim();
  if (!raw) return '';
  return raw.startsWith('/') ? API_BASE + raw : raw;
};

export const lowQualityPosterUrl = (value: unknown, size: 'w185' | 'w342' | 'w500' | 'w780' = 'w185') => {
  const url = String(value || '').trim();
  if (!url) return '';
  try {
    const parsed = new URL(url, window.location.origin);
    // Same-origin poster endpoints support explicit low/high variants. Set this
    // before assigning src so cached redirect URLs can never bypass the thumbnail.
    if (parsed.pathname.replace(/\/+$/, '') === '/api/poster') {
      parsed.searchParams.set('size', size === 'w780' ? 'w780' : 'w185');
      return parsed.toString();
    }
    if (parsed.hostname !== 'image.tmdb.org') return resizeKnownPosterHost(url, 'low') || url;
    parsed.pathname = parsed.pathname.replace(/\/t\/p\/(?:original|w780|w500|w185|w342|w300|w200|w154|w92)\//, '/t/p/' + size + '/');
    return parsed.toString();
  } catch {
    return url;
  }
};

export const posterResolveCandidateUrlsFor = (result: TorrentSearchResult) => {
  const candidates: string[] = [];
  const seen = new Set<string>();

  const addCandidate = (title: string, year = '') => {
    const clean = String(title || '')
      .replace(/[._]+/g, ' ')
      .replace(/\s+/g, ' ')
      .replace(/^[-._\s]+|[-._\s]+$/g, '')
      .trim();
    if (!clean) return;

    const yearMatches = [...clean.matchAll(/\b((?:19|20)\d{2})\b/g)];
    const trailingYear = yearMatches[yearMatches.length - 1];
    const inferredYear = year || trailingYear?.[1] || '';
    // Keep years that are part of a title (e.g. Wonder Woman 1984). Strip a
    // year from the query only when it matches the separately known release year.
    const titleOnly = trailingYear && trailingYear[1] === inferredYear
      ? clean.slice(0, trailingYear.index).trim() || clean
      : clean;

    const params = new URLSearchParams({ title: titleOnly });
    if (inferredYear) params.set('year', inferredYear);
    const url = API_BASE + '/api/poster/resolve?' + params.toString();
    if (!seen.has(url)) {
      seen.add(url);
      candidates.push(url);
    }
  };

  // Resolve from the actual title/year only. Indexer-provided poster URLs can
  // be generic thumbnails for a different movie and must not be trusted.

  const explicitYear = result.year ? String(result.year) : '';
  const mediaTitle = String(result.mediaTitle || '').trim();
  const rawTitle = String(result.title || '').trim();
  const baseTitle = mediaTitle || rawTitle;

  addCandidate(mediaTitle, explicitYear);

  const cleaned = baseTitle
    .replace(/[._]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  const yearMatch = cleaned.match(/\b((?:19|20)\d{2})\b/);
  const year = explicitYear || yearMatch?.[1] || '';

  if (!mediaTitle && yearMatch?.index != null) {
    addCandidate(cleaned.slice(0, yearMatch.index), year);
  }

  const releaseCut = cleaned.split(
    /\b(?:2160p|1440p|1080p|720p|576p|480p|4k|8k|web[- ]?dl|web[- ]?rip|webrip|bluray|brrip|hdrip|dvdrip|cam|hdcam|x264|x265|h264|h265|hevc|aac|ddp|atmos|proper|repack|remastered|extended|unrated|directors?\s+cut)\b/i
  )[0].trim();
  if (releaseCut) addCandidate(releaseCut, year);

  const softClean = cleaned
    .replace(
      /\b(?:hindi|tamil|telugu|malayalam|kannada|bengali|marathi|punjabi|gujarati|urdu|dual\s+audio|multi\s+audio|dubbed|dub|multi|proper|repack|remastered|extended|unrated|imax|hdr10\+?|dolby\s+vision)\b/gi,
      ' '
    )
    .replace(/\s+/g, ' ')
    .trim();
  if (softClean) addCandidate(softClean, year);

  const aliasPairs: Array<[RegExp, string]> = [
    [/\bspiderman\b/gi, 'Spider Man'],
    [/\bspider\s+man\b/gi, 'Spiderman'],
    [/\bantman\b/gi, 'Ant Man'],
    [/\bant\s+man\b/gi, 'Antman'],
    [/\bironman\b/gi, 'Iron Man'],
    [/\biron\s+man\b/gi, 'Ironman'],
    [/\bblackpanther\b/gi, 'Black Panther'],
    [/\bblack\s+panther\b/gi, 'Blackpanther'],
    [/\bdoctorstrange\b/gi, 'Doctor Strange'],
    [/\bdoctor\s+strange\b/gi, 'Doctorstrange'],
    [/\bcaptainamerica\b/gi, 'Captain America'],
    [/\bcaptain\s+america\b/gi, 'Captainamerica'],
    [/\bguardiansofthegalaxy\b/gi, 'Guardians of the Galaxy'],
  ];

  for (const [pattern, replacement] of aliasPairs) {
    if (pattern.test(cleaned)) {
      addCandidate(cleaned.replace(pattern, replacement), year);
    }
  }

  return candidates;
};

export const posterImageUrlForResult = (result: TorrentSearchResult): string => {
  const resolveUrl = posterResolveCandidateUrlsFor(result)[0];
  if (!resolveUrl) return '';
  try {
    const url = new URL(resolveUrl, window.location.origin);
    url.pathname = url.pathname.replace('/api/poster/resolve', '/api/poster');
    url.searchParams.set('size', 'w185');
    return url.toString();
  } catch {
    return resolveUrl.replace('/api/poster/resolve?', '/api/poster?') +
      (resolveUrl.includes('?') ? '&' : '?') + 'size=w185';
  }
};
