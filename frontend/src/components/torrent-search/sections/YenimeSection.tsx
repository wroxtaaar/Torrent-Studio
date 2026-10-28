import React from 'react';
import { Loader2, Play, X } from 'lucide-react';
import { TorrentPlayerShell } from '../TorrentPlayerShell.tsx';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export const YenimeSection: React.FC<{ vm: PanelModel }> = ({ vm }) => {
  const {
    yenimeRequest, yenimePlayer, yenimeEpisodePicker, yenimeSeasons, yenimeEpisodes,
    yenimeSelectedSeason, yenimeEpisodesLoading, yenimeEpisodesError, yenimeProvider,
    setYenimeRequest, setYenimeSelectedSeason, setYenimeProvider, closeYenime,
    closeYenimeEpisodePicker, loadYenimeEpisodes, launchYenime,
  } = vm;
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (yenimePlayer) setLoading(true);
  }, [yenimePlayer?.url]);

  const playEpisodeWithProvider = (episodeNumber: number | string) => {
    if (yenimeProvider === 'vidrift') {
      const tmdbId = Number(yenimeEpisodePicker?.tmdbId);
      if (!Number.isInteger(tmdbId) || tmdbId <= 0) {
        setYenimeRequest(current => current ? { ...current, error: 'This anime has no valid TMDB ID for VidRift playback.' } : current);
        return;
      }
      closeYenimeEpisodePicker();
      void vm.playWithNexStream({
        id: tmdbId,
        title: yenimeEpisodePicker?.title || yenimeRequest?.title || 'Anime',
        date: '', overview: '', poster: null, type: 'tv', anime: true,
      }, yenimeSelectedSeason, Number(episodeNumber));
      return;
    }
    if (yenimeRequest) launchYenime(yenimeRequest.malId, String(episodeNumber), yenimeRequest.type);
  };

  return (
    <>
      {yenimeEpisodePicker && yenimeRequest && (
        <div className="fixed inset-0 z-[10001] flex items-center justify-center bg-black/80 p-3 sm:p-6" role="dialog" aria-modal="true" aria-label="Choose an anime episode">
          <div className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl">
            <div className="flex items-start justify-between gap-3 border-b border-slate-800 px-5 py-4">
              <div className="min-w-0">
                <h3 className="text-xl font-bold text-white">Choose an episode</h3>
                <p className="mt-1 truncate text-sm text-slate-400">{yenimeEpisodePicker.title}</p>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex rounded-lg border border-slate-700 bg-slate-900 p-1" role="group" aria-label="Streaming provider">
                  <button type="button" onClick={() => setYenimeProvider('yenime')} className={yenimeProvider === 'yenime' ? 'rounded-md bg-violet-500 px-3 py-1.5 text-xs font-bold text-white' : 'rounded-md px-3 py-1.5 text-xs font-bold text-slate-300 hover:bg-slate-800'}>Yenime</button>
                  <button type="button" onClick={() => setYenimeProvider('vidrift')} className={yenimeProvider === 'vidrift' ? 'rounded-md bg-violet-500 px-3 py-1.5 text-xs font-bold text-white' : 'rounded-md px-3 py-1.5 text-xs font-bold text-slate-300 hover:bg-slate-800'}>VidRift</button>
                </div>
                <button type="button" onClick={closeYenimeEpisodePicker} className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800">Close</button>
              </div>
            </div>

            <div className="border-b border-slate-800 px-4 py-3">
              <div className="grid gap-3 sm:grid-cols-[1fr_150px]">
                <label className="text-sm text-slate-300">Season
                  <select
                    value={yenimeSelectedSeason}
                    onChange={event => {
                      const season = Number(event.target.value);
                      setYenimeSelectedSeason(season);
                      if (yenimeEpisodePicker.tmdbId) void loadYenimeEpisodes(yenimeEpisodePicker.tmdbId, season);
                    }}
                    className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
                  >
                    {yenimeSeasons.length > 0
                      ? yenimeSeasons.map(season => <option key={season.seasonNumber} value={season.seasonNumber}>Season {season.seasonNumber}{season.episodeCount ? ` (${season.episodeCount} episodes)` : ''}</option>)
                      : <option value={1}>Season 1</option>}
                  </select>
                </label>
                <label className="text-sm text-slate-300">MAL ID
                  <input
                    value={yenimeRequest.malId}
                    onChange={event => setYenimeRequest(current => current ? { ...current, malId: event.target.value, error: '' } : current)}
                    inputMode="numeric"
                    className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
                    placeholder="Manual override"
                  />
                </label>
              </div>
              <div className="mt-3 flex items-center justify-between gap-3">
                {yenimeRequest.resolving
                  ? <div className="flex items-center gap-2 text-xs text-violet-200"><Loader2 className="h-3.5 w-3.5 animate-spin" />Resolving MAL ID…</div>
                  : <div className="text-xs text-slate-500">Automatic MAL resolution · manual override available</div>}
                <div className="flex gap-2" role="group" aria-label="Audio type">
                  {(['sub', 'dub'] as const).map(type => (
                    <button key={type} type="button" onClick={() => setYenimeRequest(current => current ? { ...current, type, error: '' } : current)} className={yenimeRequest.type === type ? 'rounded-lg bg-violet-500 px-3 py-1.5 text-xs font-bold text-white' : 'rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-bold text-slate-300 hover:bg-slate-800'}>{type.toUpperCase()}</button>
                  ))}
                </div>
              </div>
              {yenimeRequest.error && <div role="alert" className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{yenimeRequest.error}</div>}
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
              {yenimeEpisodesLoading ? (
                <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-300"><Loader2 className="h-4 w-4 animate-spin" />Loading episodes…</div>
              ) : yenimeEpisodesError ? (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
                  <p>{yenimeEpisodesError}</p>
                  {yenimeEpisodePicker.tmdbId && <button type="button" onClick={() => yenimeEpisodePicker.tmdbId && void loadYenimeEpisodes(yenimeEpisodePicker.tmdbId, yenimeSelectedSeason)} className="mt-2 rounded-lg border border-amber-300/40 px-3 py-1.5 text-xs font-semibold hover:bg-amber-400/10">Retry episode list</button>}
                </div>
              ) : yenimeEpisodes.length > 0 ? (
                <div className="space-y-2">
                  {yenimeEpisodes.map(episode => (
                    <button key={episode.episodeNumber} type="button" onClick={() => playEpisodeWithProvider(episode.episodeNumber)} disabled={yenimeProvider === 'yenime' && (yenimeRequest.resolving || !yenimeRequest.malId)} className="flex w-full items-start gap-3 rounded-xl border border-slate-800 bg-slate-900/70 p-2.5 text-left transition hover:border-violet-400/60 hover:bg-violet-500/10 disabled:cursor-not-allowed disabled:opacity-50 sm:p-3">
                      {episode.still ? (
                        <img src={episode.still} alt="" className="h-16 w-24 shrink-0 rounded-lg object-cover sm:h-20 sm:w-32" />
                      ) : (
                        <div className="h-16 w-24 shrink-0 rounded-lg bg-slate-800 sm:h-20 sm:w-32" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-bold text-white">E{String(episode.episodeNumber).padStart(2, '0')} · {episode.name || 'Episode ' + episode.episodeNumber}</div>
                        {episode.airDate && <div className="mt-1 text-xs text-slate-500">{episode.airDate}</div>}
                        {episode.overview && <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-400">{episode.overview}</p>}
                      </div>
                      <Play className="mt-1 h-4 w-4 shrink-0 text-slate-300" fill="none" />
                    </button>
                  ))}
                </div>
              ) : (
                <div className="flex items-center gap-3 py-4">
                  <label className="text-xs text-slate-400">Episode
                    <input value={yenimeRequest.episode} onChange={event => setYenimeRequest(current => current ? { ...current, episode: event.target.value, error: '' } : current)} inputMode="numeric" className="mt-1 w-24 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
                  </label>
                  <button type="button" disabled={yenimeProvider === 'yenime' && (yenimeRequest.resolving || !yenimeRequest.malId)} onClick={() => playEpisodeWithProvider(yenimeRequest.episode)} className="mt-5 rounded-lg bg-violet-500 px-4 py-2 text-sm font-bold text-white disabled:opacity-50">Play episode</button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {yenimeRequest && !yenimeEpisodePicker && (
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
        <TorrentPlayerShell
          id="yenime-player-container"
          title={`${yenimePlayer.title} · Episode ${yenimePlayer.episode} · ${yenimePlayer.type.toUpperCase()}`}
          loading={loading}
          loadingLabel="Loading Yenime player…"
          closeLabel="Close Yenime player"
          onClose={closeYenime}
          providers={yenimePlayer.tmdbId ? [
            { label: 'Yenime', active: yenimeProvider === 'yenime', onSelect: () => setYenimeProvider('yenime') },
            { label: 'VidRift', active: yenimeProvider === 'vidrift', onSelect: () => {
              closeYenime();
              void vm.playWithNexStream({
                id: yenimePlayer.tmdbId as number,
                title: yenimePlayer.title,
                date: '', overview: '', poster: null, type: 'tv', anime: true,
              }, yenimePlayer.season, yenimePlayer.episode);
            } },
          ] : undefined}
        >
          <iframe key={yenimePlayer.url} src={yenimePlayer.url} title={`Yenime player for ${yenimePlayer.title}`} onLoad={() => setLoading(false)} allow="autoplay; fullscreen; encrypted-media; picture-in-picture" allowFullScreen referrerPolicy="strict-origin-when-cross-origin" className="h-full w-full border-0 bg-black" />
        </TorrentPlayerShell>
      )}
    </>
  );
};
