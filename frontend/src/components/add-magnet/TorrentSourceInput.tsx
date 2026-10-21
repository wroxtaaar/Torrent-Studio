import { Link2, Copy, FileDown, Loader2, Check } from 'lucide-react';
import type { PanelModel } from './useAddMagnetModel.tsx';

export function TorrentSourceInput({ vm }: { vm: PanelModel }) {
  const { copiedMagnet, handleCopyMagnet, handleDownloadTorrent, handleInputChange, inspectedHash, isInspecting, isSearchGrab, magnetInput, setError, setInspectedFiles, setInspectedHash, setInspectedTorrentName, setInspectionSource, setMagnetInput } = vm;
  return (
    <>
          {isSearchGrab ? (
            <div className="rounded-xl bg-slate-950/80 border border-slate-800 p-3">
              <div className="flex items-center gap-2 mb-2">
                <Link2 className="w-4 h-4 text-cyan-400" />
                <span className="text-xs font-semibold text-slate-200">Torrent Link</span>
              </div>
              <div className="flex flex-col sm:flex-row gap-2">
                <button
                  type="button"
                  onClick={() => void handleCopyMagnet()}
                  className="flex-1 px-3 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-cyan-400 text-xs font-semibold transition flex items-center justify-center gap-2"
                >
                  {copiedMagnet ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  {copiedMagnet ? 'Magnet Copied' : 'Copy Magnet Link'}
                </button>
                <button
                  type="button"
                  onClick={() => void handleDownloadTorrent()}
                  disabled={!inspectedHash}
                  className="flex-1 px-3 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-semibold transition flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <FileDown className="w-4 h-4" />
                  Download .torrent
                </button>
              </div>
            </div>
          ) : (
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                Magnet URI / Torrent Hash
              </label>
              <textarea
                rows={2}
                value={magnetInput}
                onPaste={(e) => {
                  const pasted = e.clipboardData.getData('text').trim();
                  if (!/^magnet:\?/i.test(pasted) && !/^[a-f0-9]{40}$/i.test(pasted)) return;
                  e.preventDefault();
                  setMagnetInput(pasted);
                  setInspectedFiles([]);
                  setInspectedHash('');
                  setInspectedTorrentName('');
                  setError('');
                  setInspectionSource('Ready to send directly to Seedr.');
                }}
                onChange={(e) => handleInputChange(e.target.value)}
                placeholder="Paste magnet:?xt=urn:btih:... or torrent hash"
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-slate-200 placeholder-slate-500 text-xs font-mono focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition resize-none"
              />
              {isInspecting && (
                <div className="mt-2 text-cyan-400 flex items-center gap-1.5 text-xs font-medium animate-pulse">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span className="text-[11px]">Resolving...</span>
                </div>
              )}
            </div>
          )}



          {/* File details / selective file selection */}
    </>
  );
}
