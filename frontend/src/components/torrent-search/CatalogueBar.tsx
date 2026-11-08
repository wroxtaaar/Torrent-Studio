import React from 'react';

export interface CatalogueSortOption { key: string; label: string; active: boolean; title?: string }

/**
 * The one pagination bar every catalogue grid uses: Previous, the sort buttons, the page number and Next. Sort buttons
 * are given only to the bar above the grid (the bar below passes no `sort`). Always drawn, even for a single page, so
 * the layout is the same in every section.
 */
export const CatalogueBar: React.FC<{
  page: number;
  totalPages: number;
  onPrev: () => void;
  onNext: () => void;
  /** True while a page is loading or navigation is not possible yet. */
  busy?: boolean;
  sort?: { options: CatalogueSortOption[]; onPick: (key: string) => void };
}> = ({ page, totalPages, onPrev, onNext, busy = false, sort }) => {
  const pages = Math.max(1, totalPages);
  return (
    <div className="flex items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900 px-2.5 py-2" data-catalogue-bar="true">
      <button type="button" disabled={busy || page <= 1} onClick={onPrev}
        className="shrink-0 rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs font-semibold text-slate-300 disabled:opacity-40">
        ← <span className="hidden sm:inline">Previous</span><span className="sm:hidden">Prev</span>
      </button>
      {sort && sort.options.length > 0 && (
        <div className="flex shrink-0 items-center gap-1" role="group" aria-label="Sort">
          {sort.options.map(option => (
            <button key={option.key} type="button" aria-pressed={option.active} title={option.title} onClick={() => sort.onPick(option.key)}
              className={'rounded-lg border px-2 py-1.5 text-[11px] font-bold transition-colors ' + (option.active ? 'border-cyan-400 bg-cyan-500 text-slate-950' : 'border-slate-800 bg-slate-950 text-slate-400 hover:text-slate-200')}>
              {option.label}
            </button>
          ))}
        </div>
      )}
      <span className="min-w-0 truncate text-xs text-slate-400">
        <span className="hidden sm:inline">Page </span>{page}<span className="sm:hidden">/</span><span className="hidden sm:inline"> of </span>{pages.toLocaleString()}
      </span>
      <button type="button" disabled={busy || page >= pages} onClick={onNext}
        className="shrink-0 rounded-lg bg-cyan-500 px-2.5 py-1.5 text-xs font-bold text-slate-950 disabled:opacity-40">Next →</button>
    </div>
  );
};

/** Sort options for the Popular / Rating / Year catalogues (movies and regional series). */
export const CATALOGUE_SORTS = [
  { key: 'popularity', label: 'Popular' },
  { key: 'rating', label: 'Rating' },
  { key: 'year', label: 'Year' },
] as const;
