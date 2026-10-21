import { Loader2 } from 'lucide-react';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export function SearchingBanner({ vm }: { vm: PanelModel }) {
  const { catalogueBuildProgress, isPresetCatalogueAction, isSearching } = vm;
  return (
    <>
      {isSearching && (
        <div className="p-5 sm:p-7 rounded-xl sm:rounded-2xl bg-slate-900 border border-slate-800 flex flex-col items-center justify-center gap-3">
          <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
          <div className="text-sm font-semibold text-slate-200">{catalogueBuildProgress ? 'Loading movie catalogue...' : isPresetCatalogueAction ? 'Loading catalogue...' : 'Searching torrents...'}</div>
          <div className="text-xs text-slate-500 text-center">{catalogueBuildProgress || 'Loading the selected catalogue. Please wait for the results.'}</div>
        </div>
      )}

    </>
  );
}
