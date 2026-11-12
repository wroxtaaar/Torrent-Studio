import type { NuvioStreamOption, TorrentSearchResult } from '../../api/types.ts';
import { isHindiRelease, torrentQualityDetails } from './grouping.ts';

const resolutionOf = (row: TorrentSearchResult): number => Math.floor(torrentQualityDetails(row).rank / 1000);

/** Torrents for a drop-down: no zero-seed releases, Hindi releases first, then best resolution, then the bigger file. */
export const orderTorrents = (rows: TorrentSearchResult[]): TorrentSearchResult[] =>
  rows
    .filter(row => Number(row.seeders) > 0)
    .sort((a, b) => Number(isHindiRelease(b.title)) - Number(isHindiRelease(a.title)) || resolutionOf(b) - resolutionOf(a) || (Number(b.size) || 0) - (Number(a.size) || 0));

const HD_RANK: Record<NuvioStreamOption['quality'], number> = { '2160p': 4, '1080p': 3, '720p': 2, '480p': 1, other: 0 };
/** HD options: best resolution first, then the bigger file first. */
export const orderHdOptions = (options: NuvioStreamOption[]): NuvioStreamOption[] =>
  [...options].sort((a, b) => HD_RANK[b.quality] - HD_RANK[a.quality] || (b.size || 0) - (a.size || 0));


/** One sortable number per torrent: resolution first, then size (what orderTorrents sorts by). */
export const torrentOrderValue = (row: TorrentSearchResult): number => resolutionOf(row) * 1e13 + Math.min(Number(row.size) || 0, 9.9e12);

/** Items from several sources in one list, Hindi first, then best resolution, then bigger files; items without a value go last. */
export function mergeByOrder<T extends { order?: number; lang?: string }>(...lists: T[][]): T[] {
  const hindi = (item: T) => Number(/hindi/i.test(item.lang || ''));
  return lists.flat().map((item, index) => ({ item, index }))
    .sort((a, b) => hindi(b.item) - hindi(a.item) || (b.item.order ?? -1) - (a.item.order ?? -1) || a.index - b.index)
    .map(entry => entry.item);
}

export type ResolutionBucket = '720p' | '1080p' | '4k' | 'other';
export const BUCKET_LABELS: Record<ResolutionBucket, string> = { '720p': '720p', '1080p': '1080p', '4k': '4K', other: 'Other' };
export const BUCKET_ORDER: ResolutionBucket[] = ['720p', '1080p', '4k', 'other'];

/** Which resolution button a torrent belongs to: up to 720p, 1080p / 1440p, 2160p and above; an unknown resolution goes by size (under 1 GB: 720p, else 1080p). */
export function resolutionBucket(row: TorrentSearchResult): ResolutionBucket {
  const resolution = resolutionOf(row);
  if (resolution >= 2160) return '4k';
  if (resolution >= 1080) return '1080p';
  if (resolution > 0) return '720p';
  // No resolution in the name: under 1 GB it is listed with 720p, 1 GB and over with 1080p, so nothing lands in "Other".
  return (Number(row.size) || 0) >= 1024 ** 3 ? '1080p' : '720p';
}

/** The source tag without the resolution, e.g. "2160P BluRay" gives "BluRay" (or "Release" when unknown). */
export function formatLabelOf(label: string): string {
  return String(label || '').replace(/^(?:2160P \(4K\)|\d{3,4}P)\s*/i, '').replace(/^Other release$/i, '').trim() || 'Release';
}

const NUVIO_RESOLUTION: Record<NuvioStreamOption['quality'], number> = { '2160p': 2160, '1080p': 1080, '720p': 720, '480p': 480, other: 0 };

/** Which resolution button a Nuvio file belongs to (same buckets as torrents). */
export function nuvioBucket(quality: NuvioStreamOption['quality']): ResolutionBucket {
  const resolution = NUVIO_RESOLUTION[quality] ?? 0;
  return resolution >= 2160 ? '4k' : resolution >= 1080 ? '1080p' : resolution > 0 ? '720p' : 'other';
}

/** Same sort value as torrentOrderValue, so Nuvio files and torrents merge into one list. */
export const nuvioOrderValue = (option: NuvioStreamOption): number =>
  (NUVIO_RESOLUTION[option.quality] ?? 0) * 1e13 + Math.min(Number(option.size) || 0, 9.9e12);

/**
 * Which resolution buttons to show: only the ones that have files. "Other" appears only when one of 720p / 1080p / 4K
 * is missing, so there are never more than three buttons and they fit the card.
 */
export function visibleBuckets<T extends { bucket: ResolutionBucket; items?: unknown[]; rows?: unknown[] }>(groups: T[]): T[] {
  const filled = groups.filter(group => (group.items || group.rows || []).length > 0);
  const main = filled.filter(group => group.bucket !== 'other');
  const other = filled.filter(group => group.bucket === 'other');
  return main.length >= 3 ? main : [...main, ...other];
}

/** The Hindi-related tags a release name carries: "Hindi" (also "Hin"), "Dual audio", "Multi audio". Other languages are not highlighted. */
export function releaseLanguage(name: string): string {
  const text = String(name || '');
  const tags: string[] = [];
  if (/(?:^|[^a-z0-9])(?:hindi|hin)(?:$|[^a-z0-9])/i.test(text)) tags.push('Hindi');
  if (/dual[ ._-]?audio/i.test(text)) tags.push('Dual audio');
  if (/(?:^|[^a-z0-9])multi(?:[ ._-]?audio)?(?:$|[^a-z0-9])/i.test(text)) tags.push('Multi audio');
  return tags.join(' · ');
}
