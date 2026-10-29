import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Clipboard, Download, Loader2, Play, X } from 'lucide-react';
import type { TorrentSearchResult } from '../../api/types.ts';

const WEBTOR_SDK_URL = 'https://cdn.jsdelivr.net/npm/@webtor/embed-sdk-js/dist/index.min.js';
const WEBTOR_HOSTED_BASE_URL = 'https://webtor.io';

interface WebtorEmbedConfig {
  id: string;
  magnet: string;
  title: string;
  width: string;
  mode: 'video' | 'download';
  baseUrl: string;
  controls: boolean;
}

declare global {
  interface Window {
    webtor?: { push: (config: WebtorEmbedConfig) => unknown };
  }
}

let webtorSdkPromise: Promise<void> | null = null;

function loadWebtorSdk(): Promise<void> {
  if (webtorSdkPromise) return webtorSdkPromise;
  webtorSdkPromise = new Promise((resolve, reject) => {
    let script = document.querySelector<HTMLScriptElement>(`script[src="${WEBTOR_SDK_URL}"]`);
    if (script?.dataset.loaded === 'true' || (window.webtor && !Array.isArray(window.webtor))) {
      resolve();
      return;
    }

    const shouldAppend = !script;
    if (!script) {
      script = document.createElement('script');
      script.src = WEBTOR_SDK_URL;
      script.async = true;
    }

    script.addEventListener('load', () => {
      script!.dataset.loaded = 'true';
      resolve();
    }, { once: true });
    script.addEventListener('error', () => {
      script?.remove();
      webtorSdkPromise = null;
      reject(new Error('Could not load Webtor. Check your connection and try again.'));
    }, { once: true });
    if (shouldAppend) document.head.appendChild(script);
  });
  return webtorSdkPromise;
}

export function WebtorButton({ torrent }: { torrent: TorrentSearchResult }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<WebtorEmbedConfig['mode'] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [magnetCopied, setMagnetCopied] = useState(false);
  const [showManualMagnet, setShowManualMagnet] = useState(false);
  const playerId = `webtor-player-${useId().replace(/:/g, '')}`;
  const embedId = mode ? `${playerId}-${mode}` : playerId;
  const embedRef = useRef<HTMLDivElement>(null);
  const magnet = String(torrent.magnetUrl || '').trim();

  useEffect(() => {
    if (!open || !mode || !magnet || !embedRef.current) return;

    let cancelled = false;
    setLoading(true);
    setError('');
    embedRef.current.replaceChildren();

    void loadWebtorSdk()
      .then(() => {
        if (cancelled || !embedRef.current) return;
        const sdk = window.webtor;
        // The SDK intentionally exposes an array queue before/while it initializes.
        // Calling push() is the documented way to enqueue an embed config.
        sdk.push({
          id: embedId,
          magnet,
          title: torrent.title,
          width: '100%',
          mode,
          controls: true,
          baseUrl: WEBTOR_HOSTED_BASE_URL,
        });
        // Webtor creates its iframe asynchronously after push(); checking for it
        // synchronously incorrectly reports a failure before the embed can render.
        setLoading(false);
      })
      .catch(loadError => {
        if (cancelled) return;
        setLoading(false);
        setError(loadError instanceof Error ? loadError.message : 'Could not load Webtor.');
      });

    return () => {
      cancelled = true;
      embedRef.current?.replaceChildren();
    };
  }, [open, mode, magnet, playerId, torrent.title]);

  const copyMagnet = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard access is unavailable.');
      await navigator.clipboard.writeText(magnet);
      setMagnetCopied(true);
      setShowManualMagnet(false);
    } catch {
      setMagnetCopied(false);
      setShowManualMagnet(true);
    }
  };

  return (
    <>
      <button
        type="button"
        disabled={!magnet}
        onClick={() => { setOpen(true); setMode(null); }}
        title={magnet ? 'Open the selected torrent in Webtor' : 'No magnet link is available for this result'}
        className="min-w-0 flex-1 whitespace-nowrap rounded-lg border border-cyan-400/40 bg-cyan-500/15 px-1.5 py-1.5 text-[10px] font-bold text-cyan-100 hover:bg-cyan-500/25 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Play className="mr-1 inline-block h-3.5 w-3.5" />
        Test Webtor
      </button>
      {open && createPortal(
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/85 p-2 sm:p-5">
          <section role="dialog" aria-modal="true" aria-labelledby={`${playerId}-title`} className="flex h-[92vh] w-full min-w-0 max-w-5xl flex-col overflow-hidden rounded-xl border border-slate-700 bg-slate-950 shadow-2xl">
            <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
              <div className="min-w-0">
                <h2 id={`${playerId}-title`} className="truncate text-sm font-bold text-slate-100">{torrent.title}</h2>
                <p className="text-[10px] text-slate-500">Webtor hosts torrent retrieval and media delivery; Torrent Studio does not relay video bytes.</p>
              </div>
              <button type="button" onClick={() => { setOpen(false); setMode(null); }} className="shrink-0 rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white" aria-label="Close Webtor"><X className="h-4 w-4" /></button>
            </header>
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-800 px-4 py-2">
              <button type="button" onClick={() => setMode('video')} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${mode === 'video' ? 'bg-cyan-500 text-slate-950' : 'border border-slate-700 text-slate-200 hover:border-cyan-500'}`}>
                <Play className="mr-1 inline h-3.5 w-3.5" />Play
              </button>
              <button type="button" onClick={() => setMode('download')} className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${mode === 'download' ? 'bg-cyan-500 text-slate-950' : 'border border-slate-700 text-slate-200 hover:border-cyan-500'}`}>
                <Download className="mr-1 inline h-3.5 w-3.5" />Download
              </button>
              <button type="button" onClick={() => void copyMagnet()} className="ml-auto rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200 hover:border-cyan-500">
                <Clipboard className="mr-1 inline h-3.5 w-3.5" />{magnetCopied ? 'Magnet copied' : 'Copy magnet'}
              </button>
              {showManualMagnet && (
                <input
                  aria-label="Magnet link to copy"
                  readOnly
                  value={magnet}
                  onFocus={event => event.currentTarget.select()}
                  className="w-full min-w-0 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-300"
                />
              )}
            </div>
            {!mode && <p className="shrink-0 px-4 py-2 text-xs text-slate-400">Choose Play to launch the embedded video player or Download to open Webtor’s file selector. Select a file there to begin its download.</p>}
            {loading && <div className="flex shrink-0 items-center justify-center gap-2 p-3 text-sm text-slate-300"><Loader2 className="h-4 w-4 animate-spin" />Loading Webtor…</div>}
            {error && <div role="alert" className="m-3 shrink-0 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}
            {mode && !error && (
              <div
                key={mode}
                id={embedId}
                ref={embedRef}
                className="webtor-embed-frame relative m-3 min-h-0 min-w-0 flex-1 overflow-hidden rounded-lg border border-slate-800 bg-black"
              />
            )}
          </section>
        </div>,
        document.body,
      )}
    </>
  );
}
