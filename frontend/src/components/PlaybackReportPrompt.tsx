import React, { useEffect, useState } from 'react';
import { apiFetch } from '../api/http.ts';

export function sendPlaybackReport(title: string, detail: string, player: string, reason: string): void {
  void apiFetch('/api/playback/report', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title.slice(0, 200), detail: detail.slice(0, 400), player, reason }),
  }).catch(() => { /* best effort */ });
}

/** Long-press on a card: ask once, then report the title as not playing. */
export function reportFromCard(title: string, year?: string | number | null): void {
  const label = year ? `${title} (${year})` : title;
  if (window.confirm(`Report "${label}" as not playing?`)) sendPlaybackReport(label, '', 'card', 'long_press');
}

/**
 * A quiet one-line prompt that only appears when playback has visibly gone wrong (an error, or still loading after a
 * while). It never shows while a title plays normally. One tap sends the title and release to the server.
 */
export const PlaybackReportPrompt: React.FC<{ title: string; detail?: string; player: string; failed: boolean; loading: boolean; stallMs?: number }> = ({ title, detail, player, failed, loading, stallMs = 20000 }) => {
  const [stalled, setStalled] = useState(false);
  const [sent, setSent] = useState(false);
  useEffect(() => {
    if (!loading) { setStalled(false); return undefined; }
    const timer = window.setTimeout(() => setStalled(true), stallMs);
    return () => window.clearTimeout(timer);
  }, [loading, stallMs]);
  if (!failed && !stalled) return null;
  const send = () => { setSent(true); sendPlaybackReport(title, detail || '', player, failed ? 'error' : 'stalled'); };
  return (
    <p className="text-[11px] text-slate-500" role="status">
      {sent ? 'Thanks, reported.' : (<>Not playing? <button type="button" onClick={send} className="underline decoration-dotted underline-offset-2 hover:text-slate-300">Report</button></>)}
    </p>
  );
};
