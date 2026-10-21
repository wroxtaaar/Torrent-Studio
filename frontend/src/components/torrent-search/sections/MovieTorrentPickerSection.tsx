import { X } from 'lucide-react';
import { formatBytes } from '../../../utils/formatters.ts';
import { torrentQualityDetails } from '../grouping.ts';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export function MovieTorrentPickerSection({ vm }: { vm: PanelModel }) {
  const { movieTorrentPickerGroups, movieTorrentSearchTitle, selectMovieTorrentGroup, setMovieTorrentPickerGroups } = vm;
  return (
    <>
      {movieTorrentPickerGroups && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-3 sm:p-5"
          onMouseDown={event => { if (event.target === event.currentTarget) setMovieTorrentPickerGroups(null); }}
        >
          <section role="dialog" aria-modal="true" aria-labelledby="movie-torrent-picker-title" className="flex max-h-[84vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl">
            <header className="flex items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
              <div className="min-w-0">
                <h2 id="movie-torrent-picker-title" className="text-sm font-bold text-slate-100">Choose a torrent release</h2>
                <p className="mt-1 truncate text-xs text-slate-400">{movieTorrentSearchTitle} · {movieTorrentPickerGroups.length} matching releases</p>
                <p className="mt-1 text-[10px] text-slate-500">List view · qualities are combined within each release</p>
              </div>
              <button type="button" onClick={() => setMovieTorrentPickerGroups(null)} className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white" aria-label="Close torrent picker"><X className="h-4 w-4" /></button>
            </header>
            <div className="min-h-0 flex-1 divide-y divide-slate-800 overflow-y-auto">
              {movieTorrentPickerGroups.map(group => {
                const preferred = group.variants[0];
                const qualityNames = group.variants.slice(0, 4).map(variant => torrentQualityDetails(variant).label);
                return (
                  <div key={group.key} className="flex items-center gap-3 px-4 py-3 hover:bg-slate-900/80">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold leading-snug text-slate-100">{group.title}</div>
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
                        <span className="font-semibold text-emerald-400">▲ {Number(preferred.seeders) || 0} seeders</span>
                        <span className="font-semibold text-amber-400">▼ {Number(preferred.leechers) || 0} peers</span>
                        <span className="text-slate-300">{formatBytes(Number(preferred.size) || 0)}</span>
                        {preferred.indexer && <span className="text-slate-500">{preferred.indexer}</span>}
                      </div>
                      <div className="mt-1 text-[10px] text-slate-500">
                        {group.variants.length} quality option{group.variants.length === 1 ? '' : 's'} · {qualityNames.join(', ')}{group.variants.length > 4 ? ', …' : ''}
                      </div>
                    </div>
                    <button type="button" onClick={() => selectMovieTorrentGroup(group)} className="shrink-0 rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 hover:bg-cyan-400">
                      Select
                    </button>
                  </div>
                );
              })}
            </div>
            <footer className="border-t border-slate-800 px-4 py-2.5 text-[10px] text-slate-500">
              Select a release to see its full card and quality picker without leaving the movie catalogue.
            </footer>
          </section>
        </div>
      )}

    </>
  );
}
