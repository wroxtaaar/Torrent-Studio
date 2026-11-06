import type { NuvioStreamOption, TorrentSearchResult } from '../../api/types.ts';
import { torrentQualityDetails } from './grouping.ts';

const resolutionOf = (row: TorrentSearchResult): number => Math.floor(torrentQualityDetails(row).rank / 1000);

/** Torrents for a drop-down: no zero-seed releases, best resolution first, then the bigger file first. */
export const orderTorrents = (rows: TorrentSearchResult[]): TorrentSearchResult[] =>
  rows
    .filter(row => Number(row.seeders) > 0)
    .sort((a, b) => resolutionOf(b) - resolutionOf(a) || (Number(b.size) || 0) - (Number(a.size) || 0));

const HD_RANK: Record<NuvioStreamOption['quality'], number> = { '2160p': 4, '1080p': 3, '720p': 2, '480p': 1, other: 0 };
/** HD options: best resolution first, then the bigger file first. */
export const orderHdOptions = (options: NuvioStreamOption[]): NuvioStreamOption[] =>
  [...options].sort((a, b) => HD_RANK[b.quality] - HD_RANK[a.quality] || (b.size || 0) - (a.size || 0));

