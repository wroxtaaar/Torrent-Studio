import { Download, Copy, Check, Music, Video, X, Minimize2 } from 'lucide-react';
import { formatBytes } from '../../utils/formatters.ts';
import type { PanelModel } from './useMediaPlayerModel.tsx';

export function PlayerHeader({ vm }: { vm: PanelModel }) {
  const { copied, copyStreamUrl, file, isFullscreen, isVideo, onClose, onToggleMinimize } = vm;
  return (
    <>
        <div className={`${isFullscreen ? 'hidden' : 'flex'} items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900/90 z-10`}>
          <div className="flex items-center gap-3 overflow-hidden">
            <div className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400">
              {isVideo ? <Video className="w-5 h-5" /> : <Music className="w-5 h-5" />}
            </div>
            <div className="truncate">
              <h3 className="text-sm md:text-base font-semibold text-slate-100 truncate">{file.name}</h3>
              <p className="text-xs text-slate-400 flex items-center gap-2">
                <span>{formatBytes(file.size)}</span>
                <span>•</span>
                <span className="text-emerald-400 font-medium">
                  Direct Browser Streaming
                </span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={copyStreamUrl}
              className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300 flex items-center gap-1.5 transition"
              title="Copy Direct Streaming Link"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              <span className="hidden sm:inline">{copied ? 'Copied' : 'Stream URL'}</span>
            </button>

            <a
              href={file.downloadUrl}
              download={file.name}
              className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300 flex items-center gap-1.5 transition"
              title="Direct Download File"
            >
              <Download className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Download</span>
            </a>

            <button
              onClick={onToggleMinimize}
              className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition"
              title="Minimize to Floating Player"
            >
              <Minimize2 className="w-4 h-4" />
            </button>

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition"
              title="Close Player"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>
    </>
  );
}
