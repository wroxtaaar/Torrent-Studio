import { createPortal } from 'react-dom';
import React, { useEffect, useMemo, useState } from 'react';
import { Download, ExternalLink, Loader2, Play, RefreshCw, Users, X } from 'lucide-react';
import { api } from '../../api/client.ts';
import type { TorrentSearchResult } from '../../api/types.ts';
import { formatBytes } from '../../utils/formatters.ts';
import { GLOW } from '../MovieActionButtons.tsx';
import { BUCKET_LABELS, formatLabelOf, type ResolutionBucket } from './actionOrdering.ts';
import { torrentQualityDetails, torrentResultKey } from './grouping.ts';
import { episodesOf, webtorFilePath, type EpisodeEntry } from './seriesEpisodes.ts';
import { groupByQuality, groupBySeason } from './TvSeasonActions.tsx';
import { openWebtorDownload, webtorTorrentPageUrl } from './webtor.ts';

type Files = { name: string; files: { index: number; name: string; size: number; path: string }[] };

/**
 * One pop-up with everything for a series: season chips, quality buttons, the packs of that season, and the episodes
 * inside the chosen pack. Episode lists come from the torrent's own file list (no download); Play and Download go to Webtor.
 */
export const SeriesPopup: React.FC<{
  title: string;
  year?: string | number;
  posterSrc?: string;
  releases: TorrentSearchResult[];
  onClose: () => void;
  onPlayEpisode: (pack: TorrentSearchResult, path: string, label: string) => void;
}> = ({ title, year, posterSrc, releases, onClose, onPlayEpisode }) => {
  const seasons = useMemo(() => groupBySeason(releases.filter(row => row.magnetUrl)), [releases]);
  const [seasonId, setSeasonId] = useState(() => seasons[0]?.id || '');
  const season = seasons.find(chip => chip.id === seasonId) || seasons[0];
  const qualities = useMemo(() => groupByQuality(season?.rows || []), [season]);
  const [bucket, setBucket] = useState<ResolutionBucket | ''>('');
  const activeGroup = qualities.find(group => group.bucket === bucket) || qualities[qualities.length - 1];
  const [packKey, setPackKey] = useState('');
  const pack = activeGroup?.rows.find(row => torrentResultKey(row) === packKey) || activeGroup?.rows[0];

  const [files, setFiles] = useState<Files | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = previous; };
  }, [onClose]);

  const magnet = String(pack?.magnetUrl || '');
  useEffect(() => {
    if (!magnet) { setFiles(null); setStatus('idle'); return undefined; }
    let cancelled = false;
    setFiles(null); setStatus('loading');
    api.inspectMagnet(magnet, 'Downloads', String(pack?.infoUrl || ''), '')
      .then(data => {
        if (cancelled) return;
        if (data.files?.length) { setFiles({ name: data.name, files: data.files }); setStatus('idle'); } else setStatus('error');
      })
      .catch(() => { if (!cancelled) setStatus('error'); });
    return () => { cancelled = true; };
  }, [magnet, attempt]);

  const episodes = useMemo(() => (files ? episodesOf(files.files) : []), [files]);
  const multiFile = (files?.files.length || 0) > 1;
  const showSeasonHeads = new Set(episodes.map(entry => entry.season)).size > 1;
  const packLabel = pack ? `${season?.label} · ${torrentQualityDetails(pack).label}` : '';

  const playEpisode = (entry: EpisodeEntry) => {
    if (!pack) return;
    onPlayEpisode(pack, webtorFilePath(files?.name || '', entry.file, multiFile), `${packLabel} · ${entry.label}`);
  };

  return createPortal(
    <div className="fixed inset-0 z-[110] flex items-end justify-center bg-black/80 backdrop-blur-sm sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-label={`Seasons and episodes of ${title}`}
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="flex max-h-[94vh] w-full max-w-2xl flex-col overflow-hidden rounded-t-3xl border border-slate-700/80 bg-slate-950 shadow-2xl sm:rounded-3xl">
        <header className="relative shrink-0 overflow-hidden border-b border-slate-800">
          {posterSrc && <img src={posterSrc} alt="" aria-hidden="true" className="absolute inset-0 h-full w-full scale-110 object-cover opacity-20 blur-xl" />}
          <div className="relative flex items-center gap-3 bg-gradient-to-b from-slate-950/40 to-slate-950/90 px-4 py-3">
            {posterSrc && <img src={posterSrc} alt={title} className="h-16 w-11 shrink-0 rounded-lg border border-slate-700 object-cover shadow-lg" />}
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-base font-extrabold text-white">{title}</h2>
              <p className="text-[11px] text-slate-400">{year ? year + ' · ' : ''}{seasons.length > 1 ? seasons.filter(chip => chip.id !== 'complete').length + ' seasons' : 'Seasons, quality and episodes'}</p>
            </div>
            <button type="button" onClick={onClose} aria-label="Close" className="shrink-0 rounded-full bg-slate-800/80 p-2 text-slate-300 hover:bg-slate-700 hover:text-white"><X className="h-4 w-4" /></button>
          </div>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-4">
          <section aria-label="Season">
            <h3 className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">Season</h3>
            <div role="tablist" className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
              {seasons.map(chip => {
                const on = chip.id === season?.id;
                return (
                  <button key={chip.id} role="tab" aria-selected={on} type="button" onClick={() => { setSeasonId(chip.id); setBucket(''); setPackKey(''); }}
                    className={'shrink-0 rounded-full border px-3.5 py-1.5 text-xs font-bold transition ' + (on ? 'border-cyan-300 bg-cyan-500/25 text-white shadow-[0_0_14px_rgba(34,211,238,0.5)]' : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:bg-slate-800')}>
                    {chip.label}
                  </button>
                );
              })}
            </div>
          </section>

          <section aria-label="Quality">
            <h3 className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">Quality</h3>
            <div className="flex gap-2">
              {qualities.map(group => {
                const on = group === activeGroup;
                return (
                  <button key={group.bucket} type="button" aria-pressed={on} onClick={() => { setBucket(group.bucket); setPackKey(''); }}
                    className={'inline-flex min-w-0 flex-1 items-center justify-center rounded-xl border px-3 py-2 text-sm font-extrabold transition ' + (on ? GLOW[group.bucket].active : 'bg-slate-900/70 hover:bg-slate-800 ' + GLOW[group.bucket].idle)}>
                    {BUCKET_LABELS[group.bucket]}
                  </button>
                );
              })}
            </div>
          </section>

          {activeGroup && activeGroup.rows.length > 0 && (
            <section aria-label="Release">
              <h3 className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">Release</h3>
              <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
                {activeGroup.rows.map(row => {
                  const on = row === pack;
                  return (
                    <button key={torrentResultKey(row)} type="button" aria-pressed={on} onClick={() => setPackKey(torrentResultKey(row))}
                      className={'shrink-0 rounded-xl border px-3 py-2 text-left transition ' + (on ? 'border-cyan-300 bg-cyan-500/15' : 'border-slate-800 bg-slate-900/70 hover:bg-slate-800')}>
                      <div className="text-xs font-extrabold text-white">{formatBytes(Number(row.size) || 0)}</div>
                      <div className="flex items-center gap-1 text-[10px] text-slate-400"><span>{formatLabelOf(torrentQualityDetails(row).label)}</span><Users className="ml-1 h-3 w-3" />{Number(row.seeders) || 0}</div>
                    </button>
                  );
                })}
              </div>
            </section>
          )}

          <section aria-label="Episodes">
            <div className="mb-1.5 flex items-center justify-between">
              <h3 className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Episodes{episodes.length ? ' · ' + episodes.length : ''}</h3>
              {status === 'error' && <button type="button" onClick={() => setAttempt(n => n + 1)} className="inline-flex items-center gap-1 text-[11px] font-semibold text-cyan-300 hover:text-cyan-200"><RefreshCw className="h-3 w-3" />Retry</button>}
            </div>
            {status === 'loading' && <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-4 text-xs text-slate-400"><Loader2 className="h-4 w-4 animate-spin text-cyan-400" />Reading the episode list from the torrent…</div>}
            {status === 'error' && <p className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-3 text-xs text-amber-200">Could not read the episode list yet (few peers or slow tracker). Retry, or play or download the whole pack below.</p>}
            {status === 'idle' && files && episodes.length === 0 && <p className="rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-3 text-xs text-slate-400">No video files found in this pack.</p>}
            {episodes.length > 0 && (
              <ul className="space-y-1.5">
                {episodes.map((entry, index) => (
                  <React.Fragment key={entry.file.index}>
                    {showSeasonHeads && (index === 0 || episodes[index - 1].season !== entry.season) && (
                      <li className="pt-1 text-[10px] font-bold uppercase tracking-widest text-cyan-400/80">{entry.season ? 'Season ' + entry.season : 'Other files'}</li>
                    )}
                    <li className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2">
                      <span className="w-9 shrink-0 text-xs font-extrabold text-cyan-300">{entry.episode ? entry.label : '—'}</span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs text-slate-200">{(entry.file.path.split('/').pop() || entry.file.name)}</div>
                        <div className="text-[10px] text-slate-500">{formatBytes(entry.file.size)}</div>
                      </div>
                      <button type="button" onClick={() => playEpisode(entry)} aria-label={'Play ' + entry.label} title="Play in Webtor"
                        className="rounded-full bg-cyan-500 p-2 text-slate-950 shadow shadow-cyan-500/30 hover:bg-cyan-400"><Play className="h-3.5 w-3.5 fill-current" /></button>
                    </li>
                  </React.Fragment>
                ))}
              </ul>
            )}
          </section>
        </div>

        <footer className="flex shrink-0 flex-wrap gap-2 border-t border-slate-800 bg-slate-950 px-4 py-3">
          <button type="button" disabled={!pack} onClick={() => pack && onPlayEpisode(pack, '', packLabel)}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-violet-400/40 bg-violet-500/15 px-3 py-2 text-xs font-bold text-violet-200 hover:bg-violet-500/25 disabled:opacity-40">
            <Play className="h-3.5 w-3.5 fill-current" />Play pack
          </button>
          <button type="button" disabled={!pack} onClick={() => pack && openWebtorDownload(magnet)}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 hover:bg-cyan-400 disabled:opacity-40">
            <Download className="h-3.5 w-3.5" />Download on Webtor
          </button>
          {pack && webtorTorrentPageUrl(magnet) && (
            <a href={webtorTorrentPageUrl(magnet)} target="_blank" rel="noreferrer" title="Open on webtor.io" aria-label="Open on webtor.io"
              className="inline-flex items-center justify-center rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-slate-300 hover:text-white"><ExternalLink className="h-3.5 w-3.5" /></a>
          )}
        </footer>
      </div>
    </div>,
    document.body,
  );
};
