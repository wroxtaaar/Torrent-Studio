import { FileCheck, Film, Music, FileArchive, FileText, CheckSquare, Square, HelpCircle } from 'lucide-react';
import { formatBytes } from '../../utils/formatters.ts';
import type { PanelModel } from './useAddMagnetModel.tsx';

export function InspectedFilesSection({ vm }: { vm: PanelModel }) {
  const { inspectedFiles, inspectionSource, isSingleFile, selectAll, selectOnlyAudio, selectOnlyVideos, selectedCount, toggleFile, totalSelectedSize, totalTorrentSize } = vm;
  return (
    <>
          {inspectedFiles.length > 0 && (
            isSingleFile ? (
              <div className="rounded-xl bg-slate-950/90 border border-slate-800/90 p-3.5 shadow-inner">
                <div className="flex items-start gap-3">
                  <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/20 shrink-0">
                    {inspectedFiles[0].type === 'video' && <Film className="w-5 h-5 text-indigo-400" />}
                    {inspectedFiles[0].type === 'audio' && <Music className="w-5 h-5 text-cyan-400" />}
                    {inspectedFiles[0].type === 'document' && <FileText className="w-5 h-5 text-emerald-400" />}
                    {inspectedFiles[0].type === 'archive' && <FileArchive className="w-5 h-5 text-amber-400" />}
                    {inspectedFiles[0].type === 'other' && <HelpCircle className="w-5 h-5 text-slate-400" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[11px] font-semibold text-cyan-400 mb-1">Torrent file</div>
                    <div className="text-sm font-semibold text-slate-100 break-words">
                      {inspectedFiles[0].name}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400 font-mono">
                      <span>{formatBytes(inspectedFiles[0].size)}</span>
                      <span className="text-slate-600">•</span>
                      <span>{inspectedFiles[0].type}</span>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <>
          {inspectedFiles.length > 0 && (
            <div className="rounded-xl bg-slate-950/90 border border-slate-800/90 overflow-hidden shadow-inner">
              {/* Header with question and bulk controls */}
              <div className="p-3.5 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between flex-wrap gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <FileCheck className="w-4 h-4 text-cyan-400" />
                    <span className="text-xs font-bold text-white">
                      Which files do you want to download? ({inspectedFiles.length} files found)
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    {inspectionSource && (
                      <span className="text-cyan-400 font-medium mr-2">{inspectionSource} •</span>
                    )}
                    Only checked files will be downloaded. Unchecked files will be skipped.
                  </p>
                </div>

                {/* Bulk selection pills */}
                <div className="flex items-center gap-1.5 text-xs">
                  <button
                    type="button"
                    onClick={() => selectAll(true)}
                    className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition text-[11px] font-medium"
                  >
                    Select All ({inspectedFiles.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => selectAll(false)}
                    className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition text-[11px] font-medium"
                  >
                    Deselect All
                  </button>
                  <button
                    type="button"
                    onClick={selectOnlyVideos}
                    className="px-2 py-1 rounded-lg bg-indigo-950/60 border border-indigo-500/30 text-indigo-300 hover:text-indigo-200 transition text-[11px] font-medium"
                  >
                    Videos Only
                  </button>
                  {inspectedFiles.some(f => f.type === 'audio') && (
                    <button
                      type="button"
                      onClick={selectOnlyAudio}
                      className="px-2 py-1 rounded-lg bg-cyan-950/60 border border-cyan-500/30 text-cyan-300 hover:text-cyan-200 transition text-[11px] font-medium"
                    >
                      Audio Only
                    </button>
                  )}
                </div>
              </div>

              {/* File item list */}
              <div className="max-h-60 overflow-y-auto divide-y divide-slate-800/60 p-1">
                {[...inspectedFiles]
                  .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }))
                  .map((file) => (
                  <div
                    key={file.index}
                    onClick={() => toggleFile(file.index)}
                    className={`flex items-center justify-between p-2.5 rounded-lg cursor-pointer transition select-none ${
                      file.selected
                        ? 'bg-cyan-950/20 hover:bg-cyan-950/30 text-slate-100'
                        : 'hover:bg-slate-900/50 text-slate-500 opacity-60'
                    }`}
                  >
                    <div className="flex items-center gap-3 overflow-hidden pr-2">
                      <div className="shrink-0">
                        {file.selected ? (
                          <CheckSquare className="w-4 h-4 text-cyan-400" />
                        ) : (
                          <Square className="w-4 h-4 text-slate-600" />
                        )}
                      </div>
                      <div className="shrink-0">
                        {file.type === 'video' && <Film className="w-4 h-4 text-indigo-400" />}
                        {file.type === 'audio' && <Music className="w-4 h-4 text-cyan-400" />}
                        {file.type === 'document' && <FileText className="w-4 h-4 text-emerald-400" />}
                        {file.type === 'archive' && <FileArchive className="w-4 h-4 text-amber-400" />}
                        {file.type === 'other' && <HelpCircle className="w-4 h-4 text-slate-400" />}
                      </div>
                      <span className={`text-xs font-mono truncate ${file.selected ? 'font-medium text-slate-200' : 'line-through text-slate-500'}`}>
                        {file.name}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded ${
                        file.selected
                          ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                          : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                      }`}>
                        {file.selected ? '✓ Download' : '✕ Skip'}
                      </span>
                      <span className="font-mono text-xs text-slate-300 w-20 text-right">
                        {formatBytes(file.size)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Selection summary bar */}
              <div className="p-2.5 bg-slate-950 border-t border-slate-800 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1.5 text-[11px] sm:text-xs text-slate-400">
                <span>
                  Selected: <strong className="text-cyan-400">{selectedCount}</strong> of {inspectedFiles.length} files ({inspectedFiles.length - selectedCount} skipped)
                </span>
                <span>
                  Selected Download Size: <strong className="text-cyan-400 font-mono">{formatBytes(totalSelectedSize)}</strong> / {formatBytes(totalTorrentSize)} total
                </span>
              </div>
              <div className="px-3 py-2 bg-slate-900/60 border-t border-slate-800 text-[10px] text-slate-500">
                Seedr receives the torrent after you select files. Torrent Studio sends the selected-file bitmap so only checked files are requested.
              </div>

              </div>
          )}
              </>
            )
          )}
    </>
  );
}
