import { X } from 'lucide-react';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export function PrepareErrorBanner({ vm }: { vm: PanelModel }) {
  const { prepareError, setPrepareError } = vm;
  return (
    <>
      {prepareError && (
        <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-center justify-between gap-2">
          <span>{prepareError}</span>
          <button type="button" onClick={() => setPrepareError('')} className="shrink-0 p-1 rounded text-slate-400 hover:text-slate-200" aria-label="Dismiss preparation error">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

    </>
  );
}
