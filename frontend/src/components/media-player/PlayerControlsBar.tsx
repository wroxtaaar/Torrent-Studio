import { Play, Pause, Volume2, VolumeX, Maximize, Minimize, RotateCcw, RotateCw, ExternalLink, Captions, Languages, Loader2, Timer, Minus, Plus } from 'lucide-react';
import { formatDuration } from '../../utils/formatters.ts';
import type { PanelModel } from './useMediaPlayerModel.tsx';

export function PlayerControlsBar({ vm }: { vm: PanelModel }) {
  const { audioTracks, currentTime, duration, file, formatTrackLabel, fullscreenControlsVisible, handleAudioTrackChange, handleSeek, handleSpeedChange, handleSubtitleTrackChange, handleVolume, hlsSubtitleTracks, isFullscreen, isMuted, isPlaying, isVideo, playbackSpeed, selectedAudioIndex, selectedHlsSubtitleIndex, selectedSubtitleIndex, setSubtitleOffset, setSubtitleSyncOpen, skip, subtitleOffset, subtitleSyncOpen, subtitleTracks, toggleFullscreen, toggleMute, togglePip, togglePlay, tracksLoading, volume } = vm;
  return (
    <>
        <div
          onClick={(event) => event.stopPropagation()}
          className={`p-4 bg-slate-900/95 border-t border-slate-800 flex flex-col gap-3 ${
            isFullscreen
              ? 'absolute bottom-0 left-0 right-0 z-20 backdrop-blur-md transition-opacity duration-200 ' +
                (fullscreenControlsVisible ? 'opacity-100' : 'opacity-0 pointer-events-none')
              : ''
          }`}
        >
          {/* Scrubber and Time */}
          <div className="flex items-center gap-3">
            <span className="text-xs font-mono text-slate-400 w-12 text-right">
              {formatDuration(currentTime)}
            </span>
            <div className="relative flex-1 group">
              <input
                type="range"
                min={0}
                max={duration || file.duration || 100}
                value={currentTime}
                onChange={handleSeek}
                className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-cyan-400 hover:h-2.5 transition-all"
              />
            </div>
            <span className="text-xs font-mono text-slate-400 w-12">
              {formatDuration(duration || file.duration || 0)}
            </span>
          </div>

          {/* Main Controls row */}
          <div className="flex flex-wrap items-center justify-between gap-3 overflow-visible">
            {/* Left: Playback buttons */}
            <div className="flex shrink-0 items-center gap-2">
              <button
                onClick={() => skip(-10)}
                className="p-2 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition"
                title="Rewind 10 seconds"
              >
                <RotateCcw className="w-4 h-4" />
              </button>

              <button
                onClick={togglePlay}
                className="p-3 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold transition shadow-lg shadow-cyan-500/20"
                title={isPlaying ? 'Pause' : 'Play'}
              >
                {isPlaying ? <Pause className="w-5 h-5 fill-current" /> : <Play className="w-5 h-5 fill-current" />}
              </button>

              <button
                onClick={() => skip(10)}
                className="p-2 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition"
                title="Forward 10 seconds"
              >
                <RotateCw className="w-4 h-4" />
              </button>

              {/* Volume */}
              <div className="flex shrink-0 items-center gap-2 ml-2 pl-2 border-l border-slate-800">
                <button
                  onClick={toggleMute}
                  className="p-2 rounded-lg text-slate-400 hover:text-slate-200"
                >
                  {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
                </button>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={isMuted ? 0 : volume}
                  onChange={handleVolume}
                  className="w-16 sm:w-24 h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-cyan-400"
                />
              </div>
            </div>

            {/* Right: Speed, PiP, Fullscreen */}
            <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2 overflow-visible">
              {tracksLoading && (
                <div className="flex items-center gap-1.5 bg-slate-800/80 rounded-lg px-2 py-1.5 text-[11px] text-slate-400">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-cyan-400" />
                  Tracks
                </div>
              )}

              {audioTracks.length > 1 && (
                <label className="flex min-w-0 max-w-full items-center gap-2 rounded-xl border border-slate-700/80 bg-slate-800/90 px-2.5 py-1.5 shadow-sm">
                  <Languages className="h-4 w-4 shrink-0 text-cyan-400" />
                  <span className="hidden text-[10px] font-semibold uppercase tracking-wide text-slate-500 sm:inline">Audio</span>
                  <select
                    value={selectedAudioIndex !== undefined ? selectedAudioIndex : (audioTracks[0]?.index ?? '')}
                    onChange={(e) => handleAudioTrackChange(e.target.value)}
                    className="w-[clamp(100px,18vw,185px)] min-w-0 bg-transparent text-xs font-semibold text-slate-100 outline-none"
                    title="Audio track"
                  >
                    {audioTracks.map((track, index) => (
                      <option key={track.index} value={track.index}>
                        {formatTrackLabel(track, index, 'Audio')}{track.default ? ' · Default' : ''}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {isVideo && (
                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-2 rounded-xl border border-slate-700/80 bg-slate-800/90 px-2.5 py-1.5 shadow-sm">
                  <Captions className="h-4 w-4 shrink-0 text-cyan-400" />
                  <span className="hidden text-[10px] font-semibold uppercase tracking-wide text-slate-500 sm:inline">Subs</span>
                  <select
                    disabled={tracksLoading || (hlsSubtitleTracks.length === 0 && subtitleTracks.length === 0)}
                    value={selectedHlsSubtitleIndex !== undefined ? 'hls:' + selectedHlsSubtitleIndex : selectedSubtitleIndex !== undefined ? 'external:' + selectedSubtitleIndex : 'off'}
                    onChange={(e) => handleSubtitleTrackChange(e.target.value)}
                    className="w-[clamp(95px,16vw,185px)] min-w-0 bg-transparent text-xs font-semibold text-slate-100 outline-none disabled:cursor-not-allowed disabled:text-slate-500 [color-scheme:dark]"
                    title={tracksLoading ? 'Loading subtitles' : 'Subtitles'}
                  >
                    <option value="off" className="bg-slate-900 text-slate-100">{tracksLoading ? 'Loading…' : 'Subtitles Off'}</option>
                    {hlsSubtitleTracks.map((track, index) => (
                      <option key={'hls-sub-' + track.index} value={'hls:' + track.index} className="bg-slate-900 text-slate-100">
                        {formatTrackLabel(track, index, 'Subtitle')}
                      </option>
                    ))}
                    {subtitleTracks.map((track, index) => (
                      <option key={'external-sub-' + track.index} value={'external:' + track.index} className="bg-slate-900 text-slate-100">
                        {formatTrackLabel(track, index, 'Subtitle')}
                      </option>
                    ))}
                  </select>
                  </label>

                  {subtitleTracks.length > 0 && selectedSubtitleIndex !== undefined && (
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setSubtitleSyncOpen(prev => !prev)}
                      className={`flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-xs font-semibold transition ${subtitleOffset !== 0 ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-300' : 'border-slate-700/80 bg-slate-800/90 text-slate-300 hover:text-white'}`}
                      title="Adjust subtitle timing"
                    >
                      <Timer className="h-4 w-4" />
                      <span className="hidden sm:inline">Sync</span>
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
                </div>
              )}

              {/* Playback Speed selector */}
              <div className="flex shrink-0 items-center bg-slate-800/80 rounded-lg p-0.5 text-xs font-medium text-slate-300">
                {[0.75, 1, 1.25, 1.5, 2].map((s) => (
                  <button
                    key={s}
                    onClick={() => handleSpeedChange(s)}
                    className={`px-2 py-1 rounded-md transition ${
                      playbackSpeed === s
                        ? 'bg-cyan-500 text-slate-950 font-bold'
                        : 'hover:text-white'
                    }`}
                  >
                    {s}x
                  </button>
                ))}
              </div>

              {/* PiP (video only) */}
              {isVideo && (
                <button
                  onClick={togglePip}
                  className="p-2 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition"
                  title="Picture in Picture"
                >
                  <ExternalLink className="w-4 h-4" />
                </button>
              )}

              {/* Fullscreen */}
              <button
                onClick={toggleFullscreen}
                className="p-2 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition"
                title="Fullscreen"
              >
                {isFullscreen ? <Minimize className="w-4 h-4" /> : <Maximize className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>
    </>
  );
}
