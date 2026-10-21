import React from 'react';
import { FolderDown, Loader2 } from 'lucide-react';
import { formatBytes } from '../../utils/formatters.ts';
import type { PanelModel } from './useAddMagnetModel.tsx';

export function AddMagnetFooter({ vm }: { vm: PanelModel }) {
  const { handleSubmit, inspectedFiles, isInspecting, isLoading, isSingleFile, onClose, selectedCount, totalSelectedSize } = vm;
  return (
    <>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 px-3 sm:px-5 py-3 border-t border-slate-800 bg-slate-900/95">
          <div className="text-[11px] sm:text-xs text-slate-400 w-full sm:w-auto">
            {isSingleFile && selectedCount > 0 ? (
              <span className="text-amber-300">
                Seedr selection is based on the checked files.
              </span>
            ) : isSingleFile && inspectedFiles.length > 0 ? (
              <span>Ready to download</span>
            ) : selectedCount > 0 ? (
              <span>Downloading <strong className="text-cyan-400">{selectedCount}</strong> file(s) ({formatBytes(totalSelectedSize)}) • {inspectedFiles.length - selectedCount} skipped</span>
            ) : inspectedFiles.length > 0 ? (
              <span className="text-rose-400">No files selected</span>
            ) : (
              <span>Paste a magnet link or torrent hash to load the file list</span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300 transition"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                void handleSubmit({ preventDefault: () => {} } as React.FormEvent);
              }}
              disabled={
                isLoading
              }
              className="flex-1 sm:flex-none px-4 sm:px-5 py-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 disabled:cursor-not-allowed text-slate-950 text-xs font-bold transition flex items-center gap-2 shadow-lg shadow-cyan-500/20"
            >
              {isInspecting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <FolderDown className="w-4 h-4" />
              )}
              <span>
                {isLoading ? 'Sending to Seedr...' : 'Send Magnet to Seedr'}
              </span>
            </button>
          </div>
        </div>
    </>
  );
}
