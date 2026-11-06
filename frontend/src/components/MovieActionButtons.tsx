import React, { useEffect, useState } from 'react';
import { Check, ChevronDown, Copy, Download, Loader2, Play } from 'lucide-react';
import { api } from '../api/client.ts';
import type { NuvioStreamOption, TorrentSearchResult } from '../api/types.ts';
import { formatBytes } from '../utils/formatters.ts';
import { torrentQualityDetails, torrentResultKey } from './torrent-search/grouping.ts';
import { copyMagnetAndOpenWebtor } from './torrent-search/webtor.ts';
import { HdPlayerModal } from './HdPlayerModal.tsx';
import { orderHdOptions, orderTorrents } from './torrent-search/actionOrdering.ts';

export { orderTorrents };

export interface MovieActionChip {
  key: string;
  label: string;
  title?: string;
}

export interface MovieActionButtonsProps {
  /** Used in labels and for the Webtor / HD lookups together with year and tmdbId. */
  title: string;
  year?: number | string | null;
  /** TMDB id: the Webtor (over-the-limit torrents) and HD lookups use it. */
  tmdbId?: number | string | null;
  /** The existing Vidrift / NexStream playback. Omitted when this title cannot be played. */
  play?: { disabled: boolean; resolving: boolean; onClick: () => void };
  /** Seedr: torrents up to the size limit (TORRENT_MAX_SIZE_GB). Omitted when the title has none. */
  prepare?: { chips: MovieActionChip[]; isPreparing: boolean; disabled: boolean; onPrepare: (key: string) => void };
  /** Set once the selected torrent has been prepared in Seedr (replaces the Prepare button). */
  prepared?: null | { isPlaying: boolean; isCopied: boolean; onPlay: () => void; onDownload: () => void; onCopy: () => void };
}

interface MenuItem { key: string; label: string; title?: string; href?: string; download?: string; onPick?: () => void }
interface Group {
  id: string;
  label: string;
  className: string;
  ariaLabel: string;
  disabled?: boolean;
  busy?: boolean;
  items: MenuItem[];
}

const tileClass = 'inline-flex items-center justify-center gap-1 whitespace-nowrap rounded-lg px-3 py-1.5 text-[11px] font-bold leading-tight disabled:cursor-not-allowed disabled:opacity-60';
const rowClass = 'flex w-full min-w-0 items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[11px] font-semibold text-slate-200 hover:bg-slate-800';

/** Quality text for a torrent: "1080p · 3.4 GB". */
export const torrentChip = (row: TorrentSearchResult): MovieActionChip => ({
  key: torrentResultKey(row),
  label: `${torrentQualityDetails(row).label || 'Unknown'} · ${formatBytes(Number(row.size) || 0)}`,
  title: `${row.title} · ▲${Number(row.seeders) || 0}${row.indexer ? ` · ${row.indexer}` : ''}`,
});

/**
 * The action area of a movie's second card (shown under the poster and title):
 *   [Play] [Play HD ⌄] [Prepare ⌄]
 *   [Download HD ⌄] [Webtor ⌄]
 * Each ⌄ button opens a list of qualities (best resolution first, then bigger files); picking one runs the action.
 * With a single quality the button runs directly and shows no caret. A button is rendered only when its source has
 * something. The Webtor and HD lookups start when the card opens (never on page load) and their buttons appear when
 * they return.
 *   Play      the existing Vidrift / NexStream playback
 *   Play HD   the Nuvio Streams add-on's file in the browser, with VLC / MX Player as fallback (HdPlayerModal)
 *   Prepare   Seedr, torrents up to the size limit
 *   Download HD  the same files, saved by the browser straight from the file host
 *   Webtor    torrents above the size limit: copies the magnet and opens Webtor
 */
