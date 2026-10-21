import { Link2, X } from 'lucide-react';
import type { PanelModel } from './useAddMagnetModel.tsx';

export function AddMagnetHeader({ vm }: { vm: PanelModel }) {
  const { onClose } = vm;
  return (
    <>
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800 bg-slate-900/95">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-gradient-to-tr from-cyan-500 to-blue-600 text-slate-950 font-bold shadow-md shadow-cyan-500/20">
              <Link2 className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-100">Add Magnet / .Torrent & Select Files</h3>
              <p className="text-xs text-slate-400">
                Torrent Metadata • Select Files
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
    </>
  );
}
