import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Copy, Download, Loader2, Play } from 'lucide-react';
import { api } from '../api/client.ts';
import type { NuvioStreamOption, TorrentSearchResult } from '../api/types.ts';
import { formatBytes } from '../utils/formatters.ts';
import { torrentQualityDetails, torrentResultKey } from './torrent-search/grouping.ts';
import { WebtorPlayerModal } from './WebtorPlayerModal.tsx';
import { openWebtorDownload } from './torrent-search/webtor.ts';
import { HdPlayerModal } from './HdPlayerModal.tsx';
import { BUCKET_LABELS, BUCKET_ORDER, formatLabelOf, mergeByOrder, nuvioBucket, nuvioOrderValue, orderHdOptions, orderTorrents, resolutionBucket, torrentOrderValue, visibleBuckets, type ResolutionBucket } from './torrent-search/actionOrdering.ts';

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

const tileClass = 'inline-flex w-full items-center justify-center gap-1 whitespace-nowrap rounded-lg px-2 py-1.5 text-[11px] font-bold leading-tight disabled:cursor-not-allowed disabled:opacity-60';
const rowClass = 'flex w-full min-w-0 items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[11px] font-semibold text-slate-200 hover:bg-slate-800';

export const GLOW: Record<ResolutionBucket, { idle: string; active: string }> = {
  '720p': { idle: 'border-sky-400/50 text-sky-200 shadow-[0_0_10px_rgba(56,189,248,0.35)]', active: 'border-sky-300 bg-sky-500/25 text-white shadow-[0_0_18px_rgba(56,189,248,0.8)]' },
  '1080p': { idle: 'border-violet-400/50 text-violet-200 shadow-[0_0_10px_rgba(167,139,250,0.35)]', active: 'border-violet-300 bg-violet-500/25 text-white shadow-[0_0_18px_rgba(167,139,250,0.8)]' },
  '4k': { idle: 'border-emerald-400/50 text-emerald-200 shadow-[0_0_10px_rgba(52,211,153,0.35)]', active: 'border-emerald-300 bg-emerald-500/25 text-white shadow-[0_0_18px_rgba(52,211,153,0.8)]' },
  other: { idle: 'border-slate-500/50 text-slate-300 shadow-[0_0_10px_rgba(148,163,184,0.25)]', active: 'border-slate-300 bg-slate-500/25 text-white shadow-[0_0_16px_rgba(148,163,184,0.6)]' },
};

