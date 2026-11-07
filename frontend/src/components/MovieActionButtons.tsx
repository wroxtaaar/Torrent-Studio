import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Copy, Download, Loader2, Play } from 'lucide-react';
import { api } from '../api/client.ts';
import type { NuvioStreamOption, TorrentSearchResult } from '../api/types.ts';
import { formatBytes } from '../utils/formatters.ts';
import { torrentQualityDetails, torrentResultKey } from './torrent-search/grouping.ts';
import { WebtorPlayerModal } from './WebtorPlayerModal.tsx';
import { HdPlayerModal } from './HdPlayerModal.tsx';
import { BUCKET_LABELS, BUCKET_ORDER, formatLabelOf, mergeByOrder, orderHdOptions, orderTorrents, resolutionBucket, torrentOrderValue, type ResolutionBucket } from './torrent-search/actionOrdering.ts';

export { orderTorrents };

export interface MovieActionChip {
  key: string;
  label: string;
  title?: string;
  /** Sort value (resolution, then size) so lists from different sources can be merged. */
  order?: number;
  /** The resolution button this torrent is listed under, and its source tag (BluRay, WEB-DL...). */
  bucket?: ResolutionBucket;
  format?: string;
  size?: number;
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

interface MenuItem { key: string; label: string; title?: string; href?: string; download?: string; onPick?: () => void; disabled?: boolean; order?: number; bucket?: ResolutionBucket }
interface Group {
  id: string;
  icon?: React.ReactNode;
  label: string;
  className: string;
  ariaLabel: string;
  disabled?: boolean;
  busy?: boolean;
  items: MenuItem[];
  /** Set on the Download button: its menu is one row of resolution buttons; each shows its torrents. */
  buckets?: Array<{ bucket: ResolutionBucket; label: string; items: MenuItem[] }>;
}

const tileClass = 'inline-flex items-center justify-center gap-1 whitespace-nowrap rounded-lg px-2 py-1.5 text-[11px] font-bold leading-tight disabled:cursor-not-allowed disabled:opacity-60';
const rowClass = 'flex w-full min-w-0 items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[11px] font-semibold text-slate-200 hover:bg-slate-800';

const GLOW: Record<ResolutionBucket, { idle: string; active: string }> = {
  '720p': { idle: 'border-sky-400/50 text-sky-200 shadow-[0_0_10px_rgba(56,189,248,0.35)]', active: 'border-sky-300 bg-sky-500/25 text-white shadow-[0_0_18px_rgba(56,189,248,0.8)]' },
  '1080p': { idle: 'border-violet-400/50 text-violet-200 shadow-[0_0_10px_rgba(167,139,250,0.35)]', active: 'border-violet-300 bg-violet-500/25 text-white shadow-[0_0_18px_rgba(167,139,250,0.8)]' },
  '4k': { idle: 'border-emerald-400/50 text-emerald-200 shadow-[0_0_10px_rgba(52,211,153,0.35)]', active: 'border-emerald-300 bg-emerald-500/25 text-white shadow-[0_0_18px_rgba(52,211,153,0.8)]' },
  other: { idle: 'border-slate-500/50 text-slate-300 shadow-[0_0_10px_rgba(148,163,184,0.25)]', active: 'border-slate-300 bg-slate-500/25 text-white shadow-[0_0_16px_rgba(148,163,184,0.6)]' },
};

/** Floating position for a menu opened from `rect`: under the button, above it near the bottom of the screen. */
function menuPlacement(rect: DOMRect, width: number, height: number): React.CSSProperties {
  const viewportWidth = typeof window === 'undefined' ? 360 : window.innerWidth;
  const viewportHeight = typeof window === 'undefined' ? 640 : window.innerHeight;
  const alignRight = rect.left + rect.width / 2 > viewportWidth / 2;
  const above = rect.bottom + height > viewportHeight && rect.top > height;
  return {
    position: 'fixed',
    width: Math.min(width, viewportWidth - 16),
    ...(alignRight ? { right: Math.max(8, viewportWidth - rect.right) } : { left: Math.max(8, rect.left) }),
    ...(above ? { bottom: viewportHeight - rect.top + 4 } : { top: rect.bottom + 4 }),
  };
}

/** The Download menu: one row of glowing resolution buttons; tapping one lists its torrents (sizes) underneath. */
function DownloadPanel({ group, rect, close }: { group: Group; rect: DOMRect; close: () => void }) {
  const [chosen, setChosen] = useState<ResolutionBucket | null>(null);
  const buckets = group.buckets || [];
  const shown = buckets.find(entry => entry.bucket === chosen);
  const pills: Array<{ bucket: ResolutionBucket; label: string; items: MenuItem[] }> = [
    ...(['720p', '1080p', '4k'] as ResolutionBucket[]).map(bucket => buckets.find(entry => entry.bucket === bucket) || { bucket, label: BUCKET_LABELS[bucket], items: [] }),
    ...buckets.filter(entry => entry.bucket === 'other'),
  ];
  return (
    <div data-action-menu="true" role="dialog" aria-label={group.ariaLabel} style={{ ...menuPlacement(rect, 300, 300), touchAction: 'pan-y' }}
      className="z-[100] overflow-hidden rounded-xl border border-slate-700 bg-slate-950/95 p-2.5 shadow-2xl backdrop-blur">
      <div className="flex gap-2" role="group" aria-label="Choose a resolution">
        {pills.map(entry => {
          const empty = entry.items.length === 0;
          const active = chosen === entry.bucket;
          return (
            <button key={entry.bucket} type="button" disabled={empty} aria-pressed={active} onClick={() => setChosen(active ? null : entry.bucket)}
              title={empty ? `No ${entry.label} torrents` : `${entry.items.length} ${entry.label} torrent${entry.items.length === 1 ? '' : 's'}`}
              className={'flex min-w-0 flex-1 flex-col items-center rounded-lg border px-2 py-1.5 text-xs font-extrabold transition disabled:cursor-not-allowed disabled:opacity-30 disabled:shadow-none ' + (active ? GLOW[entry.bucket].active : 'bg-slate-900/70 hover:bg-slate-800 ' + GLOW[entry.bucket].idle)}>
              <span>{entry.label}</span>
              <span className="text-[9px] font-semibold opacity-70">{empty ? '—' : entry.items.length}</span>
            </button>
          );
        })}
      </div>
      {shown ? (
        <div role="menu" aria-label={`${shown.label} torrents`} className="mt-2 max-h-48 space-y-0.5 overflow-y-auto overscroll-contain rounded-lg border border-slate-800 bg-slate-900/60 p-1">
          {shown.items.map(item => (
            <button key={item.key} type="button" role="menuitem" title={item.title} disabled={item.disabled}
              onClick={() => { close(); item.onPick?.(); }} className={rowClass + ' disabled:cursor-not-allowed disabled:opacity-50'}>{item.label}</button>
          ))}
        </div>
      ) : (
        <p className="mt-2 px-1 text-center text-[10px] text-slate-500">Choose a resolution to see the torrents</p>
      )}
    </div>
  );
}

/**
 * One group's quality list, floating just under its button (or above it near the bottom of the screen). It is drawn on
 * document.body so the card never grows and the lists of the other buttons are not affected; one list is open at a time.
 */
function menuView(group: Group, rect: DOMRect, close: () => void): React.ReactElement {
  const viewportWidth = typeof window === 'undefined' ? 360 : window.innerWidth;
  const viewportHeight = typeof window === 'undefined' ? 640 : window.innerHeight;
  const alignRight = rect.left + rect.width / 2 > viewportWidth / 2;
  const above = rect.bottom + 232 > viewportHeight && rect.top > 232;
  const style: React.CSSProperties = {
    position: 'fixed',
    maxWidth: Math.min(288, viewportWidth - 16),
    ...(alignRight ? { right: Math.max(8, viewportWidth - rect.right) } : { left: Math.max(8, rect.left) }),
    ...(above ? { bottom: viewportHeight - rect.top + 4 } : { top: rect.bottom + 4 }),
  };
  return (
    <div data-action-menu="true" role="menu" aria-label={group.ariaLabel} style={{ ...style, touchAction: "pan-y" }}
      className="z-[100] max-h-56 w-max min-w-[9rem] overflow-y-auto overscroll-contain rounded-lg border border-slate-700 bg-slate-950 p-1 shadow-2xl">
      {group.items.map(item => item.href ? (
        <a key={item.key} role="menuitem" href={item.href} target="_blank" rel="noreferrer noopener" download={item.download} title={item.title}
          onClick={close} className={rowClass}>{item.label}</a>
      ) : (
        <button key={item.key} type="button" role="menuitem" title={item.title} disabled={item.disabled} onClick={() => { close(); item.onPick?.(); }} className={rowClass}>{item.label}</button>
      ))}
    </div>
  );
}

/** Quality text for a torrent: "1080p · 3.4 GB". */
export const torrentChip = (row: TorrentSearchResult): MovieActionChip => ({
  key: torrentResultKey(row),
  label: `${torrentQualityDetails(row).label || 'Unknown'} · ${formatBytes(Number(row.size) || 0)}`,
  title: `${row.title} · ▲${Number(row.seeders) || 0}${row.indexer ? ` · ${row.indexer}` : ''}`,
  order: torrentOrderValue(row),
  bucket: resolutionBucket(row),
  format: formatLabelOf(torrentQualityDetails(row).label),
  size: Number(row.size) || 0,
});

/**
 * The action area of a movie's second card (shown under the poster and title):
 *   [Play] [Play HD ⌄] [Download ⌄] [Download HD ⌄]
 * Each ⌄ button opens a list of qualities (best resolution first, then bigger files); picking one runs the action.
 * With a single quality the button runs directly and shows no caret. A button is rendered only when its source has
 * something. The Webtor and HD lookups start when the card opens (never on page load) and their buttons appear when
 * they return.
 *   Play      the existing Vidrift / NexStream playback
 *   Play HD   the Nuvio Streams add-on's file in the browser, with VLC / MX Player as fallback (HdPlayerModal)
 *   Download  one row of glowing 720p / 1080p / 4K buttons; each lists its torrents by size. Up to the size limit goes to Seedr (prepare), larger to Webtor
 *   Download HD  the same files, saved by the browser straight from the file host
 */
export const MovieActionButtons: React.FC<MovieActionButtonsProps> = ({ title, year, tmdbId, play, prepare, prepared }) => {
  const [large, setLarge] = useState<TorrentSearchResult[]>([]);
  const [hint, setHint] = useState('');
  const [hd, setHd] = useState<NuvioStreamOption[]>([]);
  const [menu, setMenu] = useState<{ id: string; rect: DOMRect } | null>(null);
  const [hdPlayKey, setHdPlayKey] = useState('');
  const [webtorKey, setWebtorKey] = useState('');
  const [hdLoading, setHdLoading] = useState(false);
  const [largeLoading, setLargeLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLarge([]); setHd([]); setHint(''); setMenu(null); setHdPlayKey(''); setWebtorKey('');
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

  useEffect(() => {
    if (!menu) return undefined;
    const close = () => setMenu(null);
    const onScroll = (event: Event) => {
      const target = event.target as Element | null;
      if (target?.closest?.('[data-action-menu]')) return;   // scrolling the list itself must not close it
      close();
    };
    const onDown = (event: MouseEvent | TouchEvent) => {
      const target = event.target as Element | null;
      if (target?.closest?.('[data-action-menu]') || target?.closest?.('[data-action-menu-button]')) return;
      close();
    };
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') close(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('touchstart', onDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onScroll, true);   // a fixed menu would drift from its button
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('touchstart', onDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', close);
    };
  }, [menu]);

  const webtorRow = webtorKey ? large.find(row => torrentResultKey(row) === webtorKey) : undefined;
  const playingHd = hd.find(option => option.key === hdPlayKey);
  const hdTone = 'border border-emerald-400/40 bg-emerald-500/15 text-emerald-200 hover:bg-emerald-500/25';
  const groups: Group[] = [];
  if (hd.length > 0) {
    groups.push({
      id: 'play-hd', label: 'Play HD', icon: <Play className="h-3 w-3 shrink-0 fill-current" />, className: hdTone, ariaLabel: `Play HD: choose a quality for ${title}`,
      items: hd.map(option => ({ key: option.key, label: option.label, title: option.filename, onPick: () => setHdPlayKey(option.key) })),
    });
  }
  // Torrents are listed by resolution (720p, 1080p, 4K); each button's menu lists sizes, biggest first. Up to the size
  // limit a pick goes to Seedr (prepared, then played or downloaded from there); larger ones open the Webtor player.
  const rowLabel = (chip: MovieActionChip) => `${chip.format || 'Release'} · ${formatBytes(chip.size || 0)}`;
  const seedrItems: MenuItem[] = !prepared && prepare
    ? prepare.chips.map(chip => ({
        key: chip.key, label: rowLabel(chip), title: chip.title, order: chip.order, bucket: chip.bucket,
        disabled: prepare.disabled || prepare.isPreparing, onPick: () => prepare.onPrepare(chip.key),
      }))
    : [];
  const webtorItems: MenuItem[] = large.map(row => {
    const chip = torrentChip(row);
    return { key: chip.key, label: rowLabel(chip), title: chip.title, order: chip.order, bucket: chip.bucket,
      onPick: () => setWebtorKey(String(row.magnetUrl || '') ? torrentResultKey(row) : '') };
  });
  const torrentItems = mergeByOrder(seedrItems, webtorItems);
  const buckets = BUCKET_ORDER
    .map(bucket => ({ bucket, label: BUCKET_LABELS[bucket], items: torrentItems.filter(item => item.bucket === bucket) }))
    .filter(entry => entry.items.length > 0);
  if (buckets.length > 0) {
    groups.push({
      id: 'download', label: prepare?.isPreparing ? 'Preparing…' : 'Download', icon: <Download className="h-3 w-3 shrink-0" />,
      className: 'bg-cyan-500 text-slate-950 hover:bg-cyan-400', ariaLabel: `Download ${title}: choose a resolution, then a size`,
      items: torrentItems, buckets,
    });
  }

  const open = menu ? groups.find(group => group.id === menu.id && (group.buckets || group.items.length > 1)) : undefined;
  const nothing = !play && !prepared && groups.length === 0;
  const checking = hdLoading || largeLoading;

  const tile = (group: Group) => {
    const single = group.items.length === 1 && !group.buckets ? group.items[0] : null;
    const content = (
      <>
        {group.icon}
        <span>{group.label}</span>
        {!single && <ChevronDown className={'h-3 w-3 shrink-0 transition-transform ' + (menu?.id === group.id ? 'rotate-180' : '')} />}
      </>
    );
    if (single?.href) {
      return <a key={group.id} href={single.href} target="_blank" rel="noreferrer noopener" download={single.download} title={single.title} aria-label={group.ariaLabel} className={tileClass + ' ' + group.className}>{content}</a>;
    }
    return (
      <button key={group.id} type="button" disabled={group.disabled} aria-label={group.ariaLabel} aria-haspopup={single ? undefined : 'menu'} aria-expanded={single ? undefined : menu?.id === group.id}
        data-action-menu-button={single ? undefined : 'true'}
        onClick={event => {
          if (single) { single.onPick?.(); return; }
          setMenu(menu?.id === group.id ? null : { id: group.id, rect: event.currentTarget.getBoundingClientRect() });
        }} className={tileClass + ' ' + group.className}>{content}</button>
    );
  };

  const byId = (id: string) => groups.find(group => group.id === id);
  const tiles = [
    play && (
      <button key="play" type="button" disabled={play.disabled} onClick={play.onClick}
        className={tileClass + ' border border-violet-400/40 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25'}>
        {play.resolving ? <Loader2 className="h-3 w-3 shrink-0 animate-spin" /> : <Play className="h-3 w-3 shrink-0 fill-current" />}
        <span>{play.resolving ? 'Resolving…' : 'Play'}</span>
      </button>
    ),
    byId('play-hd') && tile(byId('play-hd')!),
    byId('download') && tile(byId('download')!),
    byId('download-hd') && tile(byId('download-hd')!),
  ].filter(Boolean);

  return (
    <div className="min-w-0 space-y-2">
      {tiles.length > 0 && <div className="flex flex-wrap gap-1">{tiles}</div>}

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

      {open && menu && typeof document !== 'undefined' && createPortal(open.buckets ? <DownloadPanel key={open.id} group={open} rect={menu.rect} close={() => setMenu(null)} /> : menuView(open, menu.rect, () => setMenu(null)), document.body)}
      {prepare?.isPreparing && <div className="text-[10px] text-slate-400" role="status">Preparing…</div>}
      {hint ? <div className="text-[10px] leading-snug text-slate-400" role="status">{hint}</div> : null}
      {webtorRow && <WebtorPlayerModal title={title} magnetUrl={String(webtorRow.magnetUrl || '')} label={torrentChip(webtorRow).label} onClose={() => setWebtorKey('')} />}
      {playingHd && <HdPlayerModal title={title} option={playingHd} onClose={() => setHdPlayKey('')} />}
      {!checking && !nothing && hd.length === 0 && Number.isInteger(Number(tmdbId)) && Number(tmdbId) > 0 &&
        <div className="text-[10px] text-slate-500" role="status">No HD stream available right now.</div>}
      {checking && !nothing && <div className="text-[10px] text-slate-500" role="status">Checking more downloads…</div>}
      {nothing && <div className="text-xs text-slate-400" role="status">{checking ? 'Checking available downloads…' : 'Nothing available yet'}</div>}
    </div>
  );
};
