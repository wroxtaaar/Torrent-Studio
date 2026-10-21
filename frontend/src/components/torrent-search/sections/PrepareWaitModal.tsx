import { Loader2 } from 'lucide-react';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export function PrepareWaitModal({ vm }: { vm: PanelModel }) {
  const { onOpenProgress, prepareWaitOpen, prepareWaitTitle, setPrepareWaitOpen } = vm;
  return (
    <>
      {prepareWaitOpen && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-slate-950/45 backdrop-blur-sm p-4">
          <div className="w-full max-w-sm rounded-2xl border border-cyan-400/20 bg-slate-900/95 shadow-2xl p-5">
            <div className="flex items-start gap-3">
              <div className="shrink-0 rounded-xl bg-cyan-500/10 border border-cyan-500/20 p-2">
                <Loader2 className="w-5 h-5 text-cyan-300 animate-spin" />
              </div>
              <div className="min-w-0">
                <div className="font-bold text-slate-100 text-sm">Loading is taking a little longer</div>
                <div className="mt-1 text-xs leading-5 text-slate-400">
                  <span className="text-slate-200">{prepareWaitTitle || 'This torrent'}</span> is still being prepared by Seedr. You can explore the app or wait for it to finish.
                </div>
              </div>
            </div>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={() => setPrepareWaitOpen(false)}
                className="flex-1 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-2 text-xs font-semibold transition"
              >
                Explore
              </button>
              <button
                type="button"
                onClick={() => {
                  setPrepareWaitOpen(false);
                  onOpenProgress?.();
                }}
                className="flex-1 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 px-3 py-2 text-xs font-bold transition"
              >
                View loading progress
              </button>
            </div>
          </div>
        </div>
      )}

    </>
  );
}
