import { Loader2, Play, Maximize2 } from 'lucide-react';
import { TvShowCard } from '../TvShowCard.tsx';
import { imdbRatingKey } from '../grouping.ts';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export function NexStreamSection({ vm }: { vm: PanelModel }) {
  const { imdbRatingsByKey, loadNexStreamEpisodes, nexStreamEpisodePicker, nexStreamEpisodePrefetchStatus, nexStreamEpisodes, nexStreamEpisodesError, nexStreamEpisodesLoading, nexStreamError, nexStreamLoading, nexStreamPlayer, nexStreamResolvingId, nexStreamResults, nexStreamSearchMode, nexStreamSeasons, nexStreamSelectedSeason, playWithNexStream, setNexStreamEpisodePicker, setNexStreamPlayer } = vm;
  return (
    <>
      {(nexStreamPlayer || nexStreamSearchMode === 'tv' || nexStreamSearchMode === 'movie') && (
        <section className="space-y-3 rounded-2xl border border-violet-500/30 bg-slate-900/70 p-3 sm:p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-violet-200">{nexStreamSearchMode === 'tv' ? 'NexStream TV Search' : 'NexStream movie matches'}</h3>
              <p className="mt-1 text-[11px] text-slate-400">{nexStreamSearchMode === 'tv' ? 'TV-show results are independent of torrent results. Choose a show to play an episode.' : 'Movie playback options are separate from your existing torrent and Seedr results.'}</p>
            </div>
            {nexStreamLoading && <span className="inline-flex items-center gap-1.5 text-xs text-violet-200"><Loader2 className="h-3.5 w-3.5 animate-spin" />Searching titles…</span>}
          </div>

          {nexStreamError && (
            <div role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">{nexStreamError}</div>
          )}

          {!nexStreamLoading && nexStreamResults.length > 0 && nexStreamSearchMode === 'movie' && (
            <p className="text-xs text-slate-400">NexStream movie playback options are attached to matching torrent title cards below.</p>
          )}

          {nexStreamSearchMode === 'tv' && nexStreamResults.length > 0 && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
              {nexStreamResults.filter(item => item.type === 'tv').map(item => (
                <TvShowCard
                  key={'nexstream-tv-' + item.id}
                  show={{ id: item.id, title: item.title, year: Number(item.date?.slice(0, 4)) || null, posterUrl: item.poster || undefined, overview: item.overview }}
                  imdb={imdbRatingsByKey[imdbRatingKey(item.title, item.date ? item.date.slice(0, 4) : null, 'tv')]}
                  onOpen={() => {
                    if (nexStreamResolvingId === 'tv:' + item.id || nexStreamEpisodePrefetchStatus[String(item.id)] === 'loading') return;
                    void playWithNexStream(item);
                  }}
                  footer={
                    <button
                      type="button"
                      disabled={nexStreamResolvingId === 'tv:' + item.id || nexStreamEpisodePrefetchStatus[String(item.id)] === 'loading'}
                      onClick={() => void playWithNexStream(item)}
                      className="w-full rounded-lg bg-violet-500 px-3 py-2 text-xs font-bold text-white hover:bg-violet-400 disabled:cursor-wait disabled:opacity-60"
                    >
                      {nexStreamResolvingId === 'tv:' + item.id ? <><Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />Resolving…</>
                        : nexStreamEpisodePrefetchStatus[String(item.id)] === 'loading' ? <><Loader2 className="mr-1.5 inline h-3.5 w-3.5 animate-spin" />Preparing episodes…</>
                        : nexStreamEpisodePrefetchStatus[String(item.id)] === 'ready' ? <><Play className="mr-1.5 inline h-3.5 w-3.5" />Choose episode</>
                        : <><Play className="mr-1.5 inline h-3.5 w-3.5" />{nexStreamEpisodePrefetchStatus[String(item.id)] === 'error' ? 'Retry episode data' : 'Choose episode'}</>}
                    </button>
                  }
                />
              ))}
            </div>
          )}

          {nexStreamSearchMode === 'tv' && !nexStreamLoading && !nexStreamError && nexStreamResults.length === 0 && (
            <p className="text-xs text-slate-400">No TV shows found. Try a different title.</p>
          )}

          {nexStreamEpisodePicker && (
            <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/80 p-3 sm:p-6" role="dialog" aria-modal="true" aria-labelledby="nexstream-episode-picker-title">
              <div className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-violet-400/30 bg-slate-950 shadow-2xl">
                <div className="flex items-start justify-between gap-3 border-b border-slate-800 p-4">
                  <div className="min-w-0">
                    <h3 id="nexstream-episode-picker-title" className="text-lg font-bold text-white">Choose an episode</h3>
                    <p className="mt-1 truncate text-sm text-slate-400">{nexStreamEpisodePicker.title}</p>
                  </div>
                  <button type="button" onClick={() => setNexStreamEpisodePicker(null)} className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800">Close</button>
                </div>
                <div className="flex items-center gap-3 border-b border-slate-800 p-4">
                  <label htmlFor="nexstream-season-select" className="shrink-0 text-sm font-semibold text-slate-300">Season</label>
                  <select id="nexstream-season-select" value={nexStreamSelectedSeason} onChange={event => { const season = Number(event.target.value); void loadNexStreamEpisodes(nexStreamEpisodePicker, season); }} className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white">
                    {nexStreamSeasons.map(season => <option key={season.seasonNumber} value={season.seasonNumber}>{season.name || 'Season ' + season.seasonNumber}{season.episodeCount ? ' (' + season.episodeCount + ' episodes)' : ''}</option>)}
                  </select>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
                  {nexStreamEpisodesLoading ? (
                    <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-300"><Loader2 className="h-4 w-4 animate-spin" />Loading episodes…</div>
                  ) : nexStreamEpisodesError ? (
                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
                      <p>{nexStreamEpisodesError}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <button type="button" onClick={() => { if (nexStreamEpisodePicker) void loadNexStreamEpisodes(nexStreamEpisodePicker, nexStreamSelectedSeason); }} className="rounded-lg border border-amber-300/40 px-3 py-1.5 font-semibold hover:bg-amber-400/10">Retry episode list</button>
                        <span className="text-xs text-amber-100/70">You can also enter an episode number below.</span>
                      </div>
                    </div>
                  ) : nexStreamEpisodes.length > 0 ? (
                    <div className="space-y-2">
                      {nexStreamEpisodes.map(episode => (
                        <button key={episode.episodeNumber} type="button" onClick={() => { const selected = nexStreamEpisodePicker; setNexStreamEpisodePicker(null); if (selected) void playWithNexStream(selected, nexStreamSelectedSeason, episode.episodeNumber); }} className="flex w-full items-start gap-3 rounded-xl border border-slate-800 bg-slate-900/70 p-3 text-left transition hover:border-violet-400/60 hover:bg-violet-500/10">
                          {episode.still ? <img src={episode.still} alt="" loading="lazy" className="hidden h-20 w-32 shrink-0 rounded-lg bg-slate-800 object-cover sm:block" onError={event => { event.currentTarget.style.display = 'none'; }} /> : null}
                          <div className="min-w-0 flex-1">
                            <div className="text-sm font-bold text-slate-100">E{String(episode.episodeNumber).padStart(2, '0')} · {episode.name || 'Episode ' + episode.episodeNumber}</div>
                            {episode.airDate && <div className="mt-1 text-[11px] text-slate-500">{episode.airDate}</div>}
                            {episode.overview && <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-slate-400">{episode.overview}</p>}
                          </div>
                          <Play className="mt-1 h-4 w-4 shrink-0 text-violet-300" />
                        </button>
                      ))}
                    </div>
                  ) : !nexStreamEpisodesLoading && !nexStreamEpisodesError ? (
                    <div className="py-8 text-center text-sm text-slate-400">No episode metadata was returned for this season.</div>
                  ) : null}
                  {(nexStreamEpisodesError || (!nexStreamEpisodesLoading && nexStreamEpisodes.length === 0)) && (
                    <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={event => { event.preventDefault(); const form = event.currentTarget; const input = form.elements.namedItem('episodeNumber') as HTMLInputElement; const number = Number(input.value); if (Number.isInteger(number) && number > 0 && nexStreamEpisodePicker) { const selected = nexStreamEpisodePicker; setNexStreamEpisodePicker(null); void playWithNexStream(selected, nexStreamSelectedSeason, number); } }}>
                      <label className="flex-1 text-xs text-slate-400">Episode number<input name="episodeNumber" type="number" min="1" defaultValue="1" className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" /></label>
                      <button type="submit" className="rounded-lg bg-violet-500 px-4 py-2 text-sm font-bold text-white">Play episode</button>
                    </form>
                  )}
                </div>
              </div>
            </div>
          )}

          {nexStreamPlayer && (
            <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/85 p-2 sm:p-5">
              <div className="relative flex max-h-[96vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-violet-400/40 bg-slate-950 shadow-2xl">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-4 py-3 pr-24">
                <div className="min-w-0">
                  <div className="truncate text-xs font-bold text-slate-100">{nexStreamPlayer.title}{nexStreamPlayer.year ? ' (' + nexStreamPlayer.year + ')' : ''}</div>
                </div>

              </div>
              <button
                type="button"
                onClick={() => {
                  const box = document.getElementById('nexstream-player-container');
                  if (document.fullscreenElement) { void document.exitFullscreen(); return; }
                  // Fullscreen our own box: it works even when the player inside the frame cannot go fullscreen.
                  if (box?.requestFullscreen) { void box.requestFullscreen().catch(() => window.open(nexStreamPlayer.url, '_blank', 'noopener,noreferrer')); }
                  else { window.open(nexStreamPlayer.url, '_blank', 'noopener,noreferrer'); }
                }}
                className="absolute right-12 top-2 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-slate-600 bg-slate-900/95 text-slate-200 shadow-lg hover:bg-slate-700"
                aria-label="Full screen"
                title="Full screen (press Esc to leave)"
              >
                <Maximize2 className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => setNexStreamPlayer(null)}
                className="absolute right-2 top-2 z-10 flex h-9 w-9 items-center justify-center rounded-full border border-slate-600 bg-slate-900/95 text-lg font-bold text-slate-200 shadow-lg hover:bg-slate-700"
                aria-label="Close VidRift player"
                title="Close player"
              >
                ×
              </button>
              <div
                id="nexstream-player-container"
                className="min-h-0 flex-1 aspect-video overflow-hidden bg-black max-sm:aspect-video max-sm:max-h-[calc(96vh-90px)]"
              >
                <iframe
                  id="nexstream-player-frame"
                  key={nexStreamPlayer.url}
                  src={nexStreamPlayer.url}
                  title={'VidRift player for ' + nexStreamPlayer.title}
                  allow="autoplay; fullscreen; encrypted-media; picture-in-picture"
                  allowFullScreen
                  referrerPolicy="strict-origin-when-cross-origin"
                  className="h-full w-full border-0"
                />
              </div>
              </div>
            </div>
          )}
        </section>
      )}

    </>
  );
}
