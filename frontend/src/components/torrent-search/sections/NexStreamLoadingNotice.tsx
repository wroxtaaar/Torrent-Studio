import { Loader2 } from 'lucide-react';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export function VidRiftLoadingNotice({ vm }: { vm: PanelModel }) {
  const { movieCatalogue, nexStreamError, nexStreamLoading, nexStreamPlayer, nexStreamSearchMode } = vm;
  return (
    <>
      {!movieCatalogue && !nexStreamPlayer && nexStreamSearchMode !== 'tv' && (nexStreamLoading || nexStreamError) && (
        <div className="rounded-xl border border-violet-500/20 bg-slate-900/60 px-3 py-2 text-xs text-slate-300">
          {nexStreamLoading && <span className="inline-flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" />Preparing VidRift player…</span>}
          {nexStreamError && <span className="ml-2 text-amber-200">{nexStreamError}</span>}
        </div>
      )}

    </>
  );
}
