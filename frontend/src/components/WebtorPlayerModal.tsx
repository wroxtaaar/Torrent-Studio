import { createPortal } from 'react-dom';
import React, { useEffect, useId, useState } from 'react';
import { Download, ExternalLink, Loader2, X } from 'lucide-react';
import { copyMagnetAndOpenWebtor, loadWebtorSdk, openWebtorDownload, webtorEmbedConfig } from './torrent-search/webtor.ts';

/**
 * Plays a torrent inside the app with Webtor's own player (their embed SDK, MIT). Webtor's servers fetch the torrent and
 * convert it for the browser, which is why large HEVC / DTS releases play there. If the player cannot load, the old
 * route stays available: copy the magnet and open webtor.io.
 */
export const WebtorPlayerModal: React.FC<{ title: string; magnetUrl: string; label?: string; onClose: () => void }> = ({ title, magnetUrl, label, onClose }) => {
  const reactId = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const mountId = `webtor-${reactId}`;
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [hint, setHint] = useState('');

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    const config = webtorEmbedConfig(mountId, magnetUrl, title);
    if (!config) { setState('failed'); return undefined; }
    let cancelled = false;
    setState('loading');
    loadWebtorSdk().then(() => {
      if (cancelled) return;
      const queue = ((window as unknown as { webtor?: unknown[] }).webtor ||= []) as unknown[];
      queue.push(config);
      setState('ready');
    }).catch(() => { if (!cancelled) setState('failed'); });
    return () => { cancelled = true; };
  }, [mountId, magnetUrl, title]);

  return createPortal(
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/80 p-3" role="dialog" aria-modal="true" aria-label={`Webtor player for ${title}`}
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl">
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-800 px-4 py-2.5">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-bold text-slate-100">{title}</h2>
            {label && <p className="truncate text-[11px] text-slate-400">{label}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close player" className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"><X className="h-4 w-4" /></button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-black">
          {state === 'loading' && <div className="flex items-center justify-center gap-2 py-10 text-xs text-slate-400"><Loader2 className="h-4 w-4 animate-spin" />Loading Webtor player…</div>}
          <div id={mountId} className="webtor w-full [&_iframe]:block [&_iframe]:min-h-[640px] [&_iframe]:w-full" />
        </div>
        <div className="shrink-0 space-y-2 border-t border-slate-800 px-4 py-3">
          {state === 'failed' && <p className="text-xs text-amber-300">The Webtor player could not be loaded here. Use the button below to open webtor.io instead.</p>}
          <div className="flex flex-wrap gap-2">
          <button type="button"
            onClick={() => {
              const result = openWebtorDownload(magnetUrl);
              setHint(result.opened
                ? 'Webtor opened on this torrent. Tap Download there. If it says the torrent is not found, paste the magnet (copied).'
                : 'Webtor opened. Paste the magnet (copied) to continue.');
            }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-500 px-2.5 py-1.5 text-[11px] font-bold text-slate-950 hover:bg-cyan-400">
            <Download className="h-3 w-3" />Download on Webtor
          </button>
          <button type="button"
            onClick={() => setHint(copyMagnetAndOpenWebtor(magnetUrl) ? 'Magnet copied. Paste it on Webtor to stream or download.' : 'Webtor opened, but the magnet could not be copied.')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-400/40 bg-cyan-500/15 px-2.5 py-1.5 text-[11px] font-bold text-cyan-200 hover:bg-cyan-500/25">
            <ExternalLink className="h-3 w-3" />Open on webtor.io
          </button>
          </div>
          {hint && <p className="text-[11px] text-slate-400" role="status">{hint}</p>}
        </div>
      </div>
    </div>,
    document.body,
  );
};
