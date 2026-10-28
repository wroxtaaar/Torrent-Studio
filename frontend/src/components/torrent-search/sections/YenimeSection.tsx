import React from 'react';
import { Loader2, Maximize2, X } from 'lucide-react';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export const YenimeSection: React.FC<{ vm: PanelModel }> = ({ vm }) => {
  const { yenimeRequest, yenimePlayer, setYenimeRequest, closeYenime, launchYenime } = vm;
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (yenimePlayer) setLoading(true);
  }, [yenimePlayer?.url]);

  return (
    <>
      {yenimeRequest && (
        <div className="fixed inset-0 z-[10001] flex items-center justify-center bg-black/85 p-4">
          <form
            onSubmit={event => {
              event.preventDefault();
              launchYenime(yenimeRequest.malId, yenimeRequest.episode, yenimeRequest.type);
            }}
            className="w-full max-w-md rounded-2xl border border-violet-400/40 bg-slate-950 p-5 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs font-bold uppercase tracking-wide text-violet-300">Yenime · Anime only</div>
                <h3 className="mt-1 text-lg font-bold text-white">{yenimeRequest.title}</h3>
              </div>
              <button type="button" onClick={closeYenime} className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-white" aria-label="Close Yenime"><X className="h-5 w-5" /></button>
            </div>
            {yenimeRequest.resolving && <div role="status" className="mt-3 text-xs text-violet-200">Resolving MAL ID automatically…</div>}
            <div className="mt-4 grid grid-cols-2 gap-3">
              <label className="text-xs text-slate-400">MAL ID
                <input value={yenimeRequest.malId} onChange={event => setYenimeRequest(current => current ? { ...current, malId: event.target.value, error: '' } : current)} inputMode="numeric" min="1" className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
              </label>
              <label className="text-xs text-slate-400">Episode
                <input value={yenimeRequest.episode} onChange={event => setYenimeRequest(current => current ? { ...current, episode: event.target.value, error: '' } : current)} inputMode="numeric" min="1" className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
              </label>
            </div>
            <div className="mt-3 flex gap-2" role="group" aria-label="Audio type">
              {(['sub', 'dub'] as const).map(type => (
                <button key={type} type="button" onClick={() => setYenimeRequest(current => current ? { ...current, type, error: '' } : current)} className={yenimeRequest.type === type ? 'rounded-lg bg-violet-500 px-4 py-2 text-sm font-bold text-white' : 'rounded-lg border border-slate-700 bg-slate-950 px-4 py-2 text-sm font-bold text-slate-300'}>{type.toUpperCase()}</button>
              ))}
            </div>
            {yenimeRequest.error && <div role="alert" className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{yenimeRequest.error}</div>}
            <button type="submit" disabled={yenimeRequest.resolving} className="mt-4 w-full rounded-lg bg-violet-500 px-4 py-2 text-sm font-bold text-white hover:bg-violet-400 disabled:cursor-not-allowed disabled:opacity-50">Open Yenime player</button>
          </form>
        </div>
      )}

      {yenimePlayer && (
        <div className="fixed inset-0 z-[10002] flex items-center justify-center bg-black/90 p-2 sm:p-5">
          <div id="yenime-player-container" className="relative flex max-h-[96vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-violet-400/40 bg-slate-950 shadow-2xl aspect-video">
            <div className="absolute left-2 top-2 z-10 rounded-md border border-slate-700 bg-slate-950/95 px-3 py-2 text-xs text-white">{yenimePlayer.title} · Episode {yenimePlayer.episode} · {yenimePlayer.type.toUpperCase()}</div>
            <button type="button" onClick={() => {
              const box = document.getElementById('yenime-player-container');
              if (document.fullscreenElement) void document.exitFullscreen();
              else if (box?.requestFullscreen) void box.requestFullscreen().catch(() => window.open(yenimePlayer.url, '_blank', 'noopener,noreferrer'));
              else window.open(yenimePlayer.url, '_blank', 'noopener,noreferrer');
            }} className="absolute right-12 top-2 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-slate-600 bg-slate-900/95 text-slate-200" aria-label="Fullscreen Yenime player"><Maximize2 className="h-4 w-4" /></button>
            <button type="button" onClick={closeYenime} className="absolute right-2 top-2 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-slate-600 bg-slate-900/95 text-slate-200" aria-label="Close Yenime player"><X className="h-4 w-4" /></button>
            {loading && <div role="status" className="absolute inset-0 z-[1] flex items-center justify-center bg-black/70 text-sm text-slate-200"><Loader2 className="mr-2 h-5 w-5 animate-spin" />Loading Yenime player…</div>}
            <iframe key={yenimePlayer.url} src={yenimePlayer.url} title={`Yenime player for ${yenimePlayer.title}`} onLoad={() => setLoading(false)} allow="autoplay; fullscreen; encrypted-media; picture-in-picture" allowFullScreen referrerPolicy="strict-origin-when-cross-origin" className="h-full w-full border-0 bg-black" />
          </div>
        </div>
      )}
    </>
  );
};
