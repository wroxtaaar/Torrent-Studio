import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Download, ListVideo, Play } from 'lucide-react';
import type { TorrentSearchResult } from '../../api/types.ts';
import { formatBytes } from '../../utils/formatters.ts';
import { GLOW } from '../MovieActionButtons.tsx';
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
 * Series actions: pick a season chip, then a glowing quality button, then a pack from the size list. Each pack plays in
 * the Webtor pop-up or downloads on Webtor. The chips never wrap into a long list, they scroll sideways.
 */
export const TvSeasonActions: React.FC<{
  releases: TorrentSearchResult[];
  onPlay: () => void;
  onWebtorPlay: (row: TorrentSearchResult) => void;
  onWebtorDownload: (row: TorrentSearchResult) => void;
  onBrowse?: () => void;
}> = ({ releases, onPlay, onWebtorPlay, onWebtorDownload, onBrowse }) => {
  const chips = useMemo(() => groupBySeason(releases.filter(row => row.magnetUrl)), [releases]);
  const [seasonId, setSeasonId] = useState('');
  const [bucket, setBucket] = useState<ResolutionBucket | ''>('');
  const season = chips.find(chip => chip.id === seasonId) || chips[0];
  const qualities = useMemo(() => groupByQuality(season?.rows || []), [season]);
  const activeBucket = qualities.find(group => group.bucket === bucket)?.bucket || '';
  const active = qualities.find(group => group.bucket === activeBucket);
  const activeChip = useRef<HTMLButtonElement | null>(null);
  useEffect(() => { activeChip.current?.scrollIntoView?.({ block: 'nearest', inline: 'center' }); }, [season?.id]);

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-1.5">
        <button type="button" onClick={onPlay}
          className={'inline-flex items-center justify-center gap-1 rounded-lg border border-violet-400/40 bg-violet-500/15 px-2 py-1.5 text-[11px] font-bold text-violet-200 hover:bg-violet-500/25 ' + (onBrowse ? 'col-span-1' : 'col-span-2')}>
          <Play className="h-3 w-3 fill-current" />Play
        </button>
        {onBrowse && (
          <button type="button" onClick={onBrowse}
            className="inline-flex items-center justify-center gap-1 rounded-lg border border-cyan-300/60 bg-cyan-500/20 px-2 py-1.5 text-[11px] font-extrabold text-white shadow-[0_0_14px_rgba(34,211,238,0.45)] hover:bg-cyan-500/30">
            <ListVideo className="h-3 w-3" />Episodes
          </button>
        )}
      </div>
      {chips.length > 0 && (
        <>
          {chips.length > 1 && <div role="tablist" aria-label="Season" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
            {chips.map(chip => {
              const on = chip.id === season?.id;
              return (
                <button key={chip.id} ref={on ? activeChip : undefined} role="tab" aria-selected={on} type="button"
                  onClick={() => { setSeasonId(chip.id); setBucket(''); }}
                  className={'shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-bold transition ' + (on ? 'border-cyan-300 bg-cyan-500/25 text-white shadow-[0_0_12px_rgba(34,211,238,0.5)]' : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:bg-slate-800')}>
                  {chip.label}
                </button>
              );
            })}
          </div>}
          <div className="flex gap-1">
            {qualities.map(group => {
              const on = group.bucket === activeBucket;
              return (
                <button key={group.bucket} type="button" aria-pressed={on} onClick={() => setBucket(on ? '' : group.bucket)}
                  className={'inline-flex min-w-0 flex-1 items-center justify-center rounded-lg border px-2 py-1 text-[11px] font-extrabold transition ' + (on ? GLOW[group.bucket].active : 'bg-slate-900/70 hover:bg-slate-800 ' + GLOW[group.bucket].idle)}>
                  {BUCKET_LABELS[group.bucket]}
                </button>
              );
            })}
          </div>
          {active && (
            <ul className="max-h-56 space-y-1 overflow-y-auto overscroll-contain">
              {active.rows.map(row => (
                <li key={torrentResultKey(row)} className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-950/60 px-2 py-1.5">
                  <div className="min-w-0 flex-1 text-[11px] leading-tight text-slate-200">
                    <div className="font-bold">{formatBytes(Number(row.size) || 0)}</div>
                    <div className="truncate text-[10px] text-slate-500">{formatLabelOf(torrentQualityDetails(row).label)} · ▲{Number(row.seeders) || 0}</div>
                  </div>
                  <button type="button" onClick={() => onWebtorPlay(row)} title="Play in Webtor" aria-label="Play in Webtor"
                    className="rounded-lg bg-cyan-500/20 p-1.5 text-cyan-200 hover:bg-cyan-500/30"><Play className="h-3.5 w-3.5 fill-current" /></button>
                  <button type="button" onClick={() => onWebtorDownload(row)} title="Download on Webtor" aria-label="Download on Webtor"
                    className="rounded-lg bg-slate-800 p-1.5 text-slate-300 hover:bg-slate-700 hover:text-white"><Download className="h-3.5 w-3.5" /></button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
};