export const MovieActionButtons: React.FC<MovieActionButtonsProps> = ({ title, year, tmdbId, play, prepare, prepared }) => {
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
      .then(rows => { if (!controller.signal.aborted) setLarge(orderTorrents([...rows])); })
      .catch(() => {})
      .finally(() => { if (!controller.signal.aborted) setLargeLoading(false); });
    const id = Number(tmdbId);
    if (Number.isInteger(id) && id > 0) {
      setHdLoading(true);
      void api.getNuvioStreams(id, controller.signal)
        .then(options => { if (!controller.signal.aborted) setHd(orderHdOptions(options)); })
        .catch(() => {})
        .finally(() => { if (!controller.signal.aborted) setHdLoading(false); });
    }
    return () => controller.abort();
  }, [tmdbId, title, year]);

  const playingHd = hd.find(option => option.key === hdPlayKey);
  const hdTone = 'border border-emerald-400/40 bg-emerald-500/15 text-emerald-200 hover:bg-emerald-500/25';
  const groups: Group[] = [];
  if (hd.length > 0) {
    groups.push({
      id: 'play-hd', label: 'Play HD', className: hdTone, ariaLabel: `Play HD: choose a quality for ${title}`,
      items: hd.map(option => ({ key: option.key, label: option.label, title: option.filename, onPick: () => setHdPlayKey(option.key) })),
    });
  }
  if (!prepared && prepare && prepare.chips.length > 0) {
    groups.push({
      id: 'prepare', label: prepare.isPreparing ? 'Preparing…' : 'Prepare', className: 'bg-cyan-500 text-slate-950 hover:bg-cyan-400', ariaLabel: `Prepare: choose a quality for ${title}`, disabled: prepare.disabled || prepare.isPreparing,
      items: prepare.chips.map(chip => ({ key: chip.key, label: chip.label, title: chip.title, onPick: () => prepare.onPrepare(chip.key) })),
    });
  }
  if (hd.length > 0) {
    groups.push({
      id: 'download-hd', label: 'Download HD', className: hdTone, ariaLabel: `Download HD: choose a quality for ${title}`,
      items: hd.map(option => ({ key: option.key, label: option.label, title: option.filename, href: option.url, download: option.filename || undefined })),
    });
  }
  if (large.length > 0) {
    groups.push({
      id: 'webtor', label: 'Webtor', className: 'border border-cyan-400/40 bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25',
      ariaLabel: `Webtor: choose a quality for ${title}`,
      items: large.map(row => ({
        ...torrentChip(row),
        onPick: () => {
          const copied = copyMagnetAndOpenWebtor(String(row.magnetUrl || ''));
          setHint(copied ? 'Magnet copied. Paste it on Webtor to stream or download.' : 'Webtor opened, but the magnet could not be copied. Pick another quality and try again.');
        },
      })),
    });
  }

  const open = groups.find(group => group.id === openId && group.items.length > 1);
  const nothing = !play && !prepare && !prepared && groups.length === 0;
  const checking = hdLoading || largeLoading;

  const tile = (group: Group) => {
    const single = group.items.length === 1 ? group.items[0] : null;
    const content = (
      <>
        <span>{group.label}</span>
        {!single && <ChevronDown className={'h-3 w-3 shrink-0 transition-transform ' + (openId === group.id ? 'rotate-180' : '')} />}
      </>
    );
    if (single?.href) {
      return <a key={group.id} href={single.href} target="_blank" rel="noreferrer noopener" download={single.download} title={single.title} aria-label={group.ariaLabel} className={tileClass + ' ' + group.className}>{content}</a>;
    }
    return (
      <button key={group.id} type="button" disabled={group.disabled} aria-label={group.ariaLabel} aria-haspopup={single ? undefined : 'menu'} aria-expanded={single ? undefined : openId === group.id}
        onClick={() => { if (single) single.onPick?.(); else setOpenId(openId === group.id ? '' : group.id); }} className={tileClass + ' ' + group.className}>{content}</button>
    );
  };

  const byId = (id: string) => groups.find(group => group.id === id);
  const tiles = [
    play && (
      <button key="play" type="button" disabled={play.disabled} onClick={play.onClick}
        className={tileClass + ' border border-violet-400/40 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25'}>
        {play.resolving && <Loader2 className="h-3 w-3 animate-spin" />}
        <span>{play.resolving ? 'Resolving…' : 'Play'}</span>
      </button>
    ),
    byId('play-hd') && tile(byId('play-hd')!),
    byId('prepare') && tile(byId('prepare')!),
    byId('download-hd') && tile(byId('download-hd')!),
    byId('webtor') && tile(byId('webtor')!),
  ].filter(Boolean);

  return (
    <div className="min-w-0 space-y-2">
      {tiles.length > 0 && <div className="flex flex-wrap gap-1.5">{tiles}</div>}

      {open && (
        <div role="menu" aria-label={open.ariaLabel} className="max-h-56 overflow-y-auto rounded-lg border border-slate-700 bg-slate-950 p-1">
          {open.items.map(item => item.href ? (
            <a key={item.key} role="menuitem" href={item.href} target="_blank" rel="noreferrer noopener" download={item.download} title={item.title}
              onClick={() => setOpenId('')} className={rowClass}>{item.label}</a>
          ) : (
            <button key={item.key} type="button" role="menuitem" title={item.title} onClick={() => { setOpenId(''); item.onPick?.(); }} className={rowClass}>{item.label}</button>
          ))}
        </div>
      )}

      {prepared && (
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
      )}

      {hint ? <div className="text-[10px] leading-snug text-slate-400" role="status">{hint}</div> : null}
      {playingHd && <HdPlayerModal title={title} option={playingHd} onClose={() => setHdPlayKey('')} />}
      {checking && !nothing && <div className="text-[10px] text-slate-500" role="status">Checking more downloads…</div>}
      {nothing && <div className="text-xs text-slate-400" role="status">{checking ? 'Checking available downloads…' : 'Nothing available yet'}</div>}
    </div>
  );
};
