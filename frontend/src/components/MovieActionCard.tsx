import React, { useEffect, useState } from 'react';
import { Check, ChevronDown, Copy, Download, Loader2, Play, X } from 'lucide-react';
import { api } from '../api/client.ts';
import type { NuvioStreamOption, TorrentSearchResult } from '../api/types.ts';
import { formatBytes } from '../utils/formatters.ts';
import { torrentQualityDetails, torrentResultKey } from './torrent-search/grouping.ts';
import { copyMagnetAndOpenWebtor } from './torrent-search/webtor.ts';
import { HdPlayerModal } from './HdPlayerModal.tsx';

export interface MovieActionChip {
  key: string;
  label: string;
  title?: string;
}

export interface MovieActionCardProps {
  title: string;
  titleHref: string;
  year?: number | string | null;
  /** TMDB id: the Webtor (over-the-limit torrents) and Download HD lookups use it. */
  tmdbId?: number | string | null;
  onClose: () => void;
  /** The existing Vidrift / NexStream playback. Omitted when this title cannot be played. */
  play?: { disabled: boolean; resolving: boolean; onClick: () => void };
  /** Seedr: torrents up to the size limit (TORRENT_MAX_SIZE_GB). Omitted when the title has none. */
  prepare?: { chips: MovieActionChip[]; isPreparing: boolean; disabled: boolean; onPrepare: (key: string) => void };
  /** Set once the selected torrent has been prepared in Seedr (replaces the Prepare button). */
  prepared?: null | { isPlaying: boolean; isCopied: boolean; onPlay: () => void; onDownload: () => void; onCopy: () => void };
}

const rowClass = 'flex w-full min-w-0 items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[11px] font-semibold text-slate-200 hover:bg-slate-800';

interface MenuItem { key: string; label: string; title?: string; href?: string; download?: string; onPick?: () => void }

/**
 * A button with a drop-down of qualities: tapping a quality runs the action for it. With a single option there is nothing
 * to choose, so the button runs it directly (and shows no caret). The list opens inline so the card never clips it.
 */
const ActionMenu: React.FC<{
  id: string; openId: string; setOpenId: (id: string) => void;
  label: React.ReactNode; className: string; ariaLabel: string; disabled?: boolean; items: MenuItem[];
}> = ({ id, openId, setOpenId, label, className, ariaLabel, disabled, items }) => {
  const open = openId === id;
  const single = items.length === 1 ? items[0] : null;
  const body = (
    <>{label}{!single && <ChevronDown className={'ml-0.5 h-3.5 w-3.5 shrink-0 transition-transform ' + (open ? 'rotate-180' : '')} />}</>
  );
  const base = 'flex w-full items-center justify-center gap-1 whitespace-nowrap rounded-lg px-2 py-2 text-xs font-bold disabled:cursor-not-allowed disabled:opacity-60 ' + className;
  return (
    <div>
      {single?.href ? (
        <a href={single.href} target="_blank" rel="noreferrer noopener" download={single.download} title={single.title} aria-label={ariaLabel} className={base}>{body}</a>
      ) : (
        <button type="button" disabled={disabled} aria-label={ariaLabel} aria-haspopup={single ? undefined : 'menu'} aria-expanded={single ? undefined : open}
          onClick={() => { if (single) { single.onPick?.(); } else { setOpenId(open ? '' : id); } }} className={base}>{body}</button>
      )}
      {!single && open && (
        <div role="menu" aria-label={ariaLabel} className="mt-1 max-h-56 overflow-y-auto rounded-lg border border-slate-700 bg-slate-950 p-1">
          {items.map(item => item.href ? (
            <a key={item.key} role="menuitem" href={item.href} target="_blank" rel="noreferrer noopener" download={item.download} title={item.title}
              onClick={() => setOpenId('')} className={rowClass}>{item.label}</a>
          ) : (
            <button key={item.key} type="button" role="menuitem" title={item.title} onClick={() => { setOpenId(''); item.onPick?.(); }} className={rowClass}>{item.label}</button>
          ))}
        </div>
      )}
    </div>
  );
};

