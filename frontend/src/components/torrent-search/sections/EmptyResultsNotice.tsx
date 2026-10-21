import { Search } from 'lucide-react';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export function EmptyResultsNotice({ vm }: { vm: PanelModel }) {
  const { error, groupedResults, isSearching, movieCatalogue, results, searched } = vm;
  return (
    <>
      {!movieCatalogue && !isSearching && searched && groupedResults.length === 0 && !error && (
        <div className="py-14 text-center rounded-2xl bg-slate-900 border border-slate-800">
          <Search className="w-10 h-10 text-slate-700 mx-auto mb-3" />
          <h3 className="text-sm font-bold text-slate-300">
            {results.length > 0 ? 'No results match your filters' : 'No results'}
          </h3>
          <p className="text-xs text-slate-500 mt-1">
            {results.length > 0
              ? 'Try a different resolution or sorting filter.'
              : 'Try a broader search term or change your filters.'}
          </p>
        </div>
      )}
    </>
  );
}
