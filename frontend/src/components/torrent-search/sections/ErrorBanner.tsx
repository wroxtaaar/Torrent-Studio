import { AlertCircle } from 'lucide-react';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export function ErrorBanner({ vm }: { vm: PanelModel }) {
  const { error } = vm;
  return (
    <>
      {error && (
        <div className="p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs flex items-start gap-2.5">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold">{error}</div>
            {error.toLowerCase().includes('configured') ? (
              <div className="text-amber-400/80 mt-1">
                Try the full movie or series title, and include a year or season/episode when needed.
              </div>
            ) : null}
          </div>
        </div>
      )}

    </>
  );
}