/** Quality chip text for a torrent: "1080p · 3.4 GB". */
export const torrentChip = (row: TorrentSearchResult): MovieActionChip => ({
  key: torrentResultKey(row),
  label: `${torrentQualityDetails(row).label || 'Unknown'} · ${formatBytes(Number(row.size) || 0)}`,
  title: `${row.title} · ▲${Number(row.seeders) || 0}${row.indexer ? ` · ${row.indexer}` : ''}`,
});

/**
 * The second card of a movie: only action buttons, no poster.
 *   Play      the existing Vidrift / NexStream playback
 *   Prepare   Seedr, torrents up to the size limit (drop-down of qualities)
 *   Webtor    torrents above the size limit: copies the magnet and opens Webtor (drop-down of qualities)
 *   Play HD / Download HD  the Nuvio Streams add-on's direct file links (a drop-down of qualities each). Play HD tries the
 *               browser and falls back to VLC / MX Player (see HdPlayerModal); the files are often HEVC with DTS/Dolby audio.
 * A button is rendered only when its source has something; the Webtor and HD lookups start when this
 * card opens (never on page load) and their buttons appear when they return.
 */
export const MovieActionCard: React.FC<MovieActionCardProps> = ({ title, titleHref, year, tmdbId, onClose, play, prepare, prepared }) => {
  const [large, setLarge] = useState<TorrentSearchResult[]>([]);
  const [hint, setHint] = useState('');
  const [hd, setHd] = useState<NuvioStreamOption[]>([]);
  const [openId, setOpenId] = useState('');
  const [hdPlayKey, setHdPlayKey] = useState('');
  const [hdLoading, setHdLoading] = useState(false);
  const [largeLoading, setLargeLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLarge([]); setHd([]); setHint(''); setOpenId(''); setHdPlayKey('');
    setLargeLoading(true);
    void api.getTorrentOptions({ tmdbId, title, year }, controller.signal, 'all', 'movie', true)
      .then(rows => { if (!controller.signal.aborted) setLarge(rows); })
      .catch(() => {})
      .finally(() => { if (!controller.signal.aborted) setLargeLoading(false); });
    const id = Number(tmdbId);
    if (Number.isInteger(id) && id > 0) {
      setHdLoading(true);
      void api.getNuvioStreams(id, controller.signal)
        .then(options => { if (!controller.signal.aborted) setHd(options); })
        .catch(() => {})
        .finally(() => { if (!controller.signal.aborted) setHdLoading(false); });
    }
    return () => controller.abort();
  }, [tmdbId, title, year]);

  const playingHd = hd.find(option => option.key === hdPlayKey);
  const nothing = !play && !prepare && !prepared && large.length === 0 && hd.length === 0;
  const checking = hdLoading || largeLoading;

  return (
    <div className="relative min-w-0 self-start rounded-xl border border-slate-800 bg-slate-900 p-2.5 sm:p-3 lg:rounded-[14px]">
      <div className="flex items-start gap-1.5">
        <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-1.5">
          <a href={titleHref} target="_blank" rel="noreferrer" title="Open on IMDb"
            className="min-w-0 text-left text-xs font-semibold leading-4 text-slate-100 hover:text-cyan-300 sm:text-sm">
            {title}
          </a>
          {year ? <span className="shrink-0 text-[10px] text-slate-500 sm:text-xs">{year}</span> : null}
        </div>
        <button type="button" onClick={onClose} title="Back to the movie cards" aria-label="Back to the movie cards"
          className="shrink-0 rounded-md p-1 text-slate-500 hover:bg-slate-800 hover:text-slate-100">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="mt-2.5 space-y-2">
        {play && (
          <button type="button" disabled={play.disabled} onClick={play.onClick}
            className="flex w-full items-center justify-center gap-1 whitespace-nowrap rounded-lg border border-violet-400/40 bg-violet-500/15 px-2 py-2 text-xs font-bold text-violet-200 hover:bg-violet-500/25 disabled:opacity-60">
            {play.resolving ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />Resolving…</> : <><Play className="h-3.5 w-3.5 fill-current" />Play</>}
          </button>
        )}

        {hd.length > 0 && (
          <ActionMenu id="play-hd" openId={openId} setOpenId={setOpenId} ariaLabel={`Play HD: choose a quality for ${title}`}
            className="border border-emerald-400/40 bg-emerald-500/15 text-emerald-200 hover:bg-emerald-500/25"
            label={<><Play className="h-3.5 w-3.5 fill-current" />Play HD</>}
            items={hd.map(option => ({ key: option.key, label: option.label, title: option.filename, onPick: () => setHdPlayKey(option.key) }))} />
        )}

        {hd.length > 0 && (
          <ActionMenu id="download-hd" openId={openId} setOpenId={setOpenId} ariaLabel={`Download HD: choose a quality for ${title}`}
            className="border border-emerald-400/40 bg-emerald-500/15 text-emerald-200 hover:bg-emerald-500/25"
            label={<><Download className="h-3.5 w-3.5" />Download HD</>}
            items={hd.map(option => ({ key: option.key, label: option.label, title: option.filename, href: option.url, download: option.filename || undefined }))} />
        )}

        {prepared ? (
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Prepared in Seedr</div>
            <div className="flex flex-wrap items-center gap-1.5">
              <button type="button" disabled={prepared.isPlaying} onClick={prepared.onPlay} title={prepared.isPlaying ? 'Opening stream…' : 'Play from Seedr'}
                className="flex items-center gap-1 whitespace-nowrap rounded-lg bg-emerald-400 px-2.5 py-1.5 text-xs font-bold text-slate-950 hover:bg-emerald-300 disabled:cursor-wait disabled:opacity-70">
                {prepared.isPlaying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}Play
              </button>
              <button type="button" onClick={prepared.onDownload} title="Download file" aria-label="Download file"
                className="rounded-lg bg-slate-800 p-2 text-slate-300 hover:bg-slate-700 hover:text-white"><Download className="h-3.5 w-3.5" /></button>
              <button type="button" disabled={prepared.isCopied} onClick={prepared.onCopy} title="Copy download link" aria-label="Copy download link"
                className="rounded-lg bg-slate-800 p-2 text-slate-300 hover:bg-slate-700 hover:text-cyan-400 disabled:opacity-60">
                {prepared.isCopied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>
        ) : prepare && (
          <ActionMenu id="prepare" openId={openId} setOpenId={setOpenId} ariaLabel={`Prepare: choose a quality for ${title}`}
            disabled={prepare.disabled || prepare.isPreparing}
            className="bg-cyan-500 text-slate-950 hover:bg-cyan-400"
            label={prepare.isPreparing ? 'Preparing…' : 'Prepare'}
            items={prepare.chips.map(chip => ({ key: chip.key, label: chip.label, title: chip.title, onPick: () => prepare.onPrepare(chip.key) }))} />
        )}

        {large.length > 0 && (
          <div>
            <ActionMenu id="webtor" openId={openId} setOpenId={setOpenId} ariaLabel={`Webtor: choose a quality for ${title}`}
              className="border border-cyan-400/40 bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25"
              label={<><Download className="h-3.5 w-3.5" />Webtor</>}
              items={large.map(row => ({
                ...torrentChip(row),
                onPick: () => {
                  const copied = copyMagnetAndOpenWebtor(String(row.magnetUrl || ''));
                  setHint(copied ? 'Magnet copied. Paste it on Webtor to stream or download.' : 'Webtor opened, but the magnet could not be copied. Pick another quality and try again.');
                },
              }))} />
            {hint ? <div className="mt-1.5 text-[10px] leading-snug text-slate-400" role="status">{hint}</div> : null}
          </div>
        )}
        {playingHd && <HdPlayerModal title={title} option={playingHd} onClose={() => setHdPlayKey('')} />}

        {checking && !nothing && <div className="text-[10px] text-slate-500" role="status">Checking more downloads…</div>}
        {nothing && (
          <div className="text-xs text-slate-400" role="status">{checking ? 'Checking available downloads…' : 'Nothing available yet'}</div>
        )}
      </div>
    </div>
  );
};
