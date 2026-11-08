import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Download, Play } from 'lucide-react';
import type { TorrentSearchResult } from '../../api/types.ts';
import { formatBytes } from '../../utils/formatters.ts';
import { QualityPanel, tileClass } from '../MovieActionButtons.tsx';
import { BUCKET_LABELS, BUCKET_ORDER, formatLabelOf, resolutionBucket, visibleBuckets, type ResolutionBucket } from './actionOrdering.ts';
import { torrentQualityDetails, torrentResultKey } from './grouping.ts';

export interface SeasonChip { id: string; label: string; rows: TorrentSearchResult[] }

/** Season chips in order S1, S2 ... and "Complete series" last. Packs without a season number count as complete. */
export function groupBySeason(rows: TorrentSearchResult[]): SeasonChip[] {
  const seasons = new Map<number, TorrentSearchResult[]>();
  const complete: TorrentSearchResult[] = [];
  for (const row of rows) {
    const season = Number(row.season) || 0;
    if (row.scope === 'complete' || !season) complete.push(row);
    else seasons.set(season, [...(seasons.get(season) || []), row]);
  }
  const chips: SeasonChip[] = [...seasons.entries()].sort((a, b) => a[0] - b[0]).map(([season, list]) => ({ id: 's' + season, label: 'S' + season, rows: list }));
  // One season only: a complete-series pack is the same episodes, so its qualities and sizes join that season.
  if (chips.length === 1 && complete.length) { chips[0] = { ...chips[0], rows: [...chips[0].rows, ...complete] }; return chips; }
  if (complete.length) chips.push({ id: 'complete', label: 'Complete series', rows: complete });
  return chips;
}

/** Per quality bucket (720p / 1080p / 4K) the packs of one season, bigger and better-seeded first. */
export function groupByQuality(rows: TorrentSearchResult[]): { bucket: ResolutionBucket; rows: TorrentSearchResult[] }[] {
  return visibleBuckets(BUCKET_ORDER.map(bucket => ({
    bucket,
    rows: rows.filter(row => resolutionBucket(row) === bucket)
      .sort((a, b) => (Number(b.seeders) || 0) - (Number(a.seeders) || 0) || (Number(b.size) || 0) - (Number(a.size) || 0)),
  })));
}

/**
 * Series actions, same layout as the movie card: season chips (only when there is more than one season), then
 * [Play] [Play HD] and a full-width [Download]. Download opens the 720p / 1080p / 4K bar for the chosen season; picking a
 * size opens that pack on Webtor. Play HD opens the seasons / episodes pop-up.
 */
export const TvSeasonActions: React.FC<{
  releases: TorrentSearchResult[];
  onPlay: () => void;
  onWebtorDownload: (row: TorrentSearchResult) => void;
  onBrowse?: () => void;
}> = ({ releases, onPlay, onWebtorDownload, onBrowse }) => {
  const chips = useMemo(() => groupBySeason(releases.filter(row => row.magnetUrl)), [releases]);
  const [seasonId, setSeasonId] = useState('');
  const [downloadOpen, setDownloadOpen] = useState(false);
  const season = chips.find(chip => chip.id === seasonId) || chips[0];
  const buckets = useMemo(() => groupByQuality(season?.rows || []).map(group => ({
    bucket: group.bucket,
    label: BUCKET_LABELS[group.bucket],
    items: group.rows.map(row => ({
      key: torrentResultKey(row),
      label: `${formatBytes(Number(row.size) || 0)} · ${formatLabelOf(torrentQualityDetails(row).label)} · ▲${Number(row.seeders) || 0}`,
      title: String(row.title || ''),
      onPick: () => onWebtorDownload(row),
    })),
  })), [season, onWebtorDownload]);
  const activeChip = useRef<HTMLButtonElement | null>(null);
  useEffect(() => { activeChip.current?.scrollIntoView?.({ block: 'nearest', inline: 'center' }); }, [season?.id]);

  return (
    <div className="space-y-2">
      {chips.length > 1 && (
        <div role="tablist" aria-label="Season" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
          {chips.map(chip => {
            const on = chip.id === season?.id;
            return (
              <button key={chip.id} ref={on ? activeChip : undefined} role="tab" aria-selected={on} type="button"
                onClick={() => { setSeasonId(chip.id); setDownloadOpen(false); }}
                className={'shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-bold transition ' + (on ? 'border-cyan-300 bg-cyan-500/25 text-white shadow-[0_0_12px_rgba(34,211,238,0.5)]' : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:bg-slate-800')}>
                {chip.label}
              </button>
            );
          })}
        </div>
      )}
      <div className="grid grid-cols-2 gap-1.5">
        <button type="button" onClick={onPlay} className={tileClass + ' ' + (onBrowse ? 'col-span-1' : 'col-span-2') + ' border border-violet-400/40 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25'}>
          <Play className="h-3 w-3 shrink-0 fill-current" /><span>Play</span>
        </button>
        {onBrowse && (
          <button type="button" onClick={onBrowse} className={tileClass + ' col-span-1 border border-emerald-400/40 bg-emerald-500/15 text-emerald-200 hover:bg-emerald-500/25'}>
            <Play className="h-3 w-3 shrink-0 fill-current" /><span>Play HD</span>
          </button>
        )}
        {buckets.length > 0 && (
          <button type="button" aria-expanded={downloadOpen} onClick={() => setDownloadOpen(open => !open)}
            className={tileClass + ' col-span-2 bg-cyan-500 text-slate-950 hover:bg-cyan-400'}>
            <Download className="h-3 w-3 shrink-0" /><span>Download</span>
            <ChevronDown aria-hidden="true" className={'h-3 w-3 shrink-0 transition-transform ' + (downloadOpen ? 'rotate-180' : '')} />
          </button>
        )}
      </div>
      {downloadOpen && buckets.length > 0 && (
        <QualityPanel key={season?.id} buckets={buckets} ariaLabel="Download: choose a resolution, then a size" close={() => setDownloadOpen(false)} />
      )}
    </div>
  );
};
