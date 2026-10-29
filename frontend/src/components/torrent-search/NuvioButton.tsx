import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Hls from 'hls.js';
import { Loader2, Play, X } from 'lucide-react';
import { api } from '../../api/client.ts';
import type { NuvioStream } from '../../api/types.ts';

export function NuvioButton({ nuvioId, title }: { nuvioId: string; title: string }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [streams, setStreams] = useState<NuvioStream[]>([]);
  const [durationMs, setDurationMs] = useState<number | null>(null);
  const [selectedStream, setSelectedStream] = useState<NuvioStream | null>(null);
  const [playbackMessage, setPlaybackMessage] = useState('');
  const videoRef = useRef<HTMLVideoElement>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!selectedStream || !video) return;

    setPlaybackMessage('Attempting playback…');
    const hls = new Hls();
    const isHls = /\.m3u8(?:$|[?#])/i.test(selectedStream.url);
    if (isHls && Hls.isSupported()) {
      hls.loadSource(selectedStream.url);
      hls.attachMedia(video);
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) setPlaybackMessage('Playback could not start for this source.');
      });
    } else {
      video.src = selectedStream.url;
      video.load();
    }

    return () => {
      hls.destroy();
      video.pause();
      video.removeAttribute('src');
      video.load();
    };
  }, [selectedStream]);

  const lookup = async () => {
    if (loading) return;
    setOpen(true);
    setLoading(true);
    setError('');
    setStreams([]);
    setSelectedStream(null);
    setDurationMs(null);
    setPlaybackMessage('');
    const controller = new AbortController();
    controllerRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 50_000);
    try {
      const result = await api.getNuvioMovieStreams(nuvioId, controller.signal);
      setStreams(result.streams);
      setDurationMs(result.durationMs);
    } catch (lookupError) {
      setError(lookupError instanceof DOMException && lookupError.name === 'AbortError'
        ? 'Nuvio source lookup timed out. Try again.'
        : lookupError instanceof Error
          ? lookupError.message
          : 'Could not retrieve sources from Nuvio Streams.');
    } finally {
      window.clearTimeout(timeout);
      if (controllerRef.current === controller) controllerRef.current = null;
      setLoading(false);
    }
  };

  const close = () => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setOpen(false);
    setSelectedStream(null);
  };

  return (
    <>
      <button
        type="button"
        disabled={!/^(tt\d{5,12}|tmdb:[1-9]\d{0,19})$/.test(nuvioId) || loading}
        onClick={() => void lookup()}
        title="Find sources from Nuvio Streams"
        className="min-w-0 flex-1 whitespace-nowrap rounded-lg border border-cyan-400/40 bg-cyan-500/15 px-1.5 py-1.5 text-[10px] font-bold text-cyan-100 hover:bg-cyan-500/25 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loading ? <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1 inline h-3.5 w-3.5" />}
        Nuvio
      </button>
      {open && createPortal(
        <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/85 p-2 sm:p-5">
          <section role="dialog" aria-modal="true" aria-labelledby="nuvio-title" className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-slate-700 bg-slate-950 shadow-2xl">
            <header className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
              <div className="min-w-0">
                <h2 id="nuvio-title" className="truncate text-sm font-bold text-slate-100">Nuvio · {title}</h2>
                <p className="text-[10px] text-slate-500">Source discovery does not confirm playback until the video starts.</p>
              </div>
              <button type="button" onClick={close} className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white" aria-label="Close Nuvio"><X className="h-4 w-4" /></button>
            </header>
            <div className="min-h-0 overflow-y-auto p-4">
              {loading && <p role="status" className="flex items-center gap-2 text-sm text-slate-300"><Loader2 className="h-4 w-4 animate-spin" />Looking up Nuvio streams…</p>}
              {error && <p role="alert" className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</p>}
              {!loading && !error && streams.length === 0 && <p className="text-sm text-slate-400">Nuvio returned no streams for this movie.</p>}
              {!loading && streams.length > 0 && (
                <div className="space-y-3">
                  <p className="text-xs text-slate-400">{streams.length} stream{streams.length === 1 ? '' : 's'} · lookup {durationMs ?? 0} ms</p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {streams.map((stream, index) => (
                      <button key={`${stream.url}-${index}`} type="button" onClick={() => setSelectedStream(stream)} className={`rounded-lg border p-3 text-left ${selectedStream === stream ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-800 bg-slate-900 hover:border-slate-600'}`}>
                        <span className="block text-sm font-semibold text-slate-100">{stream.name || 'Nuvio stream'}</span>
                        <span className="mt-1 block whitespace-pre-line text-xs text-slate-400">{stream.title || 'Details not provided'}</span>
                      </button>
                    ))}
                  </div>
                  {selectedStream && (
                    <div className="space-y-2 border-t border-slate-800 pt-3">
                      <video
                        ref={videoRef}
                        key={selectedStream.url}
                        controls
                        autoPlay
                        playsInline
                        className="max-h-[55vh] w-full bg-black"
                        onPlaying={() => setPlaybackMessage('Playback started.')}
                        onError={() => setPlaybackMessage('This source did not play in the browser video player.')}
                      />
                      <p role="status" className="text-xs text-slate-400">{playbackMessage}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        </div>,
        document.body,
      )}
    </>
  );
}
