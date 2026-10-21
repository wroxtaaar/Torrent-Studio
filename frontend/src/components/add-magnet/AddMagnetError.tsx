import { AlertCircle } from 'lucide-react';
import { TorrentSourceInput } from './TorrentSourceInput.tsx';
import type { PanelModel } from './useAddMagnetModel.tsx';

export function AddMagnetError({ vm }: { vm: PanelModel }) {
  const { error } = vm;
  return (
    <>
          {error && (
            <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex items-center gap-2.5">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span className="font-medium">{error}</span>
            </div>
          )}

          {/* Torrent source */}
          <TorrentSourceInput vm={vm} />
    </>
  );
}
