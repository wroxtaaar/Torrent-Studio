import { Play, Pause, Volume2, VolumeX, Maximize, Minimize, RotateCcw, RotateCw, PictureInPicture2, Gauge, Captions, Languages, Loader2, Timer, Minus, Plus } from 'lucide-react';
import { formatDuration } from '../../utils/formatters.ts';
import { ExternalPlayerButtons } from './ExternalPlayerButtons.tsx';
import { seekGradient } from './playerExtras.ts';
import type { PanelModel } from './useMediaPlayerModel.tsx';

const iconBtn = 'rounded-full bg-slate-800/80 p-2.5 text-slate-300 transition hover:bg-slate-700 hover:text-white';
const pill = 'inline-flex shrink-0 items-center gap-1.5 rounded-full border border-slate-700/80 bg-slate-800/80 px-3 py-1.5 text-xs font-semibold shadow-sm';

export function PlayerControlsBar({ vm }: { vm: PanelModel }) {
  const { audioTracks, bufferedEnd, currentTime, duration, file, formatTrackLabel, fullscreenControlsVisible, handleAudioTrackChange, handleSeek, handleSpeedChange, handleSubtitleTrackChange, handleVolume, hlsSubtitleTracks, isFullscreen, isMuted, isPlaying, isVideo, playbackSpeed, selectedAudioIndex, selectedHlsSubtitleIndex, selectedSubtitleIndex, setSubtitleOffset, setSubtitleSyncOpen, skip, subtitleOffset, subtitleSyncOpen, subtitleTracks, toggleFullscreen, toggleMute, togglePip, togglePlay, tracksLoading, volume } = vm;
  return (
    <>
        <div
          onClick={(event) => event.stopPropagation()}
          className={`p-3 sm:p-4 bg-slate-900/95 border-t border-slate-800 flex flex-col gap-3 ${
            isFullscreen
              ? 'absolute bottom-0 left-0 right-0 z-20 backdrop-blur-md transition-opacity duration-200 ' +
                (fullscreenControlsVisible ? 'opacity-100' : 'opacity-0 pointer-events-none')
              : ''
          }`}
        >
          {/* Scrubber and time */}
          <div className="flex flex-col gap-1">
            <input
              type="range"
              min={0}
              max={duration || file.duration || 100}
              value={currentTime}
              onChange={handleSeek}
              style={{ background: seekGradient(currentTime, bufferedEnd, duration || file.duration || 0) || undefined }}
              aria-label="Seek"
              className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-slate-800 accent-cyan-400 transition-all hover:h-2"
            />
            <div className="flex justify-between font-mono text-[11px] text-slate-400">
              <span>{formatDuration(currentTime)}</span>
              <span>{formatDuration(duration || file.duration || 0)}</span>
            </div>
          </div>

          {/* Transport: playback on the left, volume in the middle, view buttons on the right */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex shrink-0 items-center gap-1.5">
              <button onClick={() => skip(-10)} className={iconBtn} title="Rewind 10 seconds"><RotateCcw className="h-4 w-4" /></button>
              <button onClick={togglePlay} className="rounded-full bg-cyan-500 p-3 text-slate-950 shadow-lg shadow-cyan-500/30 transition hover:bg-cyan-400" title={isPlaying ? 'Pause' : 'Play'}>
                {isPlaying ? <Pause className="h-5 w-5 fill-current" /> : <Play className="h-5 w-5 fill-current" />}
              </button>
              <button onClick={() => skip(10)} className={iconBtn} title="Forward 10 seconds"><RotateCw className="h-4 w-4" /></button>
            </div>

            <div className="flex min-w-0 flex-1 items-center justify-center gap-1.5">
              <button onClick={toggleMute} className="rounded-lg p-1.5 text-slate-400 hover:text-slate-200" title={isMuted ? 'Unmute' : 'Mute'}>
                {isMuted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
              </button>
              <input type="range" min={0} max={1} step={0.05} value={isMuted ? 0 : volume} onChange={handleVolume} aria-label="Volume"
                className="h-1 w-14 min-w-0 cursor-pointer appearance-none rounded-full bg-slate-800 accent-cyan-400 sm:w-24" />
            </div>

            <div className="flex shrink-0 items-center gap-1.5">
              {isVideo && <button onClick={togglePip} className={iconBtn} title="Picture in Picture"><PictureInPicture2 className="h-4 w-4" /></button>}
              <button onClick={toggleFullscreen} className={iconBtn} title="Fullscreen">
                {isFullscreen ? <Minimize className="h-4 w-4" /> : <Maximize className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {/* Options: audio, subtitles, speed, open in another player. Scrolls sideways instead of wrapping. */}
          <div className="-mx-1 flex items-center gap-1.5 overflow-x-auto px-1 pb-0.5 [scrollbar-width:none]">
            {tracksLoading && (
              <div className={pill + ' text-slate-400'}>
                <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-400" />Tracks
              </div>
            )}

            {audioTracks.length > 1 && (
              <label className={pill}>
                <Languages className="h-4 w-4 shrink-0 text-cyan-400" />
                <select
                  value={selectedAudioIndex !== undefined ? selectedAudioIndex : (audioTracks[0]?.index ?? '')}
                  onChange={(e) => handleAudioTrackChange(e.target.value)}
                  className="w-[clamp(90px,28vw,170px)] min-w-0 bg-transparent text-xs font-semibold text-slate-100 outline-none [color-scheme:dark]"
                  title="Audio track"
                >
                  {audioTracks.map((track, index) => (
                    <option key={track.index} value={track.index} className="bg-slate-900 text-slate-100">
                      {formatTrackLabel(track, index, 'Audio')}{track.default ? ' · Default' : ''}
                    </option>
                  ))}
                </select>
              </label>
            )}

            {isVideo && (
              <label className={pill}>
                <Captions className="h-4 w-4 shrink-0 text-cyan-400" />
                <select
                  disabled={tracksLoading || (hlsSubtitleTracks.length === 0 && subtitleTracks.length === 0)}
                  value={selectedHlsSubtitleIndex !== undefined ? 'hls:' + selectedHlsSubtitleIndex : selectedSubtitleIndex !== undefined ? 'external:' + selectedSubtitleIndex : 'off'}
                  onChange={(e) => handleSubtitleTrackChange(e.target.value)}
                  className="w-[clamp(80px,24vw,170px)] min-w-0 bg-transparent text-xs font-semibold text-slate-100 outline-none disabled:cursor-not-allowed disabled:text-slate-500 [color-scheme:dark]"
                  title={tracksLoading ? 'Loading subtitles' : 'Subtitles'}
                >
                  <option value="off" className="bg-slate-900 text-slate-100">{tracksLoading ? 'Loading…' : 'Subtitles off'}</option>
                  {hlsSubtitleTracks.map((track, index) => (
                    <option key={'hls-sub-' + track.index} value={'hls:' + track.index} className="bg-slate-900 text-slate-100">{formatTrackLabel(track, index, 'Subtitle')}</option>
                  ))}
                  {subtitleTracks.map((track, index) => (
                    <option key={'external-sub-' + track.index} value={'external:' + track.index} className="bg-slate-900 text-slate-100">{formatTrackLabel(track, index, 'Subtitle')}</option>
                  ))}
                </select>
              </label>
            )}

            {isVideo && subtitleTracks.length > 0 && selectedSubtitleIndex !== undefined && (
              <div className="relative shrink-0">
                <button
                  type="button"
                  onClick={() => setSubtitleSyncOpen(prev => !prev)}
                  className={pill + (subtitleOffset !== 0 ? ' !border-cyan-500/60 !bg-cyan-500/10 text-cyan-300' : ' text-slate-300 hover:text-white')}
                  title="Adjust subtitle timing"
                >
                  <Timer className="h-4 w-4" />
                  {subtitleOffset !== 0 && <span>{subtitleOffset > 0 ? '+' : ''}{subtitleOffset.toFixed(1)}s</span>}
                </button>
                    {subtitleSyncOpen && (
                      <div className="fixed bottom-20 right-4 z-[9999] w-64 rounded-xl border border-slate-700 bg-slate-900 p-3 shadow-2xl">
                        <div className="mb-2 flex items-center justify-between">
                          <span className="text-xs font-semibold text-slate-200">Subtitle Sync</span>
                          <button
                            type="button"
                            onClick={() => { setSubtitleOffset(0); setSubtitleSyncOpen(false); }}
                            className="text-[11px] font-medium text-slate-400 hover:text-white"
                          >
                            Reset
                          </button>
                        </div>
                        <div className="mb-3 text-center text-sm font-bold text-cyan-300">
                          {subtitleOffset > 0 ? '+' : ''}{subtitleOffset.toFixed(1)}s
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <button
                            type="button"
                            onClick={() => setSubtitleOffset(prev => Math.max(-30, Number((prev - 0.1).toFixed(1))))}
                            className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-slate-800 px-2 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700"
                            title="Subtitles earlier"
                          >
                            <Minus className="h-3.5 w-3.5" /> 0.1s
                          </button>
                          <button
                            type="button"
                            onClick={() => setSubtitleOffset(prev => Math.min(30, Number((prev + 0.1).toFixed(1))))}
                            className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-slate-800 px-2 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700"
                            title="Subtitles later"
                          >
                            <Plus className="h-3.5 w-3.5" /> 0.1s
                          </button>
                        </div>
                        <div className="mt-2 text-center text-[10px] text-slate-500">−30s to +30s</div>
                      </div>
                    )}
              </div>
            )}

            {/* Speed: one pill that steps through the speeds */}
            <button
              type="button"
              onClick={() => { const speeds = [0.75, 1, 1.25, 1.5, 2]; handleSpeedChange(speeds[(speeds.indexOf(playbackSpeed) + 1) % speeds.length]); }}
              className={pill + ' font-mono font-bold ' + (playbackSpeed !== 1 ? '!border-cyan-500/60 !bg-cyan-500/10 text-cyan-300' : 'text-slate-200')}
              title="Playback speed (tap to change)"
              aria-label={'Playback speed ' + playbackSpeed + 'x'}
            >
              <Gauge className="h-4 w-4 text-cyan-400" />{playbackSpeed}x
            </button>

            {isVideo && file.downloadUrl && <ExternalPlayerButtons url={file.downloadUrl} className="shrink-0" />}
          </div>
        </div>
    </>
  );
}