/** The Download menu: one row of glowing resolution buttons; tapping one lists its torrents (sizes) underneath. */
function DownloadPanel({ group, close }: { group: Group; close: () => void }) {
  const [chosen, setChosen] = useState<ResolutionBucket | null>(null);
  const buckets = group.buckets || [];
  const shown = buckets.find(entry => entry.bucket === chosen);
  const pills = visibleBuckets(buckets);
  return (
    <div data-action-menu="true" role="group" aria-label={group.ariaLabel}
      className="w-full min-w-0 overflow-hidden rounded-xl border border-slate-700 bg-slate-950/80 p-2">
      <div className="flex gap-2" role="group" aria-label="Choose a resolution">
        {pills.map(entry => {
          const empty = entry.items.length === 0;
          const active = chosen === entry.bucket;
          return (
            <button key={entry.bucket} type="button" disabled={empty} aria-pressed={active} onClick={() => setChosen(active ? null : entry.bucket)}
              title={empty ? `Nothing at ${entry.label}` : `${entry.items.length} ${entry.label} option${entry.items.length === 1 ? '' : 's'}`}
              className={'inline-flex min-w-0 flex-1 items-center justify-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-extrabold leading-tight transition disabled:cursor-not-allowed disabled:opacity-30 disabled:shadow-none ' + (active ? GLOW[entry.bucket].active : 'bg-slate-900/70 hover:bg-slate-800 ' + GLOW[entry.bucket].idle)}>
              <span>{entry.label}</span>
              <ChevronDown aria-hidden="true" className={'h-3 w-3 shrink-0 opacity-80 transition-transform ' + (active ? 'rotate-180' : '')} />
            </button>
          );
        })}
      </div>
      {shown ? (
        <div role="menu" aria-label={`${shown.label} options`} className="mt-2 max-h-48 space-y-0.5 overflow-y-auto overscroll-contain rounded-lg border border-slate-800 bg-slate-900/60 p-1">
          {shown.items.map(item => item.href ? (
            <a key={item.key} role="menuitem" href={item.href} target="_blank" rel="noreferrer noopener" download={item.download} title={item.title}
              onClick={close} className={rowClass}>{item.label}</a>
          ) : (
            <button key={item.key} type="button" role="menuitem" title={item.title} disabled={item.disabled}
              onClick={() => { close(); item.onPick?.(); }} className={rowClass + ' disabled:cursor-not-allowed disabled:opacity-50'}>{item.label}</button>
          ))}
        </div>
      ) : (
        <p className="mt-1.5 px-1 text-center text-[10px] text-slate-500">Choose a resolution to see the options</p>
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
 *   [Play] [Play HD ⌄] [Download ⌄]
 * Play HD and Download each open a floating panel: a row of glowing 720p / 1080p / 4K buttons, and under the chosen one the
 * sizes (biggest first). The rows merge every source (Nuvio files, Seedr-sized torrents, larger torrents) and the source
 * is never shown; with a single row the button acts directly. A button is rendered only when it has rows. The Nuvio and
 * large-torrent lookups start when the card opens (never on page load) and rows appear as they return.
 *   Play      the existing Vidrift / NexStream playback
 *   Play HD   Nuvio file -> pop-up (browser, VLC recommended); torrent up to the size limit -> Seedr; larger -> Webtor player
 *   Download  Nuvio file -> browser download; torrent up to the size limit -> Seedr; larger -> Webtor's page for the torrent
 */
export const MovieActionButtons: React.FC<MovieActionButtonsProps> = ({ title, year, tmdbId, play, prepare, prepared }) => {
  const [large, setLarge] = useState<TorrentSearchResult[]>([]);
  const [hint, setHint] = useState('');
  const [hd, setHd] = useState<NuvioStreamOption[]>([]);
  const [menu, setMenu] = useState<{ id: string; rect: DOMRect; inline: boolean } | null>(null);
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
    document.addEventListener('keydown', onKey);
    // The resolution bar sits inside the card, so scrolling or tapping elsewhere must not close it; only the floating
    // single-list menus need that.
    if (menu.inline) return () => document.removeEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('touchstart', onDown);
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

  // One list for Play and one for Download. Rows from every source are merged by resolution, then size (biggest first);
  // the source is not shown, it only decides what a tap does:
  //   Nuvio file        Play: the browser / VLC pop-up       Download: the browser saves the file straight from its host
  //   torrent <= limit  Seedr: prepared, then played or downloaded from the Prepared row
  //   torrent  > limit  Play: Webtor player in the app       Download: Webtor's page for that torrent
  const sizeText = (size: number) => (size > 0 ? formatBytes(size) : '');
  const rowLabel = (format: string, size: number) => [format || 'Release', sizeText(size)].filter(Boolean).join(' · ');
  const nuvioRows = hd.map(option => ({
    option,
    label: rowLabel(formatLabelOf(torrentQualityDetails({ title: option.filename, quality: '' } as TorrentSearchResult).label), Number(option.size) || 0),
    bucket: nuvioBucket(option.quality),
    order: nuvioOrderValue(option),
  }));
  const seedrItems: MenuItem[] = prepare
    ? prepare.chips.map(chip => ({
        key: chip.key, label: rowLabel(chip.format || '', chip.size || 0), title: chip.title, order: chip.order, bucket: chip.bucket,
        disabled: prepare.disabled, onPick: () => prepare.onPrepare(chip.key),
      }))
    : [];
  const webtorRows = large.map(row => ({ row, chip: torrentChip(row) }));
  const webtorLabel = (chip: MovieActionChip) => rowLabel(chip.format || '', chip.size || 0);

  const playItems = mergeByOrder<MenuItem>(
    nuvioRows.map(entry => ({ key: 'hd:' + entry.option.key, label: entry.label, title: entry.option.filename, order: entry.order, bucket: entry.bucket, onPick: () => setHdPlayKey(entry.option.key) })),
    seedrItems,
    webtorRows.map(({ row, chip }) => ({ key: chip.key, label: webtorLabel(chip), title: chip.title, order: chip.order, bucket: chip.bucket,
      onPick: () => setWebtorKey(String(row.magnetUrl || '') ? torrentResultKey(row) : '') })),
  );
  const downloadItems = mergeByOrder<MenuItem>(
    nuvioRows.map(entry => ({ key: 'hd:' + entry.option.key, label: entry.label, title: entry.option.filename, order: entry.order, bucket: entry.bucket, href: entry.option.url, download: entry.option.filename || undefined })),
    seedrItems,
    webtorRows.map(({ row, chip }) => ({ key: chip.key, label: webtorLabel(chip), title: chip.title, order: chip.order, bucket: chip.bucket,
      onPick: () => {
        const result = openWebtorDownload(String(row.magnetUrl || ''));
        setHint(result.opened
          ? 'Webtor opened on this torrent. Tap Download there. If it says the torrent is not found, paste the magnet (copied).'
          : 'Webtor opened. Paste the magnet (copied) to continue.');
      } })),
  );
  const panelGroup = (id: string, label: string, icon: React.ReactNode, className: string, ariaLabel: string, items: MenuItem[]): Group | null => {
    if (items.length === 0) return null;
    const buckets = BUCKET_ORDER
      .map(bucket => ({ bucket, label: BUCKET_LABELS[bucket], items: items.filter(item => item.bucket === bucket) }))
      .filter(entry => entry.items.length > 0);
    return { id, label, icon, className, ariaLabel, items, disabled: items.length === 1 && Boolean(items[0].disabled), buckets: items.length > 1 ? buckets : undefined };
  };
  const playGroup = panelGroup('play-hd', 'Play HD', <Play className="h-3 w-3 shrink-0 fill-current" />, hdTone, `Play ${title}: choose a resolution, then a size`, playItems);
  const downloadGroup = panelGroup('download', prepare?.isPreparing ? 'Preparing…' : 'Download', <Download className="h-3 w-3 shrink-0" />,
    'bg-cyan-500 text-slate-950 hover:bg-cyan-400', `Download ${title}: choose a resolution, then a size`, downloadItems);
  if (playGroup) groups.push(playGroup);
  if (downloadGroup) groups.push(downloadGroup);

  const open = menu ? groups.find(group => group.id === menu.id && group.items.length > 1) : undefined;
  const nothing = !play && !prepared && groups.length === 0;
  const checking = hdLoading || largeLoading;

  const tile = (group: Group, layout = '') => {
    const single = group.items.length === 1 ? group.items[0] : null;
    const content = (
      <>
        {group.icon}
        <span>{group.label}</span>
        {!single && <ChevronDown className={'h-3 w-3 shrink-0 transition-transform ' + (menu?.id === group.id ? 'rotate-180' : '')} />}
      </>
    );
    if (single?.href) {
      return <a key={group.id} href={single.href} target="_blank" rel="noreferrer noopener" download={single.download} title={single.title} aria-label={group.ariaLabel} className={tileClass + ' ' + group.className + ' ' + layout}>{content}</a>;
    }
    return (
      <button key={group.id} type="button" disabled={group.disabled} aria-label={group.ariaLabel} aria-haspopup={single ? undefined : 'menu'} aria-expanded={single ? undefined : menu?.id === group.id}
        data-action-menu-button={single ? undefined : 'true'}
        onClick={event => {
          if (single) { single.onPick?.(); return; }
          setMenu(menu?.id === group.id ? null : { id: group.id, rect: event.currentTarget.getBoundingClientRect(), inline: Boolean(group.buckets) });
        }} className={tileClass + ' ' + group.className + ' ' + layout}>{content}</button>
    );
  };

  const byId = (id: string) => groups.find(group => group.id === id);
  // A two-column grid: Play and Play HD take half the row each (the whole row when only one of them exists) and
  // Download takes the full row under them.
  const playButtons = (play ? 1 : 0) + (byId('play-hd') ? 1 : 0);
  const playSpan = playButtons === 1 ? 'col-span-2' : 'col-span-1';
  const tiles = [
    play && (
      <button key="play" type="button" disabled={play.disabled} onClick={play.onClick}
        className={tileClass + ' ' + playSpan + ' border border-violet-400/40 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25'}>
        {play.resolving ? <Loader2 className="h-3 w-3 shrink-0 animate-spin" /> : <Play className="h-3 w-3 shrink-0 fill-current" />}
        <span>{play.resolving ? 'Resolving…' : 'Play'}</span>
      </button>
    ),
    byId('play-hd') && tile(byId('play-hd')!, playSpan),
    byId('download') && tile(byId('download')!, 'col-span-2'),
  ].filter(Boolean);

  return (
    <div className="min-w-0 space-y-2">
      {tiles.length > 0 && <div className="grid grid-cols-2 gap-1.5">{tiles}</div>}

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

      {open && menu && open.buckets && <DownloadPanel key={open.id} group={open} close={() => setMenu(null)} />}
      {open && menu && !open.buckets && typeof document !== 'undefined' && createPortal(menuView(open, menu.rect, () => setMenu(null)), document.body)}
      {prepare?.isPreparing && <div className="text-[10px] text-slate-400" role="status">Preparing…</div>}
      {hint ? <div className="text-[10px] leading-snug text-slate-400" role="status">{hint}</div> : null}
      {webtorRow && <WebtorPlayerModal title={title} magnetUrl={String(webtorRow.magnetUrl || '')} label={torrentChip(webtorRow).label} onClose={() => setWebtorKey('')} />}
      {playingHd && <HdPlayerModal title={title} option={playingHd} onClose={() => setHdPlayKey('')} />}
      {checking && !nothing && <div className="text-[10px] text-slate-500" role="status">Checking more downloads…</div>}
      {nothing && <div className="text-xs text-slate-400" role="status">{checking ? 'Checking available downloads…' : 'Nothing available yet'}</div>}
    </div>
  );
};
